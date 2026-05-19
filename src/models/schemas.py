from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ConversationSummary:
    conversation_id: str
    session_id: str
    user_id: str
    channel_id: str
    design_mode: bool
    first_event: datetime
    last_event: datetime
    messages_received: int
    messages_sent: int
    topics: list[str] = field(default_factory=list)
    connector_call_count: int = 0

    @property
    def duration_minutes(self) -> float:
        delta = self.last_event - self.first_event
        return round(delta.total_seconds() / 60, 1)


@dataclass
class ConnectorCall:
    timestamp: datetime
    conversation_id: str
    session_id: str
    user_id: str
    channel_id: str
    design_mode: bool
    connector_name: str
    action_target: str
    success: bool
    result_code: str
    duration_ms: float
