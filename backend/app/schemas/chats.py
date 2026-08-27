from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.agent.phases import ExecutionPhase
from app.schemas.sources import CitationResponse


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime


class ChatMessageResponse(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationResponse] = []


class CreateChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4_000)


class MessageAcceptedEvent(BaseModel):
    """The user's message is stored and the answer is being produced."""

    type: Literal["message.accepted"] = "message.accepted"
    message: ChatMessageResponse


class ExecutionProgressEvent(BaseModel):
    type: Literal["execution.progress"] = "execution.progress"
    phase: ExecutionPhase


class MessageCompletedEvent(BaseModel):
    type: Literal["message.completed"] = "message.completed"
    message: ChatMessageResponse


class ExecutionErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class ExecutionFailedEvent(BaseModel):
    type: Literal["execution.failed"] = "execution.failed"
    error: ExecutionErrorResponse
