from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from sqlalchemy import (
    DateTime,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlmodel import Field, SQLModel

AnswerSourceType = Literal["document", "web"]


class AnswerSource(SQLModel, table=True):
    """Evidence captured during one chat execution, immutable once recorded."""

    __tablename__ = "answer_sources"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "capture_index",
            name="uq_answer_sources_capture_index",
        ),
        # Capturing the same evidence twice in one execution reuses the first row.
        Index(
            "uq_answer_sources_document_chunk",
            "execution_id",
            "document_chunk_id",
            unique=True,
            postgresql_where=text("source_type = 'document'"),
        ),
        Index(
            "uq_answer_sources_web_url",
            "execution_id",
            "web_url_hash",
            unique=True,
            postgresql_where=text("source_type = 'web'"),
        ),
        Index("ix_answer_sources_chat", "chat_id", "execution_id"),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    execution_id: UUID = Field(nullable=False)
    chat_id: UUID = Field(
        foreign_key="chats.id",
        ondelete="CASCADE",
        nullable=False,
    )
    capture_index: int = Field(nullable=False)
    source_type: str = Field(max_length=12, nullable=False)

    document_id: UUID | None = Field(default=None)
    document_chunk_id: UUID | None = Field(default=None)
    document_chunk_index: int | None = Field(default=None)
    document_page: int | None = Field(default=None)
    document_filename: str | None = Field(default=None, max_length=255)
    document_excerpt: str | None = Field(default=None, sa_type=Text)

    web_url: str | None = Field(default=None, max_length=2048)
    web_url_hash: str | None = Field(default=None, max_length=64)
    web_title: str | None = Field(default=None, max_length=200)
    web_excerpt: str | None = Field(default=None, sa_type=Text)

    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )


class AnswerCitation(SQLModel, table=True):
    """Ordered link from one published assistant message to the evidence it cites."""

    __tablename__ = "answer_citations"
    __table_args__ = (
        UniqueConstraint(
            "assistant_message_id",
            "citation_index",
            name="uq_answer_citations_message_citation_index",
        ),
        UniqueConstraint(
            "assistant_message_id",
            "source_id",
            name="uq_answer_citations_message_source",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    assistant_message_id: UUID = Field(
        foreign_key="chat_messages.id",
        ondelete="CASCADE",
        nullable=False,
    )
    source_id: UUID = Field(
        foreign_key="answer_sources.id",
        ondelete="CASCADE",
        nullable=False,
    )
    citation_index: int = Field(nullable=False)
    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )
