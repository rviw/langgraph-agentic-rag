from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.answer import Answer, InvalidAnswer
from app.agent.execution import evidence_was_searched
from app.agent.grounding import (
    GroundingFailed,
    OpenAIGroundingValidator,
    check_cited_sources_exist,
)
from app.db.answer_sources import DocumentSource


def document_source(source_id):
    return DocumentSource(
        source_id=source_id,
        document_id=uuid7(),
        chunk_id=uuid7(),
        chunk_index=0,
        filename="report.pdf",
        page=1,
        excerpt="Retrieval augmented generation grounds answers.",
    )


class ScriptedModel:
    """Returns prepared judge verdicts instead of calling a provider."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)

    async def ainvoke(self, messages, **_kwargs):
        del messages
        return self._outcomes.pop(0)


def validator_with(judge_outcomes):
    validator = OpenAIGroundingValidator.__new__(OpenAIGroundingValidator)
    validator._judge = ScriptedModel(judge_outcomes)
    return validator


class Decision:
    def __init__(self, verdict, feedback=""):
        self.verdict = verdict
        self.feedback = feedback


def test_an_answer_citing_evidence_from_elsewhere_is_refused() -> None:
    source = document_source(uuid7())
    answer = Answer(
        markdown="Claim about another execution [1].",
        source_ids=(uuid7(),),
    )

    with pytest.raises(InvalidAnswer):
        check_cited_sources_exist(answer, sources=(source,))


async def test_a_grounded_draft_passes_validation() -> None:
    source = document_source(uuid7())
    draft = Answer(
        markdown="Grounded claim [1].",
        source_ids=(source.source_id,),
    )
    validator = validator_with([Decision("pass")])

    result = await validator.validate(
        draft=draft,
        sources=(source,),
        searched=True,
        user_request="What does the document say?",
    )

    assert result is None


async def test_an_answer_without_a_search_skips_judging() -> None:
    draft = Answer(markdown="Two plus two is four.", source_ids=())
    validator = validator_with([])

    result = await validator.validate(
        draft=draft,
        sources=(),
        searched=False,
        user_request="What is 2 + 2?",
    )

    assert result is None


async def test_an_ungrounded_draft_is_rejected() -> None:
    source = document_source(uuid7())
    draft = Answer(markdown="Unsupported claim [1].", source_ids=(source.source_id,))
    validator = validator_with([Decision("fail", "Unsupported.")])

    with pytest.raises(GroundingFailed):
        await validator.validate(
            draft=draft,
            sources=(source,),
            searched=True,
            user_request="What does the document say?",
        )


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        pytest.param(
            [ToolMessage(content="{}", tool_call_id="1", name="search_documents")],
            True,
            id="document-search-result",
        ),
        pytest.param(
            [ToolMessage(content="{}", tool_call_id="1", name="search_web")],
            True,
            id="web-search-result",
        ),
        pytest.param(
            [ToolMessage(content="4", tool_call_id="1", name="calculator")],
            False,
            id="calculator-only",
        ),
        pytest.param([HumanMessage(content="hello")], False, id="no-tools"),
    ],
)
def test_only_evidence_tools_count_as_a_search(messages, expected) -> None:
    assert evidence_was_searched(messages) is expected


def test_a_requested_search_counts_even_before_its_result() -> None:
    requested = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_documents", "args": {"query": "x"}, "id": "1"},
        ],
    )

    assert evidence_was_searched([requested]) is True
