import json
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.agent.phases import ExecutionPhase, report_phase
from app.api.deps import get_graph
from app.main import app
from tests.conftest import FakeSupabaseAuthClient, authenticated_claims


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
        self.contexts: list[Any] = []

    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: Any = None,
    ) -> dict[str, Any]:
        self.contexts.append(context)
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


def sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a completed SSE body into ordered (event name, payload) pairs."""

    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        name: str | None = None
        data: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").strip())
        if name is not None and data:
            events.append((name, json.loads("\n".join(data))))
    return events


@pytest.fixture
def use_graph() -> Iterator[Callable[[FakeGraph], FakeGraph]]:
    def factory(graph: FakeGraph) -> FakeGraph:
        app.dependency_overrides[get_graph] = lambda: graph
        return graph

    yield factory
    app.dependency_overrides.pop(get_graph, None)


@pytest.fixture
def headers(
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
) -> dict[str, str]:
    user_id = create_user()
    supabase_auth.auth.register("member", authenticated_claims(user_id))
    return {"Authorization": "Bearer member"}


def test_a_turn_is_accepted_then_completed_with_the_stored_answer(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph(phases=("searching", "reading")))
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "How does retrieval work?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    assert [name for name, _ in events] == [
        "message.accepted",
        "execution.progress",
        "execution.progress",
        "execution.progress",
        "message.completed",
    ]
    assert events[0][1]["message"]["content"] == "How does retrieval work?"
    assert [payload["phase"] for _, payload in events[1:4]] == [
        "understanding",
        "searching",
        "reading",
    ]
    completed = events[-1][1]["message"]
    assert completed["role"] == "assistant"
    assert completed["content"] == "A grounded answer."
    assert completed["citations"] == []


def test_the_completed_turn_is_the_stored_transcript(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph())
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "First question"},
    )

    stored = client.get(f"/api/chats/{chat_id}/messages", headers=headers).json()
    assert [(item["role"], item["content"]) for item in stored] == [
        ("user", "First question"),
        ("assistant", "A grounded answer."),
    ]


def test_the_first_turn_names_the_chat_and_later_turns_leave_it(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph())
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "First question"},
    )
    assert client.get(f"/api/chats/{chat_id}", headers=headers).json()["title"] == (
        "Generated title"
    )

    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "Second question"},
    )

    assert client.get(f"/api/chats/{chat_id}", headers=headers).json()["title"] == (
        "Generated title"
    )


def test_a_failed_execution_reports_one_safe_message(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph(failure=RuntimeError("provider key sk-secret rejected")))
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "Question"},
    )

    events = sse_events(response.text)
    assert [name for name, _ in events][-1] == "execution.failed"
    failure = events[-1][1]["error"]["message"]
    assert failure == "Couldn’t generate a response."
    assert "sk-secret" not in response.text


def test_the_user_message_survives_a_failed_answer(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph(failure=RuntimeError("no answer")))
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json={"content": "Question"},
    )

    stored = client.get(f"/api/chats/{chat_id}/messages", headers=headers).json()
    assert [(item["role"], item["content"]) for item in stored] == [
        ("user", "Question"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"content": ""}, id="empty"),
        pytest.param({"content": "x" * 20_001}, id="too-long"),
    ],
)
def test_an_unusable_request_is_refused(
    client: TestClient,
    headers: dict[str, str],
    use_graph: Callable[[FakeGraph], FakeGraph],
    payload: dict[str, Any],
) -> None:
    use_graph(FakeGraph())
    chat_id = client.post("/api/chats", headers=headers).json()["id"]

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 422


def test_messages_cannot_be_sent_to_another_users_chat(
    client: TestClient,
    headers: dict[str, str],
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
    use_graph: Callable[[FakeGraph], FakeGraph],
) -> None:
    use_graph(FakeGraph())
    chat_id = client.post("/api/chats", headers=headers).json()["id"]
    supabase_auth.auth.register("other", authenticated_claims(create_user()))

    response = client.post(
        f"/api/chats/{chat_id}/messages",
        headers={"Authorization": "Bearer other"},
        json={"content": "Question"},
    )

    assert response.status_code == 404
