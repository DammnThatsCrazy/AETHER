"""Durable versioned journey compiler — builds and rebuilds journey_versions from canonical touchpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from services.journeys.stitching import JourneyStitchingService
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = logging.getLogger("aether.measurement.journey_compiler")

_SESSION_TIMEOUT_SECONDS = 1800  # 30 minutes of inactivity = new session
_MAX_JOURNEY_TOUCHPOINTS = 2000

_scorer = JourneyStitchingService()


class JourneyCompiler:
    """Builds versioned journeys from canonical touchpoints in PostgreSQL.

    Each call creates a new journey_version row and marks the prior as stale.
    The journey_id is stable across versions; only journey_version_id changes.

    Reuses JourneyStitchingService.score() for confidence computation.
    """

    def __init__(self) -> None:
        self._journey_repo = JourneyRepository()
        self._touchpoint_repo = TouchpointRepository()
        self._conversion_repo = ConversionRepository()

    async def compile_for_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        trigger_reason: str = "manual",
        session_timeout_seconds: int = _SESSION_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Build the current journey version for a profile.

        Loads all touchpoints, groups into sessions, builds channel sequence,
        links conversions, and persists a new journey_version.
        """
        touchpoints = await self._touchpoint_repo.list_by_profile(
            tenant_id, profile_id, limit=_MAX_JOURNEY_TOUCHPOINTS,
        )
        conversions = await self._conversion_repo.list_by_profile(
            tenant_id, profile_id, attribution_eligible_only=False, limit=500,
        )

        return await self._build_and_persist(
            tenant_id=tenant_id,
            profile_id=profile_id,
            touchpoints=touchpoints,
            conversions=conversions,
            trigger_reason=trigger_reason,
            session_timeout_seconds=session_timeout_seconds,
        )

    async def rebuild_affected_by_touchpoint(
        self,
        tenant_id: str,
        touchpoint_id: str,
    ) -> list[dict[str, Any]]:
        """Rebuild journeys for the profile owning a given touchpoint."""
        tp = await self._touchpoint_repo.get(tenant_id, touchpoint_id)
        if tp is None:
            return []

        profile_id = tp.get("profile_id") or tp.get("anonymous_id")
        if not profile_id:
            return []

        version = await self.compile_for_profile(
            tenant_id, profile_id, trigger_reason="touchpoint_received",
        )
        return [version]

    async def rebuild_affected_by_identity_change(
        self,
        tenant_id: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        """Rebuild all journeys for a profile after an identity merge or update."""
        version = await self.compile_for_profile(
            tenant_id, profile_id, trigger_reason="identity_change",
        )
        return [version]

    async def rebuild_affected_by_consent_change(
        self,
        tenant_id: str,
        profile_id: str,
    ) -> list[dict[str, Any]]:
        """Rebuild journeys excluding any touchpoints whose consent was revoked.

        Touchpoints with revoked consent should already be tombstoned in the
        silver table before this method is called.
        """
        version = await self.compile_for_profile(
            tenant_id, profile_id, trigger_reason="consent_change",
        )
        return [version]

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _build_and_persist(
        self,
        tenant_id: str,
        profile_id: str,
        touchpoints: list[dict[str, Any]],
        conversions: list[dict[str, Any]],
        trigger_reason: str,
        session_timeout_seconds: int,
    ) -> dict[str, Any]:
        # Sort touchpoints chronologically
        touchpoints = sorted(touchpoints, key=lambda tp: tp.get("occurred_at", ""))

        sessions = _group_into_sessions(touchpoints, timeout_seconds=session_timeout_seconds)
        channel_sequence = _build_channel_sequence(touchpoints)

        started_at: Optional[str] = None
        ended_at: Optional[str] = None
        if touchpoints:
            started_at = touchpoints[0].get("occurred_at")
            ended_at = touchpoints[-1].get("occurred_at")

        converted_at: Optional[str] = None
        if conversions:
            sorted_convs = sorted(conversions, key=lambda c: c.get("occurred_at", ""))
            converted_at = sorted_convs[-1].get("occurred_at")

        tp_ids = [tp["touchpoint_id"] for tp in touchpoints if tp.get("touchpoint_id")]
        conv_ids = [c["conversion_id"] for c in conversions if c.get("conversion_id")]
        session_ids = list({tp.get("session_id") for tp in touchpoints if tp.get("session_id")})
        device_ids = list({tp.get("device_id") for tp in touchpoints if tp.get("device_id")})
        campaign_ids = list({tp.get("campaign_id") for tp in touchpoints if tp.get("campaign_id")})

        # Confidence scoring via JourneyStitchingService.score()
        has_user_id = any(tp.get("profile_id") for tp in touchpoints)
        has_wallet = any(tp.get("wallet_id") for tp in touchpoints)
        has_anon = any(tp.get("anonymous_id") for tp in touchpoints)
        has_fingerprint = any(tp.get("device_id") for tp in touchpoints)
        has_campaign = bool(campaign_ids)

        confidence, _ = _scorer.score(
            user_id=profile_id if has_user_id else None,
            wallet=next((tp.get("wallet_id") for tp in touchpoints if tp.get("wallet_id")), None),
            anonymous_id=next((tp.get("anonymous_id") for tp in touchpoints if tp.get("anonymous_id")), None),
            fingerprint=next((tp.get("device_id") for tp in touchpoints if tp.get("device_id")), None),
            campaign={"campaign_id": campaign_ids[0]} if campaign_ids else None,
            timestamp_proximity=len(touchpoints) > 1,
        )

        journey_state = "converted" if converted_at else ("open" if touchpoints else "empty")

        # Load prior current version for lineage
        prior_versions = await self._journey_repo.find_current_for_profile(tenant_id, profile_id)
        prior = prior_versions[0] if prior_versions else None
        journey_id = prior.get("journey_id") if prior else str(uuid4())
        previous_version_id = prior.get("journey_version_id") if prior else None

        new_version: dict[str, Any] = {
            "journey_version_id": str(uuid4()),
            "journey_id": journey_id,
            "tenant_id": tenant_id,
            "profile_id": profile_id,
            "journey_type": "profile",
            "journey_state": journey_state,
            "started_at": started_at,
            "ended_at": ended_at,
            "converted_at": converted_at,
            "entry_touchpoint_id": tp_ids[0] if tp_ids else None,
            "exit_touchpoint_id": tp_ids[-1] if tp_ids else None,
            "conversion_ids": conv_ids,
            "touchpoint_ids": tp_ids,
            "session_ids": session_ids,
            "device_ids": device_ids,
            "campaign_ids": campaign_ids,
            "channel_sequence": channel_sequence,
            "previous_version_id": previous_version_id,
            "rebuild_reason": trigger_reason,
            "compiler_version": "1.0",
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "is_current": True,
        }

        persisted = await self._journey_repo.create_version(new_version)

        logger.info(
            "Journey compiled: tenant=%s profile=%s touchpoints=%d conversions=%d sessions=%d "
            "state=%s confidence=%.2f reason=%s",
            tenant_id, profile_id, len(tp_ids), len(conv_ids), len(sessions),
            journey_state, confidence, trigger_reason,
        )

        return persisted


# ── Helpers ──────────────────────────────────────────────────────────────────

def _group_into_sessions(
    touchpoints: list[dict[str, Any]],
    timeout_seconds: int = _SESSION_TIMEOUT_SECONDS,
) -> list[list[dict[str, Any]]]:
    """Group touchpoints into sessions by inactivity gap."""
    if not touchpoints:
        return []

    sessions: list[list[dict[str, Any]]] = []
    current_session: list[dict[str, Any]] = [touchpoints[0]]
    prev_ts = _parse_ts(touchpoints[0].get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc)

    for tp in touchpoints[1:]:
        ts = _parse_ts(tp.get("occurred_at")) or prev_ts
        gap = (ts - prev_ts).total_seconds()
        if gap > timeout_seconds:
            sessions.append(current_session)
            current_session = [tp]
        else:
            current_session.append(tp)
        prev_ts = ts

    sessions.append(current_session)
    return sessions


def _build_channel_sequence(touchpoints: list[dict[str, Any]]) -> list[str]:
    """Build a deduplicated ordered list of channel:source transitions."""
    sequence: list[str] = []
    prev = None
    for tp in touchpoints:
        channel = tp.get("channel") or "unknown"
        source = tp.get("source") or ""
        label = f"{channel}:{source}" if source else channel
        if label != prev:
            sequence.append(label)
            prev = label
    return sequence


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
