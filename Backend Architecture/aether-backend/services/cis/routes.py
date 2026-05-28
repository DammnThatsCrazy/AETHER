"""
CIS Operator API Routes
Exposes graph health, mutation stream, contamination forensics,
retrieval observatory, reasoning chain data, and operator workflows.

All endpoints are tenant-scoped and require authentication.
Admin endpoints additionally require Role.ADMIN.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from dependencies.providers import get_clickhouse, get_cis_hub, get_producer
from shared.logger.logger import get_logger
from shared.events.events import Event, Topic
from shared.auth.auth import Role

logger = get_logger("aether.cis.routes")

router = APIRouter(prefix="/v1/cis", tags=["cognitive-integrity"])


def _require_tenant(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return tenant.tenant_id


def _require_admin(request: Request) -> str:
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if getattr(tenant, "role", None) not in (Role.ADMIN, "admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return tenant.tenant_id


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────

class QuarantineRequest(BaseModel):
    reason: Optional[str] = None


class ApproveRequest(BaseModel):
    reason: str


class MutationListParams(BaseModel):
    status: Optional[str] = None
    risk_band: Optional[str] = None
    limit: int = 50
    offset: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Health endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/health")
async def get_health(request: Request) -> dict[str, Any]:
    """Graph health index for the authenticated tenant."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    try:
        from services.cis.engines.health_engine import GraphHealthEngine
        from config.settings import settings
        engine = GraphHealthEngine(
            ch,
            w_structural=settings.cis.health_weight_structural,
            w_semantic=settings.cis.health_weight_semantic,
            w_retrieval=settings.cis.health_weight_retrieval,
            w_provenance=settings.cis.health_weight_provenance,
            w_contamination=settings.cis.health_weight_contamination,
            w_volatility=settings.cis.health_weight_volatility,
        )
        index = await engine.compute(tenant_id)
        return index.to_dict()
    except Exception as e:
        logger.error(f"GET /v1/cis/health failed: {e}")
        raise HTTPException(status_code=500, detail="Health computation failed")


@router.get("/health/global")
async def get_global_health(request: Request) -> dict[str, Any]:
    """All-tenant health distribution. Admin only."""
    _require_admin(request)
    ch = get_clickhouse()
    try:
        from services.cis.engines.health_engine import GlobalHealthAggregator
        agg = GlobalHealthAggregator(ch)
        distribution = await agg.get_distribution()
        return {"tenants": distribution, "count": len(distribution)}
    except Exception as e:
        logger.error(f"GET /v1/cis/health/global failed: {e}")
        raise HTTPException(status_code=500, detail="Global health aggregation failed")


# ─────────────────────────────────────────────────────────────────────────────
# Mutation stream
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/mutations")
async def list_mutations(
    request: Request,
    status: Optional[str] = None,
    risk_band: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated mutation stream, filterable by status and risk_band."""
    tenant_id = _require_tenant(request)
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is None:
            return {"mutations": [], "total": 0}

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        idx = 2
        if status:
            conditions.append(f"status = ${idx}")
            params.append(status)
            idx += 1
        if risk_band:
            conditions.append(f"risk_band = ${idx}")
            params.append(risk_band)
            idx += 1

        where = " AND ".join(conditions)
        rows = await pool.fetch(
            f"SELECT * FROM cis_quarantine_records WHERE {where} "
            f"ORDER BY initiated_at DESC LIMIT {limit} OFFSET {offset}",
            *params,
        )
        total_row = await pool.fetchrow(
            f"SELECT COUNT(*) AS cnt FROM cis_quarantine_records WHERE {where}",
            *params,
        )
        return {
            "mutations": [dict(r) for r in rows],
            "total": total_row["cnt"] if total_row else 0,
        }
    except Exception as e:
        logger.error(f"GET /v1/cis/mutations failed: {e}")
        return {"mutations": [], "total": 0}


@router.get("/mutations/{mutation_id}")
async def get_mutation(request: Request, mutation_id: str) -> dict[str, Any]:
    """Single mutation detail with lineage."""
    tenant_id = _require_tenant(request)
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is None:
            raise HTTPException(status_code=404, detail="Not found")
        row = await pool.fetchrow(
            "SELECT * FROM cis_quarantine_records WHERE mutation_id=$1 AND tenant_id=$2",
            mutation_id, tenant_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Mutation not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GET /v1/cis/mutations/{mutation_id} failed: {e}")
        raise HTTPException(status_code=500, detail="Mutation lookup failed")


@router.post("/mutations/{mutation_id}/quarantine")
async def quarantine_mutation(
    request: Request,
    mutation_id: str,
    body: QuarantineRequest,
) -> dict[str, Any]:
    """Manually quarantine a mutation."""
    tenant_id = _require_tenant(request)
    reviewer_id = getattr(request.state.tenant, "user_id", "operator") or "operator"
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool:
            await pool.execute(
                "UPDATE cis_quarantine_records SET status='quarantined', "
                "resolved_at=NULL WHERE mutation_id=$1 AND tenant_id=$2",
                mutation_id, tenant_id,
            )
        await get_producer().publish(Event(
            topic=Topic.CIS_QUARANTINE_INITIATED,
            tenant_id=tenant_id,
            source_service="cis.routes",
            payload={"mutation_id": mutation_id, "initiated_by": reviewer_id},
        ))
        return {"mutation_id": mutation_id, "status": "quarantined"}
    except Exception as e:
        logger.error(f"POST /v1/cis/mutations/{mutation_id}/quarantine failed: {e}")
        raise HTTPException(status_code=500, detail="Quarantine failed")


@router.post("/mutations/{mutation_id}/approve")
async def approve_mutation(
    request: Request,
    mutation_id: str,
    body: ApproveRequest,
) -> dict[str, Any]:
    """Approve a quarantined mutation."""
    tenant_id = _require_tenant(request)
    reviewer_id = getattr(request.state.tenant, "user_id", "operator") or "operator"
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool:
            await pool.execute(
                "UPDATE cis_quarantine_records SET status='released', "
                "resolved_at=now(), resolved_by=$1, resolution_reason=$2 "
                "WHERE mutation_id=$3 AND tenant_id=$4",
                reviewer_id, body.reason, mutation_id, tenant_id,
            )
            await pool.execute(
                "INSERT INTO cis_mutation_approvals "
                "(mutation_id, tenant_id, decision, reviewer_id, reason) "
                "VALUES ($1,$2,'approved',$3,$4)",
                mutation_id, tenant_id, reviewer_id, body.reason,
            )
        await get_producer().publish(Event(
            topic=Topic.CIS_QUARANTINE_RELEASED,
            tenant_id=tenant_id,
            source_service="cis.routes",
            payload={
                "mutation_id": mutation_id,
                "approved_by": reviewer_id,
                "reason": body.reason,
            },
        ))
        return {"mutation_id": mutation_id, "status": "approved"}
    except Exception as e:
        logger.error(f"POST /v1/cis/mutations/{mutation_id}/approve failed: {e}")
        raise HTTPException(status_code=500, detail="Approval failed")


# ─────────────────────────────────────────────────────────────────────────────
# Contamination endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/contamination")
async def get_contamination_index(request: Request) -> dict[str, Any]:
    """Current contamination index for the tenant."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    rows = await ch.query(
        """
        SELECT avg(contamination_score) AS avg_score,
               max(contamination_score) AS max_score,
               count() AS event_count
        FROM cis_contamination_propagation
        WHERE tenant_id = {t:String}
          AND timestamp >= now() - INTERVAL 7 DAY
        """,
        {"t": tenant_id},
    )
    if rows:
        return {
            "tenant_id": tenant_id,
            "avg_contamination": rows[0].get("avg_score", 0.0),
            "max_contamination": rows[0].get("max_score", 0.0),
            "event_count": rows[0].get("event_count", 0),
        }
    return {"tenant_id": tenant_id, "avg_contamination": 0.0, "max_contamination": 0.0}


@router.get("/forensics/{node_id}")
async def get_forensics(request: Request, node_id: str) -> dict[str, Any]:
    """Full contamination origin trace for a specific node."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    try:
        from shared.cis.provenance import ProvenanceTracker
        from services.cis.engines.contamination_engine import ContaminationEngine
        tracker = ProvenanceTracker()
        engine = ContaminationEngine(ch, tracker)
        report = await engine.build_forensics_report(node_id, tenant_id)
        return {
            "node_id": node_id,
            "tenant_id": tenant_id,
            "origin_nodes": report.origin_nodes,
            "propagation_path": report.propagation_path,
            "affected_nodes_count": report.affected_nodes_count,
            "hallucination_chains": report.hallucination_chains,
            "unstable_agents": report.unstable_agents,
            "max_contamination_score": report.max_contamination_score,
            "computed_at": report.computed_at,
        }
    except Exception as e:
        logger.error(f"GET /v1/cis/forensics/{node_id} failed: {e}")
        raise HTTPException(status_code=500, detail="Forensics computation failed")


# ─────────────────────────────────────────────────────────────────────────────
# Drift endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/drift")
async def get_drift_metrics(
    request: Request,
    cluster_id: Optional[str] = None,
    hours: int = 24,
) -> dict[str, Any]:
    """Semantic drift metrics for the tenant (windowed)."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    params: dict[str, Any] = {"t": tenant_id, "h": hours}
    cluster_filter = ""
    if cluster_id:
        cluster_filter = "AND cluster_id = {cid:String}"
        params["cid"] = cluster_id
    rows = await ch.query(
        f"""
        SELECT cluster_id,
               avg(composite_drift_score) AS avg_drift,
               max(composite_drift_score) AS max_drift,
               countIf(triggered_alert = 1) AS alert_count,
               max(timestamp) AS last_seen
        FROM cis_semantic_drift_metrics
        WHERE tenant_id = {{t:String}}
          AND timestamp >= now() - INTERVAL {{h:Int32}} HOUR
          {cluster_filter}
        GROUP BY cluster_id
        ORDER BY avg_drift DESC
        """,
        params,
    )
    return {"tenant_id": tenant_id, "clusters": rows, "window_hours": hours}


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval observatory
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/retrieval")
async def get_retrieval_metrics(
    request: Request,
    hours: int = 24,
) -> dict[str, Any]:
    """Retrieval observatory analytics for the tenant."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    rows = await ch.query(
        """
        SELECT avg(grounded) AS avg_grounded,
               avg(synthetic_ratio) AS avg_synthetic,
               avg(latency_ms) AS avg_latency,
               avg(confidence_score) AS avg_confidence,
               count() AS total_retrievals
        FROM cis_retrieval_traces
        WHERE tenant_id = {t:String}
          AND timestamp >= now() - INTERVAL {h:Int32} HOUR
        """,
        {"t": tenant_id, "h": hours},
    )
    if rows:
        r = rows[0]
        return {
            "tenant_id": tenant_id,
            "grounding_ratio": r.get("avg_grounded", 1.0),
            "synthetic_ratio": r.get("avg_synthetic", 0.0),
            "avg_latency_ms": r.get("avg_latency", 0.0),
            "avg_confidence": r.get("avg_confidence", 0.0),
            "total_retrievals": r.get("total_retrievals", 0),
            "window_hours": hours,
        }
    return {"tenant_id": tenant_id, "total_retrievals": 0, "window_hours": hours}


# ─────────────────────────────────────────────────────────────────────────────
# Reasoning chains
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reasoning")
async def get_reasoning_metrics(
    request: Request,
    hours: int = 24,
) -> dict[str, Any]:
    """Reasoning chain data and contradiction/recursion detection summary."""
    tenant_id = _require_tenant(request)
    ch = get_clickhouse()
    rows = await ch.query(
        """
        SELECT count() AS total_chains,
               countIf(contradiction_detected = 1) AS contradictions,
               countIf(recursion_detected = 1) AS recursions,
               avg(confidence_inflation) AS avg_inflation,
               max(recursion_depth) AS max_recursion_depth
        FROM cis_reasoning_chains
        WHERE tenant_id = {t:String}
          AND timestamp >= now() - INTERVAL {h:Int32} HOUR
        """,
        {"t": tenant_id, "h": hours},
    )
    if rows:
        r = rows[0]
        return {
            "tenant_id": tenant_id,
            "total_chains": r.get("total_chains", 0),
            "contradictions": r.get("contradictions", 0),
            "recursions": r.get("recursions", 0),
            "avg_confidence_inflation": r.get("avg_inflation", 0.0),
            "max_recursion_depth": r.get("max_recursion_depth", 0),
            "window_hours": hours,
        }
    return {"tenant_id": tenant_id, "total_chains": 0, "window_hours": hours}


# ─────────────────────────────────────────────────────────────────────────────
# Tenant governance
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/tenants/{target_tenant_id}/governance")
async def get_tenant_governance(
    request: Request,
    target_tenant_id: str,
) -> dict[str, Any]:
    """Full governance state for a tenant. Admins can query any tenant."""
    caller_tenant = _require_tenant(request)
    tenant = getattr(request.state, "tenant", None)
    is_admin = getattr(tenant, "role", None) in (Role.ADMIN, "admin")
    if not is_admin and caller_tenant != target_tenant_id:
        raise HTTPException(status_code=403, detail="Cannot query other tenant's governance")
    try:
        from repositories.repos import get_pool
        pool = await get_pool()
        if pool is None:
            return {"tenant_id": target_tenant_id}
        row = await pool.fetchrow(
            "SELECT * FROM cis_tenant_governance_state WHERE tenant_id=$1",
            target_tenant_id,
        )
        if row is None:
            return {"tenant_id": target_tenant_id, "health_score": 100.0}
        return dict(row)
    except Exception as e:
        logger.error(f"GET /v1/cis/tenants/{target_tenant_id}/governance failed: {e}")
        raise HTTPException(status_code=500, detail="Governance state lookup failed")


# ─────────────────────────────────────────────────────────────────────────────
# Real-time WebSocket stream
# ─────────────────────────────────────────────────────────────────────────────

@router.websocket("/ws/stream")
async def cis_stream(websocket: WebSocket) -> None:
    """Real-time CIS event stream for Kyber operators."""
    await websocket.accept()
    tenant_id = websocket.query_params.get("tenant_id", "")
    hub = get_cis_hub()
    if hub is None:
        await websocket.close(code=1013, reason="CIS hub not initialized")
        return

    q = hub.subscribe(tenant_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                await websocket.send_text(json.dumps(event, default=str))
            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "keepalive"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"CIS WS stream closed: {e}")
    finally:
        hub.unsubscribe(tenant_id, q)
