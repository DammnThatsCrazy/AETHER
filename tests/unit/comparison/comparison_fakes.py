"""Shared fakes for comparison-engine unit tests (imported via test-dir sys.path)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def make_events(
    n: int,
    *,
    event_type: str = "page_view",
    end: datetime | None = None,
    spacing_hours: float = 12.0,
    props: dict | None = None,
) -> list[dict]:
    """Synthetic analytics events with tz-aware timestamps, newest first."""
    end = end or datetime.now(timezone.utc)
    return [
        {
            "event_type": event_type,
            "timestamp": (end - timedelta(hours=spacing_hours * i)).isoformat(),
            "properties": dict(props or {}),
        }
        for i in range(n)
    ]


class FakeAnalytics:
    """Duck-typed AnalyticsRepository: events keyed by (tenant_id, user_id)."""

    def __init__(self) -> None:
        self.events: dict[tuple[str, str], list[dict]] = {}

    def seed(self, tenant_id: str, user_id: str, events: list[dict]) -> None:
        self.events[(tenant_id, user_id)] = events

    async def query_events(
        self, tenant_id: str, query_params: dict, limit: int = 100
    ) -> list[dict]:
        rows = self.events.get((tenant_id, str(query_params.get("user_id"))), [])
        return rows[:limit]
