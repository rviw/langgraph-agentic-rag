from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import DateTime, Index, func
from sqlmodel import Field, SQLModel

DEFAULT_CHAT_TITLE = "New chat"
CHAT_TITLE_MAX_LENGTH = 80


class Chat(SQLModel, table=True):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user_id_id", "user_id", "id"),)

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    user_id: UUID = Field(
        foreign_key="auth.users.id",
        ondelete="CASCADE",
        nullable=False,
    )
    title: str = Field(
        default=DEFAULT_CHAT_TITLE,
        max_length=CHAT_TITLE_MAX_LENGTH,
        nullable=False,
    )
    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
