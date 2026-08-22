from uuid import UUID, uuid7

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import DbSessionDep, DocumentStorageDep, OwnedChatDep
from app.core.config import settings
from app.models import Document
from app.schemas.documents import (
    CreateDocumentUploadRequest,
    DocumentResponse,
    DocumentUploadResponse,
)
from app.storage.documents import document_object_path

router = APIRouter(prefix="/chats/{chat_id}/document", tags=["documents"])

PDF_MEDIA_TYPE = "application/pdf"

# Deleting a document that is being indexed or already answers questions would
# leave an execution or its citations pointing at content that is gone.
_DELETABLE_STATUSES = frozenset(
    {"upload_pending", "indexing_pending", "indexing_failed"}
)


def _validated_filename(original_filename: str) -> str:
    """Keep only the file name, and only when it names a PDF."""

    name = original_filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or len(name) > 255 or not name.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Choose a valid PDF.",
        )
    return name


def _chat_document(
    db_session: Session,
    *,
    chat_id: UUID,
    for_update: bool = False,
) -> Document | None:
    statement = select(Document).where(Document.chat_id == chat_id)
    if for_update:
        statement = statement.with_for_update(of=Document)
    return db_session.exec(statement).one_or_none()


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_document_upload(
    payload: CreateDocumentUploadRequest,
    chat: OwnedChatDep,
    db_session: DbSessionDep,
    storage: DocumentStorageDep,
) -> dict[str, object]:
    """Reserve the document row and hand back a one-time signed upload target."""

    original_filename = _validated_filename(payload.original_filename)
    if payload.media_type != PDF_MEDIA_TYPE:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Choose a valid PDF.",
        )
    if payload.size_bytes > settings.MAX_PDF_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="PDF is too large.",
        )

    document_id = uuid7()
    document = Document(
        id=document_id,
        chat_id=chat.id,
        original_filename=original_filename,
        media_type=PDF_MEDIA_TYPE,
        size_bytes=payload.size_bytes,
        storage_object_path=document_object_path(chat.user_id, document_id),
    )
    db_session.add(document)
    try:
        db_session.flush()
    except IntegrityError as exc:
        # The one-document-per-chat constraint rejected a second reservation.
        db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chat already has a document.",
        ) from exc

    upload = storage.create_signed_upload(document.storage_object_path)
    db_session.commit()
    db_session.refresh(document)
    return {"document": document, "upload": upload}


@router.get(
    "",
    response_model=DocumentResponse,
    responses={status.HTTP_204_NO_CONTENT: {"description": "No document"}},
)
def get_document(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
) -> Document | Response:
    document = _chat_document(db_session, chat_id=chat.id)
    if document is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return document


@router.post("/confirm-upload", response_model=DocumentResponse)
def confirm_document_upload(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
    storage: DocumentStorageDep,
) -> Document:
    """Verify the uploaded object matches the reservation, then queue indexing.

    Repeating this call is safe: a document already queued or being indexed is
    returned unchanged.
    """

    document = _chat_document(db_session, chat_id=chat.id, for_update=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This document is no longer available.",
        )
    if document.status != "upload_pending":
        db_session.rollback()
        return document

    stored = storage.info(document.storage_object_path)
    if (
        stored is None
        or stored.size_bytes != document.size_bytes
        or stored.media_type != PDF_MEDIA_TYPE
    ):
        db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Couldn’t upload this document. Try again.",
        )

    document.status = "indexing_pending"
    document.indexing_error_code = None
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
    storage: DocumentStorageDep,
) -> None:
    document = _chat_document(db_session, chat_id=chat.id, for_update=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This document is no longer available.",
        )
    if document.status not in _DELETABLE_STATUSES:
        db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document can’t be removed.",
        )

    # Remove the object first so a failure cannot orphan stored bytes.
    storage.remove(document.storage_object_path)
    db_session.delete(document)
    db_session.commit()
