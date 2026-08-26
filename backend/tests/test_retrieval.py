from collections.abc import Callable, Sequence
from uuid import UUID

import pytest
from sqlmodel import Session

from app.models import Chat, Document, DocumentChunk
from app.rag.reranking import RerankDocument
from app.rag.retrieval import (
    RetrievedChunk,
    expand_with_neighbors,
    fuse_by_reciprocal_rank,
    retrieve_document_chunks,
)
from app.storage.documents import document_object_path
from tests.support.embeddings import DeterministicEmbeddings


class PoolOrderReranker:
    """Keeps the fused order, so tests observe retrieval rather than a provider."""

    def rerank(
        self,
        *,
        query: str,
        documents: Sequence[RerankDocument],
    ) -> list[int]:
        del query
        return list(range(min(4, len(documents))))


@pytest.fixture
def reranker() -> PoolOrderReranker:
    return PoolOrderReranker()


@pytest.fixture
def embeddings() -> DeterministicEmbeddings:
    return DeterministicEmbeddings()


@pytest.fixture
def indexed_chat(
    db_session: Session,
    create_user: Callable[..., UUID],
    embeddings: DeterministicEmbeddings,
):
    """Create a ready document whose chunks are indexed for retrieval."""

    def factory(
        contents: list[str],
        *,
        status: str = "ready",
        filename: str = "report.pdf",
    ) -> Chat:
        user_id = create_user()
        chat = Chat(user_id=user_id)
        db_session.add(chat)
        db_session.commit()
        db_session.refresh(chat)

        document = Document(
            chat_id=chat.id,
            original_filename=filename,
            media_type="application/pdf",
            size_bytes=2048,
            status=status,
            storage_object_path=document_object_path(user_id, chat.id),
        )
        db_session.add(document)
        db_session.commit()
        db_session.refresh(document)

        vectors = embeddings.embed_documents(contents)
        db_session.add_all(
            [
                DocumentChunk(
                    document_id=document.id,
                    chunk_index=index,
                    page_number=index + 1,
                    content=content,
                    embedding=vector,
                )
                for index, (content, vector) in enumerate(
                    zip(contents, vectors, strict=True)
                )
            ]
        )
        db_session.commit()
        return chat

    return factory


def test_a_matching_passage_is_retrieved_from_the_chats_document(
    db_session: Session,
    indexed_chat,
    embeddings: DeterministicEmbeddings,
    reranker: PoolOrderReranker,
) -> None:
    chat = indexed_chat(
        [
            "Reciprocal rank fusion merges two ranked candidate lists.",
            "Cosine distance compares embedding vectors.",
            "Storage keeps uploaded PDF bytes private.",
        ]
    )

    results = retrieve_document_chunks(
        db_session=db_session,
        embeddings=embeddings,
        reranker=reranker,
        chat_id=chat.id,
        query="reciprocal rank fusion",
    )

    assert results
    assert any("Reciprocal rank fusion" in chunk.content for chunk in results)
    assert all(chunk.filename == "report.pdf" for chunk in results)


def test_retrieval_never_crosses_into_another_chats_document(
    db_session: Session,
    indexed_chat,
    embeddings: DeterministicEmbeddings,
    reranker: PoolOrderReranker,
) -> None:
    mine = indexed_chat(["My own document about vector search."])
    indexed_chat(["Another chat's confidential salary table."], filename="other.pdf")

    results = retrieve_document_chunks(
        db_session=db_session,
        embeddings=embeddings,
        reranker=reranker,
        chat_id=mine.id,
        query="confidential salary table",
    )

    assert all(chunk.filename == "report.pdf" for chunk in results)
    assert not any("salary" in chunk.content for chunk in results)


def test_a_document_that_is_not_ready_is_not_searchable(
    db_session: Session,
    indexed_chat,
    embeddings: DeterministicEmbeddings,
    reranker: PoolOrderReranker,
) -> None:
    chat = indexed_chat(
        ["Indexing has not finished for this passage."],
        status="indexing",
    )

    results = retrieve_document_chunks(
        db_session=db_session,
        embeddings=embeddings,
        reranker=reranker,
        chat_id=chat.id,
        query="indexing has not finished",
    )

    assert results == []


def test_a_retrieved_passage_brings_its_neighbours_for_context(
    db_session: Session,
    indexed_chat,
    embeddings: DeterministicEmbeddings,
    reranker: PoolOrderReranker,
) -> None:
    chat = indexed_chat(
        [
            "Chunk zero introduces the topic.",
            "Chunk one states the unusual keyword zarquon precisely.",
            "Chunk two continues the explanation.",
        ]
    )

    results = retrieve_document_chunks(
        db_session=db_session,
        embeddings=embeddings,
        reranker=reranker,
        chat_id=chat.id,
        query="zarquon",
    )

    indices = [chunk.chunk_index for chunk in results]
    assert 1 in indices
    # The passage before and after are included as adjacent context.
    assert {0, 2} <= set(indices)


def _chunk(chunk_index: int, name: str) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=UUID(int=1),
        chunk_id=UUID(int=chunk_index + 100),
        chunk_index=chunk_index,
        filename="report.pdf",
        page=chunk_index + 1,
        content=name,
    )


def test_a_passage_both_branches_found_outranks_one_branch_alone() -> None:
    agreed = _chunk(1, "found by both")
    dense_only = _chunk(2, "dense only")
    lexical_only = _chunk(3, "lexical only")

    fused = fuse_by_reciprocal_rank(
        [dense_only, agreed],
        [lexical_only, agreed],
    )

    assert fused[0].content == "found by both"


def test_context_expansion_stays_within_its_character_budget() -> None:
    seeds = [_chunk(index, "x" * 5000) for index in range(4)]

    expanded = expand_with_neighbors(seeds=seeds, neighbors=[])

    assert sum(len(chunk.content) for chunk in expanded) <= 12_000
