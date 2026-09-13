"""Journey CRUD, version history, steps, transitions, and explain endpoints."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, field_validator

from shared.common.common import APIResponse, NotFoundError
from shared.logger.logger import get_logger
from services.measurement.repositories.activity_repo import ActivityRepository
from services.measurement.repositories.journey_repo import JourneyRepository
from services.measurement.repositories.journey_step_repo import JourneyStepRepository
from services.measurement.engine.journey_compiler import JourneyCompiler
from services.measurement.contracts import ActivityStatus

logger = get_logger("aether.measurement.routes.journeys")
router = APIRouter(prefix="/v1/journeys", tags=["Journeys"])

_journey_repo = JourneyRepository()
_step_repo = JourneyStepRepository()
_activity_repo = ActivityRepository()
_compiler = JourneyCompiler()

_MAX_STEPS_PAGE = 200
_DEFAULT_STEPS_PAGE = 50


def _require_tenant(request: Request):
    tenant = getattr(request.state, "tenant", None)
    if tenant is None:
        from shared.common.common import UnauthorizedError
        raise UnauthorizedError("Authentication required")
    return tenant


def _encode_cursor(journey_version_id: str, step_position: int) -> str:
    raw = json.dumps({"jvid": journey_version_id, "pos": step_position})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_step_cursor(cursor: str) -> Optional[int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        return int(data["pos"])
    except Exception:
        return None


class RebuildRequest(BaseModel):
    trigger_reason: str = "manual"


# ── Journey list and detail ───────────────────────────────────────────────────

@router.get("")
async def list_journeys(
    request: Request,
    profile_id: Optional[str] = Query(None),
    journey_state: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
):
    """List current journey versions for a tenant, optionally filtered by profile."""
    tenant = _require_tenant(request)
    if profile_id:
        journeys = await _journey_repo.find_current_for_profile(tenant.tenant_id, profile_id)
    else:
        journeys = await _journey_repo.list_current(
            tenant.tenant_id,
            journey_state=journey_state,
            limit=limit,
            cursor=cursor,
        )

    next_cursor = journeys[-1].get("computed_at") if len(journeys) == limit else None
    return {
        "data": journeys,
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.get("/{journey_id}")
async def get_journey(journey_id: str, request: Request):
    """Get the current journey version for a journey_id."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")
    return APIResponse(data=journey).to_dict()


@router.get("/{journey_id}/versions")
async def list_journey_versions(journey_id: str, request: Request):
    """List all versions of a journey, newest first."""
    tenant = _require_tenant(request)
    versions = await _journey_repo.list_versions(tenant.tenant_id, journey_id)
    if not versions:
        raise NotFoundError("Journey")
    return APIResponse(data=versions, meta={"version_count": len(versions)}).to_dict()


# ── Journey steps ─────────────────────────────────────────────────────────────

@router.get("/{journey_id}/steps")
async def list_journey_steps(
    journey_id: str,
    request: Request,
    limit: int = Query(_DEFAULT_STEPS_PAGE, ge=1, le=_MAX_STEPS_PAGE),
    cursor: Optional[str] = Query(None, description="Opaque cursor from previous page"),
    family: Optional[str] = Query(None, description="Filter by activity family: web2,web3,campaign,commerce,agent,x402,outcome"),
    status: Optional[str] = Query(None, description="Filter by activity status"),
    session_id: Optional[str] = Query(None),
    wallet_id: Optional[str] = Query(None),
    chain_id: Optional[str] = Query(None),
    campaign_id: Optional[str] = Query(None),
    after: Optional[datetime] = Query(None),
    before: Optional[datetime] = Query(None),
    risk_tier: Optional[str] = Query(None, description="Filter by risk tier: low,medium,high,critical"),
    fraud_disposition: Optional[str] = Query(None, description="Filter by fraud disposition: allow,monitor,review,hold,block"),
):
    """List ordered journey steps for the current journey version.

    Steps are sorted by step_position (chronological order). Use the cursor
    for keyset pagination through long journeys.
    """
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    journey_version_id = str(journey.get("journey_version_id"))
    families = [family] if family else None
    statuses = [status] if status else None
    pos_cursor = _decode_step_cursor(cursor) if cursor else None

    steps = await _step_repo.list_by_version(
        tenant.tenant_id,
        journey_version_id,
        limit=limit,
        cursor=str(pos_cursor) if pos_cursor is not None else None,
        families=families,
        statuses=statuses,
        session_id=session_id,
        wallet_id=wallet_id,
        chain_id=chain_id,
        campaign_id=campaign_id,
        after=after,
        before=before,
    )

    # Apply risk-layer filters in-process (no additional DB query)
    if risk_tier:
        steps = [s for s in steps if s.get("risk_tier") == risk_tier]
    if fraud_disposition:
        steps = [s for s in steps if s.get("fraud_disposition") == fraud_disposition]

    next_cursor = None
    if len(steps) == limit and steps:
        last_pos = steps[-1].get("step_position", 0)
        next_cursor = _encode_cursor(journey_version_id, last_pos)

    return {
        "data": steps,
        "meta": {
            "journey_id": journey_id,
            "journey_version_id": journey_version_id,
            "step_count": journey.get("step_count", 0),
            "compiler_version": journey.get("compiler_version"),
        },
        "pagination": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        },
    }


@router.get("/{journey_id}/steps/{step_id}")
async def get_journey_step(
    journey_id: str,
    step_id: str,
    request: Request,
    include_activity: bool = Query(True, description="Expand the full canonical_activity record"),
):
    """Get a single journey step with optional full activity expansion."""
    tenant = _require_tenant(request)

    # Verify journey ownership before returning step
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    step = await _step_repo.get_step(tenant.tenant_id, step_id)
    if step is None:
        raise NotFoundError("JourneyStep")

    # Verify the step belongs to this tenant's journey
    if str(step.get("journey_id")) != str(journey.get("journey_id")):
        raise NotFoundError("JourneyStep")

    adjacent = await _step_repo.get_adjacent(tenant.tenant_id, step_id)

    activity = None
    if include_activity and step.get("activity_id"):
        acts = await _activity_repo.list_by_profile(
            tenant.tenant_id,
            step.get("profile_id") or "",
            limit=1,
        )
        # Fetch specific activity by ID
        activity = next(
            (a for a in acts if str(a.get("activity_id")) == str(step.get("activity_id"))),
            None,
        )

    return APIResponse(
        data={
            "step": step,
            "adjacent": adjacent,
            "activity": activity,
        },
        meta={"journey_id": journey_id},
    ).to_dict()


# ── Transitions ───────────────────────────────────────────────────────────────

@router.get("/{journey_id}/transitions")
async def get_journey_transitions(journey_id: str, request: Request):
    """Summarize cross-rail transition types in this journey."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    journey_version_id = str(journey.get("journey_version_id"))
    # Load all steps to compute transition summary (bounded by step_count)
    steps = await _step_repo.list_by_version(
        tenant.tenant_id, journey_version_id, limit=_MAX_STEPS_PAGE
    )

    transition_counts: dict[str, int] = {}
    for step in steps:
        t = step.get("transition_type")
        if t:
            transition_counts[t] = transition_counts.get(t, 0) + 1

    family_counts: dict[str, int] = {}
    for step in steps:
        f = step.get("activity_family", "unknown")
        family_counts[f] = family_counts.get(f, 0) + 1

    return APIResponse(
        data={
            "transitions": transition_counts,
            "families": family_counts,
            "total_steps": len(steps),
            "has_web3": bool(journey.get("web3_activity_ids")),
            "has_agent": bool(journey.get("agent_activity_ids")),
            "has_x402": bool(journey.get("x402_activity_ids")),
        },
    ).to_dict()


# ── Explain ───────────────────────────────────────────────────────────────────

@router.get("/{journey_id}/explain")
async def explain_journey(journey_id: str, request: Request):
    """Return identity explanation and data-quality state for this journey."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    steps = await _step_repo.list_by_version(
        tenant.tenant_id,
        str(journey.get("journey_version_id")),
        limit=100,
    )

    # Collect identity methods and confidence distribution
    methods: dict[str, int] = {}
    confidences: list[float] = []
    for step in steps:
        m = step.get("identity_method")
        if m:
            methods[m] = methods.get(m, 0) + 1
        c = step.get("identity_confidence")
        if c is not None:
            confidences.append(float(c))

    avg_confidence = sum(confidences) / len(confidences) if confidences else None
    min_confidence = min(confidences) if confidences else None

    # Data quality state
    step_count = journey.get("step_count", 0)
    quality_status = "complete"
    if step_count == 0:
        quality_status = "empty"
    elif journey.get("compiler_version") != "2.0":
        quality_status = "partial"

    return APIResponse(
        data={
            "journey_id": journey_id,
            "profile_id": journey.get("profile_id"),
            "compiler_version": journey.get("compiler_version"),
            "rebuild_reason": journey.get("rebuild_reason"),
            "computed_at": str(journey.get("computed_at")),
            "step_count": step_count,
            "identity": {
                "methods": methods,
                "avg_confidence": avg_confidence,
                "min_confidence": min_confidence,
            },
            "rails": {
                "web3_steps": len(journey.get("web3_activity_ids") or []),
                "agent_steps": len(journey.get("agent_activity_ids") or []),
                "x402_steps": len(journey.get("x402_activity_ids") or []),
            },
            "data_quality": {
                "status": quality_status,
                "message": None if quality_status == "complete" else
                "Journey compiled with an older compiler version; rebuild for full cross-rail coverage.",
            },
        },
    ).to_dict()


# ── Rebuild ───────────────────────────────────────────────────────────────────

@router.post("/{journey_id}/rebuild")
async def rebuild_journey(journey_id: str, request: Request, body: RebuildRequest):
    """Manually trigger a journey rebuild for a profile."""
    tenant = _require_tenant(request)
    current = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if current is None:
        raise NotFoundError("Journey")

    profile_id = current.get("profile_id") or current.get("cluster_id")
    if not profile_id:
        return APIResponse(data=None, meta={"reason": "no_profile_id"}).to_dict()

    new_version = await _compiler.compile_for_profile(
        tenant.tenant_id, profile_id, trigger_reason=body.trigger_reason
    )
    return APIResponse(data=new_version, meta={"rebuilt": True}).to_dict()


# ---------------------------------------------------------------------------
# Web3 reorg / status-change webhook
# ---------------------------------------------------------------------------

_WEB3_ALLOWED_STATUSES = {
    ActivityStatus.confirmed,
    ActivityStatus.finalized,
    ActivityStatus.reverted,
    ActivityStatus.reorged,
    ActivityStatus.failed,
}


class Web3StatusChangeRequest(BaseModel):
    tx_hash: str
    new_status: ActivityStatus

    @field_validator("new_status")
    @classmethod
    def must_be_web3_status(cls, v: ActivityStatus) -> ActivityStatus:
        if v not in _WEB3_ALLOWED_STATUSES:
            raise ValueError(f"new_status must be one of {[s.value for s in _WEB3_ALLOWED_STATUSES]}")
        return v


web3_router = APIRouter(prefix="/v1/web3", tags=["Journeys"])


@web3_router.post("/status-change")
async def web3_status_change(request: Request, body: Web3StatusChangeRequest):
    """Receive a Web3 transaction status update from the chain indexer.

    Updates canonical_activity rows and triggers journey rebuilds for all
    profiles that have a step referencing this transaction.
    """
    tenant = _require_tenant(request)
    tenant.require_permission("write")
    affected = await _compiler.rebuild_affected_by_web3_status_change(
        tenant.tenant_id, body.tx_hash, body.new_status
    )
    return APIResponse(
        data=None,
        meta={"tx_hash": body.tx_hash, "new_status": body.new_status, "profiles_rebuilt": affected},
    ).to_dict()


# ── Journey risk endpoints ─────────────────────────────────────────────────────

from repositories.repos import FraudDecisionRepository as _FraudDecisionRepo

_fraud_decision_repo = _FraudDecisionRepo()


@router.get("/{journey_id}/risk")
async def get_journey_risk(journey_id: str, request: Request):
    """Return a risk summary for the current journey version.

    Aggregates risk_score, risk_tier, fraud_disposition, and fraud signal coverage
    across all journey steps.  Uses batched repository queries — no per-step calls.
    """
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    journey_version_id = str(journey.get("journey_version_id"))
    steps = await _step_repo.list_by_version(
        tenant.tenant_id,
        journey_version_id,
        limit=_MAX_STEPS_PAGE,
    )

    evaluated_steps = [s for s in steps if s.get("risk_evaluation_state") == "evaluated"]
    scores = [s["risk_score"] for s in evaluated_steps if s.get("risk_score") is not None]
    max_score = max(scores, default=None)
    avg_score = round(sum(scores) / len(scores), 2) if scores else None

    all_signals: set[str] = set()
    all_network_ids: set[str] = set()
    all_dispositions: set[str] = set()
    decision_ids: set[str] = set()

    for s in evaluated_steps:
        for sig in (s.get("fraud_signal_types") or []):
            all_signals.add(sig)
        for nid in (s.get("fraud_network_ids") or []):
            all_network_ids.add(nid)
        if s.get("fraud_disposition"):
            all_dispositions.add(s["fraud_disposition"])
        if s.get("fraud_decision_id"):
            decision_ids.add(s["fraud_decision_id"])

    from services.fraud.models import risk_tier_from_score

    return APIResponse(data={
        "journey_id": journey_id,
        "journey_version_id": journey_version_id,
        "step_count": len(steps),
        "evaluated_step_count": len(evaluated_steps),
        "coverage_pct": round(len(evaluated_steps) / max(len(steps), 1) * 100, 1),
        "max_risk_score": max_score,
        "avg_risk_score": avg_score,
        "risk_tier": risk_tier_from_score(max_score) if max_score is not None else None,
        "signal_types": sorted(all_signals),
        "fraud_network_ids": sorted(all_network_ids),
        "dispositions": sorted(all_dispositions),
        "fraud_decision_ids": sorted(decision_ids),
        "evaluation_state": "evaluated" if evaluated_steps else "not_evaluated",
        "evaluated_at": max(
            (s.get("risk_evaluated_at", "") for s in evaluated_steps),
            default=None,
        ) or None,
    }).to_dict()


@router.get("/{journey_id}/fraud-decisions")
async def list_journey_fraud_decisions(
    journey_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """List all fraud decisions linked to a journey, newest first."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    decisions = await _fraud_decision_repo.list_for_journey(
        tenant.tenant_id, journey_id, limit=limit
    )
    return APIResponse(data=decisions, meta={"count": len(decisions)}).to_dict()


@router.get("/{journey_id}/fraud-networks")
async def list_journey_fraud_networks(journey_id: str, request: Request):
    """List fraud network IDs referenced in this journey's fraud decisions."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    decisions = await _fraud_decision_repo.list_for_journey(
        tenant.tenant_id, journey_id, limit=200
    )
    network_ids: set[str] = set()
    for d in decisions:
        for nid in (d.get("fraud_network_ids") or []):
            network_ids.add(nid)

    return APIResponse(data=sorted(network_ids), meta={"count": len(network_ids)}).to_dict()


@router.get("/{journey_id}/risk-explain")
async def explain_journey_risk(journey_id: str, request: Request):
    """Return the most recent fraud decision explanation for this journey."""
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    decisions = await _fraud_decision_repo.list_for_journey(
        tenant.tenant_id, journey_id, limit=1
    )
    if not decisions:
        return APIResponse(data={
            "journey_id": journey_id,
            "evaluation_state": "not_evaluated",
            "explanation": None,
        }).to_dict()

    latest = decisions[0]
    return APIResponse(data={
        "journey_id": journey_id,
        "decision_id": latest.get("decision_id"),
        "decision": latest.get("decision"),
        "risk_score": latest.get("risk_score"),
        "risk_tier": latest.get("risk_tier"),
        "signal_types": latest.get("signal_types", []),
        "reason_codes": latest.get("reason_codes", []),
        "machine_explanation": latest.get("machine_explanation"),
        "human_explanation": latest.get("human_explanation"),
        "evaluation_state": latest.get("evaluation_state"),
        "evaluated_at": latest.get("evaluated_at"),
        "policy_version": latest.get("policy_version"),
        "detector_versions": latest.get("detector_versions", {}),
    }).to_dict()


@router.post("/{journey_id}/risk/recalculate")
async def recalculate_journey_risk(journey_id: str, request: Request):
    """Trigger a forced fraud re-evaluation for this journey.

    Evaluates the journey's primary subject, persists a new FraudDecision,
    and propagates the risk annotation to all journey steps.
    """
    tenant = _require_tenant(request)
    journey = await _journey_repo.get_current(tenant.tenant_id, journey_id)
    if journey is None:
        raise NotFoundError("Journey")

    from services.fraud.evaluation import FraudEvaluationService
    evaluator = FraudEvaluationService()
    profile_id = journey.get("profile_id") or journey.get("cluster_id")
    if not profile_id:
        return APIResponse(data={"status": "skipped", "reason": "no profile_id on journey"}).to_dict()

    decision = await evaluator.evaluate_subject(
        tenant_id=tenant.tenant_id,
        subject_type="entity",
        subject_id=profile_id,
        profile_id=profile_id,
        journey_id=journey_id,
        journey_version_id=str(journey.get("journey_version_id")),
        force=True,
    )
    return APIResponse(data={
        "journey_id": journey_id,
        "decision_id": decision.decision_id,
        "decision": decision.decision,
        "risk_score": decision.risk_score,
        "risk_tier": decision.risk_tier,
        "signal_types": decision.signal_types,
        "evaluated_at": decision.evaluated_at,
    }).to_dict()
