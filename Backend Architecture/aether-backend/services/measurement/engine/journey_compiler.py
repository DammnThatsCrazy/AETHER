"""Durable versioned journey compiler v2.0 — builds unified cross-rail journeys.

Compiler v2.0 extends v1.0 by consuming ALL canonical activity (Web2, Web3,
campaign, commerce, agent, x402, outcome) instead of only campaign touchpoints
and conversions. It persists individual journey_steps and classifies cross-rail
transitions, producing the interleaved ordered sequence required by the unified
journey product.

Backward compatibility:
  - Public API is unchanged (compile_for_profile, rebuild_affected_by_*)
  - journey_version schema is extended, not replaced (step_count, web3/agent/x402 arrays)
  - Attribution touchpoint+conversion paths remain unchanged for attribution engine use
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from services.journeys.stitching import JourneyStitchingService
from services.measurement.contracts import ActivityFamily, ActivityStatus, TransitionType
from services.measurement.repositories.activity_repo import ActivityRepository
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.journey_step_repo import JourneyStepRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = logging.getLogger("aether.measurement.journey_compiler")

_SESSION_TIMEOUT_SECONDS = 1800       # 30 min inactivity
_MAX_JOURNEY_STEPS = 2000             # Hard cap; long journeys use windowing
_COMPILER_VERSION = "2.0"

_scorer = JourneyStitchingService()

# Activity families that do NOT break session boundaries on their own
# (Web3 tx lifecycle events belong to the session that initiated them)
_NON_SESSION_BREAKING_FAMILIES = frozenset({
    ActivityFamily.web3.value,
    ActivityFamily.x402.value,
})


class JourneyCompiler:
    """Builds versioned journeys from the full canonical_activity ledger.

    Each call creates a new journey_version row (marking the prior current as
    stale) and bulk-inserts fresh journey_steps. The journey_id is stable across
    versions; only journey_version_id changes.
    """

    def __init__(self) -> None:
        self._journey_repo = JourneyRepository()
        self._step_repo = JourneyStepRepository()
        self._activity_repo = ActivityRepository()
        self._touchpoint_repo = TouchpointRepository()   # kept for attribution engine
        self._conversion_repo = ConversionRepository()   # kept for attribution engine

    async def compile_for_profile(
        self,
        tenant_id: str,
        profile_id: str,
        *,
        identity_type: str = "profile",
        trigger_reason: str = "manual",
        session_timeout_seconds: int = _SESSION_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        """Build the current unified journey version for a typed identity."""
        # Load cross-rail canonical activity
        activities = await self._activity_repo.list_by_profile(
            tenant_id,
            profile_id,
            identity_type=identity_type,
            limit=_MAX_JOURNEY_STEPS,
        )
        # Load conversions separately for attribution linkage metadata
        conversions = await self._conversion_repo.list_by_profile(
            tenant_id,
            profile_id,
            identity_type=identity_type,
            attribution_eligible_only=False,
            limit=500,
        )

        return await self._build_and_persist(
            tenant_id=tenant_id,
            profile_id=profile_id,
            identity_type=identity_type,
            activities=activities,
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
        if tp.get("profile_id"):
            identity_type, profile_id = "profile", tp["profile_id"]
        elif tp.get("cluster_id"):
            identity_type, profile_id = "cluster", tp["cluster_id"]
        else:
            identity_type, profile_id = "anonymous", tp.get("anonymous_id")
        if not profile_id:
            return []
        version = await self.compile_for_profile(
            tenant_id,
            profile_id,
            identity_type=identity_type,
            trigger_reason="touchpoint_received",
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
        """Rebuild journeys after a consent change or DSR erasure.

        Tombstoned activities are already excluded by ActivityRepository
        (NOT IN 'tombstoned', 'deleted', 'consent_restricted'), so the
        rebuild naturally produces a privacy-correct version.
        """
        version = await self.compile_for_profile(
            tenant_id, profile_id, trigger_reason="consent_change",
        )
        return [version]

    async def rebuild_affected_by_web3_status_change(
        self,
        tenant_id: str,
        tx_hash: str,
        new_status: str,
        *,
        chain_confirmed_at: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Update activity status for a tx_hash and rebuild affected profiles."""
        # Update canonical_activity rows
        affected_activity_ids = await self._activity_repo.update_status_by_tx_hash(
            tenant_id, tx_hash, new_status, chain_confirmed_at=chain_confirmed_at,
        )

        if not affected_activity_ids:
            return []

        # Propagate status to existing journey_steps (no rebuild needed for status-only change)
        for aid in affected_activity_ids:
            await self._step_repo.update_status_by_activity(tenant_id, aid, new_status)

        # If the status change affects finality (reorg/confirmation), trigger a full rebuild
        # to ensure conversion and attribution records are updated correctly
        if new_status in ("reorged", "reverted", "confirmed", "finalized"):
            # Gather affected profiles
            activities = await self._activity_repo.list_by_tx_hash(tenant_id, tx_hash)
            profile_ids = {
                a.get("profile_id") for a in activities if a.get("profile_id")
            }
            results = []
            for pid in profile_ids:
                v = await self.compile_for_profile(
                    tenant_id, pid, trigger_reason=f"web3_status_{new_status}",
                )
                results.append(v)
            return results

        return []

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _build_and_persist(
        self,
        tenant_id: str,
        profile_id: str,
        identity_type: str,
        activities: list[dict[str, Any]],
        conversions: list[dict[str, Any]],
        trigger_reason: str,
        session_timeout_seconds: int,
    ) -> dict[str, Any]:
        if identity_type not in {"profile", "cluster", "anonymous"}:
            raise ValueError(f"unsupported identity_type: {identity_type}")

        # ── 1. Sort deterministically ────────────────────────────────────────
        activities = _sort_deterministically(activities)

        # ── 1b. Collapse passive comm lifecycle noise (ADR-C5) ───────────────
        # queued/processed/deferred/bounced/dropped/suppressed communication
        # activities are state, not journey steps; they stay in facts and
        # Profile360 but never surface as primary journey steps.
        activities, collapsed_lifecycle_count = _partition_comm_lifecycle(activities)

        # Discovery crawlers, link previews, scanners, and any explicitly
        # ineligible source classifications remain in canonical activity for
        # evidence/audit purposes, but do not become eligible journey steps.
        activities, excluded_source_noise_count = _partition_source_noise(activities)

        # ── 2. Derive summary metadata ───────────────────────────────────────
        started_at: Optional[str] = activities[0].get("occurred_at") if activities else None
        ended_at: Optional[str] = activities[-1].get("occurred_at") if activities else None

        converted_at: Optional[str] = None
        if conversions:
            sorted_convs = sorted(conversions, key=lambda c: c.get("occurred_at", ""))
            converted_at = sorted_convs[-1].get("occurred_at")

        session_ids = list({a.get("session_id") for a in activities if a.get("session_id")})
        device_ids = list({a.get("device_id") for a in activities if a.get("device_id")})
        campaign_ids = list({a.get("campaign_id") for a in activities if a.get("campaign_id")})
        wallet_ids = list({a.get("wallet_id") for a in activities if a.get("wallet_id")})
        conv_ids = [str(c["conversion_id"]) for c in conversions if c.get("conversion_id")]
        touchpoint_ids = _touchpoint_ids(activities)

        web3_ids = [str(a.get("activity_id")) for a in activities
                    if a.get("activity_family") == ActivityFamily.web3.value]
        agent_ids = [str(a.get("activity_id")) for a in activities
                     if a.get("activity_family") == ActivityFamily.agent.value]
        x402_ids = [str(a.get("activity_id")) for a in activities
                    if a.get("activity_family") == ActivityFamily.x402.value]

        channel_sequence = _build_channel_sequence(activities)
        journey_state = _derive_journey_state(activities, conversions)

        # ── 3. Confidence scoring ────────────────────────────────────────────
        stored_profile_id = profile_id if identity_type != "cluster" else None
        stored_cluster_id = (
            profile_id
            if identity_type == "cluster"
            else next(
                (
                    item.get("cluster_id")
                    for item in [*activities, *conversions]
                    if item.get("cluster_id")
                ),
                None,
            )
        )
        has_user_id = bool(stored_profile_id) and any(
            a.get("profile_id") for a in activities
        )
        confidence, _ = _scorer.score(
            user_id=stored_profile_id if has_user_id else None,
            wallet=next((a.get("wallet_id") for a in activities if a.get("wallet_id")), None),
            anonymous_id=next((a.get("anonymous_id") for a in activities if a.get("anonymous_id")), None),
            fingerprint=next((a.get("device_id") for a in activities if a.get("device_id")), None),
            campaign={"campaign_id": campaign_ids[0]} if campaign_ids else None,
            timestamp_proximity=len(activities) > 1,
        )

        # ── 4. Load prior version for lineage ───────────────────────────────
        prior_versions = await self._journey_repo.find_current_for_profile(
            tenant_id,
            profile_id,
            identity_type=identity_type,
        )
        prior = prior_versions[0] if prior_versions else None
        journey_id = prior.get("journey_id") if prior else str(uuid4())
        previous_version_id = prior.get("journey_version_id") if prior else None
        new_version_id = str(uuid4())

        # ── 5. Persist journey_version ───────────────────────────────────────
        new_version: dict[str, Any] = {
            "journey_version_id": new_version_id,
            "journey_id": journey_id,
            "tenant_id": tenant_id,
            "profile_id": stored_profile_id,
            "cluster_id": stored_cluster_id,
            "journey_type": identity_type,
            "journey_state": journey_state,
            "started_at": started_at,
            "ended_at": ended_at,
            "converted_at": converted_at,
            "conversion_ids": conv_ids,
            "touchpoint_ids": touchpoint_ids,
            "entry_touchpoint_id": touchpoint_ids[0] if touchpoint_ids else None,
            "exit_touchpoint_id": touchpoint_ids[-1] if touchpoint_ids else None,
            "session_ids": session_ids,
            "device_ids": device_ids,
            "campaign_ids": campaign_ids,
            "channel_sequence": channel_sequence,
            "step_count": len(activities),
            "web3_activity_ids": web3_ids,
            "agent_activity_ids": agent_ids,
            "x402_activity_ids": x402_ids,
            "previous_version_id": previous_version_id,
            "collapsed_lifecycle_count": collapsed_lifecycle_count,
            "excluded_source_noise_count": excluded_source_noise_count,
            "rebuild_reason": trigger_reason,
            "compiler_version": _COMPILER_VERSION,
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "is_current": True,
        }

        # ── 6. Build journey_steps ───────────────────────────────────────────
        steps: list[dict[str, Any]] = []
        if activities:
            transitions = _classify_transitions(activities, session_timeout_seconds)
            steps = _build_steps(
                activities=activities,
                transitions=transitions,
                tenant_id=tenant_id,
                journey_id=journey_id,
                journey_version_id=new_version_id,
                profile_id=stored_profile_id,
            )

        # Version activation and step insertion share one repository
        # transaction so a failed drill-down write cannot publish a hollow
        # current journey version.
        persisted = await self._journey_repo.create_version(
            new_version, steps=steps
        )

        logger.info(
            "Journey compiled v2: tenant=%s profile=%s activities=%d web3=%d agent=%d "
            "x402=%d conversions=%d excluded_source_noise=%d state=%s confidence=%.2f reason=%s",
            tenant_id, profile_id,
            len(activities), len(web3_ids), len(agent_ids), len(x402_ids),
            len(conv_ids), excluded_source_noise_count, journey_state, confidence, trigger_reason,
        )

        return persisted


# ── Helpers ───────────────────────────────────────────────────────────────────

def _partition_comm_lifecycle(
    activities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Split out state-only communication lifecycle activities (ADR-C5).

    Journey roles are derived deterministically from the comms taxonomy so
    no schema change is required on canonical_activity. Non-communication
    activities always pass through.
    """
    try:
        from services.comms.contracts import (
            COMMUNICATION_EVENT_TYPES,
            JourneyRole,
            journey_role_for,
        )
    except Exception:  # pragma: no cover — comms module unavailable
        return activities, 0

    primary: list[dict[str, Any]] = []
    collapsed = 0
    for activity in activities:
        activity_type = activity.get("activity_type", "")
        if activity_type in COMMUNICATION_EVENT_TYPES:
            role = journey_role_for(activity_type)
            if role == JourneyRole.STATE_ONLY:
                collapsed += 1
                continue
        primary.append(activity)
    return primary, collapsed


def _partition_source_noise(
    activities: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep source-classification noise auditable but out of eligible journeys."""
    eligible: list[dict[str, Any]] = []
    excluded = 0
    for activity in activities:
        attribution_eligible = activity.get("attribution_eligible", True)
        is_ineligible = attribution_eligible is False or (
            isinstance(attribution_eligible, str)
            and attribution_eligible.strip().lower() in {"false", "0", "no"}
        )
        if is_ineligible or activity.get("journey_role") == "excluded":
            excluded += 1
            continue
        eligible.append(activity)
    return eligible, excluded


def _touchpoint_ids(activities: list[dict[str, Any]]) -> list[str]:
    """Return ordered, unique Silver touchpoint ids represented in this version."""
    result: list[str] = []
    seen: set[str] = set()
    for activity in activities:
        if activity.get("silver_table") != "silver_campaign_touchpoint_facts":
            continue
        touchpoint_id = activity.get("silver_fact_id")
        if not touchpoint_id:
            continue
        value = str(touchpoint_id)
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _sort_deterministically(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable canonical sort: occurred_at → sequence_key → activity_id."""
    def _key(a: dict[str, Any]) -> tuple:
        ts = a.get("occurred_at") or ""
        if isinstance(ts, datetime):
            ts = ts.isoformat()
        seq = a.get("sequence_key") or ""
        uid = str(a.get("activity_id") or "")
        return (ts, seq, uid)

    return sorted(activities, key=_key)


def _classify_transitions(
    activities: list[dict[str, Any]],
    session_timeout_seconds: int = _SESSION_TIMEOUT_SECONDS,
) -> list[Optional[str]]:
    """Classify the transition type from the previous step for each activity.

    Returns a list of the same length as activities; the first entry is always None.
    """
    if not activities:
        return []

    transitions: list[Optional[str]] = [None]  # first step has no transition

    for i in range(1, len(activities)):
        prev = activities[i - 1]
        curr = activities[i]
        transitions.append(_classify_pair(prev, curr, session_timeout_seconds))

    return transitions


def _classify_pair(
    prev: dict[str, Any],
    curr: dict[str, Any],
    session_timeout_seconds: int,
) -> str:
    """Return the TransitionType string for this consecutive pair."""
    prev_family = prev.get("activity_family", "")
    curr_family = curr.get("activity_family", "")

    # Actor transitions
    prev_actor = prev.get("actor_type", "human")
    curr_actor = curr.get("actor_type", "human")
    if prev_actor == "human" and curr_actor == "agent":
        return TransitionType.human_to_agent.value
    if prev_actor == "agent" and curr_actor == "human":
        return TransitionType.agent_to_human.value
    if prev_actor == "agent" and curr_actor == "agent":
        if prev.get("agent_id") != curr.get("agent_id"):
            return TransitionType.agent_to_agent.value

    # Cross-rail transitions
    if prev_family in (ActivityFamily.web2.value, ActivityFamily.campaign.value) and curr_family == ActivityFamily.web3.value:
        return TransitionType.web2_to_web3.value
    if prev_family == ActivityFamily.web3.value and curr_family in (ActivityFamily.web2.value, ActivityFamily.commerce.value):
        return TransitionType.web3_to_web2.value

    # Wallet events
    if curr.get("activity_type") == "wallet_connection":
        return TransitionType.wallet_connected.value
    if curr.get("activity_type") == "wallet_disconnection":
        return TransitionType.wallet_disconnected.value
    if curr_family == ActivityFamily.web3.value and curr.get("wallet_id") != prev.get("wallet_id"):
        if prev.get("wallet_id") and curr.get("wallet_id"):
            return TransitionType.cross_wallet.value

    # Campaign to owned surface
    if prev_family == ActivityFamily.campaign.value and curr_family == ActivityFamily.web2.value:
        return TransitionType.campaign_to_owned_surface.value

    # Conversion
    if curr_family in (ActivityFamily.commerce.value, ActivityFamily.outcome.value):
        return TransitionType.owned_surface_to_conversion.value

    # Chain transition
    if curr_family == ActivityFamily.web3.value and prev_family == ActivityFamily.web3.value:
        if curr.get("chain_id") and prev.get("chain_id") and curr["chain_id"] != prev["chain_id"]:
            return TransitionType.cross_chain.value

    # Platform / surface transitions
    prev_domain = prev.get("domain") or ""
    curr_domain = curr.get("domain") or ""
    prev_platform = prev.get("platform") or ""
    curr_platform = curr.get("platform") or ""
    prev_app = prev.get("app_id") or ""
    curr_app = curr.get("app_id") or ""

    if prev_domain and curr_domain and prev_domain != curr_domain:
        return TransitionType.cross_domain.value

    if "mobile" in curr_platform and "web" in prev_platform:
        return TransitionType.web_to_mobile.value
    if "web" in curr_platform and "mobile" in prev_platform:
        return TransitionType.mobile_to_web.value

    # Session boundary (only for non-Web3/x402 families)
    if curr_family not in _NON_SESSION_BREAKING_FAMILIES:
        prev_session = prev.get("session_id")
        curr_session = curr.get("session_id")
        if prev_session and curr_session and prev_session != curr_session:
            return TransitionType.cross_device.value if (
                prev.get("device_id") != curr.get("device_id")
            ) else TransitionType.new_session.value

        # Inactivity gap check
        gap = _time_gap_seconds(prev.get("occurred_at"), curr.get("occurred_at"))
        if gap is not None and gap > session_timeout_seconds:
            return TransitionType.new_session.value

    return TransitionType.same_session.value


def _build_steps(
    activities: list[dict[str, Any]],
    transitions: list[Optional[str]],
    tenant_id: str,
    journey_id: str,
    journey_version_id: str,
    profile_id: Optional[str],
) -> list[dict[str, Any]]:
    steps = []
    for i, activity in enumerate(activities):
        steps.append({
            "step_id": str(uuid4()),
            "tenant_id": tenant_id,
            "journey_id": journey_id,
            "journey_version_id": journey_version_id,
            "profile_id": profile_id or activity.get("profile_id"),
            "cluster_id": activity.get("cluster_id"),
            "step_position": i,
            "occurred_at": activity.get("occurred_at"),
            "activity_id": str(activity.get("activity_id")),
            "activity_family": activity.get("activity_family"),
            "activity_type": activity.get("activity_type"),
            "transition_type": transitions[i],
            "transition_evidence": {},
            "actor_type": activity.get("actor_type"),
            "channel": activity.get("channel"),
            "source": activity.get("source"),
            "source_class": activity.get("source_class"),
            "referral_mediation_type": activity.get("referral_mediation_type"),
            "ai_provider": activity.get("ai_provider"),
            "ai_product": activity.get("ai_product"),
            "journey_role": activity.get("journey_role"),
            "evidence_confidence": activity.get("evidence_confidence"),
            "verification_level": activity.get("verification_level"),
            "source_classifier_version": activity.get("source_classifier_version"),
            "normalized_referrer_domain": activity.get("normalized_referrer_domain"),
            "source_classification_id": activity.get("source_classification_id"),
            "attribution_eligible": activity.get("attribution_eligible", True),
            "verified_referral_link_id": activity.get("verified_referral_link_id"),
            "domain": activity.get("domain"),
            "app_id": activity.get("app_id"),
            "dapp_id": activity.get("dapp_id"),
            "chain_id": activity.get("chain_id"),
            "campaign_id": activity.get("campaign_id"),
            "conversion_id": activity.get("conversion_id"),
            "wallet_id": activity.get("wallet_id"),
            "agent_id": activity.get("agent_id"),
            "session_id": activity.get("session_id"),
            "device_id": activity.get("device_id"),
            "activity_status": activity.get("activity_status", "observed"),
            "identity_confidence": activity.get("identity_confidence"),
            "identity_method": activity.get("identity_method"),
            "identity_version": activity.get("identity_version"),
            "evidence_summary": {
                "source_event_id": activity.get("source_event_id"),
                "silver_table": activity.get("silver_table"),
                "touchpoint_id": (
                    str(activity.get("silver_fact_id"))
                    if activity.get("silver_table")
                    == "silver_campaign_touchpoint_facts"
                    and activity.get("silver_fact_id")
                    else None
                ),
                "privacy_class": activity.get("privacy_class"),
                "source_classification_id": activity.get("source_classification_id"),
                "verified_referral_link_id": activity.get("verified_referral_link_id"),
            },
            "schema_version": 2,
        })
    return steps


def _group_into_sessions(
    activities: list[dict[str, Any]],
    timeout_seconds: int = _SESSION_TIMEOUT_SECONDS,
) -> list[list[dict[str, Any]]]:
    """Group activities into sessions by inactivity gap (non-Web3 families only)."""
    if not activities:
        return []

    sessions: list[list[dict[str, Any]]] = []
    current_session: list[dict[str, Any]] = [activities[0]]
    prev_ts = _parse_ts(activities[0].get("occurred_at"))

    for act in activities[1:]:
        family = act.get("activity_family", "")
        ts = _parse_ts(act.get("occurred_at")) or prev_ts

        # Web3/x402 events don't break sessions
        if family not in _NON_SESSION_BREAKING_FAMILIES:
            gap = (ts - prev_ts).total_seconds() if prev_ts else 0
            if gap > timeout_seconds:
                sessions.append(current_session)
                current_session = [act]
                prev_ts = ts
                continue

        current_session.append(act)
        if family not in _NON_SESSION_BREAKING_FAMILIES:
            prev_ts = ts

    sessions.append(current_session)
    return sessions


def _build_channel_sequence(activities: list[dict[str, Any]]) -> list[str]:
    """Build a deduplicated ordered list of channel:source transitions."""
    sequence: list[str] = []
    prev = None
    for act in activities:
        channel = act.get("channel") or act.get("activity_family") or "unknown"
        source = act.get("source") or ""
        label = f"{channel}:{source}" if source else channel
        if label != prev:
            sequence.append(label)
            prev = label
    return sequence


def _derive_journey_state(
    activities: list[dict[str, Any]],
    conversions: list[dict[str, Any]],
) -> str:
    if not activities:
        return "empty"
    if conversions:
        return "converted"
    return "open"


def _time_gap_seconds(
    prev_ts: Any,
    curr_ts: Any,
) -> Optional[float]:
    p = _parse_ts(prev_ts)
    c = _parse_ts(curr_ts)
    if p is None or c is None:
        return None
    return (c - p).total_seconds()


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None
