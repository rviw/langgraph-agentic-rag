from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import DateTime, Index, Text, func
from sqlmodel import Field, SQLModel

MEMORY_CONTENT_MAX_LENGTH = 500


class Memory(SQLModel, table=True):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_user_created", "user_id", "created_at", "id"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    user_id: UUID = Field(
        foreign_key="auth.users.id",
        ondelete="CASCADE",
        nullable=False,
    )
    content: str = Field(sa_type=Text, nullable=False)
    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
