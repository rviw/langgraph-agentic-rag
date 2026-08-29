from collections.abc import Callable
from uuid import UUID, uuid7

import pytest
from sqlmodel import Session

from app.agent.memory import record_memories_from_turn
from app.core.db import engine
from app.db.memories import (
    IndexedMemoryWriter,
    delete_all_memories,
    list_memories,
    memory_namespace,
)


class FakeMemoryIndex:
    """Records vector writes and deletes without embedding anything."""

    def __init__(self, *, fail_on_put: bool = False) -> None:
        self.entries: dict[tuple[tuple[str, ...], str], dict] = {}
        self.deleted: list[tuple[tuple[str, ...], str]] = []
        self._fail_on_put = fail_on_put

    async def aput(self, namespace, key, value, *, index=None):
        if self._fail_on_put:
            raise RuntimeError("index unavailable")
        self.entries[(namespace, key)] = value

    async def adelete(self, namespace, key):
        self.deleted.append((namespace, key))
        self.entries.pop((namespace, key), None)


class ScriptedExtractor:
    def __init__(self, outcomes) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    async def extract(self, *, user_message: str, assistant_message: str):
        self.calls.append((user_message, assistant_message))
        if isinstance(self._outcomes, Exception):
            raise self._outcomes
        return self._outcomes


class RecordingWriter:
    def __init__(self) -> None:
        self.saved: list[tuple[UUID, str]] = []

    async def save_memory(self, *, user_id: UUID, content: str) -> None:
        self.saved.append((user_id, content))


@pytest.fixture
def user_id(create_user: Callable[..., UUID]) -> UUID:
    return create_user()


async def test_a_saved_memory_is_indexed_and_stored(
    db_session: Session,
    user_id: UUID,
) -> None:
    index = FakeMemoryIndex()
    writer = IndexedMemoryWriter(engine, index)

    await writer.save_memory(user_id=user_id, content="The user prefers Python.")

    stored = list_memories(db_session, user_id=user_id)
    assert [memory.content for memory in stored] == ["The user prefers Python."]
    # The same identifier keys the vector and the row.
    assert list(index.entries) == [(memory_namespace(user_id), str(stored[0].id))]


async def test_a_failed_index_write_stores_no_row(
    db_session: Session,
    user_id: UUID,
) -> None:
    writer = IndexedMemoryWriter(engine, FakeMemoryIndex(fail_on_put=True))

    with pytest.raises(RuntimeError):
        await writer.save_memory(user_id=user_id, content="Never stored.")

    assert list_memories(db_session, user_id=user_id) == ()


async def test_deleting_all_memories_clears_only_this_user(
    db_session: Session,
    user_id: UUID,
    create_user: Callable[..., UUID],
) -> None:
    index = FakeMemoryIndex()
    writer = IndexedMemoryWriter(engine, index)
    other_user = create_user()
    await writer.save_memory(user_id=user_id, content="Mine one.")
    await writer.save_memory(user_id=user_id, content="Mine two.")
    await writer.save_memory(user_id=other_user, content="Theirs.")

    removed = await delete_all_memories(db_session, index, user_id=user_id)

    assert removed == 2
    assert list_memories(db_session, user_id=user_id) == ()
    assert len(list_memories(db_session, user_id=other_user)) == 1


async def test_a_failed_extraction_leaves_memory_unchanged_and_the_answer_intact() -> (
    None
):
    writer = RecordingWriter()

    await record_memories_from_turn(
        extractor=ScriptedExtractor(RuntimeError("provider unavailable")),
        writer=writer,
        user_id=uuid7(),
        user_message="Question",
        assistant_message="Answer",
    )

    assert writer.saved == []
