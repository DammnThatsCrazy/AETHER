"""Comms API routes.

Tenant surface:
    POST /v1/comms/webhook              Generic signed communication webhook
    POST /v1/comms/replies              Inbound reply ingestion
    POST /v1/comms/click-tokens         Issue signed post-click tokens
    POST /v1/comms/click-tokens/verify  Verify token → correlation evidence
    GET  /v1/comms/health               Tenant comms pipeline health

Operator surface (Kyber):
    GET  /v1/comms/admin/health         Fleet projection/resolution health

The webhook is the fastest provider-neutral integration path: any system
that can POST JSON with an HMAC signature can feed communications into
Aether without a dedicated connector (docs/comms/COMMS_GENERIC_WEBHOOK.md).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.auth.auth import Permissions
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics
from services.comms.contracts import COMMUNICATION_EVENT_TYPES
from services.comms.click_token import (
    correlation_evidence_from_token,
    issue_click_token,
    verify_click_token,
)

logger = get_logger("aether.comms.routes")

router = APIRouter(prefix="/v1/comms", tags=["Communications"])

_MAX_EVENTS_PER_REQUEST = 500


class CommsWebhookEvent(BaseModel):
    event_type: str
    occurred_at: Optional[str] = None
    external_id: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class CommsWebhookBody(BaseModel):
    events: list[CommsWebhookEvent] = Field(..., min_length=1, max_length=_MAX_EVENTS_PER_REQUEST)
    provider: str = "webhook"


@router.post("/webhook")
async def generic_comms_webhook(request: Request, body: CommsWebhookBody) -> dict:
    """Generic signed communication webhook (Phase 12).

    Auth: tenant API key with write permission (standard middleware). When
    the tenant has a webhook signing secret configured, the
    X-Aether-Signature / X-Aether-Timestamp headers are additionally
    verified against the raw request body — invalid signatures are rejected.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    signature = request.headers.get("X-Aether-Signature")
    timestamp = request.headers.get("X-Aether-Timestamp")
    secret = getattr(tenant, "webhook_secret", None)
    if secret:
        from services.security.integration_security import verify_signature
        raw = await request.body()
        if not (signature and timestamp and verify_signature(secret, raw, timestamp, signature)):
            metrics.increment(
                "comms_webhook_signature_failures_total",
                labels={"tenant_id": tenant.tenant_id},
            )
            raise BadRequestError("invalid webhook signature")

    unknown = [e.event_type for e in body.events
               if e.event_type not in COMMUNICATION_EVENT_TYPES]
    if unknown:
        raise BadRequestError(
            f"unknown communication event type(s): {sorted(set(unknown))[:5]}"
        )

    normalized = [
        {
            "event_type": e.event_type,
            "source": body.provider,
            "external_id": e.external_id,
            "occurred_at": e.occurred_at,
            "properties": {**e.properties, "provider": e.properties.get("provider") or body.provider},
        }
        for e in body.events
    ]
    from services.comms.ingest import ingest_normalized_events
    counts = await ingest_normalized_events(tenant.tenant_id, normalized)
    return APIResponse(data={"accepted": True, **counts}).to_dict()


class InboundReplyBody(BaseModel):
    provider: str = "inbound_parse"
    replies: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)


@router.post("/replies")
async def ingest_replies(request: Request, body: InboundReplyBody) -> dict:
    """Inbound reply ingestion (Phase 13).

    Accepts structural reply metadata only — from, message ids, thread ids,
    headers. Bodies are not accepted; evidence stays a reference. Automated
    responses (DSN, out-of-office, loops) are detected and excluded from
    engagement while remaining recorded as facts.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    from services.comms.replies import normalize_inbound_reply
    from services.comms.ingest import ingest_normalized_events

    normalized = []
    skipped = 0
    for reply in body.replies:
        event = normalize_inbound_reply(tenant.tenant_id, reply, provider=body.provider)
        if event:
            normalized.append(event)
        else:
            skipped += 1
    counts = await ingest_normalized_events(tenant.tenant_id, normalized) if normalized else {}
    return APIResponse(data={"accepted": len(normalized), "skipped": skipped, **counts}).to_dict()


class ClickTokenRequest(BaseModel):
    campaign_id: Optional[str] = None
    external_message_id: Optional[str] = None
    recipient_alias_id: Optional[str] = None
    recipient_email: Optional[str] = None  # hashed immediately, never stored
    link_id: Optional[str] = None
    sequence_step: Optional[int] = None
    ttl_seconds: int = Field(default=30 * 24 * 3600, ge=60, le=90 * 24 * 3600)


class ClickTokenBatchBody(BaseModel):
    tokens: list[ClickTokenRequest] = Field(..., min_length=1, max_length=1000)


@router.post("/click-tokens")
async def issue_click_tokens(request: Request, body: ClickTokenBatchBody) -> dict:
    """Issue signed post-click correlation tokens (Phase 11).

    Tenants append the returned token to campaign links as ``?ae=<token>``.
    Raw recipient emails, when provided, are hashed to tenant-scoped aliases
    before entering the token; they are never stored or echoed back.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)

    from services.comms.mailbox import build_email_alias

    issued = []
    for req in body.tokens:
        alias_id = req.recipient_alias_id
        if not alias_id and req.recipient_email:
            alias = build_email_alias(req.recipient_email, tenant.tenant_id)
            alias_id = alias.alias_hash if alias else None
        token = issue_click_token(
            tenant.tenant_id,
            campaign_id=req.campaign_id,
            external_message_id=req.external_message_id,
            recipient_alias_id=alias_id,
            link_id=req.link_id,
            sequence_step=req.sequence_step,
            ttl_seconds=req.ttl_seconds,
        )
        issued.append({"token": token, "link_id": req.link_id})
    metrics.increment(
        "comms_click_tokens_issued_total", len(issued),
        labels={"tenant_id": tenant.tenant_id},
    )
    return APIResponse(data={"tokens": issued}).to_dict()


class ClickTokenVerifyBody(BaseModel):
    token: str


@router.post("/click-tokens/verify")
async def verify_click_token_route(request: Request, body: ClickTokenVerifyBody) -> dict:
    """Verify a click token and return campaign/identity correlation evidence."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    result = verify_click_token(body.token, tenant.tenant_id)
    if not result.valid:
        return APIResponse(data={"valid": False, "error": result.error}).to_dict()
    evidence = correlation_evidence_from_token(body.token, tenant.tenant_id)
    return APIResponse(data={"valid": True, "evidence": evidence}).to_dict()


@router.get("/health")
async def comms_health(request: Request) -> dict:
    """Tenant-visible comms pipeline health (Phase 26)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await _health_snapshot(tenant.tenant_id)
    return APIResponse(data=data).to_dict()


# ── Canonical suppression authority (§16) ────────────────────────────────────

@router.get("/suppressions")
async def list_suppressions(request: Request, limit: int = 200) -> dict:
    """Tenant-visible canonical suppression ledger (provider-reported vs
    Aether-enforced state visible per row)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.suppression_authority import SuppressionAuthorityService
    items = await SuppressionAuthorityService().list_for_tenant(
        tenant.tenant_id, limit=max(1, min(limit, 1000))
    )
    return APIResponse(data={"items": items}).to_dict()


# ── Provider identity bridge — provisional/unresolved queue (§13) ────────────

class IdentityResolveBody(BaseModel):
    canonical_entity_id: str = Field(..., min_length=1, max_length=200)


@router.get("/identities/provisional")
async def list_provisional_identities(request: Request, limit: int = 100) -> dict:
    """Provider identities awaiting resolution — the mapping-review queue."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.identity_bridge import ProviderIdentityRepository
    items = await ProviderIdentityRepository().list_provisional(
        tenant.tenant_id, limit=max(1, min(limit, 500))
    )
    return APIResponse(data={"items": items}).to_dict()


@router.post("/identities/{identity_id}/resolve")
async def resolve_provisional_identity(
    identity_id: str, request: Request, body: IdentityResolveBody
) -> dict:
    """Map a provisional provider identity to a canonical entity (mapping review)."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    from services.comms.identity_bridge import ProviderIdentityBridge
    row = await ProviderIdentityBridge().mark_resolved(
        tenant.tenant_id, identity_id, body.canonical_entity_id,
    )
    if row is None:
        raise BadRequestError("unknown provider identity")
    return APIResponse(data=row).to_dict()


# ── Cross-channel initiatives (Phase 10, ADR-C9) ─────────────────────────────

class InitiativeCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    campaign_ids: list[str] = Field(default_factory=list, max_length=50)


@router.post("/initiatives")
async def create_initiative(request: Request, body: InitiativeCreateBody) -> dict:
    """Create a cross-channel initiative and optionally attach member campaigns.

    Members are canonical campaign UUIDs from the existing registry; each
    keeps its own funnel and reconciliation — the initiative is rollup only.
    """
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    from services.comms.initiatives import InitiativeRepository

    repo = InitiativeRepository()
    initiative = await repo.create(
        tenant.tenant_id, body.name, description=body.description,
    )
    for campaign_id in body.campaign_ids:
        await repo.add_member(
            tenant.tenant_id, initiative["initiative_id"], campaign_id,
        )
    return APIResponse(data={
        "initiative": initiative, "members_added": len(body.campaign_ids),
    }).to_dict()


@router.get("/initiatives")
async def list_initiatives(request: Request, limit: int = 50) -> dict:
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.initiatives import InitiativeRepository

    items = await InitiativeRepository().list_for_tenant(
        tenant.tenant_id, limit=min(max(limit, 1), 100),
    )
    return APIResponse(data={"items": [
        {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in i.items()}
        for i in items
    ]}).to_dict()


class InitiativeMemberBody(BaseModel):
    campaign_id: str


@router.post("/initiatives/{initiative_id}/members")
async def add_initiative_member(
    initiative_id: str, request: Request, body: InitiativeMemberBody,
) -> dict:
    tenant = request.state.tenant
    tenant.require_permission(Permissions.WRITE)
    from services.comms.initiatives import InitiativeRepository

    repo = InitiativeRepository()
    if await repo.get(tenant.tenant_id, initiative_id) is None:
        raise BadRequestError(f"initiative {initiative_id} not found")
    added = await repo.add_member(tenant.tenant_id, initiative_id, body.campaign_id)
    return APIResponse(data={"added": added}).to_dict()


@router.get("/initiatives/{initiative_id}/rollup")
async def initiative_rollup(initiative_id: str, request: Request) -> dict:
    """Macro rollup across member campaigns: per-member comms funnels and
    summed totals. Cross-channel identity overlap is not deduplicated at
    the initiative level (stated in the response notes)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.initiatives import InitiativeRollupService

    rollup = await InitiativeRollupService().rollup(tenant.tenant_id, initiative_id)
    if rollup is None:
        raise BadRequestError(f"initiative {initiative_id} not found")
    return APIResponse(data=rollup).to_dict()


admin_router = APIRouter(prefix="/v1/comms/admin", tags=["Kyber Communications"])


@admin_router.get("/health")
async def comms_admin_health(request: Request, tenant_id: Optional[str] = None) -> dict:
    """Operator fleet view: projection, resolution, and classification health."""
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    data = await _health_snapshot(tenant_id) if tenant_id else await _fleet_snapshot()
    return APIResponse(data=data).to_dict()


# ── Operator actions (Phase 21F) — permission-gated and audited ─────────────

async def _audit_operator_action(
    request: Request, *, action: str, tenant_id: str,
    resource_id: Optional[str], outcome: str, metadata: dict[str, Any],
) -> None:
    try:
        from services.security.audit_ledger import AuditLedger
        actor = getattr(getattr(request.state, "tenant", None), "tenant_id", "operator")
        await AuditLedger().record(
            actor_id=str(actor),
            actor_type="olympus_operator",
            event_type="comms_operator_action",
            resource_type="communications",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            resource_id=resource_id,
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover — audit must not block remediation
        logger.warning("comms_operator_audit_failed action=%s: %s", action, exc)


class OperatorStateRebuildBody(BaseModel):
    tenant_id: str
    entity_id: str
    channel: str = "email"


@admin_router.post("/state/rebuild")
async def operator_rebuild_state(request: Request, body: OperatorStateRebuildBody) -> dict:
    """Rebuild one entity's communication state and journey from facts."""
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    from services.comms.rebuild_coalescer import get_rebuild_coalescer

    coalescer = get_rebuild_coalescer()
    await coalescer.request_rebuild(
        body.tenant_id, body.entity_id, channel=body.channel, reason="operator",
    )
    outcome = await coalescer.flush_key((body.tenant_id, body.entity_id))
    await _audit_operator_action(
        request, action="rebuild_state", tenant_id=body.tenant_id,
        resource_id=body.entity_id, outcome="allowed",
        metadata=outcome or {},
    )
    return APIResponse(data=outcome or {}).to_dict()


class OperatorGraphReprojectBody(BaseModel):
    tenant_id: str
    campaign_id: Optional[str] = None
    limit: int = Field(default=500, ge=1, le=5000)


@admin_router.post("/graph/reproject")
async def operator_reproject_graph(request: Request, body: OperatorGraphReprojectBody) -> dict:
    """Re-fold communication facts into the aggregated relationship graph.

    Idempotent: aggregates upsert in place, edges emit only on first
    observation / promotion transitions (ADR-C6), so repeated reprojection
    never explodes graph cardinality.
    """
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    from services.comms.graph_projection import CommsGraphProjector
    from services.comms.repository import CommsFactsRepository

    if not body.campaign_id:
        raise BadRequestError("campaign_id is required for graph reprojection")
    facts_repo = CommsFactsRepository()
    rows, _ = await facts_repo.list_for_campaign(
        body.tenant_id, body.campaign_id, limit=body.limit,
    )

    projector = CommsGraphProjector()
    projected = 0
    for row in rows:
        if await projector.project_fact(row) is not None:
            projected += 1
    await _audit_operator_action(
        request, action="reproject_graph", tenant_id=body.tenant_id,
        resource_id=body.campaign_id, outcome="allowed",
        metadata={"facts_scanned": len(rows), "relationships_updated": projected},
    )
    return APIResponse(data={
        "facts_scanned": len(rows), "relationships_updated": projected,
    }).to_dict()


class OperatorDsrEraseBody(BaseModel):
    tenant_id: str
    entity_id: str
    confirm: bool = False


@admin_router.post("/dsr/erase")
async def operator_dsr_erase(request: Request, body: OperatorDsrEraseBody) -> dict:
    """DSR erasure for one entity's communications (ADR-C10).

    Deletes communication facts and derived state; active suppression
    records are retained so opt-outs stay honored. Requires ``confirm=true``.
    """
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    if not body.confirm:
        raise BadRequestError("set confirm=true to execute DSR erasure")
    from services.comms.repository import CommsFactsRepository

    removed = await CommsFactsRepository().tombstone_by_profile(
        body.tenant_id, body.entity_id,
    )
    await _audit_operator_action(
        request, action="dsr_erase", tenant_id=body.tenant_id,
        resource_id=body.entity_id, outcome="allowed",
        metadata={"facts_removed": removed},
    )
    return APIResponse(data={"facts_removed": removed}).to_dict()


@admin_router.get("/sync-runs")
async def operator_sync_runs(
    request: Request, tenant_id: str, limit: int = 100
) -> dict:
    """Durable sync-run history for a tenant (Kyber Communications Operations)."""
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    from services.comms.sync_runs import SyncRunService
    items = await SyncRunService().list_for_tenant(
        tenant_id, limit=max(1, min(limit, 500))
    )
    return APIResponse(data={"items": items}).to_dict()


class OperatorSuppressionReconcileBody(BaseModel):
    tenant_id: str
    provider: str
    provider_reported: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


@admin_router.post("/suppressions/reconcile")
async def operator_reconcile_suppressions(
    request: Request, body: OperatorSuppressionReconcileBody
) -> dict:
    """Reconcile provider-reported suppressions against Aether's canonical set.

    Observe-only: reports drift and stamps reconciliation; never writes back to
    the provider unless suppression write-back is separately authorized.
    """
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    from services.comms.suppression_authority import SuppressionAuthorityService
    result = await SuppressionAuthorityService().reconcile(
        body.tenant_id, provider=body.provider,
        provider_reported=body.provider_reported,
    )
    await _audit_operator_action(
        request, action="reconcile_suppressions", tenant_id=body.tenant_id,
        resource_id=body.provider, outcome="allowed",
        metadata={"in_sync": result.get("in_sync")},
    )
    return APIResponse(data=result).to_dict()


async def _health_snapshot(tenant_id: str) -> dict[str, Any]:
    from repositories.repos import get_pool
    pool = await get_pool()
    if pool is None:
        from services.comms.repository import _local_facts
        rows = [r for r in _local_facts.values() if r.get("tenant_id") == tenant_id]
        resolved = sum(1 for r in rows if r.get("campaign_id"))
        machine = sum(1 for r in rows if r.get("suspected_machine_activity"))
        return {
            "tenant_id": tenant_id,
            "communication_facts": len(rows),
            "campaign_resolution_rate": round(resolved / len(rows), 4) if rows else None,
            "machine_event_rate": round(machine / len(rows), 4) if rows else None,
            "last_event_at": max((str(r.get("occurred_at")) for r in rows), default=None),
        }
    async with pool.acquire() as conn:
        rec = await conn.fetchrow(
            """
            SELECT COUNT(*) AS communication_facts,
                   COUNT(*) FILTER (WHERE campaign_id IS NOT NULL) AS resolved,
                   COUNT(*) FILTER (WHERE COALESCE(suspected_machine_activity, false)) AS machine,
                   MAX(occurred_at) AS last_event_at
            FROM silver_comms_facts WHERE tenant_id = $1
            """,
            tenant_id,
        )
    total = rec["communication_facts"] or 0
    return {
        "tenant_id": tenant_id,
        "communication_facts": total,
        "campaign_resolution_rate": round((rec["resolved"] or 0) / total, 4) if total else None,
        "machine_event_rate": round((rec["machine"] or 0) / total, 4) if total else None,
        "last_event_at": str(rec["last_event_at"]) if rec["last_event_at"] else None,
    }


async def _fleet_snapshot() -> dict[str, Any]:
    from repositories.repos import get_pool
    pool = await get_pool()
    if pool is None:
        from services.comms.repository import _local_facts
        tenants = sorted({r.get("tenant_id") for r in _local_facts.values()})
        return {"tenants": [await _health_snapshot(t) for t in tenants if t]}
    async with pool.acquire() as conn:
        records = await conn.fetch(
            """
            SELECT tenant_id,
                   COUNT(*) AS communication_facts,
                   COUNT(*) FILTER (WHERE campaign_id IS NOT NULL) AS resolved,
                   COUNT(*) FILTER (WHERE COALESCE(suspected_machine_activity, false)) AS machine,
                   MAX(occurred_at) AS last_event_at
            FROM silver_comms_facts
            GROUP BY tenant_id ORDER BY COUNT(*) DESC LIMIT 100
            """,
        )
    return {
        "tenants": [
            {
                "tenant_id": r["tenant_id"],
                "communication_facts": r["communication_facts"],
                "campaign_resolution_rate": (
                    round((r["resolved"] or 0) / r["communication_facts"], 4)
                    if r["communication_facts"] else None
                ),
                "machine_event_rate": (
                    round((r["machine"] or 0) / r["communication_facts"], 4)
                    if r["communication_facts"] else None
                ),
                "last_event_at": str(r["last_event_at"]) if r["last_event_at"] else None,
            }
            for r in records
        ]
    }
