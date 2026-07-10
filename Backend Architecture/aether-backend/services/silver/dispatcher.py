"""Silver dispatcher — fans one Bronze event out to an ordered list of projectors.

One event may need several analytical projections (ADR-C3): a communication
lifecycle fact, a campaign touchpoint, identity evidence, a data-quality fact,
one canonical activity, and a queued graph mutation. The dispatcher guarantees:

- deterministic projector order (semantic: comms lifecycle → identity
  evidence → campaign touchpoint → other facts → graph emission),
- per-projector failure isolation — one projector failing never erases
  another's successful projection,
- exactly one canonical activity per real-world event (ADR-C4): for
  communication events the CommsProjector owns activity emission and all
  other projectors are suppressed,
- replay safety (idempotency enforced at the repository layer),
- per-projector latency and failure metrics.

Usage::

    from services.silver.dispatcher import SilverDispatcher
    dispatcher = SilverDispatcher()
    results = await dispatcher.project(event_dict)
    # results: list[ProjectionResult], each with .table and .rows
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from shared.logger.logger import get_logger, metrics
from .projectors.base import BaseProjector, ProjectionResult
from .projectors import (
    ExposureProjector,
    OutcomeProjector,
    RevenueProjector,
    FrictionProjector,
    AccountActivityProjector,
    ServerOperationProjector,
    IdentityEvidenceProjector,
    AgentExecutionProjector,
    AIInvocationProjector,
    Web3TransactionProjector,
    X402FlowProjector,
    TouchpointProjector,
    ConversionProjector,
    StablecoinProjector,
    DerivativesProjector,
    InteropProjector,
)
from .projectors.silver_graph_projector import SilverGraphProjector
from services.comms.projector import CommsProjector, COMMS_TABLE
from services.comms.contracts import COMMUNICATION_EVENT_TYPES

logger = get_logger("silver.dispatcher")

# Deterministic semantic order (ADR-C3). Projectors earlier in this list run
# first for any event type they share with a later projector.
_ALL_PROJECTORS: list[BaseProjector] = [
    CommsProjector(),            # 1. communications lifecycle (authoritative)
    IdentityEvidenceProjector(), # 2. identity evidence
    TouchpointProjector(),       # 3. campaign touchpoint
    ExposureProjector(),
    OutcomeProjector(),
    RevenueProjector(),
    FrictionProjector(),
    AccountActivityProjector(),
    ServerOperationProjector(),
    AgentExecutionProjector(),
    AIInvocationProjector(),
    Web3TransactionProjector(),
    X402FlowProjector(),
    StablecoinProjector(),      # stablecoin economic observation facts
    DerivativesProjector(),     # derivatives observation facts
    InteropProjector(),         # cross-network message facts
    ConversionProjector(),
]

# event_type → ordered list of projectors (order == _ALL_PROJECTORS order)
_TYPE_MAP: dict[str, list[BaseProjector]] = {}
for _p in _ALL_PROJECTORS:
    for _t in _p.handles:
        _TYPE_MAP.setdefault(_t, []).append(_p)

_graph_projector = SilverGraphProjector()

_TOUCHPOINT_TABLE = "silver_campaign_touchpoint_facts"

# Private hint keys injected by projectors for resolver pass-through;
# these are stripped before rows reach the database writer.
_RESOLVER_HINT_KEYS = {"_canonical_campaign_id_hint", "_utm_id"}


@dataclass
class ProjectionOutcome:
    """Structured per-event dispatch report (one entry per projector run)."""
    event_type: str
    results: list[ProjectionResult] = field(default_factory=list)
    projector_status: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed_projectors(self) -> list[str]:
        return [s["projector"] for s in self.projector_status if s["status"] == "error"]


async def _resolve_campaign_rows(rows: list[dict[str, Any]], *, table: str) -> None:
    """Resolve campaign evidence for touchpoint/comms rows in-place.

    Calls CampaignResolver per row, updates campaign_id and resolution fields.
    Never raises — resolution failure writes 'unresolved' status but does not
    drop the event.
    """
    try:
        from services.campaign.resolver import CampaignResolver
        resolver = CampaignResolver()
    except Exception as exc:
        logger.warning("campaign_resolver_unavailable: %s — skipping resolution", exc)
        for row in rows:
            for k in _RESOLVER_HINT_KEYS:
                row.pop(k, None)
        return

    for row in rows:
        canonical_hint = row.pop("_canonical_campaign_id_hint", None)
        utm_id = row.pop("_utm_id", None)
        tenant_id = row.get("tenant_id", "")
        # Comms rows carry provider evidence; touchpoint rows carry UTM evidence.
        platform = row.get("platform") or row.get("provider")
        external_account_id = row.get("external_account_id") or row.get("provider_account_id")

        has_evidence = bool(
            canonical_hint or utm_id or row.get("external_campaign_id")
            or row.get("utm_campaign") or row.get("external_flow_id")
        )
        if not has_evidence:
            continue

        try:
            result = await resolver.resolve_one(
                tenant_id,
                canonical_campaign_id=canonical_hint,
                platform=platform,
                external_account_id=external_account_id,
                external_campaign_id=row.get("external_campaign_id") or row.get("external_flow_id"),
                utm_id=utm_id,
                utm_source=row.get("utm_source"),
                utm_medium=row.get("utm_medium"),
                utm_campaign=row.get("utm_campaign"),
                utm_content=row.get("utm_content"),
                utm_term=row.get("utm_term"),
                landing_url=row.get("landing_url"),
                create_review_on_failure=True,
            )
            row["campaign_id"] = str(result.campaign_id) if result.campaign_id else None
            row["campaign_resolution_status"] = result.status
            row["campaign_resolution_method"] = result.method
            row["campaign_resolution_confidence"] = (
                float(result.confidence) if result.confidence is not None else None
            )
            row["campaign_resolution_version"] = result.resolution_version
        except Exception as exc:
            logger.warning(
                "campaign_resolution_error table=%s row=%s: %s",
                table, row.get("source_event_id"), exc,
            )
            row["campaign_resolution_status"] = "unresolved"
            row["campaign_resolution_version"] = "1.0"


def _strip_hints(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        for k in _RESOLVER_HINT_KEYS:
            row.pop(k, None)


def _propagate_comms_context(event: dict[str, Any], result: ProjectionResult) -> None:
    """Share the comms classification with downstream projectors for this event.

    The touchpoint projector uses it to gate engagement touchpoints on
    machine-activity classification without re-deriving it.
    """
    if result.table == COMMS_TABLE and result.rows:
        row = result.rows[0]
        event["_comms_fact"] = {
            "suspected_machine_activity": row.get("suspected_machine_activity", False),
            "machine_activity_probability": row.get("machine_activity_probability"),
            "engagement_confidence": row.get("engagement_confidence"),
            "engagement_strength": row.get("engagement_strength"),
            "journey_role": row.get("journey_role"),
            "idempotency_key": row.get("idempotency_key"),
            "external_message_id": row.get("external_message_id"),
            "sequence_step": row.get("sequence_step"),
            "variant_id": row.get("variant_id"),
            "link_id": row.get("link_id"),
            "automated_response_kind": row.get("automated_response_kind"),
        }


class SilverDispatcher:
    """Projects a single Bronze event into Silver fact rows, then emits graph mutations."""

    async def project(self, event: dict[str, Any]) -> list[ProjectionResult]:
        outcome = await self.project_with_outcome(event)
        return outcome.results

    async def project_with_outcome(self, event: dict[str, Any]) -> ProjectionOutcome:
        event_type = event.get("type", "")
        outcome = ProjectionOutcome(event_type=event_type)
        projectors = _TYPE_MAP.get(event_type)
        if not projectors:
            return outcome

        is_comm_event = event_type in COMMUNICATION_EVENT_TYPES

        for projector in projectors:
            name = type(projector).__name__
            # ADR-C4: for comm events the CommsProjector owns canonical
            # activity; it is emitted explicitly below AFTER campaign
            # resolution so the activity carries the resolved campaign_id.
            emit_activity = not is_comm_event
            started = time.monotonic()
            try:
                result = projector.project_and_emit(event, emit_activity=emit_activity)
                elapsed_ms = (time.monotonic() - started) * 1000
                metrics.timing(
                    "silver_projector_latency_ms", elapsed_ms,
                    labels={"projector": name, "event_type": event_type},
                )
                if result and not result.skipped:
                    if result.rows and result.table in (_TOUCHPOINT_TABLE, COMMS_TABLE):
                        await _resolve_campaign_rows(result.rows, table=result.table)
                    _strip_hints(result.rows or [])
                    _propagate_comms_context(event, result)
                    if is_comm_event and isinstance(projector, CommsProjector) and result.rows:
                        # Canonical activity for comm events — exactly once,
                        # post-resolution (ADR-C4).
                        await projector._emit_to_canonical_activity(result.table, result.rows)
                    outcome.results.append(result)
                    # Fire-and-forget graph mutations; never block or fail Silver writes
                    asyncio.create_task(_graph_projector.maybe_emit(result, event))
                    outcome.projector_status.append(
                        {"projector": name, "status": "ok",
                         "rows": len(result.rows or []), "latency_ms": round(elapsed_ms, 2)}
                    )
                else:
                    outcome.projector_status.append(
                        {"projector": name, "status": "skipped",
                         "reason": result.skip_reason if result else "no_result",
                         "latency_ms": round(elapsed_ms, 2)}
                    )
            except Exception as exc:
                elapsed_ms = (time.monotonic() - started) * 1000
                metrics.increment(
                    "silver_projector_failures_total",
                    labels={"projector": name, "event_type": event_type},
                )
                logger.error(
                    "silver_projection_error event_type=%s projector=%s error=%s",
                    event_type, name, exc,
                )
                outcome.projector_status.append(
                    {"projector": name, "status": "error", "error": str(exc),
                     "latency_ms": round(elapsed_ms, 2)}
                )
                # Isolation: continue with remaining projectors.
        return outcome

    def project_sync(self, event: dict[str, Any]) -> list[ProjectionResult]:
        """Synchronous fallback for non-async callers (skips graph emission and resolution)."""
        event_type = event.get("type", "")
        projectors = _TYPE_MAP.get(event_type)
        if not projectors:
            return []
        is_comm_event = event_type in COMMUNICATION_EVENT_TYPES
        results: list[ProjectionResult] = []
        for projector in projectors:
            # Sync path has no resolution step, so the activity owner emits inline.
            emit_activity = not is_comm_event or isinstance(projector, CommsProjector)
            try:
                result = projector.project_and_emit(event, emit_activity=emit_activity)
                if result and not result.skipped:
                    _strip_hints(result.rows or [])
                    _propagate_comms_context(event, result)
                    results.append(result)
            except Exception as exc:
                logger.error(
                    "silver_projection_error event_type=%s projector=%s error=%s",
                    event_type, type(projector).__name__, exc,
                )
        return results

    def handles(self, event_type: str) -> bool:
        return event_type in _TYPE_MAP

    def projectors_for(self, event_type: str) -> list[str]:
        """Deterministic, ordered projector names for an event type."""
        return [type(p).__name__ for p in _TYPE_MAP.get(event_type, [])]
