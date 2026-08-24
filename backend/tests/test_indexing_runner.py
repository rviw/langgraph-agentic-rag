import asyncio
from collections.abc import Callable
from uuid import UUID

import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.models import Chat, Document, DocumentChunk
from app.rag.runner import (
    DocumentIndexingRunner,
    claim_next_document,
    index_next_document,
)
from app.storage.documents import document_object_path
from tests.conftest import FakeDocumentStorage
from tests.support.embeddings import DeterministicEmbeddings
from tests.support.pdf import pdf_bytes


@pytest.fixture
def queued_document(
    db_session: Session,
    create_user: Callable[..., UUID],
    document_storage: FakeDocumentStorage,
) -> Document:
    """A document waiting to be indexed, with its bytes already in Storage."""

    user_id = create_user()
    chat = Chat(user_id=user_id)
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)

    document = Document(
        chat_id=chat.id,
        original_filename="report.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        status="indexing_pending",
        storage_object_path=document_object_path(user_id, chat.id),
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    document_storage.upload(
        document.storage_object_path,
        pdf_bytes(["Retrieval augmented generation grounds answers."]),
    )
    return document


def run_indexing(document_storage: FakeDocumentStorage) -> bool:
    return index_next_document(
        engine=engine,
        storage=document_storage,
        embeddings=DeterministicEmbeddings(),
        embedding_model="test-embedding-model",
    )


def test_an_indexed_document_becomes_ready_with_its_chunks(
    db_session: Session,
    queued_document: Document,
    document_storage: FakeDocumentStorage,
) -> None:
    assert run_indexing(document_storage) is True

    db_session.expire_all()
    document = db_session.get(Document, queued_document.id)
    assert document is not None
    assert document.status == "ready"
    assert document.embedding_model == "test-embedding-model"
    assert document.indexing_error_code is None

    chunks = db_session.exec(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    ).all()
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1


def test_an_empty_queue_claims_nothing(
    document_storage: FakeDocumentStorage,
) -> None:
    assert run_indexing(document_storage) is False


def test_only_a_queued_document_is_claimed(
    db_session: Session,
    queued_document: Document,
) -> None:
    queued_document.status = "ready"
    db_session.add(queued_document)
    db_session.commit()

    with Session(engine) as session:
        assert claim_next_document(session) is None


def test_a_claim_marks_the_document_as_indexing(
    db_session: Session,
    queued_document: Document,
) -> None:
    with Session(engine) as session:
        claim = claim_next_document(session)

    assert claim is not None
    db_session.expire_all()
    document = db_session.get(Document, queued_document.id)
    assert document is not None
    assert document.status == "indexing"


def test_a_missing_stored_object_is_reported_as_such(
    db_session: Session,
    queued_document: Document,
    document_storage: FakeDocumentStorage,
) -> None:
    document_storage.remove(queued_document.storage_object_path)

    assert run_indexing(document_storage) is True

    db_session.expire_all()
    document = db_session.get(Document, queued_document.id)
    assert document is not None
    assert document.status == "indexing_failed"
    assert document.indexing_error_code == "storage_missing"


def test_a_file_that_is_not_a_pdf_is_reported_as_unreadable(
    db_session: Session,
    queued_document: Document,
    document_storage: FakeDocumentStorage,
) -> None:
    document_storage.upload(
        queued_document.storage_object_path,
        b"this is not a pdf",
    )

    assert run_indexing(document_storage) is True

    db_session.expire_all()
    document = db_session.get(Document, queued_document.id)
    assert document is not None
    assert document.status == "indexing_failed"
    assert document.indexing_error_code == "invalid_pdf"


async def test_the_runner_drains_the_queue_when_asked() -> None:
    claimed = 0

    def index_next() -> bool:
        nonlocal claimed
        if claimed >= 3:
            return False
        claimed += 1
        return True

    runner = DocumentIndexingRunner(index_next)
    await runner.start()
    for _ in range(20):
        await asyncio.sleep(0.01)
        if claimed == 3:
            break
    await runner.stop()

    assert claimed == 3


async def test_an_idle_runner_does_not_keep_claiming() -> None:
    calls = 0

    def index_next() -> bool:
        nonlocal calls
        calls += 1
        return False

    runner = DocumentIndexingRunner(index_next)
    await runner.start()
    await asyncio.sleep(0.05)
    await runner.stop()

    # One drain attempt at startup, not a spin loop.
    assert calls == 1


async def test_repeated_requests_before_a_drain_collapse_into_one() -> None:
    calls = 0

    def index_next() -> bool:
        nonlocal calls
        calls += 1
        return False

    runner = DocumentIndexingRunner(index_next)
    await runner.start()
    await asyncio.sleep(0.02)
    runner.request_run()
    runner.request_run()
    runner.request_run()
    await asyncio.sleep(0.05)
    await runner.stop()

    assert calls == 2


async def test_a_failing_cycle_does_not_kill_the_runner() -> None:
    calls = 0

    def index_next() -> bool:
        nonlocal calls
        calls += 1
        raise RuntimeError("indexing exploded")

    runner = DocumentIndexingRunner(index_next)
    await runner.start()
    await asyncio.sleep(0.02)
    runner.request_run()
    await asyncio.sleep(0.05)
    await runner.stop()

    assert calls >= 2
