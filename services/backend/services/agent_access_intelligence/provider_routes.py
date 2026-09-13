"""Agent Access Intelligence — capability provider API (PR 3, Phase A, §9.6).

``/v1/capability-providers`` is the mounted entry point for the agentic provider
framework. ``GET /adapters`` serves ``provider_framework.provider_registry`` directly and
``GET /permission-findings`` runs ``provider_framework.compute_permission_findings`` over
stored evidence — the framework is reached through this router, not duplicated behind it.

Mirrors the conventions of ``declaration_routes.py``: read ``request.state.tenant``, call
``require_permission(...)``, scope every query by ``tenant.tenant_id``, return
``APIResponse``. Service-layer errors (``BadRequestError``/``NotFoundError``) propagate to
the shared handlers rather than being re-mapped here, so a cross-tenant read fails
identically to an absent one.

**Nothing on this router verifies a publisher.** Evidence records what a *provider*
reported, attributed to that provider; every response carries the attestation disclosure
so a record cannot be lifted out of its envelope and read as platform verification. The
adapter registry is read-only by construction (``provider_framework``'s INVARIANT: AETHER
never writes to, executes against, or mutates external provider state) and this router
exposes no operation that would change that.

No lifecycle event is published: capturing a provider's attestation grants no authority to
anyone, and inventing a new event type for it would add an unconsumed topic to the
registry. The ``recorded_by_entity_id`` on the row plus the platform audit trail are the
record of who captured what.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse
from shared.logger.logger import get_logger, metrics

from services.agentic_observability.provider_framework import provider_registry
from services.agent_access_intelligence.provider_evidence import (
    ATTESTATION_DISCLOSURE,
    provider_evidence_service,
)

logger = get_logger("aether.service.agent_access_intelligence.provider_routes")

capability_providers_router = APIRouter(
    prefix="/v1/capability-providers",
    tags=["Agent Access Intelligence"],
)


# ── Request models ────────────────────────────────────────────────────────────

class ProviderEvidenceRequest(BaseModel):
    """One provider attestation about an agent's access to a capability.

    ``tenant_id`` is deliberately absent: it comes from ``request.state.tenant`` so a body
    can never widen a write into another tenant."""

    provider_id: str = Field(
        description="The provider that reported this. Evidence is attributed to it.",
    )
    capability_id: Optional[str] = None
    external_account_id: Optional[str] = Field(
        default=None,
        description="Sanitized before storage — credentials/tokens in a URL are stripped.",
    )
    agent_id: Optional[str] = None
    verification_status: Optional[str] = Field(
        default=None,
        description=(
            "The PROVIDER's own claim, from ProviderVerificationStatus (confirmed, "
            "contradicted, unverified, pending, expired, revoked, insufficient_data). "
            "Omitted means the provider asserted nothing and is recorded as "
            "insufficient_data, not as unverified."
        ),
    )
    verification_method: Optional[str] = Field(
        default=None,
        description="How the provider says it determined this. Sanitized before storage.",
    )
    verified_at: Optional[str] = Field(
        default=None,
        description=(
            "When the provider states it determined this. ISO-8601 with an explicit "
            "offset or 'Z'; naive or malformed values are rejected."
        ),
    )
    notes: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER ADAPTERS
# ══════════════════════════════════════════════════════════════════════════════

@capability_providers_router.get("/adapters")
async def list_provider_adapters(request: Request):
    """The registered agentic provider adapters and what each one supports.

    Served straight from ``provider_framework.provider_registry`` — this endpoint is the
    registry's reachable surface, so an adapter that is registered is an adapter an
    operator can see."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    items: list[dict[str, Any]] = [asdict(md) for md in provider_registry.list_metadata()]
    metrics.increment("provider_adapters_listed")
    return APIResponse(data={
        "items": items,
        "count": len(items),
        # Restated from the framework's own INVARIANT rather than assumed by the reader:
        # every adapter operation is a read-only reference operation.
        "read_only": all(bool(item.get("read_only")) for item in items),
        "attestation": ATTESTATION_DISCLOSURE,
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# PROVIDER EVIDENCE
# ══════════════════════════════════════════════════════════════════════════════

@capability_providers_router.post("/evidence")
async def capture_provider_evidence(body: ProviderEvidenceRequest, request: Request):
    """Record what a provider reported about an agent's access (upsert).

    Re-capturing the same ``(provider, capability, account)`` updates that row instead of
    creating a second one, so one access never carries two competing provider claims."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    recorded_by = tenant.user_id or tenant.tenant_id

    record = await provider_evidence_service.capture(
        tenant_id=tenant.tenant_id,
        recorded_by_entity_id=recorded_by,
        provider_id=body.provider_id,
        capability_id=body.capability_id,
        external_account_id=body.external_account_id,
        agent_id=body.agent_id,
        verification_status=body.verification_status,
        verification_method=body.verification_method,
        verified_at=body.verified_at,
        notes=body.notes,
    )
    metrics.increment(
        "provider_evidence_captured",
        labels={
            "provider_id": str(record.get("provider_id") or "unknown"),
            "verification_status": str(record.get("verification_status") or "unknown"),
        },
    )
    return APIResponse(data=record).to_dict()


@capability_providers_router.get("/evidence")
async def list_provider_evidence(
    request: Request,
    provider_id: Optional[str] = Query(default=None),
    capability_id: Optional[str] = Query(
        default=None,
        description="The observed-catalog capability this evidence is attested against.",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await provider_evidence_service.list(
        tenant_id=tenant.tenant_id,
        provider_id=provider_id,
        capability_id=capability_id,
        limit=limit,
        offset=offset,
    )
    return APIResponse(data={
        "items": rows,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        # A full page may or may not be the end of the collection; say which rather than
        # letting a caller read `count < limit` as "and that is all of it".
        "truncated": len(rows) >= limit,
        "attestation": ATTESTATION_DISCLOSURE,
    }).to_dict()


@capability_providers_router.get("/evidence/{evidence_id}")
async def read_provider_evidence(evidence_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(
        data=await provider_evidence_service.get(
            tenant_id=tenant.tenant_id, evidence_id=evidence_id
        )
    ).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION FINDINGS
# ══════════════════════════════════════════════════════════════════════════════

@capability_providers_router.get("/permission-findings")
async def list_permission_findings(
    request: Request,
    limit: int = Query(
        500, ge=1, le=500,
        description=(
            "Bound on each backing read; whether any was hit is reported in `coverage`. "
            "Capped at 500 because the framework's pass is O(grants x actions)."
        ),
    ),
):
    """Permission findings computed by ``provider_framework.compute_permission_findings``.

    Read-only and idempotent, so it requires ``read`` — gating it on ``write`` would stop
    read-only compliance callers from asking the one question this surface answers.

    An empty ``items`` with ``findings_known: false`` means the inputs were absent, NOT
    that the tenant is clean; every count is ``null`` in that case."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    result = await provider_evidence_service.permission_findings(
        tenant_id=tenant.tenant_id, limit=limit
    )
    metrics.increment(
        "provider_permission_findings_computed",
        labels={"known": "true" if result.get("findings_known") else "false"},
    )
    return APIResponse(data=result).to_dict()
