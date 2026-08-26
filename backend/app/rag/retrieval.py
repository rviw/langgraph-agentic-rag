import json
import logging
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from langchain_core.embeddings import Embeddings
from langchain_core.tools import BaseTool, tool
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolRuntime
from pydantic import Field, StringConstraints
from sqlalchemy import func, literal, literal_column, tuple_, union_all
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.agent.context import AgentContext
from app.agent.phases import report_phase
from app.models import Document, DocumentChunk
from app.rag.reranking import DocumentReranker, RerankDocument

logger = logging.getLogger(__name__)

# Each branch contributes candidates; reciprocal rank fusion merges them.
_BRANCH_LIMIT = 20
_SEED_LIMIT = 4
_CONTEXT_CHUNK_LIMIT = 12
_CONTEXT_CHARACTER_LIMIT = 12_000
# The usual reciprocal-rank-fusion constant: it damps the influence of top ranks.
_RRF_K = 60
_SIMPLE_REGCONFIG = literal_column("'simple'::regconfig")

# Normalizing at the schema boundary means retrieval receives usable text only.
_DocumentQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    filename: str
    page: int
    content: str


def _readable_chunks(chat_id: UUID) -> Any:
    """Chunks this chat may cite: its own document, once indexing finished."""

    return (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            Document.original_filename,
            DocumentChunk.page_number,
            DocumentChunk.content,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.chat_id == chat_id, Document.status == "ready")
    )


def _chunk(row: Any) -> RetrievedChunk:
    chunk_id, document_id, chunk_index, filename, page, content = row
    return RetrievedChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        filename=filename,
        page=page,
        content=content,
    )


def fuse_by_reciprocal_rank(
    dense: list[RetrievedChunk],
    lexical: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Merge two ranked lists so agreement outranks a single strong branch."""

    candidates: dict[UUID, RetrievedChunk] = {}
    scores: dict[UUID, float] = {}
    ranks: dict[UUID, list[int]] = {}

    for branch in (dense, lexical):
        for rank, candidate in enumerate(branch, start=1):
            candidates.setdefault(candidate.chunk_id, candidate)
            scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0.0) + 1 / (
                _RRF_K + rank
            )
            ranks.setdefault(candidate.chunk_id, []).append(rank)

    return sorted(
        candidates.values(),
        # Ties fall back to the best branch rank, then the identifier, so the
        # order is total and repeatable.
        key=lambda candidate: (
            -scores[candidate.chunk_id],
            min(ranks[candidate.chunk_id]),
            str(candidate.chunk_id),
        ),
    )


def expand_with_neighbors(
    *,
    seeds: list[RetrievedChunk],
    neighbors: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Place seeds first, then adjacent chunks, bounded by count and length."""

    by_position = {
        (candidate.document_id, candidate.chunk_index): candidate
        for candidate in neighbors
    }
    ordered: list[RetrievedChunk] = []
    seen: set[UUID] = set()

    for seed in seeds:
        if seed.chunk_id not in seen:
            seen.add(seed.chunk_id)
            ordered.append(seed)

    for seed in seeds:
        for offset in (-1, 1):
            neighbor = by_position.get((seed.document_id, seed.chunk_index + offset))
            if neighbor is not None and neighbor.chunk_id not in seen:
                seen.add(neighbor.chunk_id)
                ordered.append(neighbor)

    results: list[RetrievedChunk] = []
    characters = 0
    for candidate in ordered:
        if len(results) >= _CONTEXT_CHUNK_LIMIT:
            break
        remaining = _CONTEXT_CHARACTER_LIMIT - characters
        if remaining <= 0:
            break
        content = candidate.content[:remaining]
        results.append(
            RetrievedChunk(
                document_id=candidate.document_id,
                chunk_id=candidate.chunk_id,
                chunk_index=candidate.chunk_index,
                filename=candidate.filename,
                page=candidate.page,
                content=content,
            )
        )
        characters += len(content)
        if len(content) < len(candidate.content):
            break

    return results


def search_candidates(
    *,
    db_session: Session,
    embeddings: Embeddings,
    chat_id: UUID,
    query: str,
) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
    """Run the dense and lexical branches in one database round trip."""

    readable = _readable_chunks(chat_id)
    distance = DocumentChunk.embedding.cosine_distance(embeddings.embed_query(query))
    dense_statement = (
        readable.add_columns(
            literal("dense").label("branch"),
            func.row_number()
            .over(order_by=(distance, DocumentChunk.id))
            .label("branch_rank"),
        )
        .order_by(distance, DocumentChunk.id)
        .limit(_BRANCH_LIMIT)
    )

    document_vector = func.to_tsvector(_SIMPLE_REGCONFIG, DocumentChunk.content)
    lexical_query = func.plainto_tsquery(_SIMPLE_REGCONFIG, query)
    lexical_rank = func.ts_rank_cd(document_vector, lexical_query)
    lexical_statement = (
        readable.add_columns(
            literal("lexical").label("branch"),
            func.row_number()
            .over(order_by=(lexical_rank.desc(), DocumentChunk.id))
            .label("branch_rank"),
        )
        .where(document_vector.bool_op("@@")(lexical_query))
        .order_by(lexical_rank.desc(), DocumentChunk.id)
        .limit(_BRANCH_LIMIT)
    )

    # One round trip returns both branches, each tagged with its own rank.
    union = union_all(dense_statement, lexical_statement).subquery()
    rows = db_session.exec(
        select(
            union.c.id,
            union.c.document_id,
            union.c.chunk_index,
            union.c.original_filename,
            union.c.page_number,
            union.c.content,
            union.c.branch,
            union.c.branch_rank,
        ).order_by(union.c.branch, union.c.branch_rank)
    ).all()

    branches: dict[str, list[RetrievedChunk]] = {"dense": [], "lexical": []}
    for row in rows:
        values = tuple(row)
        branches[values[6]].append(_chunk(values[:6]))

    return branches["dense"], branches["lexical"]


def load_neighbors(
    *,
    db_session: Session,
    chat_id: UUID,
    seeds: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Read adjacent chunks from ready documents, excluding known seeds."""

    seed_positions = {(seed.document_id, seed.chunk_index) for seed in seeds}
    wanted = {
        (seed.document_id, seed.chunk_index + offset)
        for seed in seeds
        for offset in (-1, 1)
        if seed.chunk_index + offset >= 0
    } - seed_positions
    if not wanted:
        return []

    rows = db_session.exec(
        _readable_chunks(chat_id)
        .where(
            tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(
                sorted(wanted, key=lambda item: (str(item[0]), item[1]))
            )
        )
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    ).all()
    return [_chunk(row) for row in rows]


def retrieve_document_chunks(
    *,
    db_session: Session,
    embeddings: Embeddings,
    reranker: DocumentReranker,
    chat_id: UUID,
    query: str,
) -> list[RetrievedChunk]:
    """Find passages by meaning and by wording, then rerank and expand them."""

    dense, lexical = search_candidates(
        db_session=db_session,
        embeddings=embeddings,
        chat_id=chat_id,
        query=query,
    )
    fused = fuse_by_reciprocal_rank(dense, lexical)
    seeds: list[RetrievedChunk] = []
    if fused:
        ranked_positions = reranker.rerank(
            query=query,
            documents=[
                RerankDocument(index=candidate.chunk_index, text=candidate.content)
                for candidate in fused
            ],
        )
        seeds = [fused[position] for position in ranked_positions][:_SEED_LIMIT]

    neighbors = load_neighbors(db_session=db_session, chat_id=chat_id, seeds=seeds)
    chunks = expand_with_neighbors(seeds=seeds, neighbors=neighbors)
    logger.info(
        "document_search",
        extra={
            "chat_id": str(chat_id),
            "dense_count": len(dense),
            "lexical_count": len(lexical),
            "fused_count": len(fused),
            "result_count": len(chunks),
        },
    )
    return chunks


def create_search_documents_tool(
    *,
    engine: Engine,
    embeddings: Embeddings,
    reranker: DocumentReranker,
) -> BaseTool:
    @tool
    def search_documents(
        query: Annotated[
            _DocumentQuery,
            Field(description="A focused search query for the uploaded PDF"),
        ],
        runtime: ToolRuntime[AgentContext, MessagesState],
    ) -> str:
        """Search the PDF uploaded to the current chat."""

        report_phase("searching")
        with Session(engine) as db_session:
            chunks = retrieve_document_chunks(
                db_session=db_session,
                embeddings=embeddings,
                reranker=reranker,
                chat_id=runtime.context.chat_id,
                query=query,
            )
        report_phase("reading")
        return json.dumps(
            {
                "results": [
                    {
                        "filename": chunk.filename,
                        "page": chunk.page,
                        "content": chunk.content,
                    }
                    for chunk in chunks
                ]
            },
            ensure_ascii=False,
        )

    return search_documents
