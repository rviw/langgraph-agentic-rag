"""create baseline schema

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Vector search needs the extension before any embedding column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_user_id_id", "chats", ["user_id", "id"], unique=False)
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memories_user_created",
        "memories",
        ["user_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "answer_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("capture_index", sa.Integer(), nullable=False),
        sa.Column(
            "source_type", sqlmodel.sql.sqltypes.AutoString(length=12), nullable=False
        ),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("document_chunk_index", sa.Integer(), nullable=True),
        sa.Column("document_page", sa.Integer(), nullable=True),
        sa.Column(
            "document_filename",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("document_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "web_url", sqlmodel.sql.sqltypes.AutoString(length=2048), nullable=True
        ),
        sa.Column(
            "web_url_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column(
            "web_title", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True
        ),
        sa.Column("web_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_id", "capture_index", name="uq_answer_sources_capture_index"
        ),
    )
    op.create_index(
        "ix_answer_sources_chat",
        "answer_sources",
        ["chat_id", "execution_id"],
        unique=False,
    )
    op.create_index(
        "uq_answer_sources_document_chunk",
        "answer_sources",
        ["execution_id", "document_chunk_id"],
        unique=True,
        postgresql_where=sa.text("source_type = 'document'"),
    )
    op.create_index(
        "uq_answer_sources_web_url",
        "answer_sources",
        ["execution_id", "web_url_hash"],
        unique=True,
        postgresql_where=sa.text("source_type = 'web'"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("message_index", sa.BigInteger(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=9), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_id", "message_index", name="uq_chat_messages_message_index"
        ),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column(
            "original_filename",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column(
            "media_type", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False
        ),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            server_default="upload_pending",
            nullable=False,
        ),
        sa.Column(
            "embedding_model",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
        sa.Column(
            "storage_object_path",
            sqlmodel.sql.sqltypes.AutoString(length=500),
            nullable=False,
        ),
        sa.Column(
            "indexing_error_code",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", name="uq_documents_chat_id"),
    )
    op.create_index(
        "ix_documents_indexing_queue",
        "documents",
        ["created_at", "id"],
        unique=False,
        postgresql_where=sa.text("status = 'indexing_pending'"),
    )
    op.create_table(
        "answer_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assistant_message_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["answer_sources.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistant_message_id",
            "citation_index",
            name="uq_answer_citations_message_citation_index",
        ),
        sa.UniqueConstraint(
            "assistant_message_id",
            "source_id",
            name="uq_answer_citations_message_source",
        ),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "chunk_index",
            name="uq_document_chunks_document_id_chunk_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_content_fts",
        "document_chunks",
        [sa.literal_column("to_tsvector('simple'::regconfig, content)")],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_document_chunks_content_fts",
        table_name="document_chunks",
        postgresql_using="gin",
    )
    op.drop_table("document_chunks")
    op.drop_table("answer_citations")
    op.drop_index(
        "ix_documents_indexing_queue",
        table_name="documents",
        postgresql_where=sa.text("status = 'indexing_pending'"),
    )
    op.drop_table("documents")
    op.drop_table("chat_messages")
    op.drop_index(
        "uq_answer_sources_web_url",
        table_name="answer_sources",
        postgresql_where=sa.text("source_type = 'web'"),
    )
    op.drop_index(
        "uq_answer_sources_document_chunk",
        table_name="answer_sources",
        postgresql_where=sa.text("source_type = 'document'"),
    )
    op.drop_index("ix_answer_sources_chat", table_name="answer_sources")
    op.drop_table("answer_sources")
    op.drop_index("ix_memories_user_created", table_name="memories")
    op.drop_table("memories")
    op.drop_index("ix_chats_user_id_id", table_name="chats")
    op.drop_table("chats")
