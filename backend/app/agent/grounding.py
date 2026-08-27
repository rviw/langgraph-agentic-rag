from app.agent.answer import Answer, InvalidAnswer
from app.db.answer_sources import AnswerSourceSnapshot


class GroundingFailed(RuntimeError):
    """The current answer failed grounding validation."""


def check_cited_sources_exist(
    answer: Answer,
    *,
    sources: tuple[AnswerSourceSnapshot, ...],
) -> None:
    """Refuse an answer that cites anything outside this execution's evidence."""

    allowed = {source.source_id for source in sources}
    if any(source_id not in allowed for source_id in answer.source_ids):
        raise InvalidAnswer("Answer cites a source outside the current execution")
