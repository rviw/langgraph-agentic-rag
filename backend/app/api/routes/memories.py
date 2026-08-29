from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUserDep, DbSessionDep, MemoryIndexDep
from app.db import memories as memory_store
from app.models import Memory
from app.schemas.memories import MemoryResponse

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryResponse])
def list_memories(
    db_session: DbSessionDep,
    current_user: CurrentUserDep,
) -> tuple[Memory, ...]:
    """List this user's saved memories, newest first."""

    return memory_store.list_memories(db_session, user_id=current_user.id)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: UUID,
    db_session: DbSessionDep,
    memory_index: MemoryIndexDep,
    current_user: CurrentUserDep,
) -> None:
    deleted = await memory_store.delete_memory(
        db_session,
        memory_index,
        memory_id=memory_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This memory is no longer available.",
        )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_memories(
    db_session: DbSessionDep,
    memory_index: MemoryIndexDep,
    current_user: CurrentUserDep,
) -> None:
    await memory_store.delete_all_memories(
        db_session,
        memory_index,
        user_id=current_user.id,
    )
