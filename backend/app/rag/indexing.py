import unicodedata
from dataclasses import dataclass
from io import BytesIO

from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pypdf import filters as pypdf_filters

from app.core.config import settings

# An uploaded PDF is untrusted input. These bounds keep a crafted file from
# exhausting memory or CPU while it is parsed and split.
_MAX_PDF_PAGES = 100
_MAX_STREAM_BYTES = 8 * 1024 * 1024
_MAX_TOTAL_STREAM_BYTES = 32 * 1024 * 1024
_MAX_EXTRACTED_CHARACTERS = 1_000_000
_MAX_CHUNKS = 1500
_MAX_ZLIB_RECOVERY_INPUT_BYTES = 1024 * 1024
_PDF_SIGNATURE = b"%PDF-"


class DocumentValidationError(ValueError):
    """The uploaded bytes are not a PDF this application can index."""


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    page_number: int
    content: str
    embedding: list[float]


@dataclass(frozen=True, slots=True)
class _PageText:
    page_number: int
    content: str


def _apply_decompression_limits() -> None:
    """Bound pypdf's decompression before any untrusted stream is decoded."""

    pypdf_filters.MAX_DECLARED_STREAM_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.JBIG2_MAX_OUTPUT_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.LZW_MAX_OUTPUT_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.RUN_LENGTH_MAX_OUTPUT_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.ZLIB_MAX_OUTPUT_LENGTH = _MAX_STREAM_BYTES
    pypdf_filters.ZLIB_MAX_RECOVERY_INPUT_LENGTH = _MAX_ZLIB_RECOVERY_INPUT_BYTES
    pypdf_filters.FLATE_MAX_BUFFER_SIZE = _MAX_STREAM_BYTES
    # Never shell out to an external decoder for untrusted image streams.
    pypdf_filters.JBIG2DEC_BINARY = None


def _normalized(text: str) -> str:
    """Fold extracted text into a comparable form without control characters."""

    normalized = (
        unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    )
    return "".join(
        character
        if character in {"\n", "\t"}
        or unicodedata.category(character) not in {"Cc", "Cf"}
        else " "
        for character in normalized
    ).strip()


def _extract_pages(file_data: bytes) -> list[_PageText]:
    _apply_decompression_limits()
    reader = PdfReader(BytesIO(file_data), strict=False)

    if reader.is_encrypted:
        raise DocumentValidationError("encrypted_pdf")
    if len(reader.pages) > _MAX_PDF_PAGES:
        raise DocumentValidationError("too_many_pages")

    pages: list[_PageText] = []
    total_stream_bytes = 0
    total_characters = 0

    for page_number, page in enumerate(reader.pages, start=1):
        contents = page.get_contents()
        if contents is not None:
            stream_bytes = len(contents.get_data())
            if stream_bytes > _MAX_STREAM_BYTES:
                raise DocumentValidationError("page_too_large")
            total_stream_bytes += stream_bytes
            if total_stream_bytes > _MAX_TOTAL_STREAM_BYTES:
                raise DocumentValidationError("document_too_large")

        content = _normalized(page.extract_text() or "")
        if not content:
            continue

        total_characters += len(content)
        if total_characters > _MAX_EXTRACTED_CHARACTERS:
            raise DocumentValidationError("too_much_text")
        pages.append(_PageText(page_number=page_number, content=content))

    if not pages:
        raise DocumentValidationError("no_extractable_text")
    return pages


def _split(pages: list[_PageText]) -> list[_PageText]:
    """Split each page separately so every chunk keeps a real page number."""

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.DOCUMENT_CHUNK_SIZE,
        chunk_overlap=settings.DOCUMENT_CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ".", "。", "．", ",", "，", "、", ""],
    )
    chunks: list[_PageText] = []

    for page in pages:
        chunks.extend(
            _PageText(page_number=page.page_number, content=piece.strip())
            for piece in splitter.split_text(page.content)
            if piece.strip()
        )
        if len(chunks) > _MAX_CHUNKS:
            raise DocumentValidationError("too_many_chunks")

    if not chunks:
        raise DocumentValidationError("no_indexable_text")
    return chunks


def validate_pdf_signature(file_data: bytes) -> None:
    if not file_data.startswith(_PDF_SIGNATURE):
        raise DocumentValidationError("invalid_pdf_signature")


def prepare_document_index(
    *,
    file_data: bytes,
    embeddings: Embeddings,
) -> list[IndexedChunk]:
    """Turn stored PDF bytes into embedded chunks ready to persist."""

    try:
        validate_pdf_signature(file_data)
        chunks = _split(_extract_pages(file_data))
    except Exception as exc:
        # Every parse failure is reported to the user the same way.
        raise DocumentValidationError("invalid_pdf") from exc

    vectors = embeddings.embed_documents([chunk.content for chunk in chunks])
    return [
        IndexedChunk(
            page_number=chunk.page_number,
            content=chunk.content,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
