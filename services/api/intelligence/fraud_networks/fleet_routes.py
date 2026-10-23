"""Fleet hypothesis routes: build from the spawn tree, read, and human review."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics

from .fleet_hypothesis import (
    FleetHypothesisRepository, ReviewError, build_fleet_hypothesis, observations_from_rows,
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


async def _project_to_fraud360(saved: dict) -> dict:
    """Mirror the fleet hypothesis into Fraud360 (flag-gated, failure-isolated)."""
    if not settings.risk_fraud_360.fraud360_enabled:
        return {"status": "disabled"}
    try:
        from .fleet_fraud360 import project_fleet_hypothesis

        return await project_fleet_hypothesis(saved)
    except Exception as exc:  # noqa: BLE001 — never let the projection fail the write
        logger.warning(
            "fleet_hypothesis.fraud360_projection_failed",
            extra={"tenant_id": saved.get("tenant_id"), "error_type": type(exc).__name__},
        )
        return {"status": "failed"}


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


async def _human_principals(tenant_id: str, entity_ids: set[str]) -> list[str]:
    """Keep only grantors the canonical identity authority resolves to a human.

    ``DelegationRepository`` models generic entity-to-entity grants, so a
    grantor may be another agent, an organization or an arbitrary id. Only an
    active canonical subject of type ``human`` (after following merge
    tombstones) may lift a hypothesis to a person link, and it is recorded
    under its surviving canonical id. Anything the authority cannot resolve,
    or cannot be asked, is excluded: no person is better than a guessed one.
    """
    from identity.identity.models import EntityType, SubjectStatus
    from identity.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    humans: set[str] = set()
    for entity_id in sorted(entity_ids)[:100]:
        try:
            surviving = await repo.resolve_surviving_canonical_entity_id(tenant_id, entity_id)
            subject = await repo.get_subject_by_canonical_entity_id(tenant_id, surviving)
        except Exception as exc:
            logger.warning(
                "fleet_hypothesis.principal_lookup_failed",
                extra={"tenant_id": tenant_id, "error_type": type(exc).__name__},
            )
            continue
        if (
            subject
            and subject.get("entity_type") == EntityType.HUMAN.value
            and subject.get("status") == SubjectStatus.ACTIVE.value
        ):
            humans.add(surviving)  # the live identity, not a merged-away alias of it
    return sorted(humans)


async def _principals(tenant_id: str, root_agent_ref: str) -> list[str]:
    """Human grantors of active, non-spawn delegations to the orchestrator."""
    from repositories.repos import DelegationRepository

    active = await DelegationRepository().active_for(root_agent_ref, tenant_id)
    grantors = {
        d["grantor_entity_id"] for d in active
        if d.get("grantor_entity_id")
        and (d.get("metadata") or {}).get("source") != "agent_subagent_spawned"
        and (d.get("scope") or {}).get("type") != "subagent"
    }
    return await _human_principals(tenant_id, grantors)


@router.post("/build", response_model=None)
async def build(body: BuildRequest, request: Request) -> dict:
    _require(request, body.tenant_id, "fraud:evaluate")
    from actions.agent.lineage import (
        MAX_NODES, agent_refs_in_tree, edge_event_refs, read_lineage_facts,
    )
    from dependencies.providers import get_cache
    from repositories.repos import AnalyticsRepository

    analytics = AnalyticsRepository(get_cache())
    facts = await read_lineage_facts(
        analytics, tenant_id=body.tenant_id, root_agent_ref=body.root_agent_ref
    )
    lineage = facts["shape"]
    refs = agent_refs_in_tree(lineage["tree"])[:MAX_NODES]
    rows = [row for ref in refs for row in facts["activity"].get(ref, [])]
    observations = observations_from_rows(rows + facts["spawn_rows"], body.tenant_id, refs)
    hypothesis = build_fleet_hypothesis(
        tenant_id=body.tenant_id,
        root_agent_ref=body.root_agent_ref,
        member_refs=refs,
        observations=observations,
        principal_entity_ids=await _principals(body.tenant_id, body.root_agent_ref),
        risk_flagged_refs=await _risk_flagged(body.tenant_id, refs),
        source_event_refs=edge_event_refs(lineage["tree"]),
        source_truncation=lineage["source_truncation"],
    )
    if hypothesis is None:
        return {"data": {"status": "insufficient_fleet", "root_agent_ref": body.root_agent_ref}}
    saved = await _repo.save(hypothesis)
    metrics.increment("fleet_hypothesis_built_total", labels={"status": saved["status"]})
    return {"data": saved, "fraud360": await _project_to_fraud360(saved)}


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
    tenant = request.state.tenant
    reviewer = getattr(tenant, "user_id", None) or ""
    try:
        saved = await _repo.review(
            body.tenant_id, hypothesis_id,
            reviewer_id=reviewer, decision=body.decision, reason=body.reason,
        )
    except ReviewError as exc:
        raise BadRequestError(str(exc))
    if saved is None:
        raise NotFoundError("fleet hypothesis")
    metrics.increment("fleet_hypothesis_reviewed_total", labels={"decision": body.decision})
    return {"data": saved, "fraud360": await _project_to_fraud360(saved)}
