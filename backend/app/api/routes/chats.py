import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID, uuid7

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.agent.answer import title_from_question
from app.agent.execution import ChatExecution, execute_chat
from app.agent.grounding import GroundingFailed
from app.agent.memory import record_memories_from_turn
from app.agent.phases import ExecutionPhase, observe_phases
from app.api.deps import (
    CurrentUserDep,
    DbSessionDep,
    DocumentStorageDep,
    GraphDep,
    GroundingValidatorDep,
    MemoryExtractorDep,
    MemoryIndexDep,
    OwnedChatDep,
    TracerDep,
)
from app.api.streaming import (
    HEARTBEAT_FRAME,
    HEARTBEAT_SECONDS,
    SSE_HEADERS,
    event_frame,
)
from app.core.db import engine
from app.db.answer_sources import (
    publish_citations,
    read_citations,
    read_source_detail,
)
from app.db.chat_messages import (
    append_assistant_message,
    append_user_message,
    set_chat_title,
)
from app.db.chat_messages import list_chat_messages as list_stored_messages
from app.db.memories import IndexedMemoryWriter
from app.models import Chat, Document
from app.schemas.chats import (
    ChatMessageResponse,
    ChatResponse,
    CreateChatMessageRequest,
    ExecutionErrorResponse,
    ExecutionFailedEvent,
    ExecutionProgressEvent,
    MessageAcceptedEvent,
    MessageCompletedEvent,
)
from app.schemas.sources import (
    SourceDetailResponse,
    citation_responses,
    source_detail_response,
)

router = APIRouter(prefix="/chats", tags=["chats"])
logger = logging.getLogger(__name__)

_GENERIC_FAILURE = "Couldn’t generate a response."
_UNGROUNDED_FAILURE = "Sources don’t support an answer. Try another question."


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
def create_chat(
    db_session: DbSessionDep,
    current_user: CurrentUserDep,
) -> Chat:
    chat = Chat(user_id=current_user.id)
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)
    return chat


@router.get("", response_model=list[ChatResponse])
def list_chats(
    db_session: DbSessionDep,
    current_user: CurrentUserDep,
) -> list[Chat]:
    """List the caller's chats, newest first."""

    # Identifiers are UUIDv7, so ordering by id is chronological.
    chats = db_session.exec(
        select(Chat).where(Chat.user_id == current_user.id).order_by(Chat.id.desc())
    ).all()
    return list(chats)


@router.get("/{chat_id}", response_model=ChatResponse)
def get_chat(chat: OwnedChatDep) -> Chat:
    return chat


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
    storage: DocumentStorageDep,
) -> None:
    """Delete a chat. Cascades remove its transcript and captured sources."""

    # Stored objects are not covered by database cascades.
    document = db_session.exec(
        select(Document).where(Document.chat_id == chat.id)
    ).one_or_none()
    if document is not None:
        storage.remove(document.storage_object_path)

    db_session.delete(chat)
    db_session.commit()


@router.get("/{chat_id}/messages", response_model=list[ChatMessageResponse])
def list_chat_message_history(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
) -> list[ChatMessageResponse]:
    """Return the stored transcript in the order it was written."""

    messages = list_stored_messages(db_session, chat_id=chat.id)
    citations = read_citations(
        db_session,
        message_ids=[message.id for message in messages],
    )
    return [
        ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
            citations=citation_responses(citations.get(message.id, ())),
        )
        for message in messages
    ]


@router.get(
    "/{chat_id}/messages/{message_id}/sources/{source_id}",
    response_model=SourceDetailResponse,
)
def get_source_detail(
    chat: OwnedChatDep,
    message_id: UUID,
    source_id: UUID,
    db_session: DbSessionDep,
) -> SourceDetailResponse:
    """Read a source cited by the requested message in an owned chat."""

    detail = read_source_detail(
        db_session, chat_id=chat.id, message_id=message_id, source_id=source_id
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This source is no longer available.",
        )
    return source_detail_response(detail)


async def _stream_turn(
    *,
    graph,
    grounding_validator,
    memory_extractor,
    memory_writer,
    execution: ChatExecution,
    content: str,
) -> AsyncIterator[str]:
    """Stream one turn: accept the message, report progress, publish the answer.

    The answer runs as its own task so progress frames and heartbeats keep
    flowing while the agent works.
    """

    answer_task: asyncio.Task[MessageCompletedEvent] | None = None
    try:
        with Session(engine) as db_session:
            accepted = append_user_message(
                db_session,
                chat_id=execution.chat_id,
                content=content,
            )

        yield event_frame(
            MessageAcceptedEvent(
                message=ChatMessageResponse(
                    id=accepted.message.id,
                    role="user",
                    content=accepted.message.content,
                )
            )
        )

        phases: asyncio.Queue[ExecutionPhase | None] = asyncio.Queue()

        async def produce_answer() -> MessageCompletedEvent:
            try:
                with observe_phases(phases.put_nowait):
                    answer = await execute_chat(
                        graph=graph,
                        grounding_validator=grounding_validator,
                        execution=execution,
                        messages=accepted.history,
                        generate_title=accepted.is_first_user_message,
                    )
                with Session(engine) as db_session:
                    assistant = append_assistant_message(
                        db_session,
                        chat_id=execution.chat_id,
                        content=answer.markdown,
                    )
                    citations = publish_citations(
                        db_session,
                        assistant_message_id=assistant.id,
                        source_ids=answer.source_ids,
                    )
                    if accepted.is_first_user_message:
                        set_chat_title(
                            db_session,
                            chat_id=execution.chat_id,
                            title=answer.title or title_from_question(content),
                        )
                    db_session.commit()
                # Saved before the completed event, so a memory the turn
                # revealed is available as soon as the answer appears.
                await record_memories_from_turn(
                    extractor=memory_extractor,
                    writer=memory_writer,
                    user_id=execution.user_id,
                    user_message=content,
                    assistant_message=answer.markdown,
                )
                return MessageCompletedEvent(
                    message=ChatMessageResponse(
                        id=assistant.id,
                        role="assistant",
                        content=assistant.content,
                        citations=citation_responses(citations),
                    )
                )
            finally:
                phases.put_nowait(None)

        answer_task = asyncio.create_task(produce_answer())

        last_phase: ExecutionPhase = "understanding"
        yield event_frame(ExecutionProgressEvent(phase=last_phase))

        while True:
            try:
                phase = await asyncio.wait_for(phases.get(), HEARTBEAT_SECONDS)
            except TimeoutError:
                yield HEARTBEAT_FRAME
                continue
            if phase is None:
                break
            if phase != last_phase:
                last_phase = phase
                yield event_frame(ExecutionProgressEvent(phase=phase))

        yield event_frame(await answer_task)
    except GroundingFailed:
        # The evidence genuinely does not support an answer, which is worth saying.
        logger.info("Chat execution produced no grounded answer")
        yield event_frame(
            ExecutionFailedEvent(
                error=ExecutionErrorResponse(message=_UNGROUNDED_FAILURE)
            )
        )
    except Exception:
        # The caller sees one safe message; details stay in the server log.
        logger.exception("Chat execution failed")
        yield event_frame(
            ExecutionFailedEvent(error=ExecutionErrorResponse(message=_GENERIC_FAILURE))
        )
    finally:
        if answer_task is not None and not answer_task.done():
            answer_task.cancel()


async def _traced_turn(
    *,
    tracer,
    execution: ChatExecution,
    **turn: object,
) -> AsyncIterator[str]:
    """Stream one turn inside a single trace covering its model and tool calls."""

    with tracer.trace_execution(
        execution_id=execution.execution_id,
        chat_id=execution.chat_id,
        user_id=execution.user_id,
    ):
        async for frame in _stream_turn(execution=execution, **turn):
            yield frame


@router.post("/{chat_id}/messages", response_class=StreamingResponse)
def create_chat_message(
    payload: CreateChatMessageRequest,
    chat: OwnedChatDep,
    graph: GraphDep,
    grounding_validator: GroundingValidatorDep,
    memory_extractor: MemoryExtractorDep,
    memory_index: MemoryIndexDep,
    tracer: TracerDep,
) -> StreamingResponse:
    """Answer one user message, streaming progress until the answer is stored."""

    execution = ChatExecution(
        execution_id=uuid7(),
        chat_id=chat.id,
        user_id=chat.user_id,
    )
    return StreamingResponse(
        _traced_turn(
            tracer=tracer,
            graph=graph,
            grounding_validator=grounding_validator,
            memory_extractor=memory_extractor,
            memory_writer=IndexedMemoryWriter(engine, memory_index),
            execution=execution,
            content=payload.content,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
