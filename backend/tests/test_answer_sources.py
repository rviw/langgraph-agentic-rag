from collections.abc import Callable
from uuid import UUID, uuid7

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.answer_sources import (
    DocumentSourceCandidate,
    WebSource,
    WebSourceCandidate,
    WebSourceDetail,
    list_execution_sources,
    publish_citations,
    read_citations,
    read_source_detail,
    record_document_sources,
    record_web_sources,
)
from app.db.chat_messages import append_assistant_message
from app.models import Chat, Document, DocumentChunk
from app.storage.documents import document_object_path
from tests.conftest import FakeSupabaseAuthClient, authenticated_claims
from tests.support.embeddings import DeterministicEmbeddings


@pytest.fixture
def chat(db_session: Session, create_user: Callable[..., UUID]) -> Chat:
    chat = Chat(user_id=create_user())
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)
    return chat


@pytest.fixture
def indexed_document(db_session: Session, chat: Chat) -> Document:
    document = Document(
        chat_id=chat.id,
        original_filename="report.pdf",
        media_type="application/pdf",
        size_bytes=2048,
        status="ready",
        storage_object_path=document_object_path(chat.user_id, chat.id),
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    contents = ["Passage zero.", "Passage one.", "Passage two."]
    vectors = DeterministicEmbeddings().embed_documents(contents)
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
    return document


def document_candidates(
    document: Document,
    db_session: Session,
) -> list[DocumentSourceCandidate]:
    from sqlmodel import select

    chunks = db_session.exec(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index)
    ).all()
    return [
        DocumentSourceCandidate(
            document_id=document.id,
            chunk_id=chunk.id,
            chunk_index=chunk.chunk_index,
            filename=document.original_filename,
            page=chunk.page_number,
            excerpt=chunk.content,
        )
        for chunk in chunks
    ]


def test_captured_evidence_is_listed_in_capture_order(
    db_session: Session,
    chat: Chat,
    indexed_document: Document,
) -> None:
    execution_id = uuid7()
    candidates = document_candidates(indexed_document, db_session)

    record_document_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=candidates[:2],
    )
    record_web_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=[
            WebSourceCandidate(
                title="Retrieval augmented generation",
                url="https://example.test/rag",
                excerpt="RAG grounds answers.",
            )
        ],
    )

    sources = list_execution_sources(db_session, execution_id=execution_id)
    assert [source.type for source in sources] == ["document", "document", "web"]


def test_capturing_the_same_passage_twice_reuses_one_source(
    db_session: Session,
    chat: Chat,
    indexed_document: Document,
) -> None:
    execution_id = uuid7()
    candidates = document_candidates(indexed_document, db_session)

    first = record_document_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=candidates[:1],
    )
    second = record_document_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=candidates[:1],
    )

    assert first[0].source_id == second[0].source_id
    assert len(list_execution_sources(db_session, execution_id=execution_id)) == 1


def test_capturing_the_same_url_twice_reuses_one_source(
    db_session: Session,
    chat: Chat,
) -> None:
    execution_id = uuid7()
    candidate = WebSourceCandidate(
        title="Same page",
        url="https://example.test/same",
        excerpt="Same excerpt.",
    )

    first = record_web_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=[candidate],
    )
    second = record_web_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=[candidate],
    )

    assert first[0].source_id == second[0].source_id


def test_published_citations_keep_the_answers_order(
    db_session: Session,
    chat: Chat,
    indexed_document: Document,
) -> None:
    execution_id = uuid7()
    sources = record_document_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=document_candidates(indexed_document, db_session),
    )
    message = append_assistant_message(
        db_session,
        chat_id=chat.id,
        content="An answer citing [1] and [2].",
    )
    # The answer cited the third passage first.
    cited = [sources[2].source_id, sources[0].source_id]

    published = publish_citations(
        db_session,
        assistant_message_id=message.id,
        source_ids=cited,
    )
    db_session.commit()

    assert [source.source_id for source in published] == cited
    stored = read_citations(db_session, message_ids=[message.id])
    assert [source.source_id for source in stored[message.id]] == cited


def test_a_document_citation_opens_with_its_adjacent_passages(
    db_session: Session,
    chat: Chat,
    indexed_document: Document,
    client: TestClient,
    supabase_auth: FakeSupabaseAuthClient,
) -> None:
    execution_id = uuid7()
    sources = record_document_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=document_candidates(indexed_document, db_session),
    )

    message = append_assistant_message(
        db_session, chat_id=chat.id, content="Document answer [1]."
    )
    publish_citations(
        db_session,
        assistant_message_id=message.id,
        source_ids=[sources[1].source_id],
    )
    db_session.commit()
    supabase_auth.auth.register("member", authenticated_claims(chat.user_id))
    response = client.get(
        f"/api/chats/{chat.id}/messages/{message.id}/sources/{sources[1].source_id}",
        headers={"Authorization": "Bearer member"},
    )
    assert response.status_code == 200
    assert response.json()["type"] == "document"
    assert response.json()["chunk_index"] == 1
    assert [item["chunk_index"] for item in response.json()["context"]] == [0, 2]


def test_a_web_citation_opens_with_the_stored_snapshot_only(
    db_session: Session,
    chat: Chat,
) -> None:
    execution_id = uuid7()
    sources = record_web_sources(
        db_session,
        execution_id=execution_id,
        chat_id=chat.id,
        candidates=[
            WebSourceCandidate(
                title="Only page",
                url="https://example.test/only",
                excerpt="Stored excerpt.",
            )
        ],
    )

    message = append_assistant_message(
        db_session, chat_id=chat.id, content="Web answer [1]."
    )
    publish_citations(
        db_session,
        assistant_message_id=message.id,
        source_ids=[sources[0].source_id],
    )
    db_session.commit()
    detail = read_source_detail(
        db_session,
        chat_id=chat.id,
        message_id=message.id,
        source_id=sources[0].source_id,
    )

    assert isinstance(detail, WebSourceDetail)
    assert isinstance(detail.source, WebSource)
    assert detail.source.url == "https://example.test/only"


@pytest.mark.parametrize(
    "mismatch",
    [
        "other_user",
        "other_chat",
        "other_message",
        "uncited_source",
    ],
)
def test_source_details_require_a_citation_on_the_requested_message(
    mismatch: str,
    client: TestClient,
    db_session: Session,
    chat: Chat,
    create_user: Callable[..., UUID],
    supabase_auth: FakeSupabaseAuthClient,
) -> None:
    """A known source ID grants no access outside its published citation."""

    cited, uncited = record_web_sources(
        db_session,
        execution_id=uuid7(),
        chat_id=chat.id,
        candidates=[
            WebSourceCandidate(
                title=title,
                url=f"https://example.test/{title}",
                excerpt=f"{title} excerpt.",
            )
            for title in ("cited", "uncited")
        ],
    )
    message = append_assistant_message(
        db_session, chat_id=chat.id, content="Answer [1]."
    )
    publish_citations(
        db_session,
        assistant_message_id=message.id,
        source_ids=[cited.source_id],
    )
    db_session.commit()

    user_id, chat_id = chat.user_id, chat.id
    message_id, source_id = message.id, cited.source_id
    if mismatch == "other_user":
        user_id = create_user()
        # Even an owned chat cannot be used to open another user's source.
        other_chat = Chat(user_id=user_id)
        db_session.add(other_chat)
        db_session.commit()
        chat_id = other_chat.id
    elif mismatch == "other_chat":
        other_chat = Chat(user_id=user_id)
        db_session.add(other_chat)
        db_session.commit()
        chat_id = other_chat.id
    elif mismatch == "other_message":
        message_id = append_assistant_message(
            db_session, chat_id=chat.id, content="Another answer."
        ).id
        db_session.commit()
    elif mismatch == "uncited_source":
        source_id = uncited.source_id

    supabase_auth.auth.register("member", authenticated_claims(user_id))
    response = client.get(
        f"/api/chats/{chat_id}/messages/{message_id}/sources/{source_id}",
        headers={"Authorization": "Bearer member"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "This source is no longer available."}
