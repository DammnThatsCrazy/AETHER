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


admin_router = APIRouter(prefix="/v1/comms/admin", tags=["Kyber Communications"])


@admin_router.get("/health")
async def comms_admin_health(request: Request, tenant_id: Optional[str] = None) -> dict:
    """Operator fleet view: projection, resolution, and classification health."""
    from services.security.request_context import require_kyber_operator
    require_kyber_operator(request)
    data = await _health_snapshot(tenant_id) if tenant_id else await _fleet_snapshot()
    return APIResponse(data=data).to_dict()


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
