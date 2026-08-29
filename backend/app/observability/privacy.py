"""Remove credentials from trace data before it leaves this process."""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

REDACTED = "[REDACTED]"

# Traces carry prompts and retrieved text, so anything credential-shaped must go.
_SENSITIVE_KEY_SUFFIXES = (
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "credential",
    "databaseurl",
    "jwt",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "secretkey",
    "signedurl",
    "token",
)
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "dburl",
        "key",
        "publishablekey",
    }
)
# Query names that make a URL a bearer credential on its own.
_SIGNED_QUERY_NAMES = frozenset(
    {
        "policy",
        "sig",
        "signature",
    }
)

_DATABASE_URL = re.compile(
    r"(?i)\b(?:postgres(?:ql)?(?:\+[a-z0-9_-]+)?|mysql|mariadb|"
    r"mongodb(?:\+srv)?|redis|sqlite)://[^\s\"'<>]+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_HEADER_LINE = re.compile(
    r"(?im)((?:(?:proxy-)?authorization|(?:set-)?cookie)\s*[:=]\s*)[^\r\n]+"
)
_LABELED_SECRET = re.compile(
    r"(?i)\b((?:api[-_ ]?key|secret[-_ ]?key|access[-_ ]?token|"
    r"refresh[-_ ]?token|password|jwt)\s*[:=]\s*)[^\s,;}]+"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_JWT = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
)
_PROVIDER_KEY = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:sk|pk|rk|tvly|co)-[A-Za-z0-9_-]{8,}"
)
# Uploaded PDF bytes must never reach a trace, in any encoding.
_PDF_MARKER = re.compile(
    r"(?i:%PDF-[0-9]|data:application/pdf[^,]*,)"
    r"|(?<![A-Za-z0-9+/_-])JVBERi0[A-Za-z0-9+/=_-]*"
)
_WEB_URL = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

_MAX_DEPTH = 32


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith(
        _SENSITIVE_KEY_SUFFIXES
    )


def _is_sensitive_url(value: str, known_secrets: Sequence[str]) -> bool:
    """A URL is sensitive when it carries authority rather than just a location."""

    candidate = value.rstrip(".,;:)")
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return True
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username is not None or parsed.password is not None:
        return True

    decoded = unquote(candidate)
    query_names = {name.lower() for name, _value in parse_qsl(parsed.query)}
    if (
        query_names & _SIGNED_QUERY_NAMES
        or any(is_sensitive_key(name) for name in query_names)
        or any(name.startswith(("x-amz-", "x-goog-")) for name in query_names)
    ):
        return True
    return (
        any(secret in decoded for secret in known_secrets)
        or _JWT.search(decoded) is not None
        or _PROVIDER_KEY.search(decoded) is not None
    )


class SecretRedactor:
    """Deterministically redact credentials from any trace payload."""

    def __init__(self, known_secrets: Sequence[str] = ()) -> None:
        # Longest first, so a longer secret is not partly masked by a shorter one.
        self._known_secrets = tuple(
            sorted(
                {secret for secret in known_secrets if secret and len(secret) >= 8},
                key=len,
                reverse=True,
            )
        )

    def redact(self, value: Any, *, key: object | None = None) -> Any:
        try:
            return self._redact(value, key=key, depth=0)
        except Exception:
            # Failing closed keeps an unexpected shape from leaking.
            return REDACTED

    def _redact(self, value: Any, *, key: object | None, depth: int) -> Any:
        if depth > _MAX_DEPTH:
            return REDACTED
        if key is not None and is_sensitive_key(key):
            return REDACTED
        # Raw bytes and file objects are never safe to export.
        if isinstance(value, (bytes, bytearray, memoryview)):
            return REDACTED
        if callable(getattr(value, "read", None)):
            return REDACTED
        if isinstance(value, str):
            return self._redact_string(value, depth=depth)
        if isinstance(value, Mapping):
            return {
                self._redact_string(str(item_key), depth=depth + 1): self._redact(
                    item_value, key=item_key, depth=depth + 1
                )
                for item_key, item_value in value.items()
            }
        if isinstance(value, (list, tuple)):
            # A two-item pair is often a header, so respect its key.
            if len(value) == 2 and is_sensitive_key(value[0]):
                pair = (self._redact_string(str(value[0]), depth=depth + 1), REDACTED)
                return pair if isinstance(value, tuple) else list(pair)
            items = [self._redact(item, key=None, depth=depth + 1) for item in value]
            return tuple(items) if isinstance(value, tuple) else items
        if isinstance(value, (type(None), bool, int, float)):
            return value

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return self._redact(model_dump(mode="json"), key=key, depth=depth + 1)
        if is_dataclass(value) and not isinstance(value, type):
            return self._redact(asdict(value), key=key, depth=depth + 1)
        return REDACTED

    def _redact_string(self, value: str, *, depth: int) -> str:
        stripped = value.strip()
        if _PDF_MARKER.search(stripped):
            return REDACTED

        # Serialized payloads are redacted per field, not as one opaque string.
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except ValueError:
                pass
            else:
                return json.dumps(
                    self._redact(decoded, key=None, depth=depth + 1),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )

        redacted = value
        for secret in self._known_secrets:
            redacted = redacted.replace(secret, REDACTED)
        redacted = _DATABASE_URL.sub(REDACTED, redacted)
        redacted = _HEADER_LINE.sub(r"\1" + REDACTED, redacted)
        redacted = _LABELED_SECRET.sub(r"\1" + REDACTED, redacted)
        redacted = _PRIVATE_KEY.sub(REDACTED, redacted)
        redacted = _BEARER.sub(REDACTED, redacted)
        redacted = _JWT.sub(REDACTED, redacted)
        redacted = _PROVIDER_KEY.sub(REDACTED, redacted)
        return _WEB_URL.sub(
            lambda match: (
                REDACTED
                if _is_sensitive_url(match.group(0), self._known_secrets)
                else match.group(0)
            ),
            redacted,
        )
