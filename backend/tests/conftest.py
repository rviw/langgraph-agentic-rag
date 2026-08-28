from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session
from supabase_auth.errors import AuthApiError

from app.agent.answer import Answer
from app.api.deps import (
    get_db,
    get_document_storage,
    get_grounding_validator,
    get_supabase_auth,
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
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
