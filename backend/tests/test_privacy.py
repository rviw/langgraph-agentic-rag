import json

import pytest

from app.observability.privacy import REDACTED, SecretRedactor
from app.observability.tracing import build_span_mask

KNOWN_SECRET = "sb_secret_N7UND0UgjKTVK_example"


@pytest.fixture
def redactor() -> SecretRedactor:
    return SecretRedactor((KNOWN_SECRET,))


def test_answer_and_question_text_is_preserved(redactor: SecretRedactor) -> None:
    """Traces are for debugging answers, so ordinary content must survive."""

    payload = {
        "question": "How does retrieval augmented generation work?",
        "answer": "It grounds answers in retrieved passages.",
        "page": 3,
        "score": 0.42,
    }

    assert redactor.redact(payload) == payload


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "Authorization",
        "database_url",
        "openai_api_key",
        "refresh_token",
        "SUPABASE_SECRET_KEY",
        "set-cookie",
    ],
)
def test_a_credential_named_field_is_removed(
    redactor: SecretRedactor,
    key: str,
) -> None:
    assert redactor.redact({key: "value-that-must-not-appear"}) == {key: REDACTED}


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(f"key is {KNOWN_SECRET}", id="configured-secret"),
        pytest.param("Authorization: Bearer abc.def.ghijklmnop", id="bearer-header"),
        pytest.param(
            "postgresql://postgres:password@db.example.test:5432/postgres",
            id="database-url",
        ),
        pytest.param("api_key=sk-abcdefghijklmnop", id="labelled-key"),
        pytest.param("sk-abcdefghijklmnopqrstuv", id="provider-key"),
        pytest.param(
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N",
            id="jwt",
        ),
        pytest.param(
            "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBg\n-----END PRIVATE KEY-----",
            id="private-key",
        ),
    ],
)
def test_credential_shaped_text_is_removed(
    redactor: SecretRedactor,
    value: str,
) -> None:
    redacted = redactor.redact(value)

    assert REDACTED in redacted
    assert KNOWN_SECRET not in redacted
    assert "sk-abcdefghijklmnop" not in redacted
    assert "password@db.example.test" not in redacted


def test_a_plain_web_url_survives_but_a_signed_one_does_not(
    redactor: SecretRedactor,
) -> None:
    """A cited source URL is useful; a signed URL is a credential."""

    assert redactor.redact("See https://example.test/article") == (
        "See https://example.test/article"
    )
    assert REDACTED in redactor.redact(
        "https://example.test/object?X-Amz-Signature=abc123&X-Amz-Credential=def"
    )
    assert REDACTED in redactor.redact("https://user:pass@example.test/object")


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(b"%PDF-1.7 binary", id="pdf-bytes"),
        pytest.param("%PDF-1.7 extracted", id="pdf-text"),
        pytest.param("JVBERi0xLjcKJcfsj6IK", id="pdf-base64"),
        pytest.param("data:application/pdf;base64,JVBERi0x", id="pdf-data-uri"),
    ],
)
def test_uploaded_document_bytes_never_reach_a_trace(
    redactor: SecretRedactor,
    value: object,
) -> None:
    assert redactor.redact(value) == REDACTED


def test_a_serialized_payload_is_redacted_field_by_field(
    redactor: SecretRedactor,
) -> None:
    payload = json.dumps({"question": "What is RAG?", "api_key": "sk-abcdefghijkl"})

    redacted = json.loads(redactor.redact(payload))

    assert redacted["question"] == "What is RAG?"
    assert redacted["api_key"] == REDACTED


def test_a_header_pair_keeps_its_name_and_loses_its_value(
    redactor: SecretRedactor,
) -> None:
    assert redactor.redact(("authorization", "Bearer abc")) == (
        "authorization",
        REDACTED,
    )


def test_export_masking_patches_every_sensitive_span_attribute(
    redactor: SecretRedactor,
) -> None:
    """The export stage is the last defense, after every instrumentation."""

    class Span:
        attributes = {
            "gen_ai.prompt": "What is RAG?",
            "http.request.header.authorization": "Bearer abc.def.ghi",
            "app.api_key": KNOWN_SECRET,
        }

    class Params:
        spans = {"span-1": Span()}

    result = build_span_mask(redactor)(params=Params())

    assert result is not None
    patched = result.span_patches["span-1"].set_attributes
    assert patched["http.request.header.authorization"] == REDACTED
    assert patched["app.api_key"] == REDACTED
    # Unchanged attributes are not patched, so answer text is left intact.
    assert "gen_ai.prompt" not in patched
