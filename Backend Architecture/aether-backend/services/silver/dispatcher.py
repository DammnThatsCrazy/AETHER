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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    CardLinkedProjector,
    ConversionProjector,
    StablecoinProjector,
    DerivativesProjector,
    InteropProjector,
)
from .projectors.silver_graph_projector import SilverGraphProjector
from services.comms.projector import CommsProjector, COMMS_TABLE
from services.comms.contracts import COMMUNICATION_EVENT_TYPES
from services.traffic.referral_links import VerifiedReferralLinkRepository
from services.traffic import metrics as traffic_metrics
from services.traffic.shadow import shadow_compare_rows, is_shadow_enabled_for
from services.agent_access_intelligence.catalog_service import (
    capability_catalog_service as _capability_catalog,
)

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
    CardLinkedProjector(),    # card-linked context on payment/commerce events (never activity owner)
]

# event_type → ordered list of projectors (order == _ALL_PROJECTORS order)
_TYPE_MAP: dict[str, list[BaseProjector]] = {}
for _p in _ALL_PROJECTORS:
    for _t in _p.handles:
        _TYPE_MAP.setdefault(_t, []).append(_p)

_graph_projector = SilverGraphProjector()
_verified_referral_links = VerifiedReferralLinkRepository()

_TOUCHPOINT_TABLE = "silver_campaign_touchpoint_facts"

# Private hint keys injected by projectors for resolver pass-through;
# these are stripped before rows reach the database writer.
_RESOLVER_HINT_KEYS = {"_canonical_campaign_id_hint", "_utm_id"}

_REFERRAL_TOKEN_FIELD_KEYS = frozenset(
    {"aether_ref", "aetherref", "referral_token", "referraltoken"}
)
_REFERRAL_TOKEN_HASH_FIELD_KEYS = frozenset(
    {"aether_ref_hash", "aetherrefhash", "referral_token_hash", "referraltokenhash"}
)
_UNTRUSTED_VERIFIED_CLAIM_KEYS = frozenset(
    {"verified_referral", "verifiedreferral"}
)


def _normalized_field_key(value: Any) -> str:
    return str(value).strip().replace("-", "_").lower()


def _token_from_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        query = value[1:] if value.startswith("?") else urlsplit(value).query
        for key, token in parse_qsl(query, keep_blank_values=True):
            if _normalized_field_key(key) in {"aether_ref", "aetherref"} and token:
                return token
    except (TypeError, ValueError):
        return None
    return None


def _strip_referral_token_from_url(value: Any) -> Any:
    """Remove plaintext ``aether_ref`` while preserving all other evidence."""

    if not isinstance(value, str) or not value:
        return value
    try:
        if value.startswith("?"):
            filtered = [
                (key, item)
                for key, item in parse_qsl(value[1:], keep_blank_values=True)
                if _normalized_field_key(key) not in {"aether_ref", "aetherref"}
            ]
            encoded = urlencode(filtered, doseq=True)
            return f"?{encoded}" if encoded else ""
        parsed = urlsplit(value)
        filtered = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if _normalized_field_key(key) not in {"aether_ref", "aetherref"}
        ]
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered, doseq=True), parsed.fragment)
        )
    except (TypeError, ValueError):
        # An unparsable value cannot safely be retained if it visibly carries
        # the secret parameter.
        return "" if "aether_ref" in value.lower() else value


def _extract_and_sanitize_referral_token(
    event: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Extract the opaque token and remove all client-asserted verified claims.

    Only a successful repository lookup may later populate
    ``event['_verified_referral']``.  This prevents an SDK payload from
    self-asserting provider, campaign, agent, or verification metadata.
    """

    event.pop("_verified_referral", None)
    ctx = event.get("context") if isinstance(event.get("context"), dict) else {}
    props = event.get("properties") if isinstance(event.get("properties"), dict) else {}
    acquisition = (
        ctx.get("acquisitionEvidence")
        if isinstance(ctx.get("acquisitionEvidence"), dict)
        else {}
    )
    traffic_source = (
        ctx.get("trafficSource") if isinstance(ctx.get("trafficSource"), dict) else {}
    )
    page = ctx.get("page") if isinstance(ctx.get("page"), dict) else {}

    token: str | None = None
    token_hash: str | None = None
    for mapping in (acquisition, traffic_source, ctx, props, event):
        for key in list(mapping):
            normalized = _normalized_field_key(key)
            if normalized in _REFERRAL_TOKEN_FIELD_KEYS:
                candidate = mapping.pop(key, None)
                if token is None and candidate:
                    token = str(candidate)
            elif normalized in _REFERRAL_TOKEN_HASH_FIELD_KEYS:
                candidate = mapping.pop(key, None)
                if token_hash is None and candidate:
                    token_hash = str(candidate)
            elif normalized in _UNTRUSTED_VERIFIED_CLAIM_KEYS:
                mapping.pop(key, None)

    url_fields = (
        (page, "url"),
        (page, "search"),
        (acquisition, "landingPage"),
        (acquisition, "landing_page"),
        (traffic_source, "landingPage"),
        (traffic_source, "landing_page"),
        (props, "landing_url"),
        (props, "landingUrl"),
    )
    for mapping, field_name in url_fields:
        if field_name not in mapping:
            continue
        raw_value = mapping.get(field_name)
        token = token or _token_from_url(raw_value)
        mapping[field_name] = _strip_referral_token_from_url(raw_value)

    return token, token_hash


async def _record_handoff_replay_audit(tenant_id: str, source_event_id: Any) -> None:
    """Best-effort audit record for a rejected handoff replay (attack signal)."""

    try:
        from services.security.audit_ledger import AuditLedger

        await AuditLedger().record(
            actor_id="silver_dispatcher",
            actor_type="system",
            event_type="verified_source_link",
            resource_type="source_link_handoff",
            action="replay_reject",
            outcome="denied",  # type: ignore[arg-type]
            tenant_id=str(tenant_id),
            resource_id=str(source_event_id) if source_event_id else None,
            metadata={"reason": "handoff_token_already_consumed"},
        )
    except Exception as exc:  # pragma: no cover — audit must not block Silver
        logger.warning("handoff_replay_audit_failed tenant=%s: %s", tenant_id, exc)


async def _resolve_verified_referral(event: dict[str, Any]) -> None:
    """Attach only tenant-verified referral metadata to an event in-place.

    ``aether_ref`` carries EITHER a direct verified-link token (existing path)
    OR a one-time redirect handoff token minted by GET /v1/r/{token}.  The
    direct path is tried first (no side effects on miss); the handoff path is
    one-time-consumable, replay-rejected, and marks the redirect link-use as
    correlated.
    """

    token, token_hash = _extract_and_sanitize_referral_token(event)
    if not token and not token_hash:
        return
    ctx = event.get("context") if isinstance(event.get("context"), dict) else {}
    tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
    source_event_id = event.get("messageId") or event.get("id")
    handoff_status: str | None = None
    try:
        if token:
            claim = await _verified_referral_links.resolve_token(
                str(tenant_id), token, source_event_id=source_event_id
            )
            if claim is None:
                claim, handoff_status = await _verified_referral_links.consume_handoff(
                    str(tenant_id), token, source_event_id=source_event_id
                )
        else:
            claim = await _verified_referral_links.resolve_token_hash(
                str(tenant_id),
                str(token_hash),
                source_event_id=source_event_id,
            )
            if claim is None:
                claim, handoff_status = (
                    await _verified_referral_links.consume_handoff_hash(
                        str(tenant_id),
                        str(token_hash),
                        source_event_id=source_event_id,
                    )
                )
    except Exception as exc:
        logger.warning("verified_referral_resolution_error tenant=%s: %s", tenant_id, exc)
        metrics.increment(
            "verified_referral_resolution_total", labels={"status": "error"}
        )
        return
    if claim is None:
        if handoff_status == "replayed":
            metrics.increment(
                "verified_referral_resolution_total",
                labels={"status": "replay_rejected"},
            )
            # Spec §16: a consumed handoff replay is both a source-link replay
            # signal and a failed handoff correlation.
            traffic_metrics.record_source_link_replay()
            traffic_metrics.record_handoff_correlation("failed")
            await _record_handoff_replay_audit(str(tenant_id), source_event_id)
        elif handoff_status == "expired":
            traffic_metrics.record_handoff_correlation("expired")
            metrics.increment(
                "verified_referral_resolution_total", labels={"status": "rejected"}
            )
        else:
            metrics.increment(
                "verified_referral_resolution_total", labels={"status": "rejected"}
            )
        return
    event["_verified_referral"] = claim
    if handoff_status is not None:
        # Claim resolved via the one-time redirect handoff — successful correlation.
        traffic_metrics.record_handoff_correlation("success")
    metrics.increment(
        "verified_referral_resolution_total", labels={"status": "verified"}
    )


def _apply_verified_referral_to_rows(
    rows: list[dict[str, Any]], event: dict[str, Any]
) -> None:
    """Apply trusted placement/agent/campaign metadata before campaign resolution."""

    claim = event.get("_verified_referral")
    if not isinstance(claim, dict):
        return
    for row in rows:
        if claim.get("verified_referral_link_id"):
            # Preserve the verified-link lineage even when a stronger machine
            # user-agent rule controls actor/source classification.
            row["verified_referral_link_id"] = claim["verified_referral_link_id"]
        if claim.get("placement_id"):
            row["placement_id"] = claim["placement_id"]
        if claim.get("agent_id"):
            row["agent_id"] = claim["agent_id"]
        if claim.get("campaign_id"):
            # CampaignResolver remains authoritative and validates tenant
            # ownership of the UUID; the link does not bypass it.
            row["_canonical_campaign_id_hint"] = claim["campaign_id"]


@dataclass
class ProjectionOutcome:
    """Structured per-event dispatch report (one entry per projector run)."""
    event_type: str
    results: list[ProjectionResult] = field(default_factory=list)
    projector_status: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed_projectors(self) -> list[str]:
        return [s["projector"] for s in self.projector_status if s["status"] == "error"]


def _row_campaign_evidence(row: dict[str, Any]) -> bool:
    """True only when the row carries real campaign-identity evidence.

    Campaign identity is a separate dimension from source classification:
    utm_source/utm_medium alone are NOT campaign evidence. Evidence is a
    canonical campaign hint (including a verified-link campaign hint, which
    arrives as ``_canonical_campaign_id_hint``), utm_campaign, utm_id,
    external_campaign_id, or a connector flow id.
    """
    return bool(
        row.get("_canonical_campaign_id_hint")
        or row.get("_utm_id")
        or row.get("external_campaign_id")
        or row.get("utm_campaign")
        or row.get("external_flow_id")
    )


async def _resolve_campaign_rows(rows: list[dict[str, Any]], *, table: str) -> None:
    """Resolve campaign evidence for touchpoint/comms rows in-place.

    Calls CampaignResolver per row, updates campaign_id and resolution fields.
    The resolver is only invoked for rows with campaign evidence — evidence-free
    rows are terminal ``not_applicable`` and never create Mapping Review rows.
    Never raises — resolution failure writes 'unresolved' status but does not
    drop the event (the row keeps its full source classification).
    """
    evidence_rows = [row for row in rows if _row_campaign_evidence(row)]
    evidence_row_ids = {id(row) for row in evidence_rows}
    for row in rows:
        if id(row) not in evidence_row_ids:
            row.pop("_canonical_campaign_id_hint", None)
            row.pop("_utm_id", None)
            row["campaign_resolution_status"] = "not_applicable"
    if not evidence_rows:
        return

    try:
        from services.campaign.resolver import CampaignResolver
        resolver = CampaignResolver()
    except Exception as exc:
        logger.warning("campaign_resolver_unavailable: %s — skipping resolution", exc)
        for row in rows:
            for k in _RESOLVER_HINT_KEYS:
                row.pop(k, None)
        return

    for row in evidence_rows:
        canonical_hint = row.pop("_canonical_campaign_id_hint", None)
        utm_id = row.pop("_utm_id", None)
        tenant_id = row.get("tenant_id", "")
        # Comms rows carry provider evidence; touchpoint rows carry UTM evidence.
        platform = row.get("platform") or row.get("provider")
        external_account_id = row.get("external_account_id") or row.get("provider_account_id")

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


def _emit_classification_metrics(rows: list[dict[str, Any]]) -> None:
    """Emit spec §16 classification counters from resolved touchpoint rows.

    Purely observational — reads the source_class/proof_level/conflict fields the
    classifier already assigned; never mutates the rows.
    """
    for row in rows:
        source_class = row.get("source_class")
        if not source_class:
            continue
        traffic_metrics.record_classification(
            str(source_class), str(row.get("proof_level") or "none")
        )
        if source_class == "direct_unknown":
            traffic_metrics.record_direct_unknown()
        conflicts = row.get("evidence_conflicts") or ()
        try:
            conflict_count = len(conflicts)
        except TypeError:
            conflict_count = 0
        if conflict_count:
            traffic_metrics.record_evidence_conflict(conflict_count)
        if row.get("attribution_eligible") is False and row.get("actor_type") == "machine":
            traffic_metrics.record_machine_excluded()


async def _shadow_compare_touchpoints(
    tenant_id: str, rows: list[dict[str, Any]]
) -> None:
    """When shadow mode is on for the tenant, record legacy-vs-canonical drift.

    Shadow-mode is observational: it copies the rows before comparison so the
    customer-visible touchpoint rows and their attribution are never touched.
    """
    if not rows or not is_shadow_enabled_for(tenant_id):
        return
    snapshot = [dict(row) for row in rows]
    await shadow_compare_rows(tenant_id, snapshot)


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

        # Resolve the opaque link before any touchpoint classifier runs.  This
        # step also strips plaintext tokens and untrusted verified claims from
        # the event even when lookup fails.
        await _resolve_verified_referral(event)

        is_comm_event = event_type in COMMUNICATION_EVENT_TYPES
        has_touchpoint_projector = any(
            isinstance(candidate, TouchpointProjector) for candidate in projectors
        )

        for projector in projectors:
            name = type(projector).__name__
            # ADR-C4: for comm events the CommsProjector owns canonical
            # activity; it is emitted explicitly below AFTER campaign
            # resolution so the activity carries the resolved campaign_id.
            # Non-comms touchpoints are likewise delayed until verified-link
            # and campaign resolution have both completed.  When a touchpoint
            # projection exists it is the sole non-comms activity owner, so
            # overlapping fact projectors cannot race it with stale evidence.
            is_touchpoint_projector = isinstance(projector, TouchpointProjector)
            emit_activity = not is_comm_event and not has_touchpoint_projector
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
                        if result.table == _TOUCHPOINT_TABLE:
                            _apply_verified_referral_to_rows(result.rows, event)
                        await _resolve_campaign_rows(result.rows, table=result.table)
                    if result.rows and result.table == _TOUCHPOINT_TABLE:
                        _emit_classification_metrics(result.rows)
                        tenant_id = str(
                            (event.get("context") or {}).get("tenantId")
                            or event.get("tenantId")
                            or "default"
                        )
                        await _shadow_compare_touchpoints(tenant_id, result.rows)
                    _strip_hints(result.rows or [])
                    _propagate_comms_context(event, result)
                    if is_comm_event and isinstance(projector, CommsProjector) and result.rows:
                        # Canonical activity for comm events — exactly once,
                        # post-resolution (ADR-C4).
                        await projector._emit_to_canonical_activity(result.table, result.rows)
                    elif not is_comm_event and is_touchpoint_projector and result.rows:
                        # Canonical touchpoint activity — exactly once and only
                        # after verified referral + campaign resolution.
                        await projector._emit_to_canonical_activity(result.table, result.rows)
                    outcome.results.append(result)
                    # Fire-and-forget graph mutations; never block or fail Silver writes
                    asyncio.create_task(_graph_projector.maybe_emit(result, event))
                    # Fire-and-forget capability-catalog maintenance; mirrors the graph
                    # projector hook — out-of-band, never blocks or fails Silver writes.
                    asyncio.create_task(_capability_catalog.maybe_record(result, event))
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
        # The sync compatibility path cannot perform a durable lookup, but it
        # must still prevent plaintext tokens or client-asserted verification
        # metadata from reaching Silver.
        _extract_and_sanitize_referral_token(event)
        is_comm_event = event_type in COMMUNICATION_EVENT_TYPES
        has_touchpoint_projector = any(
            isinstance(candidate, TouchpointProjector) for candidate in projectors
        )
        results: list[ProjectionResult] = []
        for projector in projectors:
            # Sync path has no resolution step, so the activity owner emits inline.
            if is_comm_event:
                emit_activity = isinstance(projector, CommsProjector)
            elif has_touchpoint_projector:
                emit_activity = isinstance(projector, TouchpointProjector)
            else:
                emit_activity = True
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
