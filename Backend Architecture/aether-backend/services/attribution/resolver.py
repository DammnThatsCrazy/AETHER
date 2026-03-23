"""
Aether Backend — Attribution Resolver

Resolves attribution for reward eligibility by collecting touchpoints
from the user journey and applying the configured attribution model.

Design:
    - ``AttributionResolver`` is the primary entry point.  It accepts raw
      touchpoint dicts, converts them to ``Touchpoint`` objects, filters by
      the configured lookback window, and delegates to the selected model.
    - ``JourneyStore`` persists touchpoints durably in the shared repository
      store so attribution history survives process restarts.

Integration:
    Consumed by ``services.attribution.routes`` and by the reward-evaluation
    pipeline in ``services.rewards``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from services.attribution.models import (
    AttributionModel,
    AttributionResult,
    DataDrivenModel,
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


class JourneyStore:
    """
    Durable touchpoint store keyed by user ID.
    """

    def __init__(self) -> None:
        self._repo = BaseRepository("attribution_touchpoints")

    async def add(self, user_id: str, touchpoint: dict[str, Any]) -> None:
        """Append a raw touchpoint dict for a user."""
        ts = touchpoint.get("timestamp") or datetime.now(timezone.utc).isoformat()
        touchpoint_id = f"{user_id}:{ts}:{touchpoint.get('channel', 'unknown')}:{touchpoint.get('source', 'unknown')}"
        await self._repo.insert(touchpoint_id, {"user_id": user_id, **touchpoint})

    async def get(self, user_id: str) -> list[dict[str, Any]]:
        """Return all stored touchpoints for a user (oldest first)."""
        return await self._repo.find_many(filters={"user_id": user_id}, limit=10_000, sort_by="timestamp", sort_order="asc")

    async def clear(self, user_id: str) -> int:
        """Remove all touchpoints for a user.  Returns count removed."""
        existing = await self._repo.find_many(filters={"user_id": user_id}, limit=10_000)
        for record in existing:
            await self._repo.delete(record["id"])
        count = len(existing)
        return count

    async def count(self, user_id: str) -> int:
        return await self._repo.count(filters={"user_id": user_id})

    async def all_user_ids(self) -> list[str]:
        rows = await self._repo.find_many(limit=100_000)
        return sorted({row["user_id"] for row in rows if row.get("user_id")})


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

        Returns:
            An ``AttributionResult`` with weighted credits summing to 1.0.
        """
        # Step 1 — convert
        typed_touchpoints = self._parse_touchpoints(touchpoints)

        # Step 2 — filter by lookback window
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.config.lookback_window_hours)
        filtered = [tp for tp in typed_touchpoints if tp.timestamp >= cutoff]

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
