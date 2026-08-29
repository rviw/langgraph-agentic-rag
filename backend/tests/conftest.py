import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid7

import pytest

# Set before the application is imported below: the trace exporter starts
# background workers as soon as it is built, and tests export nothing.
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlmodel import Session
from supabase_auth.errors import AuthApiError

from app.agent.answer import Answer
from app.agent.phases import ExecutionPhase, report_phase
from app.api.deps import (
    get_db,
    get_document_storage,
    get_grounding_validator,
    get_memory_extractor,
    get_memory_index,
    get_supabase_auth,
    get_tracer,
)
from app.core.db import engine
from app.db.answer_sources import AnswerSourceSnapshot
from app.main import app
from app.rag.runner import DocumentIndexingRunner
from app.storage.documents import (
    DocumentObjectInfo,
    DocumentObjectNotFound,
    SignedUpload,
)

# Tables the tests truncate between cases, ordered so cascades stay valid.
_APPLICATION_TABLES = (
    "answer_citations",
    "answer_sources",
    "chat_messages",
    "document_chunks",
    "documents",
    "memories",
    "chats",
)


class FakeAuth:
    """Stands in for the Supabase Auth SDK by returning prepared claims."""

    def __init__(self) -> None:
        self._claims_by_token: dict[str, dict[str, Any]] = {}

    def register(self, token: str, claims: dict[str, Any]) -> None:
        self._claims_by_token[token] = claims

    def get_claims(self, *, jwt: str) -> dict[str, Any]:
        claims = self._claims_by_token.get(jwt)
        if claims is None:
            raise AuthApiError("invalid token", 401, "invalid_token")
        return {"claims": claims}

    def close(self) -> None:
        pass


class FakeSupabaseAuthClient:
    def __init__(self) -> None:
        self.auth = FakeAuth()


def authenticated_claims(
    user_id: UUID,
    *,
    email: str = "member@example.test",
    **overrides: Any,
) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "aud": "authenticated",
        "role": "authenticated",
        "is_anonymous": False,
        "email": email,
    }
    claims.update(overrides)
    return claims


@pytest.fixture
def supabase_auth() -> FakeSupabaseAuthClient:
    return FakeSupabaseAuthClient()


class FakeDocumentStorage:
    """Records Storage calls and serves only objects a test uploaded."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.signed_paths: list[str] = []
        self.removed_paths: list[str] = []

    def upload(
        self, path: str, data: bytes, media_type: str = "application/pdf"
    ) -> None:
        self.objects[path] = (data, media_type)

    def create_signed_upload(self, path: str) -> SignedUpload:
        self.signed_paths.append(path)
        return SignedUpload(bucket="documents", path=path, token="signed-token")

    def info(self, path: str) -> DocumentObjectInfo | None:
        stored = self.objects.get(path)
        if stored is None:
            return None
        data, media_type = stored
        return DocumentObjectInfo(size_bytes=len(data), media_type=media_type)

    def download(self, path: str) -> bytes:
        stored = self.objects.get(path)
        if stored is None:
            raise DocumentObjectNotFound
        return stored[0]

    def remove(self, path: str) -> None:
        self.removed_paths.append(path)
        self.objects.pop(path, None)


@pytest.fixture
def document_storage() -> FakeDocumentStorage:
    return FakeDocumentStorage()


class PassThroughGroundingValidator:
    """Accepts drafts so stream tests observe the route only."""

    def __init__(self) -> None:
        self.calls: list[tuple[Answer, bool]] = []

    async def validate(
        self,
        *,
        draft: Answer,
        sources: tuple[AnswerSourceSnapshot, ...],
        searched: bool,
        user_request: str,
    ) -> None:
        del sources, user_request
        self.calls.append((draft, searched))


@pytest.fixture
def grounding_validator() -> PassThroughGroundingValidator:
    return PassThroughGroundingValidator()


class FakeMemoryIndex:
    """Records vector writes and deletes without embedding anything."""

    def __init__(self) -> None:
        self.entries: dict[tuple[tuple[str, ...], str], dict] = {}
        self.deleted: list[tuple[tuple[str, ...], str]] = []

    async def aput(self, namespace, key, value, *, index=None):
        del index
        self.entries[(namespace, key)] = value

    async def adelete(self, namespace, key):
        self.deleted.append((namespace, key))
        self.entries.pop((namespace, key), None)

    async def asearch(self, namespace, *, query, limit):
        del query, limit
        return [
            type("Item", (), {"value": value})()
            for (entry_namespace, _key), value in self.entries.items()
            if entry_namespace == namespace
        ]


@pytest.fixture
def memory_index() -> FakeMemoryIndex:
    return FakeMemoryIndex()


class RecordingMemoryExtractor:
    """Returns prepared memories instead of calling a provider."""

    def __init__(self) -> None:
        self.memories: tuple[str, ...] = ()
        self.calls: list[tuple[str, str]] = []

    async def extract(self, *, user_message: str, assistant_message: str):
        self.calls.append((user_message, assistant_message))
        return self.memories


@pytest.fixture
def memory_extractor() -> RecordingMemoryExtractor:
    return RecordingMemoryExtractor()


class RecordingTracer:
    """Records traced executions without exporting anything."""

    def __init__(self) -> None:
        self.executions: list[tuple[UUID, UUID, UUID]] = []

    @contextmanager
    def trace_execution(self, *, execution_id, chat_id, user_id):
        self.executions.append((execution_id, chat_id, user_id))
        yield

    async def shutdown(self) -> None:
        pass


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer()


class FakeGraph:
    """Stands in for the compiled agent by replaying a scripted final answer."""

    def __init__(
        self,
        *,
        answer: dict[str, Any] | None = None,
        phases: tuple[ExecutionPhase, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self._answer = answer or {
            "markdown": "A grounded answer.",
            "source_ids": [],
            "title": "Generated title",
        }
        self._phases = phases
        self._failure = failure

    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: Any = None,
    ) -> dict[str, Any]:
        del config, context
        for phase in self._phases:
            report_phase(phase)
        if self._failure is not None:
            raise self._failure
        return {
            "messages": [
                *state["messages"],
                AIMessage(content=json.dumps(self._answer)),
            ]
        }


@pytest.fixture
def use_graph() -> Iterator[Any]:
    """Serve a scripted agent for one test."""

    from app.api.deps import get_graph

    def factory(graph: Any) -> Any:
        app.dependency_overrides[get_graph] = lambda: graph
        return graph

    yield factory
    app.dependency_overrides.pop(get_graph, None)


@pytest.fixture
def db_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Leave the database as the test found it, including created auth users."""

    yield
    with Session(engine) as session:
        session.exec(text(f"TRUNCATE {', '.join(_APPLICATION_TABLES)} CASCADE"))
        session.exec(
            text("DELETE FROM auth.users WHERE email LIKE :pattern").bindparams(
                pattern="%@example.test",
            )
        )
        session.commit()


@pytest.fixture
def create_user(db_session: Session):
    """Insert a Supabase Auth user row so application foreign keys resolve."""

    def factory(email: str | None = None) -> UUID:
        user_id = uuid7()
        db_session.exec(
            text(
                "INSERT INTO auth.users (id, instance_id, aud, role, email) "
                "VALUES (:id, '00000000-0000-0000-0000-000000000000', "
                "'authenticated', 'authenticated', :email)"
            ).bindparams(
                id=user_id,
                email=email or f"{user_id}@example.test",
            )
        )
        db_session.commit()
        return user_id

    return factory


class RecordingIndexingRunner:
    """Record API wakeups; dedicated runner tests exercise actual indexing."""

    def __init__(self) -> None:
        self.requests = 0

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def request_run(self) -> None:
        self.requests += 1


@pytest.fixture
def indexing_runner() -> RecordingIndexingRunner:
    return RecordingIndexingRunner()


@pytest.fixture
def client(
    supabase_auth: FakeSupabaseAuthClient,
    db_session: Session,
    document_storage: FakeDocumentStorage,
    indexing_runner: RecordingIndexingRunner,
    monkeypatch: pytest.MonkeyPatch,
    grounding_validator: PassThroughGroundingValidator,
    memory_index: FakeMemoryIndex,
    memory_extractor: RecordingMemoryExtractor,
    tracer: RecordingTracer,
) -> Iterator[TestClient]:
    """A client whose Supabase Auth boundary is a double, on the real database."""

    # Lifespan creates this worker directly, outside FastAPI dependency overrides.
    # Patch its factory before TestClient starts the application.
    monkeypatch.setattr(
        DocumentIndexingRunner,
        "for_database",
        classmethod(lambda _cls, **_kwargs: indexing_runner),
    )
    app.dependency_overrides[get_supabase_auth] = lambda: supabase_auth
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_document_storage] = lambda: document_storage
    app.dependency_overrides[get_grounding_validator] = lambda: grounding_validator
    app.dependency_overrides[get_memory_index] = lambda: memory_index
    app.dependency_overrides[get_memory_extractor] = lambda: memory_extractor
    app.dependency_overrides[get_tracer] = lambda: tracer
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
