"""
Aether Service — Durable Operator Briefings

Backend/Kyber-facing durable briefings for one-person operation. The Agent
Layer's in-memory ``BriefingStore`` (Agent Layer/agent_controller/runtime/
briefing.py) remains the controller-side scratchpad; THIS module is the
hosted, tenant-scoped record built over ``get_store("agent_briefings")``
(migration 20260712_ops_runtime) so briefs survive restarts and are readable
from Kyber.

A briefing summarizes what one operator needs right now: objectives by
status, stuck runs, pending review batches, staged mutation posture, the
kill switch, and recent compressed alerts.

Mount (main.py, inside the agent-layer block):
    from services.agent.briefings import briefings_router
    app.include_router(briefings_router)
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.store import get_store
from services.agent import ops_alerts
from services.agent.runtime_repository import (
    OBJECTIVE_STATUSES,
    _age_seconds,
    get_agent_runtime_repository,
    new_id,
    utc_now,
)

logger = get_logger("aether.service.agent.briefings")

BRIEFING_TYPES = {"run_complete", "alert", "handoff", "daily"}
BRIEFING_RETENTION_DAYS = int(os.getenv("AGENT_BRIEFING_RETENTION_DAYS", "30"))

_briefings = get_store("agent_briefings")


async def generate_briefing(
    tenant_id: str,
    briefing_type: str = "daily",
    actor_id: str = "operator",
    request_id: str = "",
) -> dict[str, Any]:
    """Build a briefing from live durable state and persist it."""
    if briefing_type not in BRIEFING_TYPES:
        raise BadRequestError(
            f"Invalid briefing type: {briefing_type}. Valid: {sorted(BRIEFING_TYPES)}"
        )
    repo = get_agent_runtime_repository()

    objectives_by_status = {
        status: await repo.count_objectives(tenant_id, status=status)
        for status in sorted(OBJECTIVE_STATUSES)
    }
    run_counts = await repo.run_counts(tenant_id)
    stuck_runs = await repo.list_stuck_runs(tenant_id)
    pending_batches = await repo.count_review_batches(tenant_id, status="pending")
    mutation_counts = {
        status: await repo.staged_mutations.count(tenant_id=tenant_id, status=status)
        for status in ("staged", "approved", "committed", "quarantined", "rejected", "rolled_back", "failed_commit")
    }
    kill_switch = await repo.get_kill_switch(tenant_id)
    recent_alerts = await ops_alerts.list_alerts(tenant_id, status="open", limit=10)

    attention: list[str] = []
    if kill_switch.get("enabled"):
        attention.append("Kill switch is ENGAGED — all dispatch is blocked")
    if stuck_runs:
        attention.append(f"{len(stuck_runs)} stuck run(s) need recovery/replay")
    if pending_batches:
        attention.append(f"{pending_batches} review batch(es) awaiting your approval")
    if mutation_counts.get("quarantined"):
        attention.append(f"{mutation_counts['quarantined']} quarantined mutation(s) to triage")
    if run_counts.get("failed"):
        attention.append(f"{run_counts['failed']} failed run(s)")
    p0_p1 = [a for a in recent_alerts if a.get("severity") in ("P0", "P1")]
    if p0_p1:
        attention.append(f"{len(p0_p1)} open P0/P1 alert(s)")

    now = utc_now()
    briefing = {
        "briefing_id": new_id("brief"),
        "tenant_id": tenant_id,
        "type": briefing_type,
        "status": "generated",
        "generated_by": actor_id,
        "request_id": request_id,
        "summary": "; ".join(attention) if attention else "All clear — no items need attention",
        "sections": {
            "objectives": objectives_by_status,
            "runs": run_counts,
            "stuck_runs": [
                {
                    "run_id": r.get("run_id"),
                    "objective_id": r.get("objective_id"),
                    "controller": r.get("controller"),
                    "status": r.get("status"),
                    "heartbeat_at": r.get("heartbeat_at"),
                }
                for r in stuck_runs[:20]
            ],
            "review": {"pending_batches": pending_batches},
            "staged_mutations": mutation_counts,
            "kill_switch": {"enabled": bool(kill_switch.get("enabled")), "reason": kill_switch.get("reason", "")},
            "alerts": [
                {
                    "alert_id": a.get("alert_id"),
                    "severity": a.get("severity"),
                    "kind": a.get("kind"),
                    "count": a.get("count", 1),
                    "last_seen_at": a.get("last_seen_at"),
                }
                for a in recent_alerts
            ],
            "attention": attention,
        },
        "created_at": now,
        "updated_at": now,
    }
    await _briefings.set(briefing["briefing_id"], briefing)
    metrics.increment("agent_briefings_generated", labels={"type": briefing_type})
    logger.info(
        "Briefing generated: tenant=%s type=%s attention_items=%d request_id=%s",
        tenant_id, briefing_type, len(attention), request_id,
    )
    return briefing


async def list_briefings(
    tenant_id: str,
    briefing_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = {"tenant_id": tenant_id}
    if briefing_type:
        filters["type"] = briefing_type
    rows = await _briefings.find(**filters)
    rows.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return rows[:limit]


async def get_briefing(tenant_id: str, briefing_id: str) -> dict[str, Any] | None:
    briefing = await _briefings.get(briefing_id)
    if not briefing or briefing.get("tenant_id") != tenant_id:
        return None
    return briefing


async def prune_briefings(tenant_id: str, keep_days: int = BRIEFING_RETENTION_DAYS) -> int:
    """Retention: drop briefings older than keep_days (they are snapshots,
    not audit records — the timeline events they summarize are kept)."""
    cutoff_seconds = max(0, keep_days) * 86400
    pruned = 0
    for briefing in await _briefings.find(tenant_id=tenant_id):
        if _age_seconds(briefing.get("created_at")) > cutoff_seconds:
            await _briefings.delete(briefing["briefing_id"])
            pruned += 1
    return pruned


# ── Routes ────────────────────────────────────────────────────────────────

briefings_router = APIRouter(prefix="/v1/agent/briefings", tags=["Agent Briefings"])


def _require_briefings_enabled() -> None:
    flags = settings.one_person_ops
    if not (flags.one_person_ops_enabled or flags.command_center_enabled):
        raise BadRequestError("One-person ops is not enabled")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


def _envelope(data: Any, request: Request) -> dict[str, Any]:
    return {
        "data": data,
        "status": "success",
        "timestamp": utc_now(),
        "meta": {"request_id": _request_id(request)},
    }


class BriefingRequest(BaseModel):
    briefing_type: str = Field(default="daily", pattern="^(run_complete|alert|handoff|daily)$")


@briefings_router.get("")
async def get_briefings(request: Request, briefing_type: str | None = None, limit: int = 50):
    _require_briefings_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    if briefing_type and briefing_type not in BRIEFING_TYPES:
        raise BadRequestError(f"Invalid briefing type: {briefing_type}")
    rows = await list_briefings(tenant.tenant_id, briefing_type=briefing_type, limit=limit)
    return _envelope({"briefings": rows, "total": len(rows)}, request)


@briefings_router.get("/{briefing_id}")
async def get_briefing_detail(briefing_id: str, request: Request):
    _require_briefings_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    briefing = await get_briefing(tenant.tenant_id, briefing_id)
    if briefing is None:
        raise NotFoundError("Briefing")
    return _envelope(briefing, request)


@briefings_router.post("/generate")
async def generate_briefing_route(body: BriefingRequest, request: Request):
    _require_briefings_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    actor = getattr(tenant, "user_id", None) or tenant.tenant_id
    briefing = await generate_briefing(
        tenant.tenant_id, briefing_type=body.briefing_type,
        actor_id=actor, request_id=_request_id(request),
    )
    return _envelope(briefing, request)
