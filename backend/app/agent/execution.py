import logging
from dataclasses import dataclass
from uuid import UUID, uuid7

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from sqlmodel import Session

from app.agent.answer import Answer, parse_answer
from app.agent.context import AgentContext
from app.agent.grounding import GroundingFailed, GroundingValidator
from app.core.db import engine
from app.db.answer_sources import list_execution_sources

logger = logging.getLogger(__name__)

# Bounds answer/tool rounds within each independent graph run.
GRAPH_RECURSION_LIMIT = 32
# Two retries after the initial run: at most three graph executions.
MAX_GROUNDING_RETRIES = 2
_EVIDENCE_TOOLS = frozenset({"search_documents", "search_web"})


@dataclass(frozen=True, slots=True)
class ChatExecution:
    execution_id: UUID
    chat_id: UUID
    user_id: UUID


async def execute_chat(
    *,
    graph: CompiledStateGraph,
    grounding_validator: GroundingValidator,
    execution: ChatExecution,
    messages: tuple[BaseMessage, ...],
    generate_title: bool,
) -> Answer:
    """Return a validated answer, rerunning the agent on grounding failures only."""

    attempt = 0
    while True:
        context = AgentContext(
            user_id=execution.user_id,
            chat_id=execution.chat_id,
            execution_id=execution.execution_id if attempt == 0 else uuid7(),
            generate_title=generate_title,
        )
        # Start from the original conversation, never a failed run's messages.
        result = await graph.ainvoke(
            {"messages": list(messages)},
            config={"recursion_limit": GRAPH_RECURSION_LIMIT},
            context=context,
        )
        produced = result["messages"]
        draft = parse_answer(str(produced[-1].text))

        with Session(engine) as db_session:
            sources = list_execution_sources(
                db_session,
                execution_id=context.execution_id,
            )
        try:
            await grounding_validator.validate(
                draft=draft,
                sources=sources,
                searched=evidence_was_searched(produced[len(messages) :]),
                user_request=str(messages[-1].text),
            )
        except GroundingFailed:
            if attempt == MAX_GROUNDING_RETRIES:
                raise
            logger.info(
                "Grounding validation failed; rerunning the agent",
                extra={
                    "execution_id": str(context.execution_id),
                    "attempt": attempt + 1,
                },
            )
            attempt += 1
        else:
            return draft


def evidence_was_searched(messages: list[BaseMessage]) -> bool:
    """Whether this turn consulted a tool whose results must be cited."""

    for message in messages:
        if isinstance(message, ToolMessage) and message.name in _EVIDENCE_TOOLS:
            return True
        if isinstance(message, AIMessage) and any(
            call.get("name") in _EVIDENCE_TOOLS for call in message.tool_calls
        ):
            return True
    return False
