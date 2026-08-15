from typing import Literal

import httpx
from supabase import Client, ClientOptions, create_client

from app.core.config import settings

_AUTH_TIMEOUT_SECONDS = 30.0
_STORAGE_TIMEOUT_SECONDS = 120.0

SupabaseClientPurpose = Literal["auth", "storage"]


def _create_supabase_client(*, purpose: SupabaseClientPurpose) -> Client:
    """Create a backend client without persisting or auto-refreshing user sessions.

    Keep per-user session state out of clients shared across requests.
    """

    key = (
        settings.SUPABASE_PUBLISHABLE_KEY
        if purpose == "auth"
        else settings.SUPABASE_SECRET_KEY
    )
    timeout = (
        _STORAGE_TIMEOUT_SECONDS if purpose == "storage" else _AUTH_TIMEOUT_SECONDS
    )
    return create_client(
        str(settings.SUPABASE_URL).rstrip("/"),
        key.get_secret_value(),
        options=ClientOptions(
            auto_refresh_token=False,
            persist_session=False,
            httpx_client=httpx.Client(timeout=timeout, follow_redirects=True),
        ),
    )


def create_supabase_auth_client() -> Client:
    """The least-privileged client, used only to verify user access tokens."""

    return _create_supabase_client(purpose="auth")


def create_supabase_storage_client() -> Client:
    """The server-only client for private document Storage calls."""

    return _create_supabase_client(purpose="storage")
