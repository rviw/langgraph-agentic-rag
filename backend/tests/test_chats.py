from collections.abc import Callable
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeSupabaseAuthClient, authenticated_claims


@pytest.fixture
def signed_in(
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
) -> Callable[..., dict[str, str]]:
    """Register a real user row plus the token that authenticates as them."""

    def factory(token: str = "member"):
        user_id = create_user()
        supabase_auth.auth.register(
            token,
            authenticated_claims(user_id, email=f"{user_id}@example.test"),
        )
        return {"Authorization": f"Bearer {token}"}

    return factory


def test_a_new_chat_starts_with_the_default_title(
    client: TestClient,
    signed_in: Callable[..., dict[str, str]],
) -> None:
    headers = signed_in()

    created = client.post("/api/chats", headers=headers)

    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "New chat"
    assert body["created_at"]


def test_chats_are_listed_newest_first(
    client: TestClient,
    signed_in: Callable[..., dict[str, str]],
) -> None:
    headers = signed_in()
    first = client.post("/api/chats", headers=headers).json()["id"]
    second = client.post("/api/chats", headers=headers).json()["id"]

    listed = client.get("/api/chats", headers=headers)

    assert listed.status_code == 200
    assert [chat["id"] for chat in listed.json()] == [second, first]


def test_one_user_never_sees_or_reaches_another_users_chat(
    client: TestClient,
    signed_in: Callable[..., dict[str, str]],
) -> None:
    owner = signed_in("owner")
    other = signed_in("other")
    chat_id = client.post("/api/chats", headers=owner).json()["id"]

    assert client.get("/api/chats", headers=other).json() == []
    assert client.get(f"/api/chats/{chat_id}", headers=other).status_code == 404
    assert client.delete(f"/api/chats/{chat_id}", headers=other).status_code == 404
    assert client.get(f"/api/chats/{chat_id}", headers=owner).status_code == 200


def test_deleting_a_chat_removes_it(
    client: TestClient,
    signed_in: Callable[..., dict[str, str]],
) -> None:
    headers = signed_in()
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    deleted = client.delete(f"/api/chats/{chat_id}", headers=headers)

    assert deleted.status_code == 204
    assert client.get(f"/api/chats/{chat_id}", headers=headers).status_code == 404


def test_an_unknown_chat_is_reported_as_missing(
    client: TestClient,
    signed_in: Callable[..., dict[str, str]],
) -> None:
    headers = signed_in()

    response = client.get(f"/api/chats/{uuid7()}", headers=headers)

    assert response.status_code == 404


def test_chat_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/chats").status_code == 401
    assert client.post("/api/chats").status_code == 401
