"""Dimension observation collection for the comparison engine.

Observations are collected from the EXISTING analytics events plane
(``repositories.repos.AnalyticsRepository`` — the same store the profile and
expectations engines read). A dimension the collector has no real source for
is reported as ``uncollectable`` — never as an empty-but-comparable series.
Missing data is a first-class state here, so the engine's data-truth
preflight can refuse instead of concluding "no difference".
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now

from services.intelligence.comparison.contracts import ComparisonSubject
from services.intelligence.comparison.generated_vocabulary import COMPARISON_DIMENSIONS


class MetricValue(BaseModel):
    """One observed metric with enough metadata for honest alignment."""

    model_config = ConfigDict(extra="forbid")

    name: str
    value: float
    unit: str  # e.g. "count", "count_per_day", "usd", "types"
    window_days: Optional[float] = None
    provenance: str = "analytics_events"


class DimensionObservations(BaseModel):
    """Everything observed for one subject along one dimension."""

    model_config = ConfigDict(extra="forbid")

    dimension: str
    collectable: bool
    observation_count: int = 0
    metrics: list[MetricValue] = Field(default_factory=list)
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    source: str = "analytics_events"
    reason: Optional[str] = None  # why uncollectable / empty

    @property
    def is_empty(self) -> bool:
        return self.observation_count == 0

    def metric(self, name: str) -> Optional[MetricValue]:
        for m in self.metrics:
            if m.name == name:
                return m
        return None


# ── Dimension → event predicate mapping ─────────────────────────────────────
# Only dimensions with a REAL source on the analytics plane are collectable.
# Everything else is honestly uncollectable (reason recorded) until its
# owning plane exposes observations.

def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or "")


def _has_prop(*keys: str) -> Callable[[dict[str, Any]], bool]:
    def check(event: dict[str, Any]) -> bool:
        props = event.get("properties") or {}
        return any(k in props or k in event for k in keys)

    return check


def _type_contains(*fragments: str) -> Callable[[dict[str, Any]], bool]:
    def check(event: dict[str, Any]) -> bool:
        et = _event_type(event).lower()
        return any(f in et for f in fragments)

    return check


def _any_event(event: dict[str, Any]) -> bool:
    return True


COLLECTABLE_DIMENSIONS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "behavior": _any_event,
    "sessions": _type_contains("session"),
    "devices": _has_prop("device", "device_id", "platform"),
    "campaigns": _has_prop("campaign_id", "utm_campaign"),
    "economic_activity": _has_prop("revenue", "revenue_usd", "value_usd", "amount"),
    "temporal_activity": _any_event,
    "geography": _has_prop("country", "region", "city", "geo"),
}

UNCOLLECTABLE_REASON = "no_observation_source_registered_for_dimension"


def validate_dimensions(dimensions: list[str]) -> None:
    unknown = [d for d in dimensions if d not in COMPARISON_DIMENSIONS]
    if unknown:
        raise ValueError(f"Unknown comparison dimensions: {unknown}")


class AnalyticsDimensionCollector:
    """Collects per-dimension observations from the analytics events plane."""

    def __init__(self, analytics_repo: Any) -> None:
        # repositories.repos.AnalyticsRepository (duck-typed for tests).
        self._analytics = analytics_repo

    async def collect(
        self,
        tenant_id: str,
        subject: ComparisonSubject,
        dimension: str,
        *,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
        limit: int = 500,
    ) -> DimensionObservations:
        if dimension not in COMPARISON_DIMENSIONS:
            raise ValueError(f"Unknown comparison dimension: {dimension!r}")

        predicate = COLLECTABLE_DIMENSIONS.get(dimension)
        if predicate is None:
            return DimensionObservations(
                dimension=dimension,
                collectable=False,
                reason=UNCOLLECTABLE_REASON,
                source="none",
            )

        end = window_end or utc_now()
        start = window_start or (end - timedelta(days=30))

        events = await self._analytics.query_events(
            tenant_id, {"user_id": subject.subject_id}, limit=limit
        )
        in_window = [e for e in events if self._in_window(e, start, end)]
        matched = [e for e in in_window if predicate(e)]

        window_days = max((end - start).total_seconds() / 86400.0, 1e-9)
        # The standard metric set is ALWAYS emitted once the query executed:
        # zero matches over a covered window is an OBSERVED zero (silence),
        # not missing data. Missing data is signalled by observation_count=0
        # so the engine's preflight can still refuse empty-vs-empty — a
        # single empty side compares against explicit zeros instead.
        metrics: list[MetricValue] = [
            MetricValue(
                name="event_count",
                value=float(len(matched)),
                unit="count",
                window_days=window_days,
            ),
            MetricValue(
                name="events_per_day",
                value=len(matched) / window_days,
                unit="count_per_day",
                window_days=window_days,
            ),
            MetricValue(
                name="distinct_event_types",
                value=float(len({_event_type(e) for e in matched})),
                unit="types",
                window_days=window_days,
            ),
        ]

        return DimensionObservations(
            dimension=dimension,
            collectable=True,
            observation_count=len(matched),
            metrics=metrics,
            window_start=start,
            window_end=end,
            reason=None if matched else "no_events_in_window",
        )

    @staticmethod
    def _in_window(event: dict[str, Any], start: datetime, end: datetime) -> bool:
        raw = event.get("timestamp") or event.get("occurred_at") or event.get("created_at")
        if not raw:
            # No timestamp — cannot place the event in the window; excluding it
            # is the honest choice (it can never silently satisfy a window).
            return False
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return False
        if ts.tzinfo is None:
            return False
        return start <= ts <= end


__all__ = [
    "MetricValue",
    "DimensionObservations",
    "COLLECTABLE_DIMENSIONS",
    "UNCOLLECTABLE_REASON",
    "AnalyticsDimensionCollector",
    "validate_dimensions",
]
