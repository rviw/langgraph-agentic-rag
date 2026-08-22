from dataclasses import dataclass
from uuid import UUID

from storage3.exceptions import StorageApiError
from supabase import Client


class DocumentObjectNotFound(RuntimeError):
    """An expected document object is absent from Storage."""


def document_object_path(user_id: UUID, document_id: UUID) -> str:
    """The one location a document may occupy. The browser never chooses this."""

    return f"{user_id}/{document_id}/original.pdf"


@dataclass(frozen=True, slots=True)
class DocumentObjectInfo:
    size_bytes: int
    media_type: str


@dataclass(frozen=True, slots=True)
class SignedUpload:
    bucket: str
    path: str
    token: str


class DocumentStorage:
    """Server-owned access to the single private documents bucket."""

    def __init__(self, client: Client, bucket: str) -> None:
        self._bucket_name = bucket
        self._bucket = client.storage.from_(bucket)

    def create_signed_upload(self, path: str) -> SignedUpload:
        # Options are omitted on purpose: a signed upload must not overwrite.
        response = self._bucket.create_signed_upload_url(path)
        return SignedUpload(
            bucket=self._bucket_name,
            path=path,
            token=response["token"],
        )

    def info(self, path: str) -> DocumentObjectInfo | None:
        try:
            payload = self._bucket.info(path)
        except StorageApiError as exc:
            if int(exc.status) == 404:
                return None
            raise
        return DocumentObjectInfo(
            size_bytes=int(payload["size"]),
            media_type=payload["content_type"],
        )

    def download(self, path: str) -> bytes:
        try:
            return self._bucket.download(path)
        except StorageApiError as exc:
            if int(exc.status) == 404:
                raise DocumentObjectNotFound from exc
            raise

    def remove(self, path: str) -> None:
        """Remove an object, treating an already-absent object as removed."""

        try:
            self._bucket.remove([path])
        except StorageApiError as exc:
            if int(exc.status) != 404:
                raise
