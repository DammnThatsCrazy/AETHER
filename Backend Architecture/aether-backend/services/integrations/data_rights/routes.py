"""
Aether — Data Rights Ledger Routes

Tenant-scoped and operator routes for data rights grant management.

Routes:
    GET    /v1/integrations/data-rights              List tenant's grants
    POST   /v1/integrations/data-rights/grants       Create grant
    GET    /v1/integrations/data-rights/grants/{id}  Get grant detail
    POST   /v1/integrations/data-rights/grants/{id}/revoke  Revoke grant
    POST   /v1/integrations/data-rights/policy-check  Evaluate policy check
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.integrations.data_rights.models import (
    DataRightsGrantCreate,
    DataRightsGrantRevoke,
    GrantStatus,
    PolicyCheckRequest,
)
from services.integrations.data_rights.service import data_rights_service
from shared.rights_authority.contracts import (
    ActorRef,
    AgreementRef,
    ArtifactRef,
    AttachRightsEnvelope,
    IssueRightsPolicySet,
    RevokeRightsAuthority,
    RetentionRule,
    RightsProfile,
    UseGrant,
)
from shared.rights_authority.service import rights_authority

logger = get_logger("aether.service.data_rights.routes")

router = APIRouter(
    prefix="/v1/integrations/data-rights",
    tags=["Integrations — Data Rights"],
)

admin_router = APIRouter(
    prefix="/v1/admin/kyber/data-rights",
    tags=["Admin — Kyber Data Rights"],
)


class RightsPolicyCreate(BaseModel):
    """Tenant-submitted policy authority backed by an accepted agreement."""

    contract_id: str
    contract_version: str
    accepted_at: str
    rights_profile: RightsProfile = "secure_tenant"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    deployment_constraints: dict[str, Any] = Field(default_factory=dict)
    allowed_uses: list[UseGrant] = Field(default_factory=list)
    retention_rules: list[RetentionRule] = Field(default_factory=list)
    approval_refs: list[str] = Field(default_factory=list)


class RightsPolicyTransition(BaseModel):
    activation_state: str
    evidence_ref: str


class RightsEnvelopeCreate(BaseModel):
    artifact: ArtifactRef
    primary_rights_class: str
    policy_set_ref: str
    source_grant_refs: list[str] = Field(default_factory=list)
    consent_snapshot_refs: list[str] = Field(default_factory=list)
    source_license_refs: list[str] = Field(default_factory=list)
    classification_refs: list[str] = Field(default_factory=list)
    evidence_manifest_refs: list[str] = Field(default_factory=list)
    lineage_root_refs: list[str] = Field(default_factory=list)
    retention_class: str = "tenant_event_90d"
    retention_deadline: Optional[str] = None
    disclosure_ceiling: str = "tenant_scoped"


class RightsImpactRevoke(BaseModel):
    root_refs: list[str]
    reason: str


class RightsEvidenceManifestCreate(BaseModel):
    subject_refs: list[str] = Field(default_factory=list)
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    expires_at: Optional[str] = None


def _rights_actor(request: Request, *, operator: bool = False) -> ActorRef:
    tenant = getattr(request.state, "tenant", None)
    return ActorRef(
        kind="operator" if operator else "tenant_user",
        id=_actor(request),
        tenant_id=None if operator else getattr(tenant, "tenant_id", None),
    )


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


def _actor(request: Request) -> str:
    t = getattr(request.state, "tenant", None)
    return getattr(t, "user_id", None) or getattr(t, "tenant_id", None) or "system"


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


# ══════════════════════════════════════════════════════════════════════════════
# TENANT ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("")
async def list_data_rights(
    request: Request,
    connector_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """List the tenant's data rights grants."""
    tenant_id = _tenant_id(request)

    status_enum = None
    if status:
        try:
            status_enum = GrantStatus(status)
        except ValueError:
            pass

    grants = await data_rights_service.list_grants(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status_enum,
    )
    return APIResponse(data={
        "items": [g.model_dump() for g in grants],
        "count": len(grants),
    }).to_dict()


@router.post("/grants")
async def create_grant(body: DataRightsGrantCreate, request: Request):
    """Create a new data rights grant.

    Fail-closed: all permissions default False unless explicitly set.
    BYOK credential does NOT imply lake ingestion or training rights.
    """
    tenant_id = _tenant_id(request, "admin")

    if body.tenant_id != tenant_id:
        raise ForbiddenError("Cannot create grants for other tenants")

    actor = _actor(request)
    grant = await data_rights_service.create_grant(body, granted_by_user_id=actor)

    return APIResponse(data=grant.model_dump()).to_dict()


@router.get("/grants/{grant_id}")
async def get_grant(grant_id: str, request: Request):
    """Get full detail for a data rights grant."""
    tenant_id = _tenant_id(request)
    grant = await data_rights_service.get_grant(grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    return APIResponse(data=grant.model_dump()).to_dict()


@router.post("/grants/{grant_id}/revoke")
async def revoke_grant(grant_id: str, body: DataRightsGrantRevoke, request: Request):
    """Revoke a data rights grant. All data use is denied immediately."""
    tenant_id = _tenant_id(request, "admin")
    grant = await data_rights_service.get_grant(grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    updated = await data_rights_service.revoke_grant(grant_id, body)
    return APIResponse(data=updated.model_dump()).to_dict()


@router.post("/policy-check")
async def policy_check(body: PolicyCheckRequest, request: Request):
    """Evaluate a specific policy check on a grant (fail-closed)."""
    tenant_id = _tenant_id(request)
    grant = await data_rights_service.get_grant(body.grant_id)

    if not grant:
        raise NotFoundError("grant")
    if grant.tenant_id != tenant_id:
        raise ForbiddenError("Access denied to this grant")

    result = await data_rights_service.check_policy(body.grant_id, body.check_type)
    return APIResponse(data=result.model_dump()).to_dict()


@router.post("/policies")
async def create_rights_policy(body: RightsPolicyCreate, request: Request):
    """Create a pending IRRL policy set from an accepted agreement."""
    tenant_id = _tenant_id(request, "admin")
    policy = await rights_authority.issue_policy_set(IssueRightsPolicySet(
        tenant_id=tenant_id,
        agreement_ref=AgreementRef(
            contract_id=body.contract_id,
            contract_version=body.contract_version,
            accepted_at=body.accepted_at,
        ),
        rights_profile=body.rights_profile,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        deployment_constraints=body.deployment_constraints,
        allowed_uses=body.allowed_uses,
        retention_rules=body.retention_rules,
        approval_refs=body.approval_refs,
        activation_state="rights_pending",
    ))
    return APIResponse(data=policy.model_dump(mode="json")).to_dict()


@router.get("/policies")
async def list_rights_policies(request: Request):
    tenant_id = _tenant_id(request)
    rows = await rights_authority.repository.list_policies(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@router.post("/policies/{policy_set_ref}/request-review")
async def request_policy_review(
    policy_set_ref: str, body: RightsPolicyTransition, request: Request,
):
    tenant_id = _tenant_id(request, "admin")
    policy = await rights_authority.repository.get_policy(policy_set_ref)
    if not policy or policy.get("tenant_id") != tenant_id:
        raise NotFoundError("rights policy set")
    if body.activation_state not in {"rights_pending", "rights_review"}:
        raise ForbiddenError("tenant policy routes may only request review")
    transitioned = await rights_authority.transition_policy_set(
        policy_set_ref,
        activation_state=body.activation_state,
        actor=_rights_actor(request),
        evidence_ref=body.evidence_ref,
    )
    return APIResponse(data=transitioned.model_dump(mode="json")).to_dict()


@router.post("/envelopes")
async def create_rights_envelope(body: RightsEnvelopeCreate, request: Request):
    tenant_id = _tenant_id(request, "admin")
    policy = await rights_authority.repository.get_policy(body.policy_set_ref)
    if not policy or policy.get("tenant_id") != tenant_id:
        raise NotFoundError("rights policy set")
    envelope = await rights_authority.attach_artifact(AttachRightsEnvelope(
        artifact_ref=body.artifact.model_copy(update={"tenant_id": tenant_id}),
        primary_rights_class=body.primary_rights_class,  # type: ignore[arg-type]
        policy_set_ref=body.policy_set_ref,
        tenant_id=tenant_id,
        source_grant_refs=body.source_grant_refs,
        consent_snapshot_refs=body.consent_snapshot_refs,
        source_license_refs=body.source_license_refs,
        classification_refs=body.classification_refs,
        evidence_manifest_refs=body.evidence_manifest_refs,
        lineage_root_refs=body.lineage_root_refs,
        retention_class=body.retention_class,
        retention_deadline=body.retention_deadline,
        disclosure_ceiling=body.disclosure_ceiling,  # type: ignore[arg-type]
    ))
    return APIResponse(data=envelope.model_dump(mode="json")).to_dict()


@router.get("/envelopes")
async def list_rights_envelopes(request: Request):
    tenant_id = _tenant_id(request)
    rows = await rights_authority.repository.list_envelopes(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@router.post("/evidence-manifests")
async def create_evidence_manifest(body: RightsEvidenceManifestCreate, request: Request):
    """Create a signed manifest of consent/license/approval evidence."""
    tenant_id = _tenant_id(request, "admin")
    manifest = await rights_authority.issue_evidence_manifest(
        tenant_id=tenant_id,
        subject_refs=body.subject_refs,
        evidence=body.evidence,
        attested_by=_rights_actor(request),
        expires_at=body.expires_at,
    )
    return APIResponse(data=manifest.model_dump(mode="json")).to_dict()


@router.get("/evidence-manifests")
async def list_evidence_manifests(request: Request):
    tenant_id = _tenant_id(request)
    rows = await rights_authority.repository.list_evidence_manifests(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@router.get("/decisions")
async def list_rights_decisions(request: Request, limit: int = 100):
    tenant_id = _tenant_id(request)
    rows = await rights_authority.repository.list_decisions(tenant_id, limit=min(max(limit, 1), 500))
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@router.post("/impacts/revoke")
async def revoke_rights_impact(body: RightsImpactRevoke, request: Request):
    tenant_id = _tenant_id(request, "admin")
    graph = await rights_authority.revoke(RevokeRightsAuthority(
        root_refs=body.root_refs,
        reason=body.reason,
        actor=_rights_actor(request),
        tenant_id=tenant_id,
    ))
    return APIResponse(data=graph.model_dump(mode="json")).to_dict()


@router.get("/impacts")
async def list_rights_impacts(request: Request):
    tenant_id = _tenant_id(request)
    rows = await rights_authority.repository.list_impacts(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@router.get("/impacts/{impact_graph_id}/remediation")
async def list_impact_remediation(impact_graph_id: str, request: Request):
    tenant_id = _tenant_id(request)
    impact = await rights_authority.repository.get_impact(impact_graph_id)
    if not impact or impact.get("tenant_id") != tenant_id:
        raise NotFoundError("rights impact graph")
    steps = await rights_authority.repository.list_remediation_steps(impact_graph_id)
    receipts = await rights_authority.repository.list_remediation_receipts(impact_graph_id)
    return APIResponse(data={
        "impact_graph_id": impact_graph_id,
        "status": impact.get("status"),
        "steps": steps,
        "receipts": receipts,
    }).to_dict()


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN / KYBER ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@admin_router.get("")
async def admin_list_grants(
    request: Request,
    tenant_id: Optional[str] = None,
    connector_id: Optional[str] = None,
    status: Optional[str] = None,
):
    """Operator view: list all data rights grants across tenants."""
    _require_operator(request)

    status_enum = None
    if status:
        try:
            status_enum = GrantStatus(status)
        except ValueError:
            pass

    grants = await data_rights_service.list_grants(
        tenant_id=tenant_id,
        connector_id=connector_id,
        status=status_enum,
    )
    return APIResponse(data={
        "items": [g.model_dump() for g in grants],
        "count": len(grants),
    }).to_dict()


@admin_router.post("/grants/{grant_id}/revoke")
async def admin_revoke_grant(grant_id: str, body: DataRightsGrantRevoke, request: Request):
    """Operator: force-revoke any grant (e.g., compliance enforcement)."""
    _require_operator(request)

    grant = await data_rights_service.get_grant(grant_id)
    if not grant:
        raise NotFoundError("grant")

    updated = await data_rights_service.revoke_grant(grant_id, body)
    return APIResponse(data=updated.model_dump()).to_dict()


@admin_router.get("/policies")
async def admin_list_rights_policies(request: Request, tenant_id: Optional[str] = None):
    _require_operator(request)
    rows = await rights_authority.repository.list_policies(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@admin_router.post("/policies/{policy_set_ref}/transition")
async def admin_transition_rights_policy(
    policy_set_ref: str, body: RightsPolicyTransition, request: Request,
):
    _require_operator(request)
    policy = await rights_authority.repository.get_policy(policy_set_ref)
    if not policy:
        raise NotFoundError("rights policy set")
    transitioned = await rights_authority.transition_policy_set(
        policy_set_ref,
        activation_state=body.activation_state,
        actor=_rights_actor(request, operator=True),
        evidence_ref=body.evidence_ref,
    )
    return APIResponse(data=transitioned.model_dump(mode="json")).to_dict()


@admin_router.get("/impacts")
async def admin_list_rights_impacts(request: Request, tenant_id: Optional[str] = None):
    _require_operator(request)
    rows = await rights_authority.repository.list_impacts(tenant_id)
    return APIResponse(data={"items": rows, "count": len(rows)}).to_dict()


@admin_router.get("/reconciliation")
async def admin_rights_reconciliation(
    request: Request,
    tenant_id: Optional[str] = None,
    limit_per_table: int = 10_000,
):
    """Kyber migration dashboard report; this endpoint never mutates rows."""
    _require_operator(request)
    from shared.rights_authority.reconciliation import build_reconciliation_report

    if limit_per_table < 1 or limit_per_table > 100_000:
        raise ForbiddenError("limit_per_table must be between 1 and 100000")
    report = await build_reconciliation_report(
        tenant_id=tenant_id,
        limit_per_table=limit_per_table,
    )
    return APIResponse(data=report).to_dict()


@admin_router.post("/impacts/{impact_graph_id}/execute")
async def admin_execute_impact(impact_graph_id: str, request: Request):
    """Run remediation; absent adapters remain visibly blocked."""
    _require_operator(request)
    from shared.rights_authority.remediation import execute_impact

    result = await execute_impact(impact_graph_id)
    return APIResponse(data=result).to_dict()
