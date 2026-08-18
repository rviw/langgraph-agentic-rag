from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.chat import CHAT_TITLE_MAX_LENGTH, DEFAULT_CHAT_TITLE


class InvalidAnswer(ValueError):
    """The answer does not satisfy the application's answer contract."""


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown: str
    source_ids: list[str]
    title: str | None


@dataclass(frozen=True, slots=True)
class Answer:
    markdown: str
    source_ids: tuple[UUID, ...]
    title: str | None = None


def normalize_title(title: str | None) -> str | None:
    if title is None:
        return None
    normalized = " ".join(title.split()).strip(" \"'")
    if not normalized:
        return None
    if len(normalized) <= CHAT_TITLE_MAX_LENGTH:
        return normalized
    return f"{normalized[: CHAT_TITLE_MAX_LENGTH - 1].rstrip()}…"


def title_from_question(question: str) -> str:
    return normalize_title(question) or DEFAULT_CHAT_TITLE


def parse_answer(content: str) -> Answer:
    try:
        payload = AnswerPayload.model_validate_json(content)
        source_ids = tuple(dict.fromkeys(UUID(value) for value in payload.source_ids))
    except (TypeError, ValueError) as exc:
        raise InvalidAnswer("Final answer is malformed") from exc

    return Answer(
        markdown=payload.markdown,
        source_ids=source_ids,
        title=normalize_title(payload.title),
    )
