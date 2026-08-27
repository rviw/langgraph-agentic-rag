from typing import Annotated, Literal, assert_never
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.answer_sources import (
    AnswerSourceDetail,
    AnswerSourceSnapshot,
    DocumentContext,
    DocumentSource,
    DocumentSourceDetail,
    WebSource,
    WebSourceDetail,
)


class DocumentCitationResponse(BaseModel):
    source_id: UUID
    type: Literal["document"] = "document"
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    filename: str
    page: int
    excerpt: str


class WebCitationResponse(BaseModel):
    source_id: UUID
    type: Literal["web"] = "web"
    title: str
    url: str
    excerpt: str


CitationResponse = Annotated[
    DocumentCitationResponse | WebCitationResponse,
    Field(discriminator="type"),
]


class DocumentContextResponse(BaseModel):
    chunk_id: UUID
    chunk_index: int
    page: int
    excerpt: str


class DocumentSourceDetailResponse(DocumentCitationResponse):
    context: list[DocumentContextResponse]


class WebSourceDetailResponse(WebCitationResponse):
    pass


SourceDetailResponse = Annotated[
    DocumentSourceDetailResponse | WebSourceDetailResponse,
    Field(discriminator="type"),
]


def citation_response(source: AnswerSourceSnapshot) -> CitationResponse:
    if isinstance(source, DocumentSource):
        return DocumentCitationResponse(
            source_id=source.source_id,
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            chunk_index=source.chunk_index,
            filename=source.filename,
            page=source.page,
            excerpt=source.excerpt,
        )
    if isinstance(source, WebSource):
        return WebCitationResponse(
            source_id=source.source_id,
            title=source.title,
            url=source.url,
            excerpt=source.excerpt,
        )
    assert_never(source)


def citation_responses(
    sources: tuple[AnswerSourceSnapshot, ...],
) -> list[CitationResponse]:
    return [citation_response(source) for source in sources]


def _context_response(context: DocumentContext) -> DocumentContextResponse:
    return DocumentContextResponse(
        chunk_id=context.chunk_id,
        chunk_index=context.chunk_index,
        page=context.page,
        excerpt=context.excerpt,
    )


def source_detail_response(detail: AnswerSourceDetail) -> SourceDetailResponse:
    if isinstance(detail, DocumentSourceDetail):
        source = detail.source
        return DocumentSourceDetailResponse(
            source_id=source.source_id,
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            chunk_index=source.chunk_index,
            filename=source.filename,
            page=source.page,
            excerpt=source.excerpt,
            context=[_context_response(item) for item in detail.context],
        )
    if isinstance(detail, WebSourceDetail):
        return WebSourceDetailResponse(
            source_id=detail.source.source_id,
            title=detail.source.title,
            url=detail.source.url,
            excerpt=detail.source.excerpt,
        )
    assert_never(detail)
