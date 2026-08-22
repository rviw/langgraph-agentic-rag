from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentIndexingErrorCode, DocumentStatus


class CreateDocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0)


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    media_type: str
    size_bytes: int
    status: DocumentStatus
    indexing_error_code: DocumentIndexingErrorCode | None = None
    created_at: datetime


class UploadTargetResponse(BaseModel):
    """Where the browser uploads the file, signed by the server."""

    bucket: str
    path: str
    token: str


class DocumentUploadResponse(BaseModel):
    document: DocumentResponse
    upload: UploadTargetResponse
