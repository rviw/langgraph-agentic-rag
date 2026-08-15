from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import CurrentUserDep, get_supabase_auth
from tests.conftest import FakeSupabase, authenticated_claims


@pytest.fixture
def client(supabase: FakeSupabase) -> TestClient:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(current_user: CurrentUserDep) -> dict[str, str]:
        return {"id": str(current_user.id), "email": current_user.email}

    app.dependency_overrides[get_supabase_auth] = lambda: supabase
    return TestClient(app)


def test_a_verified_end_user_token_identifies_the_caller(
    client: TestClient,
    supabase: FakeSupabase,
    user_id: UUID,
) -> None:
    supabase.auth.register(
        "valid",
        authenticated_claims(user_id, email="member@example.test"),
    )

    response = client.get("/whoami", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(user_id),
        "email": "member@example.test",
    }


def test_an_audience_list_containing_authenticated_is_accepted(
    client: TestClient,
    supabase: FakeSupabase,
    user_id: UUID,
) -> None:
    supabase.auth.register(
        "list-audience",
        authenticated_claims(user_id, aud=["authenticated", "other"]),
    )

    response = client.get(
        "/whoami",
        headers={"Authorization": "Bearer list-audience"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user_id)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"role": "service_role"}, id="service-role"),
        pytest.param({"is_anonymous": True}, id="anonymous-session"),
        pytest.param({"aud": "unverified"}, id="other-audience"),
        pytest.param({"email": "  "}, id="blank-email"),
    ],
)
def test_a_token_that_is_not_an_end_user_session_is_rejected(
    client: TestClient,
    supabase: FakeSupabase,
    user_id: UUID,
    overrides: dict[str, object],
) -> None:
    supabase.auth.register(
        "unsupported",
        authenticated_claims(user_id, **overrides),
    )

    response = client.get(
        "/whoami",
        headers={"Authorization": "Bearer unsupported"},
    )

    assert response.status_code == 401


def test_an_unverifiable_token_is_rejected(client: TestClient) -> None:
    response = client.get("/whoami", headers={"Authorization": "Bearer forged"})

    assert response.status_code == 401


def test_a_request_without_credentials_is_rejected(client: TestClient) -> None:
    assert client.get("/whoami").status_code == 401
