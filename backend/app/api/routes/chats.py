from fastapi import APIRouter, status
from sqlmodel import select

from app.api.deps import CurrentUserDep, DbSessionDep, OwnedChatDep
from app.db.chat_messages import list_chat_messages as list_stored_messages
from app.models import Chat
from app.schemas.chats import ChatMessageResponse, ChatResponse

router = APIRouter(prefix="/chats", tags=["chats"])


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
def delete_chat(chat: OwnedChatDep, db_session: DbSessionDep) -> None:
    """Delete a chat. Cascades remove its transcript and captured sources."""

    db_session.delete(chat)
    db_session.commit()


@router.get("/{chat_id}/messages", response_model=list[ChatMessageResponse])
def list_chat_message_history(
    chat: OwnedChatDep,
    db_session: DbSessionDep,
) -> list[ChatMessageResponse]:
    """Return the stored transcript in the order it was written."""

    return [
        ChatMessageResponse(
            id=message.id,
            role=message.role,
            content=message.content,
        )
        for message in list_stored_messages(db_session, chat_id=chat.id)
    ]
