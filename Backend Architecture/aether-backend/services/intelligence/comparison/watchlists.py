"""Watchlist definitions and noise controls for comparison findings.

A watchlist scopes which comparison definitions/dimensions a tenant watches
and applies three noise controls before a finding is surfaced:

- **materiality floor** — findings scoring below the floor are suppressed;
- **dedupe window** — a finding that repeats an already-open finding
  (same definition/dimension/metric/direction) inside the window is
  suppressed as a duplicate;
- **mute rules** — dimension/finding-type mutes, optionally until a time.

Suppression is never silent: every suppressed finding is still persisted
with disposition ``suppressed`` and a typed ``suppression_reason``.

Stored via the BaseRepository JSONB convention — NO alembic migrations.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.common.common import utc_now
from shared.temporal import ensure_aware_utc, parse_instant_strict

from services.intelligence.comparison.generated_vocabulary import (
    COMPARISON_DIMENSIONS,
)
from services.intelligence.comparison.store import TenantScopedComparisonRepository


class MuteRule(BaseModel):
    """Mute findings matching dimension and/or finding_type, optionally until."""

    model_config = ConfigDict(extra="forbid")

    dimension: Optional[str] = None
    finding_type: Optional[str] = None
    until: Optional[datetime] = None
    reason: Optional[str] = None

    def model_post_init(self, __context) -> None:  # noqa: D105
        if self.dimension is not None and self.dimension not in COMPARISON_DIMENSIONS:
            raise ValueError(f"Unknown comparison dimension: {self.dimension!r}")
        if self.dimension is None and self.finding_type is None:
            raise ValueError("A mute rule needs a dimension and/or a finding_type")
        if self.until is not None:
            # tz-naive mute deadlines are rejected (temporal-integrity kernel).
            object.__setattr__(self, "until", ensure_aware_utc(self.until))

    def matches(self, finding: dict[str, Any], now: datetime) -> bool:
        if self.until is not None and now > self.until:
            return False
        if self.dimension is not None and finding.get("dimension") != self.dimension:
            return False
        if self.finding_type is not None and finding.get("finding_type") != self.finding_type:
            return False
        return True


class NoiseControls(BaseModel):
    model_config = ConfigDict(extra="forbid")

    materiality_floor: float = Field(default=0.0, ge=0.0, le=1.0)
    dedupe_window_seconds: int = Field(default=3600, ge=0)
    mute_rules: list[MuteRule] = Field(default_factory=list)


class WatchlistDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    watchlist_id: str
    tenant_id: str
    name: str
    enabled: bool = True
    definition_ids: list[str] = Field(default_factory=list)  # empty = all
    dimensions: list[str] = Field(default_factory=list)  # empty = all
    noise: NoiseControls = Field(default_factory=NoiseControls)
    created_by: Optional[str] = None

    def model_post_init(self, __context) -> None:  # noqa: D105
        unknown = [d for d in self.dimensions if d not in COMPARISON_DIMENSIONS]
        if unknown:
            raise ValueError(f"Unknown comparison dimensions: {unknown}")

    def watches(self, definition_id: str, dimension: Optional[str]) -> bool:
        if not self.enabled:
            return False
        if self.definition_ids and definition_id not in self.definition_ids:
            return False
        if self.dimensions and dimension is not None and dimension not in self.dimensions:
            return False
        return True


class NoiseDecision(BaseModel):
    """Allow, or suppress with a typed reason (never a silent drop)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    suppression_reason: Optional[str] = None
    watchlist_id: Optional[str] = None


class WatchlistRepository(TenantScopedComparisonRepository):
    natural_id_key = "watchlist_id"

    def __init__(self) -> None:
        super().__init__("comparison_watchlists")

    async def upsert(self, watchlist: WatchlistDefinition) -> dict[str, Any]:
        return await self.upsert_scoped(
            watchlist.tenant_id, watchlist.watchlist_id, watchlist.model_dump(mode="json")
        )

    async def list_for_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[WatchlistDefinition]:
        rows = await self.list_scoped(tenant_id, limit=limit, offset=offset)
        return [WatchlistDefinition(**row) for row in rows]


def _finding_dedupe_key(finding: dict[str, Any]) -> tuple:
    return (
        finding.get("dimension"),
        finding.get("metric"),
        finding.get("finding_type"),
        finding.get("direction"),
    )


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return parse_instant_strict(str(value))
    except Exception:
        return None


def apply_noise_controls(
    watchlists: list[WatchlistDefinition],
    definition_id: str,
    finding: dict[str, Any],
    recent_findings: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> NoiseDecision:
    """Evaluate a candidate finding against every watching watchlist.

    The FIRST watchlist that suppresses wins (its typed reason is recorded);
    a finding no watchlist objects to is allowed. No watchlists → allowed.
    """
    now = now or utc_now()
    dimension = finding.get("dimension")
    for watchlist in watchlists:
        if not watchlist.watches(definition_id, dimension):
            continue

        materiality = finding.get("materiality")
        if (
            materiality is not None
            and float(materiality) < watchlist.noise.materiality_floor
        ):
            return NoiseDecision(
                allowed=False,
                suppression_reason=(
                    f"below_materiality_floor:{watchlist.noise.materiality_floor}"
                ),
                watchlist_id=watchlist.watchlist_id,
            )

        for rule in watchlist.noise.mute_rules:
            if rule.matches(finding, now):
                return NoiseDecision(
                    allowed=False,
                    suppression_reason="muted_by_watchlist_rule",
                    watchlist_id=watchlist.watchlist_id,
                )

        if watchlist.noise.dedupe_window_seconds > 0:
            window_start = now - timedelta(seconds=watchlist.noise.dedupe_window_seconds)
            key = _finding_dedupe_key(finding)
            for prior in recent_findings:
                if _finding_dedupe_key(prior) != key:
                    continue
                observed = _parse_ts(
                    prior.get("last_observed_at") or prior.get("first_observed_at")
                )
                if observed is not None and observed >= window_start:
                    return NoiseDecision(
                        allowed=False,
                        suppression_reason=(
                            f"duplicate_within_dedupe_window:"
                            f"{watchlist.noise.dedupe_window_seconds}s"
                        ),
                        watchlist_id=watchlist.watchlist_id,
                    )

    return NoiseDecision(allowed=True)


__all__ = [
    "MuteRule",
    "NoiseControls",
    "NoiseDecision",
    "WatchlistDefinition",
    "WatchlistRepository",
    "apply_noise_controls",
]
