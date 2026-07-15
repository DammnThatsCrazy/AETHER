"""
Aether Backend — Attribution Resolver

Resolves attribution for reward eligibility by collecting touchpoints
from the user journey and applying the configured attribution model.

Design:
    - ``AttributionResolver`` is the primary entry point.  It accepts raw
      touchpoint dicts, converts them to ``Touchpoint`` objects, filters by
      the configured lookback window, and delegates to the selected model.
    - ``JourneyStore`` is an in-memory touchpoint store for demo and
      testing purposes (production: DynamoDB / ClickHouse).

Integration:
    Consumed by ``services.attribution.routes`` and by the reward-evaluation
    pipeline in ``services.rewards``.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.attribution.models import (
    ActorWeightedModel,
    AttributionModel,
    AttributionResult,
    DataDrivenModel,
    ExposureAwareModel,
    FirstTouchModel,
    LastTouchModel,
    LinearModel,
    PositionBasedModel,
    TimeDecayModel,
    Touchpoint,
)

logger = logging.getLogger("aether.attribution.resolver")


def _inmemory_journey_store_allowed() -> bool:
    return (
        os.getenv("AETHER_ENV", "local").lower() == "local"
        or os.getenv("AETHER_ALLOW_INMEMORY_JOURNEY_STORE", "0") == "1"
    )


# ========================================================================
# CONFIGURATION
# ========================================================================

@dataclass
class AttributionConfig:
    """Resolver configuration."""

    default_model: str = "last_touch"
    lookback_window_hours: int = 720   # 30 days
    min_touchpoints: int = 1


# ========================================================================
# IN-MEMORY JOURNEY STORE
# ========================================================================

class JourneyStore:
    """
    In-memory touchpoint store keyed by (tenant_id, user_id).

    Tenant isolation is enforced at the key level — touchpoints from
    Tenant A are never visible to Tenant B even for the same user_id.

    Production replacement: DynamoDB, ClickHouse, or a dedicated
    time-series store with tenant_id as a partition key.
    """

    def __init__(self) -> None:
        if not _inmemory_journey_store_allowed():
            raise RuntimeError(
                "JourneyStore is disabled outside local mode. Configure a persistent attribution "
                "store or set AETHER_ALLOW_INMEMORY_JOURNEY_STORE=1 for an explicit override."
            )
        self._store: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    def _key(self, tenant_id: str, user_id: str) -> tuple[str, str]:
        return (tenant_id, user_id)

    def add(self, tenant_id: str, user_id: str, touchpoint: dict[str, Any]) -> None:
        """Append a raw touchpoint dict for a (tenant, user) pair."""
        self._store[self._key(tenant_id, user_id)].append(touchpoint)

    def get(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        """Return all stored touchpoints for a (tenant, user) pair (oldest first)."""
        return list(self._store.get(self._key(tenant_id, user_id), []))

    def clear(self, tenant_id: str, user_id: str) -> int:
        """Remove all touchpoints for a (tenant, user) pair. Returns count removed."""
        count = len(self._store.pop(self._key(tenant_id, user_id), []))
        return count

    def count(self, tenant_id: str, user_id: str) -> int:
        return len(self._store.get(self._key(tenant_id, user_id), []))

    def all_user_ids(self, tenant_id: str) -> list[str]:
        return [uid for (tid, uid) in self._store if tid == tenant_id]


# ========================================================================
# RESOLVER
# ========================================================================

class AttributionResolver:
    """
    Orchestrates touchpoint collection and model selection.

    Usage::

        resolver = AttributionResolver(AttributionConfig(default_model="linear"))
        result = await resolver.resolve(
            user_id="user_123",
            event={"event_type": "conversion"},
            touchpoints=[
                {"channel": "social", "source": "twitter", ...},
                {"channel": "organic", "source": "google", ...},
            ],
        )
    """

    def __init__(self, config: Optional[AttributionConfig] = None) -> None:
        self.config = config or AttributionConfig()
        self._models: dict[str, AttributionModel] = {}
        self._register_defaults()

    # -- model registry ---------------------------------------------------

    def _register_defaults(self) -> None:
        """Register all built-in attribution models."""
        defaults: list[AttributionModel] = [
            FirstTouchModel(),
            LastTouchModel(),
            LinearModel(),
            TimeDecayModel(),
            PositionBasedModel(),
            DataDrivenModel(),
            ActorWeightedModel(),
            ExposureAwareModel(),
        ]
        for model in defaults:
            self._models[model.name] = model

    def get_model(self, name: str) -> AttributionModel:
        """Look up a model by name.  Raises ``KeyError`` if not found."""
        if name not in self._models:
            raise KeyError(f"Unknown attribution model: {name!r}")
        return self._models[name]

    def list_models(self) -> list[str]:
        """Return the names of all registered models."""
        return sorted(self._models.keys())

    # -- resolution -------------------------------------------------------

    async def resolve(
        self,
        user_id: str,
        event: dict[str, Any],
        touchpoints: list[dict[str, Any]],
        model_name: Optional[str] = None,
        *,
        lookback_window_hours: Optional[int] = None,
    ) -> AttributionResult:
        """
        Resolve attribution for a user event.

        Steps:
            1. Convert raw dicts to ``Touchpoint`` objects.
            2. Filter by the lookback window.
            3. Validate minimum touchpoint count.
            4. Select and run the configured (or overridden) model.

        Args:
            user_id:      The user whose journey is being attributed.
            event:        The conversion / target event dict.
            touchpoints:  Raw touchpoint dicts from the journey store or
                          provided inline.
            model_name:   Optional override for the attribution model.
            lookback_window_hours: Optional per-resolution lookback override.
                          This is used when replaying a model-config snapshot
                          whose horizon differs from the resolver default.

        Returns:
            An ``AttributionResult`` with weighted credits summing to 1.0.
        """
        # Step 1 — convert
        typed_touchpoints = self._parse_touchpoints(touchpoints)

        # Step 2 — filter by lookback window
        # Historical recomputation must evaluate lookback relative to the
        # conversion, not wall-clock time. Callers that omit an event timestamp
        # retain the legacy "now" behavior.
        reference_time = _event_reference_time(event)
        # The canonical measurement engine can replay an immutable model-config
        # snapshot whose click/view horizon is longer than this resolver's
        # process-wide default.  An explicit per-run horizon must therefore win;
        # otherwise valid historical touches are silently capped at 30 days.
        effective_lookback_hours = (
            self.config.lookback_window_hours
            if lookback_window_hours is None
            else int(lookback_window_hours)
        )
        cutoff = reference_time - timedelta(hours=effective_lookback_hours)
        filtered = [
            tp for tp in typed_touchpoints
            if cutoff <= tp.timestamp <= reference_time
        ]

        # Sort chronologically
        filtered.sort(key=lambda tp: tp.timestamp)

        # Step 3 — validate
        if len(filtered) < self.config.min_touchpoints:
            logger.warning(
                "Insufficient touchpoints for user=%s: found=%d required=%d",
                user_id, len(filtered), self.config.min_touchpoints,
            )
            return AttributionResult(credits=[], model_used="none", total_credit=0.0)

        # Step 4 — run model
        selected = model_name or self.config.default_model
        model = self.get_model(selected)

        result = await model.attribute(filtered)
        logger.info(
            "Attribution resolved: user=%s model=%s touchpoints=%d",
            user_id, selected, len(filtered),
        )
        return result

    # -- private helpers --------------------------------------------------

    @staticmethod
    def _parse_touchpoints(raw: list[dict[str, Any]]) -> list[Touchpoint]:
        """Convert raw dicts to ``Touchpoint`` objects with safe defaults."""
        touchpoints: list[Touchpoint] = []
        for item in raw:
            ts = item.get("timestamp")
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    ts = datetime.now(timezone.utc)
            elif not isinstance(ts, datetime):
                ts = datetime.now(timezone.utc)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            touchpoints.append(
                Touchpoint(
                    channel=item.get("channel", "unknown"),
                    source=item.get("source", "unknown"),
                    campaign=item.get("campaign", ""),
                    timestamp=ts,
                    event_type=item.get("event_type", "pageview"),
                    properties=item.get("properties", {}),
                )
            )
        return touchpoints


def _event_reference_time(event: dict[str, Any]) -> datetime:
    raw = event.get("timestamp") or event.get("occurred_at") or event.get("created_at")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)
