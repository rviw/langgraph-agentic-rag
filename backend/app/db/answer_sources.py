from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, assert_never
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import AnswerCitation, AnswerSource, ChatMessage, DocumentChunk

MAX_CONTEXT_EXCERPT_CHARACTERS = 12_000


@dataclass(frozen=True, slots=True)
class DocumentSourceCandidate:
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    filename: str
    page: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class WebSourceCandidate:
    title: str
    url: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class DocumentSource:
    source_id: UUID
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    filename: str
    page: int
    excerpt: str
    type: Literal["document"] = "document"


@dataclass(frozen=True, slots=True)
class WebSource:
    source_id: UUID
    title: str
    url: str
    excerpt: str
    type: Literal["web"] = "web"


type AnswerSourceSnapshot = DocumentSource | WebSource


@dataclass(frozen=True, slots=True)
class DocumentContext:
    """A passage adjacent to a cited one, shown when a citation is opened."""

    chunk_id: UUID
    chunk_index: int
    page: int
    excerpt: str


@dataclass(frozen=True, slots=True)
class DocumentSourceDetail:
    source: DocumentSource
    context: tuple[DocumentContext, ...]


@dataclass(frozen=True, slots=True)
class WebSourceDetail:
    source: WebSource


type AnswerSourceDetail = DocumentSourceDetail | WebSourceDetail


def _url_hash(url: str) -> str:
    """Hash the URL so uniqueness does not depend on its stored length."""

    return sha256(url.encode()).hexdigest()


def _document_snapshot(source: AnswerSource) -> DocumentSource:
    return DocumentSource(
        source_id=source.id,
        document_id=source.document_id,
        chunk_id=source.document_chunk_id,
        chunk_index=source.document_chunk_index,
        filename=source.document_filename,
        page=source.document_page,
        excerpt=source.document_excerpt,
    )


def _web_snapshot(source: AnswerSource) -> WebSource:
    return WebSource(
        source_id=source.id,
        title=source.web_title,
        url=source.web_url,
        excerpt=source.web_excerpt,
    )


def _snapshot(source: AnswerSource) -> AnswerSourceSnapshot:
    """Read the snapshot fields for the recorded source type."""

    if source.source_type == "document":
        return _document_snapshot(source)
    return _web_snapshot(source)


def _next_capture_index(db_session: Session, execution_id: UUID) -> int:
    current = db_session.exec(
        select(func.max(AnswerSource.capture_index)).where(
            AnswerSource.execution_id == execution_id
        )
    ).one()
    return 0 if current is None else int(current) + 1


def record_document_sources(
    db_session: Session,
    *,
    execution_id: UUID,
    chat_id: UUID,
    candidates: Sequence[DocumentSourceCandidate],
) -> tuple[DocumentSource, ...]:
    """Record document evidence once per execution, reusing earlier captures."""

    existing = {
        row.document_chunk_id: row
        for row in db_session.exec(
            select(AnswerSource).where(
                AnswerSource.execution_id == execution_id,
                AnswerSource.source_type == "document",
            )
        ).all()
    }
    capture_index = _next_capture_index(db_session, execution_id)
    sources: list[DocumentSource] = []

    for candidate in candidates:
        row = existing.get(candidate.chunk_id)
        if row is None:
            row = AnswerSource(
                execution_id=execution_id,
                chat_id=chat_id,
                capture_index=capture_index,
                source_type="document",
                document_id=candidate.document_id,
                document_chunk_id=candidate.chunk_id,
                document_chunk_index=candidate.chunk_index,
                document_page=candidate.page,
                document_filename=candidate.filename,
                document_excerpt=candidate.excerpt,
            )
            db_session.add(row)
            db_session.flush()
            existing[candidate.chunk_id] = row
            capture_index += 1
        sources.append(_document_snapshot(row))

    db_session.commit()
    return tuple(sources)


def record_web_sources(
    db_session: Session,
    *,
    execution_id: UUID,
    chat_id: UUID,
    candidates: Sequence[WebSourceCandidate],
) -> tuple[WebSource, ...]:
    """Record web evidence once per execution, reusing earlier captures."""

    existing = {
        row.web_url_hash: row
        for row in db_session.exec(
            select(AnswerSource).where(
                AnswerSource.execution_id == execution_id,
                AnswerSource.source_type == "web",
            )
        ).all()
    }
    capture_index = _next_capture_index(db_session, execution_id)
    sources: list[WebSource] = []

    for candidate in candidates:
        url_hash = _url_hash(candidate.url)
        row = existing.get(url_hash)
        if row is None:
            row = AnswerSource(
                execution_id=execution_id,
                chat_id=chat_id,
                capture_index=capture_index,
                source_type="web",
                web_url=candidate.url,
                web_url_hash=url_hash,
                web_title=candidate.title,
                web_excerpt=candidate.excerpt,
            )
            db_session.add(row)
            db_session.flush()
            existing[url_hash] = row
            capture_index += 1
        sources.append(_web_snapshot(row))

    db_session.commit()
    return tuple(sources)


def list_execution_sources(
    db_session: Session,
    *,
    execution_id: UUID,
) -> tuple[AnswerSourceSnapshot, ...]:
    """Every piece of evidence captured during one execution, in capture order."""

    return tuple(
        _snapshot(row)
        for row in db_session.exec(
            select(AnswerSource)
            .where(AnswerSource.execution_id == execution_id)
            .order_by(AnswerSource.capture_index)
        ).all()
    )


def publish_citations(
    db_session: Session,
    *,
    assistant_message_id: UUID,
    source_ids: Sequence[UUID],
) -> tuple[AnswerSourceSnapshot, ...]:
    """Attach the cited evidence to a published answer, preserving its order."""

    if not source_ids:
        return ()

    rows = {
        row.id: row
        for row in db_session.exec(
            select(AnswerSource).where(AnswerSource.id.in_(source_ids))
        ).all()
    }
    db_session.add_all(
        [
            AnswerCitation(
                assistant_message_id=assistant_message_id,
                source_id=source_id,
                citation_index=citation_index,
            )
            for citation_index, source_id in enumerate(source_ids)
        ]
    )
    return tuple(_snapshot(rows[source_id]) for source_id in source_ids)


def read_citations(
    db_session: Session,
    *,
    message_ids: Sequence[UUID],
) -> dict[UUID, tuple[AnswerSourceSnapshot, ...]]:
    """Citations for several messages at once, keyed by message."""

    if not message_ids:
        return {}

    rows = db_session.exec(
        select(AnswerCitation, AnswerSource)
        .join(AnswerSource, AnswerSource.id == AnswerCitation.source_id)
        .where(AnswerCitation.assistant_message_id.in_(message_ids))
        .order_by(
            AnswerCitation.assistant_message_id,
            AnswerCitation.citation_index,
        )
    ).all()

    grouped: dict[UUID, list[AnswerSourceSnapshot]] = {}
    for citation, source in rows:
        grouped.setdefault(citation.assistant_message_id, []).append(_snapshot(source))
    return {message_id: tuple(items) for message_id, items in grouped.items()}


def read_source_detail(
    db_session: Session,
    *,
    chat_id: UUID,
    message_id: UUID,
    source_id: UUID,
) -> AnswerSourceDetail | None:
    """Read evidence cited by this message in the caller's owned chat."""

    source = db_session.exec(
        select(AnswerSource)
        .join(AnswerCitation, AnswerCitation.source_id == AnswerSource.id)
        .join(ChatMessage, ChatMessage.id == AnswerCitation.assistant_message_id)
        .where(
            AnswerSource.id == source_id,
            AnswerSource.chat_id == chat_id,
            ChatMessage.id == message_id,
            ChatMessage.chat_id == chat_id,
        )
    ).one_or_none()
    if source is None:
        return None

    snapshot = _snapshot(source)
    if isinstance(snapshot, WebSource):
        return WebSourceDetail(source=snapshot)
    if isinstance(snapshot, DocumentSource):
        neighbors = db_session.exec(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == snapshot.document_id,
                DocumentChunk.chunk_index.in_(
                    [snapshot.chunk_index - 1, snapshot.chunk_index + 1]
                ),
            )
            .order_by(DocumentChunk.chunk_index)
        ).all()
        return DocumentSourceDetail(
            source=snapshot,
            context=tuple(
                DocumentContext(
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    page=chunk.page_number,
                    excerpt=chunk.content[:MAX_CONTEXT_EXCERPT_CHARACTERS],
                )
                for chunk in neighbors
            ),
        )
    assert_never(snapshot)
