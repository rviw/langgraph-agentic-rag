from dataclasses import dataclass
from uuid import UUID

from langchain_core.messages import BaseMessage
from langgraph.graph.state import CompiledStateGraph
from sqlmodel import Session

from app.agent.answer import Answer, InvalidAnswer, parse_answer
from app.agent.context import AgentContext
from app.agent.grounding import GroundingFailed, check_cited_sources_exist
from app.core.db import engine
from app.db.answer_sources import list_execution_sources

# Bounds how many answer/tool rounds one request may take.
GRAPH_RECURSION_LIMIT = 32


@dataclass(frozen=True, slots=True)
class ChatExecution:
    execution_id: UUID
    chat_id: UUID
    user_id: UUID


async def execute_chat(
    *,
    graph: CompiledStateGraph,
    execution: ChatExecution,
    messages: tuple[BaseMessage, ...],
    generate_title: bool,
) -> Answer:
    """Run one chat turn and return the parsed final answer."""

    result = await graph.ainvoke(
        {"messages": list(messages)},
        config={"recursion_limit": GRAPH_RECURSION_LIMIT},
        context=AgentContext(
            user_id=execution.user_id,
            chat_id=execution.chat_id,
            execution_id=execution.execution_id,
            generate_title=generate_title,
        ),
    )
    draft = parse_answer(str(result["messages"][-1].text))
    with Session(engine) as db_session:
        sources = list_execution_sources(
            db_session,
            execution_id=execution.execution_id,
        )
    try:
        check_cited_sources_exist(draft, sources=sources)
    except InvalidAnswer as exc:
        raise GroundingFailed from exc
    return draft
