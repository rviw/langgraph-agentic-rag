from collections.abc import Callable
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FakeMemoryIndex,
    FakeSupabaseAuthClient,
    RecordingMemoryExtractor,
    authenticated_claims,
)


@pytest.fixture
def headers(
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
) -> dict[str, str]:
    user_id = create_user()
    supabase_auth.auth.register("member", authenticated_claims(user_id))
    return {"Authorization": "Bearer member"}


def test_a_new_account_has_no_memories(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.get("/api/memories", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_a_finished_turn_saves_what_it_revealed(
    client: TestClient,
    headers: dict[str, str],
    memory_extractor: RecordingMemoryExtractor,
    memory_index: FakeMemoryIndex,
    use_graph,
) -> None:
    from tests.test_chat_messages_api import FakeGraph

    use_graph(FakeGraph())
    memory_extractor.memories = ("The user prefers Python.",)
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "I work in Python."},
    )

    saved = client.get("/api/memories", headers=headers).json()
    assert [item["content"] for item in saved] == ["The user prefers Python."]
    # The memory is searchable as soon as the answer is published.
    assert len(memory_index.entries) == 1


def test_a_saved_memory_can_be_deleted(
    client: TestClient,
    headers: dict[str, str],
    memory_extractor: RecordingMemoryExtractor,
    memory_index: FakeMemoryIndex,
    use_graph,
) -> None:
    from tests.test_chat_messages_api import FakeGraph

    use_graph(FakeGraph())
    memory_extractor.memories = ("The user prefers Python.",)
    chat_id = client.post("/api/chats", headers=headers).json()["id"]
    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "I work in Python."},
    )
    memory_id = client.get("/api/memories", headers=headers).json()[0]["id"]

    deleted = client.delete(f"/api/memories/{memory_id}", headers=headers)

    assert deleted.status_code == 204
    assert client.get("/api/memories", headers=headers).json() == []
    assert memory_index.entries == {}


def test_deleting_an_unknown_memory_is_reported_as_missing(
    client: TestClient,
    headers: dict[str, str],
) -> None:
    response = client.delete(f"/api/memories/{uuid7()}", headers=headers)

    assert response.status_code == 404


def test_all_memories_can_be_deleted_at_once(
    client: TestClient,
    headers: dict[str, str],
    memory_extractor: RecordingMemoryExtractor,
    use_graph,
) -> None:
    from tests.test_chat_messages_api import FakeGraph

    use_graph(FakeGraph())
    memory_extractor.memories = ("First fact.", "Second fact.")
    chat_id = client.post("/api/chats", headers=headers).json()["id"]
    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "Two facts."},
    )
    assert len(client.get("/api/memories", headers=headers).json()) == 2

    deleted = client.delete("/api/memories", headers=headers)

    assert deleted.status_code == 204
    assert client.get("/api/memories", headers=headers).json() == []


def test_one_user_never_sees_another_users_memories(
    client: TestClient,
    headers: dict[str, str],
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
    memory_extractor: RecordingMemoryExtractor,
    use_graph,
) -> None:
    from tests.test_chat_messages_api import FakeGraph

    use_graph(FakeGraph())
    memory_extractor.memories = ("Owner fact.",)
    chat_id = client.post("/api/chats", headers=headers).json()["id"]
    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "A fact."},
    )
    memory_id = client.get("/api/memories", headers=headers).json()[0]["id"]

    supabase_auth.auth.register("other", authenticated_claims(create_user()))
    other = {"Authorization": "Bearer other"}

    assert client.get("/api/memories", headers=other).json() == []
    assert client.delete(f"/api/memories/{memory_id}", headers=other).status_code == (
        404
    )
    assert len(client.get("/api/memories", headers=headers).json()) == 1


def test_memory_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/memories").status_code == 401
    assert client.delete("/api/memories").status_code == 401
