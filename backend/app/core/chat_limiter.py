from datetime import date, datetime
from threading import Lock
from uuid import UUID
from zoneinfo import ZoneInfo


class DailyChatLimiter:
    """Enforce a per-user daily limit within a single server process."""

    def __init__(self, *, limit: int, timezone: str) -> None:
        self._limit = limit
        self._timezone = ZoneInfo(timezone)
        self._day: date | None = None
        self._counts: dict[UUID, int] = {}
        self._lock = Lock()

    def consume(self, user_id: UUID) -> bool:
        """Consume one message allowance, returning false when none remain."""

        today = datetime.now(self._timezone).date()
        with self._lock:
            if today != self._day:
                self._day = today
                self._counts.clear()

            used = self._counts.get(user_id, 0)
            if used >= self._limit:
                return False

            self._counts[user_id] = used + 1
            return True
