from collections.abc import Callable
from uuid import UUID

import pytest
from sqlmodel import Session

from app.db.chat_messages import (
    append_assistant_message,
    append_user_message,
    list_chat_messages,
)
from app.models import Chat


@pytest.fixture
def chat(db_session: Session, create_user: Callable[..., UUID]) -> Chat:
    chat = Chat(user_id=create_user())
    db_session.add(chat)
    db_session.commit()
    db_session.refresh(chat)
    return chat


def test_a_turn_is_stored_in_the_order_it_was_written(
    db_session: Session,
    chat: Chat,
) -> None:
    append_user_message(db_session, chat_id=chat.id, content="First question")
    append_assistant_message(db_session, chat_id=chat.id, content="First answer")
    db_session.commit()
    append_user_message(db_session, chat_id=chat.id, content="Second question")

    stored = list_chat_messages(db_session, chat_id=chat.id)

    assert [(item.role, item.content, item.message_index) for item in stored] == [
        ("user", "First question", 0),
        ("assistant", "First answer", 1),
        ("user", "Second question", 2),
    ]


def test_the_answering_history_carries_the_whole_transcript(
    db_session: Session,
    chat: Chat,
) -> None:
    append_user_message(db_session, chat_id=chat.id, content="Question")
    append_assistant_message(db_session, chat_id=chat.id, content="Answer")
    db_session.commit()

    appended = append_user_message(db_session, chat_id=chat.id, content="Follow up")

    assert [message.text for message in appended.history] == [
        "Question",
        "Answer",
        "Follow up",
    ]
    assert [message.type for message in appended.history] == ["human", "ai", "human"]
