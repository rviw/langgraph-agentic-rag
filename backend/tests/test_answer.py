import json
from uuid import uuid7

import pytest

from app.agent.answer import (
    InvalidAnswer,
    normalize_title,
    parse_answer,
    title_from_question,
)
from app.agent.tools import evaluate_expression


def test_the_answer_keeps_its_markdown_and_first_use_citation_order() -> None:
    first, second = uuid7(), uuid7()
    content = json.dumps(
        {
            "markdown": "Claim one [1] and claim two [2], back to [1].",
            "source_ids": [str(first), str(second), str(first)],
            "title": "  Reviewed  answer  ",
        }
    )

    answer = parse_answer(content)

    assert answer.markdown == "Claim one [1] and claim two [2], back to [1]."
    assert answer.source_ids == (first, second)
    assert answer.title == "Reviewed answer"


def test_malformed_json_is_refused() -> None:
    with pytest.raises(InvalidAnswer):
        parse_answer("not json")


def test_a_long_title_is_shortened_to_the_stored_limit() -> None:
    normalized = normalize_title("word " * 40)

    assert normalized is not None
    assert len(normalized) <= 80
    assert normalized.endswith("…")


def test_title_from_question_uses_question_or_default_chat_title() -> None:
    assert title_from_question("How does retrieval work?") == "How does retrieval work?"
    assert title_from_question("   ") == "New chat"


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3 * 4", "14"),
        ("(8 - 3) / 2", "2.5"),
        ("7 // 2", "3"),
        ("2 ** 10", "1024"),
        ("-5 % 3", "1"),
    ],
)
def test_arithmetic_is_evaluated_without_executing_code(
    expression: str,
    expected: str,
) -> None:
    assert str(evaluate_expression(expression)) == expected


@pytest.mark.parametrize(
    "expression",
    [
        pytest.param("__import__('os').system('true')", id="import-call"),
        pytest.param("open('/etc/passwd').read()", id="file-read"),
        pytest.param("1 / 0", id="division-by-zero"),
        pytest.param("9 ** 9999", id="unbounded-exponent"),
        pytest.param("", id="empty"),
        pytest.param("2 +", id="incomplete"),
    ],
)
def test_unsafe_or_unusable_expressions_are_refused(expression: str) -> None:
    with pytest.raises(ValueError):
        evaluate_expression(expression)
