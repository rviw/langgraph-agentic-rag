import json
from dataclasses import dataclass
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolRuntime
from pydantic import Field, SecretStr, StringConstraints
from sqlalchemy.engine import Engine
from sqlmodel import Session
from tavily import AsyncTavilyClient

from app.agent.context import AgentContext
from app.agent.phases import report_phase
from app.db.answer_sources import WebSourceCandidate, record_web_sources

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


def create_search_web_tool(*, api_key: SecretStr, engine: Engine) -> BaseTool:
    @tool
    async def search_web(
        query: Annotated[
            _WebQuery,
            Field(description="A focused web search query for current information"),
        ],
        runtime: ToolRuntime[AgentContext, MessagesState],
    ) -> str:
        """Search the web for current information."""

        report_phase("searching")
        context = runtime.context
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

        with Session(engine) as db_session:
            sources = record_web_sources(
                db_session,
                execution_id=context.execution_id,
                chat_id=context.chat_id,
                candidates=[
                    WebSourceCandidate(
                        title=result.title,
                        url=result.url,
                        excerpt=result.excerpt,
                    )
                    for result in normalize_results(payload)
                ],
            )

        report_phase("reading")
        return json.dumps(
            {
                "results": [
                    {
                        # The model may cite only these identifiers.
                        "source_id": str(source.source_id),
                        "type": source.type,
                        "title": source.title,
                        "url": source.url,
                        "content": source.excerpt,
                    }
                    for source in sources
                ]
            },
            ensure_ascii=False,
        )

    return search_web
