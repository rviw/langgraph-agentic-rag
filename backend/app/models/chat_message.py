from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from sqlalchemy import (
    BigInteger,
    DateTime,
    Text,
    UniqueConstraint,
    func,
)
from sqlmodel import Field, SQLModel

ChatMessageRole = Literal["user", "assistant"]


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"
    __table_args__ = (
        # One position per chat keeps the transcript order unambiguous.
        UniqueConstraint(
            "chat_id",
            "message_index",
            name="uq_chat_messages_message_index",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    chat_id: UUID = Field(
        foreign_key="chats.id",
        ondelete="CASCADE",
        nullable=False,
    )
    message_index: int = Field(sa_type=BigInteger, nullable=False)
    role: str = Field(max_length=9, nullable=False)
    content: str = Field(sa_type=Text, nullable=False)
    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
