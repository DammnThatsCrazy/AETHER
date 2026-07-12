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

# In-memory session store (stateless; production would use Redis with TTL)
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

    Creates an immutable audit record. All subsequent graph queries with the
    returned session_id are recorded as operator-scoped. Access is revoked by
    calling DELETE on this endpoint.

    Requires: kyber:operator permission (is_platform_admin).
    """
    _require_kyber_operator(request)

    operator_id = getattr(request.state.tenant, "tenant_id", "unknown")
    session_id = str(uuid.uuid4())
    entered_at = _utc_now()

    expires_dt = datetime.now(tz=timezone.utc) + timedelta(minutes=body.duration_minutes)
    expires_at = expires_dt.isoformat().replace("+00:00", "Z")

    session = {
        "session_id": session_id,
        "operator_id": operator_id,
        "tenant_id": body.tenant_id,
        "purpose": body.purpose,
        "access_reason": body.access_reason,
        "entered_at": entered_at,
        "expires_at": expires_at,
        "duration_minutes": body.duration_minutes,
        "active": True,
    }
    _active_sessions[session_id] = session

    logger.info(
        "kyber_operator_tenant_entry",
        extra={
            "session_id": session_id,
            "operator_id": operator_id,
            "tenant_id": body.tenant_id,
            "purpose": body.purpose,
        },
    )

    return APIResponse(
        data={
            "session_id": session_id,
            "tenant_id": body.tenant_id,
            "purpose": body.purpose,
            "entered_at": entered_at,
            "expires_at": expires_at,
            "message": f"Entering tenant {body.tenant_id} as operator — all actions audited",
        }
    ).to_dict()


@router.delete("/operator/tenant-entry")
async def exit_tenant(session_id: str, request: Request) -> dict:
    """Revoke an active operator tenant-entry session and record exit event."""
    _require_kyber_operator(request)

    session = _active_sessions.get(session_id)
    if not session:
        return APIResponse(data={"status": "already_expired"}).to_dict()

    # Idempotent exit: already-exited sessions (concurrent or duplicate calls) return early
    # so we never overwrite the original exited_at audit timestamp.
    if session.get("exited_at") or not session.get("active"):
        return APIResponse(data={"status": "already_expired", "session_id": session_id}).to_dict()

    # Enforce expiry — treat expired sessions as already exited
    expires_at_str = session.get("expires_at")
    if expires_at_str:
        try:
            exp = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            if datetime.now(tz=timezone.utc) >= exp:
                session["active"] = False
                return APIResponse(data={"status": "already_expired", "session_id": session_id}).to_dict()
        except (ValueError, TypeError):
            pass

    session["active"] = False
    session["exited_at"] = _utc_now()
    operator_id = getattr(request.state.tenant, "tenant_id", "unknown")

    logger.info(
        "kyber_operator_tenant_exit",
        extra={
            "session_id": session_id,
            "operator_id": operator_id,
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
    all_verts = await graph.get_all_vertices(limit=10000)
    tenant_verts = [v for v in all_verts if v.properties.get("tenantId") == tenant_id]
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
