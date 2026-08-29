import asyncio
import logging
from typing import Protocol
from uuid import UUID, uuid7

from langgraph.store.base import BaseStore
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.models import Memory

logger = logging.getLogger(__name__)


def memory_namespace(user_id: UUID) -> tuple[str, ...]:
    """Each user's memories live in their own vector namespace."""

    return ("users", str(user_id), "memories")


class MemoryWriter(Protocol):
    async def save_memory(self, *, user_id: UUID, content: str) -> None: ...


class IndexedMemoryWriter:
    """Save a memory to the vector index and the database, or to neither."""

    def __init__(self, engine: Engine, memory_index: BaseStore) -> None:
        self._engine = engine
        self._memory_index = memory_index

    async def save_memory(self, *, user_id: UUID, content: str) -> None:
        memory_id = uuid7()
        # One identifier keys both records, so they can be kept in step.
        await self._memory_index.aput(
            memory_namespace(user_id),
            str(memory_id),
            {"memory": content},
            index=["memory"],
        )

        try:
            await asyncio.to_thread(
                _insert_memory,
                self._engine,
                memory_id=memory_id,
                user_id=user_id,
                content=content,
            )
        except Exception:
            # Leaving an indexed vector with no row would let a memory be
            # recalled that the user can never see or delete.
            try:
                await self._memory_index.adelete(
                    memory_namespace(user_id),
                    str(memory_id),
                )
            except Exception:
                logger.warning("Rolling back an indexed memory failed")
            raise


def _insert_memory(
    engine: Engine,
    *,
    memory_id: UUID,
    user_id: UUID,
    content: str,
) -> None:
    with Session(engine) as db_session:
        db_session.add(Memory(id=memory_id, user_id=user_id, content=content))
        db_session.commit()


def list_memories(db_session: Session, *, user_id: UUID) -> tuple[Memory, ...]:
    return tuple(
        db_session.exec(
            select(Memory)
            .where(Memory.user_id == user_id)
            .order_by(Memory.created_at.desc(), Memory.id.desc())
        ).all()
    )


async def delete_memory(
    db_session: Session,
    memory_index: BaseStore,
    *,
    memory_id: UUID,
    user_id: UUID,
) -> bool:
    """Forget one memory, clearing the index before the row it belongs to."""

    memory = db_session.exec(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    ).one_or_none()
    if memory is None:
        return False

    await memory_index.adelete(memory_namespace(user_id), str(memory.id))
    db_session.delete(memory)
    db_session.commit()
    return True


async def delete_all_memories(
    db_session: Session,
    memory_index: BaseStore,
    *,
    user_id: UUID,
) -> int:
    memories = list_memories(db_session, user_id=user_id)
    for memory in memories:
        await memory_index.adelete(memory_namespace(user_id), str(memory.id))
        db_session.delete(memory)
    if memories:
        db_session.commit()
    return len(memories)
