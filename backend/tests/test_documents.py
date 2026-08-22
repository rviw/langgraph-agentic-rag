from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FakeDocumentStorage,
    FakeSupabaseAuthClient,
    authenticated_claims,
)

PDF_BYTES = b"%PDF-1.7\nminimal test document\n"


@pytest.fixture
def headers(
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
) -> dict[str, str]:
    user_id = create_user()
    supabase_auth.auth.register("member", authenticated_claims(user_id))
    return {"Authorization": "Bearer member"}


@pytest.fixture
def chat_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.post("/api/chats", headers=headers).json()["id"]


def reserve(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    **overrides: Any,
):
    payload: dict[str, Any] = {
        "original_filename": "report.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(PDF_BYTES),
    }
    payload.update(overrides)
    return client.post(f"/api/chats/{chat_id}/document", headers=headers, json=payload)


def test_a_reservation_returns_a_server_owned_upload_target(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
) -> None:
    response = reserve(client, headers, chat_id)

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["status"] == "upload_pending"
    assert body["upload"]["bucket"] == "documents"
    # The browser is told where to upload; it never chooses the location.
    assert body["upload"]["path"].endswith(f"/{body['document']['id']}/original.pdf")
    assert document_storage.signed_paths == [body["upload"]["path"]]


def test_a_path_in_the_filename_cannot_escape_the_document_location(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
) -> None:
    response = reserve(
        client,
        headers,
        chat_id,
        original_filename="../../etc/passwd.pdf",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["document"]["original_filename"] == "passwd.pdf"
    assert ".." not in body["upload"]["path"]


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        pytest.param({"original_filename": "notes.txt"}, 415, id="not-a-pdf-name"),
        pytest.param({"media_type": "text/plain"}, 415, id="not-a-pdf-type"),
        pytest.param({"size_bytes": 10 * 1024 * 1024 + 1}, 413, id="too-large"),
        pytest.param({"size_bytes": 0}, 422, id="empty"),
    ],
)
def test_an_unusable_document_is_refused(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    overrides: dict[str, Any],
    expected_status: int,
) -> None:
    assert reserve(client, headers, chat_id, **overrides).status_code == (
        expected_status
    )


def test_a_chat_accepts_only_one_document(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
) -> None:
    assert reserve(client, headers, chat_id).status_code == 201

    assert reserve(client, headers, chat_id).status_code == 409


def test_a_chat_without_a_document_reports_no_content(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
) -> None:
    response = client.get(f"/api/chats/{chat_id}/document", headers=headers)

    assert response.status_code == 204


def test_confirming_a_completed_upload_queues_indexing(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
) -> None:
    reserved = reserve(client, headers, chat_id).json()
    document_storage.upload(reserved["upload"]["path"], PDF_BYTES)

    confirmed = client.post(
        f"/api/chats/{chat_id}/document/confirm-upload",
        headers=headers,
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "indexing_pending"


def test_confirming_twice_leaves_the_queued_document_alone(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
) -> None:
    reserved = reserve(client, headers, chat_id).json()
    document_storage.upload(reserved["upload"]["path"], PDF_BYTES)
    url = f"/api/chats/{chat_id}/document/confirm-upload"

    first = client.post(url, headers=headers)
    second = client.post(url, headers=headers)

    assert first.json()["status"] == "indexing_pending"
    assert second.status_code == 200
    assert second.json()["status"] == "indexing_pending"


@pytest.mark.parametrize(
    "stored",
    [
        pytest.param(None, id="nothing-uploaded"),
        pytest.param(("wrong size", "application/pdf"), id="size-mismatch"),
        pytest.param((None, "text/plain"), id="type-mismatch"),
    ],
)
def test_confirming_an_upload_that_does_not_match_is_refused(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
    stored: tuple[str | None, str] | None,
) -> None:
    reserved = reserve(client, headers, chat_id).json()
    if stored is not None:
        data, media_type = stored
        document_storage.upload(
            reserved["upload"]["path"],
            b"different length" if data else PDF_BYTES,
            media_type,
        )

    response = client.post(
        f"/api/chats/{chat_id}/document/confirm-upload",
        headers=headers,
    )

    assert response.status_code == 409
    document = client.get(f"/api/chats/{chat_id}/document", headers=headers).json()
    assert document["status"] == "upload_pending"


def test_a_document_is_removed_from_storage_before_the_row(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
) -> None:
    reserved = reserve(client, headers, chat_id).json()
    path = reserved["upload"]["path"]
    document_storage.upload(path, PDF_BYTES)

    deleted = client.delete(f"/api/chats/{chat_id}/document", headers=headers)

    assert deleted.status_code == 204
    assert document_storage.removed_paths == [path]
    assert (
        client.get(f"/api/chats/{chat_id}/document", headers=headers).status_code == 204
    )


def test_deleting_the_chat_also_removes_the_stored_object(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    document_storage: FakeDocumentStorage,
) -> None:
    reserved = reserve(client, headers, chat_id).json()
    document_storage.upload(reserved["upload"]["path"], PDF_BYTES)

    assert client.delete(f"/api/chats/{chat_id}", headers=headers).status_code == 204

    assert document_storage.removed_paths == [reserved["upload"]["path"]]


def test_documents_are_reachable_only_by_the_chat_owner(
    client: TestClient,
    headers: dict[str, str],
    chat_id: str,
    supabase_auth: FakeSupabaseAuthClient,
    create_user: Callable[..., UUID],
) -> None:
    reserve(client, headers, chat_id)
    supabase_auth.auth.register("other", authenticated_claims(create_user()))
    other = {"Authorization": "Bearer other"}

    assert client.get(f"/api/chats/{chat_id}/document", headers=other).status_code == (
        404
    )
    assert reserve(client, other, chat_id).status_code == 404
    assert (
        client.delete(f"/api/chats/{chat_id}/document", headers=other).status_code
        == 404
    )
