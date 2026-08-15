from typing import Any
from uuid import UUID, uuid7

import pytest
from supabase_auth.errors import AuthApiError


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


class FakeSupabase:
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
def user_id() -> UUID:
    return uuid7()


@pytest.fixture
def supabase() -> FakeSupabase:
    return FakeSupabase()
