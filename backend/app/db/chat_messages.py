from dataclasses import dataclass
from typing import cast
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Chat, ChatMessage
from app.models.chat import DEFAULT_CHAT_TITLE
from app.models.chat_message import ChatMessageRole


@dataclass(frozen=True, slots=True)
class StoredChatMessage:
    id: UUID
    role: ChatMessageRole
    content: str


@dataclass(frozen=True, slots=True)
class AppendedUserMessage:
    """A committed user message plus the transcript the agent should answer."""

    message: StoredChatMessage
    history: tuple[BaseMessage, ...]
    is_first_user_message: bool


def _stored(message: ChatMessage) -> StoredChatMessage:
    return StoredChatMessage(
        id=message.id,
        role=cast(ChatMessageRole, message.role),
        content=message.content,
    )


def list_chat_messages(
    db_session: Session,
    *,
    chat_id: UUID,
) -> list[ChatMessage]:
    return list(
        db_session.exec(
            select(ChatMessage)
            .where(ChatMessage.chat_id == chat_id)
            .order_by(ChatMessage.message_index)
        ).all()
    )


def _as_model_messages(messages: list[ChatMessage]) -> tuple[BaseMessage, ...]:
    return tuple(
        HumanMessage(id=str(message.id), content=message.content)
        if message.role == "user"
        else AIMessage(id=str(message.id), content=message.content)
        for message in messages
    )


def _append(
    db_session: Session,
    *,
    chat_id: UUID,
    role: ChatMessageRole,
    content: str,
) -> ChatMessage:
    """Append one message at the next free position in the chat."""

    normalized = content.strip()
    if not normalized:
        raise ValueError("Chat messages must not be blank")

    latest_index = db_session.exec(
        select(func.max(ChatMessage.message_index)).where(
            ChatMessage.chat_id == chat_id
        )
    ).one()
    message = ChatMessage(
        chat_id=chat_id,
        message_index=0 if latest_index is None else int(latest_index) + 1,
        role=role,
        content=normalized,
    )
    db_session.add(message)
    db_session.flush()
    return message


def append_user_message(
    db_session: Session,
    *,
    chat_id: UUID,
    content: str,
) -> AppendedUserMessage:
    """Commit the user's message and read back the transcript to answer."""

    try:
        message = _append(
            db_session,
            chat_id=chat_id,
            role="user",
            content=content,
        )
        messages = list_chat_messages(db_session, chat_id=chat_id)
        appended = AppendedUserMessage(
            message=_stored(message),
            history=_as_model_messages(messages),
            is_first_user_message=not any(
                item.role == "user" and item.id != message.id for item in messages
            ),
        )
        db_session.commit()
        return appended
    except Exception:
        db_session.rollback()
        raise


def append_assistant_message(
    db_session: Session,
    *,
    chat_id: UUID,
    content: str,
) -> StoredChatMessage:
    return _stored(
        _append(
            db_session,
            chat_id=chat_id,
            role="assistant",
            content=content,
        )
    )


def set_chat_title(
    db_session: Session,
    *,
    chat_id: UUID,
    title: str,
) -> None:
    """Name a chat once, leaving a title the user already sees untouched."""

    chat = db_session.exec(select(Chat).where(Chat.id == chat_id)).one()
    if chat.title == DEFAULT_CHAT_TITLE:
        chat.title = title
        db_session.add(chat)
