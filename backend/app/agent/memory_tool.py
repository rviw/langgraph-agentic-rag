import json
from typing import Annotated

from langchain_core.tools import BaseTool, tool
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolRuntime
from pydantic import Field, StringConstraints

from app.agent.context import AgentContext
from app.agent.phases import report_phase
from app.db.memories import memory_namespace
from app.models.memory import MEMORY_CONTENT_MAX_LENGTH

MAX_MEMORY_RESULTS = 5

_MemoryQuery = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MEMORY_CONTENT_MAX_LENGTH,
    ),
]


def create_search_memories_tool() -> BaseTool:
    @tool
    async def search_memories(
        query: Annotated[
            _MemoryQuery,
            Field(description="A focused query about a saved fact for this user"),
        ],
        runtime: ToolRuntime[AgentContext, MessagesState],
    ) -> str:
        """Search facts this user stated in earlier chats."""

        report_phase("searching")
        # The namespace is derived from the request, never from the query.
        items = await runtime.store.asearch(
            memory_namespace(runtime.context.user_id),
            query=query,
            limit=MAX_MEMORY_RESULTS,
        )
        report_phase("reading")
        return json.dumps(
            {"results": [{"memory": item.value["memory"]} for item in items]},
            ensure_ascii=False,
        )

    return search_memories
