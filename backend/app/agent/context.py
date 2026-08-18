from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AgentContext:
    user_id: UUID
    chat_id: UUID
    execution_id: UUID
    generate_title: bool
