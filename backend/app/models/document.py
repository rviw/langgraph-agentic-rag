from datetime import datetime
from typing import Literal
from uuid import UUID, uuid7

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlmodel import Field, SQLModel

EMBEDDING_DIMENSIONS = 1536

DocumentStatus = Literal[
    "upload_pending",
    "indexing_pending",
    "indexing",
    "ready",
    "indexing_failed",
]
DocumentIndexingErrorCode = Literal[
    "invalid_pdf",
    "storage_missing",
    "unexpected_failure",
]


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    __table_args__ = (
        # The database, not the API, guarantees one document per chat.
        UniqueConstraint("chat_id", name="uq_documents_chat_id"),
        Index(
            "ix_documents_indexing_queue",
            "created_at",
            "id",
            postgresql_where=text("status = 'indexing_pending'"),
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    chat_id: UUID = Field(
        foreign_key="chats.id",
        ondelete="CASCADE",
        nullable=False,
    )
    original_filename: str = Field(max_length=255, nullable=False)
    media_type: str = Field(max_length=100, nullable=False)
    size_bytes: int = Field(sa_type=BigInteger, nullable=False)
    status: str = Field(
        default="upload_pending",
        max_length=20,
        nullable=False,
        sa_column_kwargs={"server_default": "upload_pending"},
    )
    embedding_model: str | None = Field(default=None, max_length=100)
    storage_object_path: str = Field(max_length=500, nullable=False)
    indexing_error_code: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = Field(
        default=None,
        nullable=False,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"server_default": func.now()},
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
        # Supports the lexical branch of hybrid retrieval.
        Index(
            "ix_document_chunks_content_fts",
            text("to_tsvector('simple'::regconfig, content)"),
            postgresql_using="gin",
        ),
    )

    id: UUID = Field(default_factory=uuid7, primary_key=True)
    document_id: UUID = Field(
        foreign_key="documents.id",
        ondelete="CASCADE",
        nullable=False,
    )
    chunk_index: int = Field(nullable=False)
    page_number: int = Field(nullable=False)
    content: str = Field(sa_type=Text, nullable=False)
    embedding: list[float] = Field(
        sa_type=VECTOR(EMBEDDING_DIMENSIONS),
        nullable=False,
    )
