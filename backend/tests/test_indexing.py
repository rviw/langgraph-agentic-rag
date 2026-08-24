import pytest

from app.rag.indexing import (
    DocumentValidationError,
    prepare_document_index,
)
from tests.support.embeddings import DeterministicEmbeddings
from tests.support.pdf import pdf_bytes


def test_a_pdf_becomes_embedded_chunks_that_keep_their_page() -> None:
    data = pdf_bytes(
        [
            "Retrieval augmented generation grounds answers in sources.",
            "Vector search finds passages by meaning.",
        ]
    )
    embeddings = DeterministicEmbeddings()

    chunks = prepare_document_index(file_data=data, embeddings=embeddings)

    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert "Retrieval augmented generation" in chunks[0].content
    assert "Vector search" in chunks[1].content
    assert all(len(chunk.embedding) == 1536 for chunk in chunks)


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"not a pdf at all", id="not-a-pdf"),
        pytest.param(b"%PDF-1.7\ntruncated", id="truncated-pdf"),
        pytest.param(pdf_bytes([" "]), id="no-extractable-text"),
    ],
)
def test_an_unusable_document_reports_one_safe_failure(data: bytes) -> None:
    with pytest.raises(DocumentValidationError) as failure:
        prepare_document_index(
            file_data=data,
            embeddings=DeterministicEmbeddings(),
        )

    assert str(failure.value) == "invalid_pdf"


def test_a_document_with_too_many_pages_is_refused() -> None:
    with pytest.raises(DocumentValidationError):
        prepare_document_index(
            file_data=pdf_bytes(["page"] * 101),
            embeddings=DeterministicEmbeddings(),
        )
