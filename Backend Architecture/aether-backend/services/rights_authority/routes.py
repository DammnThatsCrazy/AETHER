"""Optional Rights Authority HTTP surface (blueprint §17 tenant surface).

NOT wired into ``main.py``. Integrator: mount
``services.rights_authority.routes:router`` (prefix ``/v1/rights``). Additive
only — matches the original ``services/dsr_propagation`` pattern.

Only the *authoritative* seams are exposed:
* ``POST /v1/rights/decisions/effective`` — resolve a durable
  ``RightsDecision`` through the effective rights resolver (grants loaded by the
  resolver, consent verified via the wired consent seam).
* ``GET /v1/rights/decisions/{decision_id}`` — tenant-scoped read of a durable
  decision (cross-tenant / unknown reads as 404).
* ``POST /v1/rights/revocations`` — run the §66 revocation pipeline against a
  tenant-owned grant (tenant-scoped ownership is enforced inside the pipeline).

The Generalization Gateway is deliberately NOT exposed here: its eligibility
context (``pii_present`` / ``tenant_identifiable`` / population / grants) must be
derived from lineage + data-profiling evidence server-side, never asserted by a
client over HTTP — exposing it would recreate the client-trusted-context
fail-open this authority is built to prevent. A context-composing surface is a
later integration phase.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from shared.auth.auth import TenantContext
from shared.common.common import APIResponse
from shared.decorators import require_permission
from shared.logger.logger import get_logger
from services.security.request_context import tenant_actor

logger = get_logger("aether.rights_irrl.routes")
router = APIRouter(prefix="/v1/rights", tags=["Rights Authority"])

# Baseline tenant permissions. Read/resolve surfaces use ``read``; the §66
# revocation is a destructive mutation and requires the established ``write``
# scope (never ``read``), so a read-only principal cannot revoke rights. Real
# Kyber/tenant capability wiring is a later phase (the resolver/revocation
# pipeline additionally enforce their own tenant-scoped checks server-side).
_RIGHTS_READ_PERMISSION = "read"
_RIGHTS_WRITE_PERMISSION = "write"


class EffectiveRightsResolveRequest(BaseModel):
    """Inputs for an effective-rights resolution (blueprint §16).

    ``actor`` is deliberately NOT client-suppliable: the actor whose rights are
    being resolved is the authenticated caller (derived server-side from
    ``tenant_actor``). Cross-actor delegation, if ever needed, must ride an
    explicit delegation capability — never a caller-asserted identity.
    """

    tenant_id: str
    source: list[str] = Field(
        default_factory=list, description="governing rights/source refs"
    )
    artifact: Optional[str] = None
    requested_use: str
    purpose: Optional[str] = None
    destination: Optional[str] = None
    as_of: Optional[str] = None


class RevocationRequest(BaseModel):
    """Inputs for the §66 revocation pipeline."""

    tenant_id: str
    grant_id: str
    reason: str
    delivery_evidence: list[str] = Field(default_factory=list)


def _same_tenant_or_403(request: Request, tenant_id: str) -> None:
    actor = tenant_actor(request)
    if actor.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="cross-tenant access denied")


@router.post("/decisions/effective")
async def resolve_effective_decision(
    body: EffectiveRightsResolveRequest,
    request: Request,
    _tenant: TenantContext = Depends(require_permission(_RIGHTS_READ_PERMISSION)),
) -> dict:
    """Resolve (and durably record) the effective rights decision for a use."""
    _same_tenant_or_403(request, body.tenant_id)
    from .resolver import effective_rights_resolver

    # Actor is the authenticated caller — never a client-supplied identity. A
    # principal resolving rights for itself is the only posture this minimal
    # surface permits without an explicit delegation capability.
    actor = tenant_actor(request).actor_id
    decision = await effective_rights_resolver.resolve(
        tenant=body.tenant_id,
        source=body.source,
        artifact=body.artifact,
        actor=actor,
        requested_use=body.requested_use,
        purpose=body.purpose,
        destination=body.destination,
        as_of=body.as_of,
    )
    return APIResponse(data=_dump(decision)).to_dict()


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str,
    request: Request,
    _tenant: TenantContext = Depends(require_permission(_RIGHTS_READ_PERMISSION)),
) -> dict:
    """Tenant-scoped read of a durable RightsDecision (404 on unknown/cross-tenant)."""
    actor = tenant_actor(request)
    from .repositories import rights_decision_repository

    record = await rights_decision_repository.get(decision_id)
    if record is None or str(record.get("tenant_id", "") or "") != actor.tenant_id:
        raise HTTPException(status_code=404, detail="decision not found")
    return APIResponse(data=record).to_dict()


@router.post("/revocations")
async def run_revocation(
    body: RevocationRequest,
    request: Request,
    _tenant: TenantContext = Depends(require_permission(_RIGHTS_WRITE_PERMISSION)),
) -> dict:
    """Run the §66 revocation pipeline.

    Ownership is verified server-side at two layers: this route requires
    ``body.tenant_id`` to equal the authenticated caller's tenant, and the
    pipeline's Step-0 guard loads the grant by id and refuses any grant that is
    unknown or owned by another tenant (``RevocationError`` → 404) before a
    single decision/impact row is recorded. ``body.grant_id`` never names an
    owner; the grant's tenant is authoritative.
    """
    _same_tenant_or_403(request, body.tenant_id)
    from .impact import RevocationError, revocation_pipeline

    try:
        summary = await revocation_pipeline(
            tenant_id=body.tenant_id,
            grant_id=body.grant_id,
            reason=body.reason,
            delivery_evidence=body.delivery_evidence or None,
        )
    except RevocationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return APIResponse(data=_dump(summary)).to_dict()


def _dump(value: object) -> dict:
    """Model/dict → plain JSON-safe dict."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value or {})
