from collections.abc import Generator
from dataclasses import dataclass
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select
from supabase import Client
from supabase_auth.errors import AuthError

from app.core.db import engine
from app.models import Chat

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
