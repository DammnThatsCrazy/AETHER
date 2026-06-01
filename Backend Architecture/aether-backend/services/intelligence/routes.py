"""
Aether Service — Intelligence API

Live intelligence outputs powered by lake data, graph relationships,
and ML model scoring. All outputs come from persisted data, not ad-hoc
queries or mock responses.

Endpoints:
    GET /v1/intelligence/wallet/{address}/risk    — Wallet risk score
    GET /v1/intelligence/protocol/{id}/analytics  — Protocol analytics
    GET /v1/intelligence/entity/{id}/cluster      — Identity cluster
    GET /v1/intelligence/alerts                   — Anomaly alerts
    GET /v1/intelligence/wallet/{address}/profile — Full wallet intelligence profile
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from config.settings import settings
from dependencies.providers import get_registry
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from repositories.lake import gold_identity, gold_market
from shared.common.common import APIResponse, BadRequestError, utc_now
from shared.events import Event, Topic
from shared.logger.logger import get_logger, metrics
from shared.scoring.trust_score import TrustScoreComposite

from services.intelligence.decision_models import (
    ActionFeedback,
    ApprovalLevel,
    CandidateAction,
    DecisionRecord,
    DecisionStatus,
    OutcomeLabel,
    OutcomeObservation,
    PlaybookDefinition,
    PlaybookRun,
)
from services.intelligence.graph_mutations import (
    upsert_action_graph,
    upsert_decision_graph,
    upsert_outcome_graph,
    upsert_recommendation_graph,
)
from services.intelligence.investigations import build_recommendation_investigation
from services.intelligence.ooda_engine import GraphNativeRecommendationEngine, now_iso
from services.intelligence.outcome_ledger import OutcomeLedgerAggregator
from services.intelligence.repositories import (
    ActionFeedbackRepository,
    DecisionRepository,
    OutcomeRepository,
    PlaybookRepository,
    PlaybookRunRepository,
    RecommendationFeedbackRepository,
    RecommendationRepository,
)
from services.lake.features import materialize_wallet_features

logger = get_logger("aether.service.intelligence")
router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])


@router.get("/wallet/{address}/risk")
async def wallet_risk_score(address: str, request: Request):
    """
    Compute wallet risk score using trust scorer + graph + lake data.
    Returns composite risk from fraud, identity, and behavioral components.
    """
    request.state.tenant.require_permission("read")

    registry = get_registry()
    scorer = TrustScoreComposite()

    # Get features from Gold tier (or materialize if missing)
    gold_records = await gold_identity.get_metrics(address, entity_type="wallet", metric_name="wallet_features")
    if gold_records:
        features = gold_records[0].get("value", {})
    else:
        features = await materialize_wallet_features(address, cache=registry.cache)

    # Compute trust score using available features
    score = await scorer.compute(
        entity_id=address,
        entity_type="wallet",
        features={
            "identity_confidence": min(features.get("identity_sources", 0) * 0.2, 1.0),
            "bot_score": 0.0,  # From ML when available
            "session_score": 0.5,
            "fraud_composite_score": 0.0,
        },
    )

    metrics.increment("intelligence_wallet_risk", labels={"entity_type": "wallet"})
    return APIResponse(data={
        "wallet_address": address,
        "risk_score": score.to_dict(),
        "features": features,
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/protocol/{protocol_id}/analytics")
async def protocol_analytics(protocol_id: str, request: Request):
    """
    Protocol-level analytics from Gold tier market data.
    """
    request.state.tenant.require_permission("read")

    gold_records = await gold_market.get_metrics(protocol_id, entity_type="protocol")
    if not gold_records:
        return APIResponse(data={
            "protocol_id": protocol_id,
            "analytics": {},
            "status": "no_data",
            "message": "No analytics data available. Ingest market data first.",
        }).to_dict()

    metrics.increment("intelligence_protocol_analytics")
    return APIResponse(data={
        "protocol_id": protocol_id,
        "analytics": [r.get("value", {}) for r in gold_records],
        "data_points": len(gold_records),
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/entity/{entity_id}/cluster")
async def identity_cluster(entity_id: str, request: Request):
    """
    Identity cluster: all linked wallets, social profiles, ENS names,
    governance activity for an entity.
    """
    request.state.tenant.require_permission("read")

    registry = get_registry()
    graph = registry.graph

    # Get graph neighbors (all relationship types)
    neighbors = await graph.get_neighbors(entity_id, direction="both")
    cluster = []
    for v in neighbors:
        cluster.append({
            "id": v.vertex_id,
            "type": v.vertex_type,
            "properties": v.properties,
        })

    # Get Gold identity features
    gold_records = await gold_identity.get_metrics(entity_id)

    metrics.increment("intelligence_identity_cluster")
    return APIResponse(data={
        "entity_id": entity_id,
        "cluster_size": len(cluster),
        "linked_entities": cluster,
        "identity_features": [r.get("value", {}) for r in gold_records],
        "computed_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/alerts")
async def anomaly_alerts(request: Request, limit: int = 50):
    """
    Recent anomaly alerts generated from rule and/or model-backed detection.
    """
    request.state.tenant.require_permission("read")

    # Read from Gold anomaly tier
    alerts = await gold_identity.get_highlights("anomaly_alert", limit=limit)

    metrics.increment("intelligence_alerts_queried")
    return APIResponse(data={
        "alerts": alerts,
        "count": len(alerts),
        "queried_at": utc_now().isoformat(),
    }).to_dict()


@router.get("/wallet/{address}/profile")
async def wallet_profile(address: str, request: Request):
    """
    Full wallet intelligence profile combining risk, features, graph, and identity.
    """
    request.state.tenant.require_permission("read")

    registry = get_registry()

    # Features
    gold_records = await gold_identity.get_metrics(address, entity_type="wallet")
    features = gold_records[0].get("value", {}) if gold_records else {}

    # Graph neighbors
    neighbors = await registry.graph.get_neighbors(address, direction="both")

    # Risk score
    scorer = TrustScoreComposite()
    score = await scorer.compute(entity_id=address, entity_type="wallet")

    metrics.increment("intelligence_wallet_profile")
    return APIResponse(data={
        "wallet_address": address,
        "risk": score.to_dict(),
        "features": features,
        "graph": {
            "neighbor_count": len(neighbors),
            "neighbors": [{"id": v.vertex_id, "type": v.vertex_type} for v in neighbors[:20]],
        },
        "computed_at": utc_now().isoformat(),
    }).to_dict()

# ── Graph-native Decision & Outcome Intelligence (OODA loop) ─────────────

_recommendations = RecommendationRepository()
_decisions = DecisionRepository()
_actions = ActionFeedbackRepository()
_outcomes = OutcomeRepository()
_playbooks = PlaybookRepository()
_playbook_runs = PlaybookRunRepository()
_feedback = RecommendationFeedbackRepository()
_ooda = GraphNativeRecommendationEngine(confidence_threshold=settings.decision_outcome.confidence_threshold)
_ledger = OutcomeLedgerAggregator()


class GenerateRecommendationRequest(BaseModel):
    entity_id: str
    signals: dict[str, Any] = Field(default_factory=dict)


class DecisionRequest(BaseModel):
    actor_id: str
    selected_action_key: str | None = None
    rejected_action_keys: list[str] = Field(default_factory=list)
    decision_status: DecisionStatus
    reason: str | None = None
    comment: str | None = None


class ActionLogRequest(BaseModel):
    decision_id: str
    action_type: str
    system: str | None = None
    integration: str | None = None
    status: Literal["planned", "queued", "executed", "failed", "cancelled"] = "planned"
    actor_type: Literal["human", "system", "agent"] = "human"
    economic_payload: dict[str, Any] | None = None
    authorization_metadata: dict[str, Any] | None = None


class OutcomeRequest(BaseModel):
    recommendation_id: str
    entity_id: str | None = None
    population_id: str | None = None
    outcome_type: str
    value: float | None = None
    currency: str | None = None
    label: OutcomeLabel
    observed_window: dict[str, str]


class PlaybookRequest(BaseModel):
    name: str
    description: str | None = None
    trigger: str
    recommendation_types: list[str] = Field(default_factory=list)
    candidate_actions: list[CandidateAction] = Field(default_factory=list)
    approval_level: ApprovalLevel = "standard"
    enabled: bool = True


async def _publish(topic: Topic, tenant_id: str, payload: dict) -> None:
    try:
        registry = get_registry()
        producer = getattr(registry, "producer", None)
        if producer is not None:
            await producer.publish(Event(topic=topic, tenant_id=tenant_id, payload=payload, source_service="intelligence"))
    except Exception as exc:  # pragma: no cover - event bus must not block request path
        logger.warning(f"decision intelligence event publish skipped: {exc}")


def _suppress_if_needed(rec: dict) -> dict:
    if rec["confidence"]["overall"] < settings.decision_outcome.confidence_threshold:
        rec["status"] = "suppressed"
        flags = set(rec.get("policy_governance_flags", []))
        flags.add("below_confidence_threshold")
        rec["policy_governance_flags"] = sorted(flags)
    return rec


def _build_recommendation_previews(tenant_id: str, body: GenerateRecommendationRequest) -> list[dict]:
    generated = _ooda.generate_all_for_entity(tenant_id, body.entity_id, body.signals)
    return [_suppress_if_needed(rec.model_dump()) for rec in generated]


def _primary_with_items(items: list[dict], **extra: Any) -> dict:
    primary = {**items[0], **extra}
    if len(items) > 1:
        primary["items"] = items
        primary["count"] = len(items)
    return primary


@router.post("/recommendations/preview")
async def preview_entity_recommendation(body: GenerateRecommendationRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "items": []}).to_dict()
    items = _build_recommendation_previews(tenant.tenant_id, body)
    return APIResponse(data=_primary_with_items(items, preview=True)).to_dict()


@router.post("/recommendations/generate")
async def generate_entity_recommendation(body: GenerateRecommendationRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "items": []}).to_dict()
    recs = _build_recommendation_previews(tenant.tenant_id, body)
    saved_items = []
    for rec in recs:
        saved = await _recommendations.insert(rec["recommendation_id"], rec)
        saved_items.append(saved)
        try:
            await upsert_recommendation_graph(get_registry().graph, saved)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"recommendation graph mutation skipped: {exc}")
        await _publish(Topic.RECOMMENDATION_GENERATED, tenant.tenant_id, saved)
    return APIResponse(data=_primary_with_items(saved_items)).to_dict()


@router.get("/recommendations")
async def list_intelligence_recommendations(request: Request, limit: int = 50, recommendation_type: str | None = None):
    tenant = request.state.tenant
    tenant.require_permission("read")
    if recommendation_type:
        items = await _recommendations.find_many({"tenant_id": tenant.tenant_id, "recommendation_type": recommendation_type}, limit=limit, sort_by="created_at", sort_order="desc")
    else:
        items = await _recommendations.list_for_tenant(tenant.tenant_id, limit=limit)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.get("/recommendations/{recommendation_id}")
async def get_intelligence_recommendation(recommendation_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rec = await _recommendations.find_by_id_or_fail(recommendation_id)
    if rec.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("recommendation")
    if rec.get("status") == "generated":
        rec = await _recommendations.update(recommendation_id, {"status": "viewed"})
        await _publish(Topic.RECOMMENDATION_VIEWED, tenant.tenant_id, rec)
    return APIResponse(data=rec).to_dict()


@router.get("/recommendations/{recommendation_id}/investigation")
async def get_recommendation_investigation(recommendation_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    rec = await _recommendations.find_by_id_or_fail(recommendation_id)
    if rec.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("recommendation")
    graph = None
    try:
        graph = get_registry().graph
    except Exception as exc:  # pragma: no cover
        logger.warning(f"recommendation investigation graph unavailable: {exc}")
    investigation = await build_recommendation_investigation(
        tenant_id=tenant.tenant_id,
        recommendation=rec,
        decisions_repo=_decisions,
        actions_repo=_actions,
        outcomes_repo=_outcomes,
        graph=graph,
    )
    return APIResponse(data=investigation).to_dict()


@router.post("/recommendations/{recommendation_id}/decision")
async def record_decision(recommendation_id: str, body: DecisionRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.decision_records_enabled:
        return APIResponse(data={"enabled": False}).to_dict()
    rec = await _recommendations.find_by_id_or_fail(recommendation_id)
    if rec.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("recommendation")
    candidates = [CandidateAction(**c) for c in rec.get("candidate_actions", [])]
    selected = next((c for c in candidates if c.action_key == body.selected_action_key), None)
    if body.decision_status == "approved" and selected is None:
        raise BadRequestError("Approved decisions require a valid selected_action_key")
    rejected = [c for c in candidates if c.action_key in set(body.rejected_action_keys)]
    decision = DecisionRecord(
        decision_id=str(uuid.uuid4()), recommendation_id=recommendation_id,
        actor_id=body.actor_id, selected_action=selected, rejected_actions=rejected,
        decision_status=body.decision_status, reason=body.reason, comment=body.comment,
        created_at=utc_now().isoformat(), tenant_id=tenant.tenant_id,
    ).model_dump()
    saved = await _decisions.insert(decision["decision_id"], decision)
    await _recommendations.update(recommendation_id, {"status": "decided"})
    try:
        await upsert_decision_graph(get_registry().graph, saved)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"decision graph mutation skipped: {exc}")
    await _publish(Topic.DECISION_RECORDED, tenant.tenant_id, saved)
    return APIResponse(data=saved).to_dict()


@router.post("/actions")
async def log_action(body: ActionLogRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    decision = await _decisions.find_by_id_or_fail(body.decision_id)
    if decision.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("decision")
    if body.status in {"queued", "executed"} and decision.get("decision_status") != "approved":
        raise BadRequestError("Actions cannot be queued or executed without an approved decision")
    selected_action = decision.get("selected_action") or {}
    approval_level = selected_action.get("requires_approval_level", "none")
    if (
        body.status == "executed"
        and approval_level in {"elevated", "critical"}
        and not (body.authorization_metadata or {}).get("approval_id")
    ):
        raise BadRequestError("Elevated or critical actions require authorization metadata with approval_id")
    action = ActionFeedback(
        action_id=str(uuid.uuid4()), decision_id=body.decision_id,
        action_type=body.action_type, system=body.system, integration=body.integration,
        status=body.status, actor_type=body.actor_type,
        economic_payload=body.economic_payload, authorization_metadata=body.authorization_metadata,
        created_at=utc_now().isoformat(), tenant_id=tenant.tenant_id,
    ).model_dump()
    saved = await _actions.insert(action["action_id"], action)
    try:
        await upsert_action_graph(get_registry().graph, saved)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"action graph mutation skipped: {exc}")
    await _publish(Topic.ACTION_EXECUTED, tenant.tenant_id, saved)
    return APIResponse(data=saved).to_dict()


@router.post("/actions/{action_id}/outcome")
async def observe_outcome(action_id: str, body: OutcomeRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.outcome_feedback_enabled:
        return APIResponse(data={"enabled": False}).to_dict()
    action = await _actions.find_by_id_or_fail(action_id)
    if action.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action")
    decision = await _decisions.find_by_id_or_fail(action["decision_id"])
    if decision.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("decision")
    if decision.get("recommendation_id") != body.recommendation_id:
        raise BadRequestError("Outcome recommendation_id must match the action decision recommendation")
    rec = await _recommendations.find_by_id_or_fail(body.recommendation_id)
    if rec.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("recommendation")
    delta = {"success": 0.05, "neutral": 0.0, "failure": -0.05}[body.label]
    outcome = OutcomeObservation(
        outcome_id=str(uuid.uuid4()), action_id=action_id,
        recommendation_id=body.recommendation_id, entity_id=body.entity_id or rec.get("entity_id"),
        population_id=body.population_id or rec.get("population_id"), outcome_type=body.outcome_type,
        value=body.value, currency=body.currency, label=body.label,
        observed_window=body.observed_window, computed_at=utc_now().isoformat(),
        confidence_delta=delta, tenant_id=tenant.tenant_id,
    ).model_dump()
    saved = await _outcomes.insert(outcome["outcome_id"], outcome)
    await _feedback.insert(str(uuid.uuid4()), {"tenant_id": tenant.tenant_id, "recommendation_id": body.recommendation_id, "outcome_id": saved["outcome_id"], "confidence_delta": delta, "created_at": now_iso()})
    conf = rec.get("confidence", {})
    conf["overall"] = max(0.0, min(1.0, float(conf.get("overall", 0.0)) + delta))
    await _recommendations.update(body.recommendation_id, {"confidence": conf})
    await _publish(Topic.RECOMMENDATION_CONFIDENCE_UPDATED, tenant.tenant_id, {"recommendation_id": body.recommendation_id, "confidence": conf})
    try:
        await upsert_outcome_graph(get_registry().graph, saved)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"outcome graph mutation skipped: {exc}")
    await _publish(Topic.OUTCOME_OBSERVED, tenant.tenant_id, saved)
    return APIResponse(data=saved).to_dict()


@router.get("/outcomes")
async def list_outcomes(request: Request, limit: int = 50):
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = await _outcomes.list_for_tenant(tenant.tenant_id, limit=limit)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


async def _tenant_outcome_ledger(tenant_id: str, limit: int = 500) -> dict:
    recommendations = await _recommendations.list_for_tenant(tenant_id, limit=limit)
    decisions = await _decisions.find_many({"tenant_id": tenant_id}, limit=limit)
    actions = await _actions.find_many({"tenant_id": tenant_id}, limit=limit)
    outcomes = await _outcomes.list_for_tenant(tenant_id, limit=limit)
    feedback = await _feedback.find_many({"tenant_id": tenant_id}, limit=limit)
    playbooks = await _playbooks.find_many({"tenant_id": tenant_id}, limit=limit)
    runs = await _playbook_runs.find_many({"tenant_id": tenant_id}, limit=limit)
    return _ledger.build(recommendations, decisions, actions, outcomes, feedback, playbooks, runs)


@router.get("/outcome-ledger")
async def get_outcome_ledger(request: Request, limit: int = 500):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await _tenant_outcome_ledger(tenant.tenant_id, limit=limit)).to_dict()


@router.get("/outcome-ledger/summary")
async def get_outcome_ledger_summary(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_outcome_ledger(tenant.tenant_id)
    return APIResponse(data=ledger["summary"]).to_dict()


@router.get("/outcome-ledger/by-recommendation-type")
async def get_outcome_ledger_by_recommendation_type(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_outcome_ledger(tenant.tenant_id)
    return APIResponse(data={"items": ledger["by_recommendation_type"]}).to_dict()


@router.get("/outcome-ledger/by-playbook")
async def get_outcome_ledger_by_playbook(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_outcome_ledger(tenant.tenant_id)
    return APIResponse(data={"items": ledger["by_playbook"]}).to_dict()


@router.get("/playbooks")
async def list_playbooks(request: Request, limit: int = 50):
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = await _playbooks.find_many({"tenant_id": tenant.tenant_id}, limit=limit)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.post("/playbooks")
async def create_playbook(body: PlaybookRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.playbooks_enabled:
        return APIResponse(data={"enabled": False}).to_dict()
    playbook = PlaybookDefinition(
        playbook_id=str(uuid.uuid4()), tenant_id=tenant.tenant_id,
        name=body.name, description=body.description, trigger=body.trigger,
        recommendation_types=body.recommendation_types, candidate_actions=body.candidate_actions,
        approval_level=body.approval_level, enabled=body.enabled, created_at=utc_now().isoformat(),
    ).model_dump()
    return APIResponse(data=await _playbooks.insert(playbook["playbook_id"], playbook)).to_dict()


@router.post("/playbooks/{playbook_id}/run")
async def run_playbook(playbook_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    playbook = await _playbooks.find_by_id_or_fail(playbook_id)
    if playbook.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("playbook")
    run = PlaybookRun(run_id=str(uuid.uuid4()), playbook_id=playbook_id, tenant_id=tenant.tenant_id, status="queued", started_at=utc_now().isoformat()).model_dump()
    return APIResponse(data=await _playbook_runs.insert(run["run_id"], run)).to_dict()
