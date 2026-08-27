import json
from dataclasses import dataclass
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from pydantic import Field, SecretStr, StringConstraints
from tavily import AsyncTavilyClient

from app.agent.phases import report_phase

MAX_WEB_RESULTS = 5
_MAX_TITLE_CHARACTERS = 200
_MAX_EXCERPT_CHARACTERS = 1200
_TIMEOUT_SECONDS = 60

_WebQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=400),
]


@dataclass(frozen=True, slots=True)
class WebResult:
    """A web result trimmed to the fields this application stores and cites."""

    title: str
    url: str
    excerpt: str


def normalize_results(payload: dict[str, object]) -> list[WebResult]:
    """Keep only usable results, trimmed to the lengths the schema allows."""

    results: list[WebResult] = []
    for item in payload.get("results", []) or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:_MAX_TITLE_CHARACTERS]
        url = str(item.get("url") or "").strip()
        excerpt = str(item.get("content") or "").strip()[:_MAX_EXCERPT_CHARACTERS]
        if title and url and excerpt:
            results.append(WebResult(title=title, url=url, excerpt=excerpt))
    return results


def create_search_web_tool(*, api_key: SecretStr) -> BaseTool:
    @tool
    async def search_web(
        query: Annotated[
            _WebQuery,
            Field(description="A focused web search query for current information"),
        ],
    ) -> str:
        """Search the web for current information."""

        report_phase("searching")
        async with AsyncTavilyClient(api_key=api_key.get_secret_value()) as client:
            payload = await client.search(
                query=query,
                topic="general",
                search_depth="advanced",
                max_results=MAX_WEB_RESULTS,
                include_answer=False,
                include_raw_content=False,
                include_images=False,
                timeout=_TIMEOUT_SECONDS,
            )

        report_phase("reading")
        return json.dumps(
            {
                "results": [
                    {
                        "title": result.title,
                        "url": result.url,
                        "content": result.excerpt,
                    }
                    for result in normalize_results(payload)
                ]
            },
            ensure_ascii=False,
        )

    return search_web
