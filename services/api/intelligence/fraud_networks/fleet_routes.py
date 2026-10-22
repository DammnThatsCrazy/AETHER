"""Fleet hypothesis routes: build from the spawn tree, read, and human review."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics

from .fleet_hypothesis import (
    FleetHypothesisRepository, ReviewError, apply_review, build_fleet_hypothesis,
    observations_from_rows,
)

logger = get_logger("aether.service.fraud_networks.fleet")
router = APIRouter(prefix="/v1/fraud/fleet-hypotheses", tags=["Fraud Fleet Hypotheses"])
_repo = FleetHypothesisRepository()


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    root_agent_ref: str = Field(..., min_length=1, max_length=256)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    decision: Literal["confirm", "reject"]
    reason: str = Field(..., min_length=10, max_length=1000)


def _require(request: Request, tenant_id: str, permission: str) -> None:
    if not settings.fraud_intelligence.fraud_networks_enabled:
        raise NotFoundError("Fraud Networks feature is not enabled")
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


async def _risk_flagged(tenant_id: str, refs: list[str]) -> set[str]:
    """Agents with any Risk360 signal. Best effort: failures mean 'not flagged'."""
    flagged: set[str] = set()
    try:
        from actions.agent.agent360_provider import RepositoryAgent360Source

        source = RepositoryAgent360Source()
        for ref in refs[:100]:
            if await source.risk_signals(tenant_id, ref, 1):
                flagged.add(ref)
    except Exception as exc:
        logger.warning(
            "fleet_hypothesis.risk_lookup_failed",
            extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
        )
    return flagged


async def _principals(tenant_id: str, root_agent_ref: str) -> list[str]:
    """Grantors of active, non-spawn delegations to the orchestrator."""
    from repositories.repos import DelegationRepository

    active = await DelegationRepository().active_for(root_agent_ref, tenant_id)
    return sorted({
        d["grantor_entity_id"] for d in active
        if d.get("grantor_entity_id")
        and (d.get("metadata") or {}).get("source") != "agent_subagent_spawned"
        and (d.get("scope") or {}).get("type") != "subagent"
    })


@router.post("/build", response_model=None)
async def build(body: BuildRequest, request: Request) -> dict:
    _require(request, body.tenant_id, "fraud:evaluate")
    from actions.agent.lineage import (
        MAX_NODES, SPAWN_EVENT, agent_refs_in_tree, build_lineage_tree,
    )
    from dependencies.providers import get_cache
    from repositories.repos import AnalyticsRepository

    analytics = AnalyticsRepository(get_cache())
    spawn_rows = await analytics.query_silver(
        "silver_agent_execution_facts",
        {"tenant_id": body.tenant_id, "event_name": SPAWN_EVENT},
        limit=1000,
    )
    lineage = build_lineage_tree(
        tenant_id=body.tenant_id, root_agent_ref=body.root_agent_ref, spawn_rows=spawn_rows
    )
    refs = agent_refs_in_tree(lineage["tree"])[:MAX_NODES]
    rows: list[dict] = []
    for ref in refs:
        rows.extend(await analytics.query_silver(
            "silver_agent_execution_facts",
            {"tenant_id": body.tenant_id, "agent_id": ref},
            limit=200,
        ))
    observations = observations_from_rows(rows + spawn_rows, body.tenant_id, refs)
    hypothesis = build_fleet_hypothesis(
        tenant_id=body.tenant_id,
        root_agent_ref=body.root_agent_ref,
        member_refs=refs,
        observations=observations,
        principal_entity_ids=await _principals(body.tenant_id, body.root_agent_ref),
        risk_flagged_refs=await _risk_flagged(body.tenant_id, refs),
        source_event_refs=[
            str(r["source_event_id"]) for r in spawn_rows
            if r.get("source_event_id") and r.get("root_agent_ref") in (None, body.root_agent_ref)
        ][:25],
    )
    if hypothesis is None:
        return {"data": {"status": "insufficient_fleet", "root_agent_ref": body.root_agent_ref}}
    saved = await _repo.save(hypothesis)
    metrics.increment("fleet_hypothesis_built_total", labels={"status": saved["status"]})
    return {"data": saved}


@router.get("", response_model=None)
async def list_hypotheses(request: Request, tenant_id: str, limit: int = 50) -> dict:
    _require(request, tenant_id, "fraud:read")
    items = await _repo.list_for_tenant(tenant_id, limit=max(1, min(limit, 200)))
    return {"data": {"items": items, "count": len(items)}}


@router.get("/{hypothesis_id:path}", response_model=None)
async def get_hypothesis(hypothesis_id: str, request: Request, tenant_id: str) -> dict:
    _require(request, tenant_id, "fraud:read")
    row = await _repo.get(tenant_id, hypothesis_id)
    if row is None:
        raise NotFoundError("fleet hypothesis")
    return {"data": row}


@router.post("/{hypothesis_id:path}/review", response_model=None)
async def review(hypothesis_id: str, body: ReviewRequest, request: Request) -> dict:
    _require(request, body.tenant_id, "fraud:evaluate")
    row = await _repo.get(body.tenant_id, hypothesis_id)
    if row is None:
        raise NotFoundError("fleet hypothesis")
    tenant = request.state.tenant
    reviewer = getattr(tenant, "user_id", None) or ""
    try:
        updated = apply_review(
            row, reviewer_id=reviewer, decision=body.decision, reason=body.reason
        )
    except ReviewError as exc:
        raise BadRequestError(str(exc))
    saved = await _repo.insert_tenant_scoped(updated["hypothesis_id"], updated, body.tenant_id)
    metrics.increment("fleet_hypothesis_reviewed_total", labels={"decision": body.decision})
    return {"data": saved}
