from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from sqlmodel import Session, select
from supabase import Client
from supabase_auth.errors import AuthError

from app.agent.grounding import GroundingValidator
from app.agent.memory import MemoryExtractor
from app.core.db import engine
from app.models import Chat
from app.rag.runner import DocumentIndexingRunner
from app.storage.documents import DocumentStorage

_JWT_AUDIENCE = "authenticated"
_bearer = HTTPBearer()


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired. Sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_db() -> Generator[Session]:
    with Session(engine) as db_session:
        yield db_session


DbSessionDep = Annotated[Session, Depends(get_db)]


def get_supabase_auth(request: Request) -> Client:
    return cast(Client, request.app.state.supabase_auth)


SupabaseAuthDep = Annotated[Client, Depends(get_supabase_auth)]


def get_graph(request: Request) -> CompiledStateGraph:
    return cast(CompiledStateGraph, request.app.state.graph)


GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]


def get_grounding_validator(request: Request) -> GroundingValidator:
    return cast(GroundingValidator, request.app.state.grounding_validator)


GroundingValidatorDep = Annotated[
    GroundingValidator,
    Depends(get_grounding_validator),
]


def get_memory_index(request: Request) -> BaseStore:
    return cast(BaseStore, request.app.state.memory_index)


MemoryIndexDep = Annotated[BaseStore, Depends(get_memory_index)]


def get_memory_extractor(request: Request) -> MemoryExtractor:
    return cast(MemoryExtractor, request.app.state.memory_extractor)


MemoryExtractorDep = Annotated[MemoryExtractor, Depends(get_memory_extractor)]


def get_document_storage(request: Request) -> DocumentStorage:
    return cast(DocumentStorage, request.app.state.document_storage)


DocumentStorageDep = Annotated[DocumentStorage, Depends(get_document_storage)]


def get_indexing_runner(request: Request) -> DocumentIndexingRunner:
    return cast(DocumentIndexingRunner, request.app.state.indexing_runner)


IndexingRunnerDep = Annotated[DocumentIndexingRunner, Depends(get_indexing_runner)]


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: UUID
    email: str


CredentialsDep = Annotated[HTTPAuthorizationCredentials, Depends(_bearer)]


def _current_user_from_claims(claims: dict[str, Any]) -> CurrentUser:
    """Accept only a signed token that names a real, non-anonymous end user."""

    audience = claims["aud"]
    if audience != _JWT_AUDIENCE and not (
        isinstance(audience, list) and _JWT_AUDIENCE in audience
    ):
        raise ValueError
    if claims["role"] != "authenticated" or claims["is_anonymous"] is not False:
        raise ValueError

    email = claims["email"]
    if not isinstance(email, str) or not email.strip():
        raise ValueError

    return CurrentUser(id=UUID(claims["sub"]), email=email)


def get_current_user(
    credentials: CredentialsDep,
    supabase_auth: SupabaseAuthDep,
) -> CurrentUser:
    """Resolve the caller from a Supabase-verified access token.

    The SDK checks the signature against the project JWKS, so this only has to
    reject tokens that are valid but not an end-user session.
    """

    try:
        response = supabase_auth.auth.get_claims(jwt=credentials.credentials)
    except AuthError as exc:
        raise unauthorized() from exc

    try:
        return _current_user_from_claims(response["claims"])
    except (KeyError, TypeError, ValueError) as exc:
        raise unauthorized() from exc


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def get_owned_chat(
    chat_id: UUID,
    db_session: DbSessionDep,
    current_user: CurrentUserDep,
) -> Chat:
    """Load a chat the caller owns, hiding other users' chats as missing."""

    chat = db_session.exec(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == current_user.id,
        )
    ).one_or_none()
    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This chat is no longer available.",
        )
    return chat


OwnedChatDep = Annotated[Chat, Depends(get_owned_chat)]
