import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from uuid import UUID

from langchain_core.embeddings import Embeddings
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from app.models import Document, DocumentChunk
from app.models.document import DocumentIndexingErrorCode
from app.rag.indexing import (
    DocumentValidationError,
    IndexedChunk,
    prepare_document_index,
)
from app.storage.documents import DocumentObjectNotFound, DocumentStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedDocument:
    document_id: UUID
    storage_object_path: str


def claim_next_document(db_session: Session) -> ClaimedDocument | None:
    """Take the oldest queued document, skipping any row already claimed."""

    document = db_session.exec(
        select(Document)
        .where(Document.status == "indexing_pending")
        .order_by(Document.created_at, Document.id)
        .limit(1)
        .with_for_update(of=Document, skip_locked=True)
    ).one_or_none()
    if document is None:
        db_session.rollback()
        return None

    claim = ClaimedDocument(
        document_id=document.id,
        storage_object_path=document.storage_object_path,
    )
    document.status = "indexing"
    document.indexing_error_code = None
    db_session.add(document)
    db_session.commit()
    return claim


def _locked_claim(db_session: Session, claim: ClaimedDocument) -> Document | None:
    """Re-read the claimed row, giving up if it no longer belongs to this claim."""

    document = db_session.exec(
        select(Document)
        .where(Document.id == claim.document_id)
        .with_for_update(of=Document)
    ).one_or_none()
    if document is None or document.status != "indexing":
        db_session.rollback()
        return None
    return document


def finish_indexing(
    db_session: Session,
    *,
    claim: ClaimedDocument,
    chunks: list[IndexedChunk],
    embedding_model: str,
) -> bool:
    document = _locked_claim(db_session, claim)
    if document is None:
        return False

    db_session.add_all(
        [
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                page_number=chunk.page_number,
                content=chunk.content,
                embedding=chunk.embedding,
            )
            for index, chunk in enumerate(chunks)
        ]
    )
    document.status = "ready"
    document.embedding_model = embedding_model
    document.indexing_error_code = None
    db_session.add(document)
    db_session.commit()
    return True


def fail_indexing(
    db_session: Session,
    *,
    claim: ClaimedDocument,
    error_code: DocumentIndexingErrorCode,
) -> bool:
    document = _locked_claim(db_session, claim)
    if document is None:
        return False

    document.status = "indexing_failed"
    document.indexing_error_code = error_code
    db_session.add(document)
    db_session.commit()
    return True


def _index_claim(
    *,
    engine: Engine,
    claim: ClaimedDocument,
    storage: DocumentStorage,
    embeddings: Embeddings,
    embedding_model: str,
) -> None:
    error_code: DocumentIndexingErrorCode
    try:
        file_data = storage.download(claim.storage_object_path)
        chunks = prepare_document_index(
            file_data=file_data,
            embeddings=embeddings,
        )
    except DocumentObjectNotFound:
        error_code = "storage_missing"
    except DocumentValidationError:
        error_code = "invalid_pdf"
    except Exception:
        error_code = "unexpected_failure"
    else:
        with Session(engine) as db_session:
            finish_indexing(
                db_session,
                claim=claim,
                chunks=chunks,
                embedding_model=embedding_model,
            )
        return

    logger.warning(
        "Document indexing failed",
        extra={
            "document_id": str(claim.document_id),
            "indexing_error_code": error_code,
        },
    )
    with Session(engine) as db_session:
        fail_indexing(db_session, claim=claim, error_code=error_code)


def index_next_document(
    *,
    engine: Engine,
    storage: DocumentStorage,
    embeddings: Embeddings,
    embedding_model: str,
) -> bool:
    """Index at most one queued document. Returns whether one was claimed."""

    with Session(engine) as db_session:
        claim = claim_next_document(db_session)
    if claim is None:
        return False

    _index_claim(
        engine=engine,
        claim=claim,
        storage=storage,
        embeddings=embeddings,
        embedding_model=embedding_model,
    )
    return True


class DocumentIndexingRunner:
    """Indexes queued documents one at a time, woken by the request that queued them."""

    def __init__(self, index_next: Callable[[], bool]) -> None:
        self._index_next = index_next
        self._wake = asyncio.Event()
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    @classmethod
    def for_database(
        cls,
        *,
        engine: Engine,
        storage: DocumentStorage,
        embeddings: Embeddings,
        embedding_model: str,
    ) -> DocumentIndexingRunner:
        return cls(
            partial(
                index_next_document,
                engine=engine,
                storage=storage,
                embeddings=embeddings,
                embedding_model=embedding_model,
            )
        )

    async def start(self) -> None:
        # Wake once at startup so documents queued before this process drain.
        self._wake.set()
        self._task = asyncio.create_task(self._run(), name="document-indexing")

    def request_run(self) -> None:
        """Ask for a drain. Repeated calls before a drain collapse into one."""

        if not self._stopping:
            self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stopping:
            await self._wake.wait()
            self._wake.clear()
            while not self._stopping:
                try:
                    # Indexing is blocking work, so keep it off the event loop.
                    claimed = await asyncio.to_thread(self._index_next)
                except Exception:
                    logger.exception("Document indexing cycle failed")
                    break
                if not claimed:
                    break
