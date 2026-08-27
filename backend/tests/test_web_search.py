import pytest

from app.rag.web import normalize_results


def test_usable_results_keep_their_title_url_and_excerpt() -> None:
    results = normalize_results(
        {
            "results": [
                {
                    "title": "  Retrieval augmented generation  ",
                    "url": "https://example.test/rag",
                    "content": "  RAG grounds answers in retrieved sources.  ",
                }
            ]
        }
    )

    assert len(results) == 1
    assert results[0].title == "Retrieval augmented generation"
    assert results[0].url == "https://example.test/rag"
    assert results[0].excerpt == "RAG grounds answers in retrieved sources."


@pytest.mark.parametrize(
    "item",
    [
        pytest.param({"url": "https://example.test", "content": "text"}, id="no-title"),
        pytest.param({"title": "Title", "content": "text"}, id="no-url"),
        pytest.param(
            {"title": "Title", "url": "https://example.test"}, id="no-excerpt"
        ),
        pytest.param("not an object", id="not-an-object"),
    ],
)
def test_a_result_missing_what_a_citation_needs_is_dropped(item: object) -> None:
    assert normalize_results({"results": [item]}) == []


def test_an_empty_or_absent_result_list_is_handled() -> None:
    assert normalize_results({}) == []
    assert normalize_results({"results": []}) == []
    assert normalize_results({"results": None}) == []


def test_long_provider_text_is_trimmed_to_storable_lengths() -> None:
    results = normalize_results(
        {
            "results": [
                {
                    "title": "T" * 400,
                    "url": "https://example.test",
                    "content": "C" * 5000,
                }
            ]
        }
    )

    assert len(results[0].title) == 200
    assert len(results[0].excerpt) == 1200
