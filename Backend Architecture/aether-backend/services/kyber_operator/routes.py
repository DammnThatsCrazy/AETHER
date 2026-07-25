"""Kyber Operator — privileged tenant access and fleet operational envelope.

Routes:
    POST   /v1/kyber/operator/tenant-entry          Request privileged tenant access
    DELETE /v1/kyber/operator/tenant-entry          Exit tenant access session
    GET    /v1/kyber/tenants/{tenant_id}/operational-envelope  Tenant health summary
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field

from dependencies.providers import get_graph
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

logger = get_logger("aether.service.kyber_operator")

router = APIRouter(prefix="/v1/kyber", tags=["Kyber Operator"])

# Retained only so an in-flight session_id issued before this deployment still
# resolves on exit. New entries are NEVER written here — they go to the durable
# kyber_access_scopes table via access_scope_service. The previous behaviour
# (this dict as the only store) meant a scope vanished on restart, was invisible
# to every other replica, and was read by nothing, so the "all subsequent
# queries are operator-scoped" guarantee below was never actually enforced.
_active_sessions: dict[str, dict] = {}

ACCESS_PURPOSES = frozenset({
    "incident_response",
    "customer_support",
    "compliance_audit",
    "security_investigation",
    "data_request",
    "diagnostics",
    "break_glass",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


from services.security.request_context import require_kyber_operator as _canonical_kyber_gate


def _require_kyber_operator(request: Request) -> None:
    """Canonical fail-closed Kyber operator gate.

    Replaces the previous ``is_platform_admin`` check (a field never set on any
    TenantContext, which locked out real operators). Now recognises operators by
    the configured ``kyber:operator`` grant or the operator tenant-id allowlist,
    while still denying every Aether tenant (including ``Role.ADMIN``).
    """
    _canonical_kyber_gate(request)


# ── Models ─────────────────────────────────────────────────────────────────────

class TenantEntryRequest(BaseModel):
    tenant_id: str
    access_reason: str = Field(..., min_length=10, description="Required justification for tenant access")
    purpose: Literal[
        "incident_response", "customer_support", "compliance_audit",
        "security_investigation", "data_request", "diagnostics", "break_glass"
    ]
    duration_minutes: int = Field(default=60, ge=1, le=480)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/operator/tenant-entry")
async def enter_tenant(body: TenantEntryRequest, request: Request) -> dict:
    """Request privileged scoped access to a specific tenant's data.

    Compatibility shim over the durable scope plane. The response shape is
    unchanged — the existing Kyber frontend calls this endpoint — but the scope
    is now a row in ``kyber_access_scopes``: session- and device-bound,
    expiring, revocable, audited, and actually consulted by
    ``require_kyber_access`` when a route reaches tenant data.

    Prefer ``POST /v1/kyber/scopes`` for new work.
    """
    context = _require_kyber_operator(request)

    from services.kyber.access.dependencies import current_kyber_context
    from services.kyber.access.scopes import access_scope_service

    kyber_context = current_kyber_context(request)
    if kyber_context is None or not getattr(kyber_context, "session", None):
        # A durable scope is bound to a session and a device. Without a Kyber
        # workforce session there is nothing to bind to, and issuing an
        # unbindable scope id would recreate exactly the non-enforcement this
        # shim exists to remove.
        raise ForbiddenError(
            "a Kyber workforce session is required to enter a tenant; "
            "authenticate through /v1/kyber/auth/login"
        )

    scope = await access_scope_service.open_scope(
        operator_id=kyber_context.operator_id,
        session_id=kyber_context.session.session_id,
        device_id=getattr(kyber_context, "device_id", None),
        environment=getattr(kyber_context, "environment", "unknown"),
        tenant_id=body.tenant_id,
        purpose=body.purpose,
        reason=body.access_reason,
        ttl_minutes=body.duration_minutes,
    )

    logger.info(
        "kyber_operator_tenant_entry",
        extra={
            "session_id": scope.scope_id,
            "operator_id": kyber_context.operator_id,
            "tenant_id": body.tenant_id,
            "purpose": body.purpose,
        },
    )

    return APIResponse(
        data={
            # The legacy field name is preserved for the existing client; it now
            # carries the durable scope id.
            "session_id": scope.scope_id,
            "tenant_id": scope.tenant_id,
            "purpose": scope.purpose,
            "entered_at": scope.entered_at,
            "expires_at": scope.expires_at,
            "message": f"Entering tenant {body.tenant_id} as operator — all actions audited",
        }
    ).to_dict()


@router.delete("/operator/tenant-entry")
async def exit_tenant(session_id: str, request: Request) -> dict:
    """Close an operator tenant scope. Idempotent.

    Resolves the durable scope first. The legacy in-process entry is still
    honoured so a session_id issued before this deployment can still be exited
    cleanly, but nothing new is ever written there.
    """
    context = _require_kyber_operator(request)

    from services.kyber.access.dependencies import current_kyber_context
    from services.kyber.access.scopes import access_scope_service

    kyber_context = current_kyber_context(request)
    actor_id = getattr(kyber_context, "operator_id", None) or getattr(
        request.state.tenant, "tenant_id", "unknown"
    )

    scope = await access_scope_service.get(session_id)
    if scope is not None:
        if scope.status != "active":
            return APIResponse(
                data={"status": "already_expired", "session_id": session_id}
            ).to_dict()
        # An operator may only close their own scope. Without this, any operator
        # could close another's scope mid-investigation.
        if kyber_context is not None and scope.operator_id != actor_id:
            raise ForbiddenError("a tenant scope may only be exited by the operator that opened it")
        await access_scope_service.exit_scope(session_id, actor_id=actor_id)
        return APIResponse(data={"status": "exited", "session_id": session_id}).to_dict()

    # ── Legacy pre-deployment entry ──────────────────────────────────────────
    session = _active_sessions.get(session_id)
    if not session or session.get("exited_at") or not session.get("active"):
        return APIResponse(data={"status": "already_expired", "session_id": session_id}).to_dict()
    session["active"] = False
    session["exited_at"] = _utc_now()
    logger.info(
        "kyber_operator_tenant_exit",
        extra={
            "session_id": session_id,
            "operator_id": actor_id,
            "tenant_id": session.get("tenant_id"),
        },
    )
    return APIResponse(data={"status": "exited", "session_id": session_id}).to_dict()


@router.get("/tenants/{tenant_id}/operational-envelope")
async def tenant_operational_envelope(
    tenant_id: str = Path(..., description="Target tenant ID"),
    request: Request = ...,
    graph: GraphClient = Depends(get_graph),
) -> dict:
    """Return operational health envelope for a specific tenant.

    Aggregates health signals from SDK, connector, graph, measurement, and fraud
    services into a single operational snapshot for Kyber operator dashboards.

    Requires: kyber:operator permission.
    """
    _require_kyber_operator(request)

    # ── Graph health ──────────────────────────────────────────────────────────
    # Scoped to the path tenant: the cap bounds THAT tenant's rows, so an
    # envelope for a tenant sorting past a global page no longer reports zero.
    tenant_verts = await graph.get_vertices_for_tenant(tenant_id, limit=10000)
    graph_node_count = len(tenant_verts)

    # Count edges for the sampled nodes
    edge_count = 0
    for v in tenant_verts[:100]:
        try:
            edges = await graph.get_edges(v.vertex_id, direction="out")
            edge_count += len(edges)
        except Exception:
            pass

    # ── Fraud volume (from fraud_networks) ────────────────────────────────────
    fraud_network_count = 0
    try:
        from repositories.repos import FraudNetworkRepository
        _fraud_repo = FraudNetworkRepository()
        networks = await _fraud_repo.list_by_tenant(tenant_id, limit=200)
        fraud_network_count = len(networks)
    except Exception:
        pass

    # ── SDK health (from sdk_health events) ──────────────────────────────────
    sdk_health_score: Optional[float] = None
    try:
        from services.data_quality.service import intelligence_quality_service
        report = intelligence_quality_service.dimension_report("graph", tenant_id)
        sdk_health_score = float(report.get("quality_score", 0.0))
    except Exception:
        pass

    computed_at = _utc_now()

    return APIResponse(
        data={
            "tenant_id": tenant_id,
            "computed_at": computed_at,
            "graph": {
                "node_count": graph_node_count,
                "edge_count_sample": edge_count,
                "has_data": graph_node_count > 0,
            },
            "fraud": {
                "fraud_network_count": fraud_network_count,
            },
            "sdk": {
                "health_score": sdk_health_score,
            },
            "status": "healthy" if graph_node_count > 0 else "no_data",
        }
    ).to_dict()
