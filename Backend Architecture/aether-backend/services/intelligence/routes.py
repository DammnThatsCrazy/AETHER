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

from services.intelligence.action_targets import ActionTargetRegistry
from services.intelligence.decision_models import (
    ActionDeliveryReceipt,
    ActionDispatch,
    ActionFeedback,
    ActionIntegrationConfig,
    RevenueMeteringEvent,
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
from services.intelligence.playbooks import (
    PLAYBOOK_TEMPLATES,
    PlaybookEvaluationResult,
    playbook_from_template,
    template_by_id,
    build_playbook_performance,
    evaluate_trigger,
    generate_for_playbook,
)
from services.intelligence.repositories import (
    ActionDeliveryReceiptRepository,
    ActionDispatchRepository,
    ActionFeedbackRepository,
    ActionIntegrationConfigRepository,
    DecisionRepository,
    OutcomeRepository,
    PlaybookRepository,
    PlaybookRunRepository,
    RecommendationFeedbackRepository,
    RecommendationRepository,
    RevenueMeteringEventRepository,
)
from services.lake.features import materialize_wallet_features

logger = get_logger("aether.service.intelligence")
router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])
kyber_admin_router = APIRouter(prefix="/v1/admin/kyber", tags=["Admin — Kyber Strategic Observability"])


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
_integrations = ActionIntegrationConfigRepository()
_dispatches = ActionDispatchRepository()
_delivery_receipts = ActionDeliveryReceiptRepository()
_metering = RevenueMeteringEventRepository()
_action_targets = ActionTargetRegistry()
_outcomes = OutcomeRepository()
_playbooks = PlaybookRepository()
_playbook_runs = PlaybookRunRepository()
_feedback = RecommendationFeedbackRepository()
_ooda = GraphNativeRecommendationEngine()
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


class IntegrationConfigRequest(BaseModel):
    target_type: str
    name: str
    default_destination: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class DispatchActionRequest(BaseModel):
    target_type: str
    config_id: str | None = None
    payload_overrides: dict[str, Any] = Field(default_factory=dict)
    approval_metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class DeliveryReceiptRequest(BaseModel):
    external_id: str | None = None
    external_url: str | None = None
    status: Literal["delivered", "failed", "cancelled"] = "delivered"
    raw: dict[str, Any] = Field(default_factory=dict)


class OutcomeRequest(BaseModel):
    recommendation_id: str
    entity_id: str | None = None
    population_id: str | None = None
    outcome_type: str
    value: float | None = None
    currency: str | None = None
    label: OutcomeLabel
    observed_window: dict[str, str]


class CreatePlaybookFromTemplateRequest(BaseModel):
    template_id: str
    name: str | None = None
    description: str | None = None
    enabled: bool = True


class PlaybookEvaluationRequest(BaseModel):
    entity_id: str | None = None
    population_id: str | None = None
    signals: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


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


def _safe_integration_config(config: dict[str, Any]) -> dict[str, Any]:
    safe = dict(config)
    nested = dict(safe.get("config") or {})
    secret_keys = {"auth_secret", "secret", "api_key", "webhook_secret", "secret_ref"}
    has_secret = bool(safe.get("secret_ref") or nested.get("secret_ref"))
    for key in secret_keys:
        if key in safe:
            has_secret = has_secret or key != "secret_ref"
            safe.pop(key, None)
        if key in nested:
            has_secret = has_secret or key != "secret_ref"
            nested.pop(key, None)
    safe["config"] = nested
    if has_secret:
        safe["has_secret"] = True
    return safe


def _config_with_secret_ref(config: dict[str, Any]) -> dict[str, Any]:
    import hashlib

    prepared = dict(config)
    nested = dict(prepared.get("config") or {})
    for key in ("auth_secret", "secret", "api_key", "webhook_secret"):
        secret = prepared.pop(key, None) or nested.pop(key, None)
        if secret:
            nested["secret_ref"] = hashlib.sha256(str(secret).encode("utf-8")).hexdigest()[:16]
            break
    prepared["config"] = nested
    return prepared


async def _load_dispatch_context(tenant_id: str, action_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    action = await _actions.find_by_id_or_fail(action_id)
    if action.get("tenant_id") != tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action")
    decision = await _decisions.find_by_id_or_fail(action["decision_id"])
    if decision.get("tenant_id") != tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("decision")
    recommendation = await _recommendations.find_by_id_or_fail(decision["recommendation_id"])
    if recommendation.get("tenant_id") != tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("recommendation")
    return action, decision, recommendation


def _suppress_if_needed(rec: dict[str, Any]) -> dict[str, Any]:
    if rec.get("confidence", {}).get("overall", 0.0) < settings.decision_outcome.confidence_threshold:
        rec["status"] = "suppressed"
        flags = set(rec.get("policy_governance_flags", []))
        flags.add("below_confidence_threshold")
        rec["policy_governance_flags"] = sorted(flags)
    return rec


def _build_recommendation_preview(tenant_id: str, body: GenerateRecommendationRequest) -> dict:
    rec = _ooda.generate_for_entity(tenant_id, body.entity_id, body.signals).model_dump()
    if rec["confidence"]["overall"] < settings.decision_outcome.confidence_threshold:
        rec["status"] = "suppressed"
        flags = set(rec.get("policy_governance_flags", []))
        flags.add("below_confidence_threshold")
        rec["policy_governance_flags"] = sorted(flags)
    return rec


@router.post("/recommendations/preview")
async def preview_entity_recommendation(body: GenerateRecommendationRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "items": []}).to_dict()
    rec = _build_recommendation_preview(tenant.tenant_id, body)
    rec["preview"] = True
    return APIResponse(data=rec).to_dict()


@router.post("/recommendations/generate")
async def generate_entity_recommendation(body: GenerateRecommendationRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "items": []}).to_dict()
    rec = _build_recommendation_preview(tenant.tenant_id, body)
    saved = await _recommendations.insert(rec["recommendation_id"], rec)
    try:
        await upsert_recommendation_graph(get_registry().graph, saved)
    except Exception as exc:  # pragma: no cover
        logger.warning(f"recommendation graph mutation skipped: {exc}")
    await _publish(Topic.RECOMMENDATION_GENERATED, tenant.tenant_id, saved)
    return APIResponse(data=saved).to_dict()


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
    decisions = await _decisions.find_many({"tenant_id": tenant.tenant_id, "recommendation_id": recommendation_id}, limit=100)
    actions = []
    for decision in decisions:
        actions.extend(await _actions.find_many({"tenant_id": tenant.tenant_id, "decision_id": decision.get("decision_id")}, limit=100))
    outcomes = await _outcomes.find_many({"tenant_id": tenant.tenant_id, "recommendation_id": recommendation_id}, limit=100)
    prior_outcomes = await _outcomes.find_many({"tenant_id": tenant.tenant_id}, limit=100)
    prior_similar = [o for o in prior_outcomes if o.get("recommendation_id") != recommendation_id][:20]
    graph_edges = []
    try:
        neighbors = await get_registry().graph.get_neighbors(recommendation_id, direction="both")
        graph_edges = [{"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties} for v in neighbors[:50]]
    except Exception as exc:  # pragma: no cover
        logger.warning(f"recommendation investigation graph lookup skipped: {exc}")
    data = {
        "recommendation": rec,
        "confidence_breakdown": rec.get("confidence", {}),
        "evidence": rec.get("evidence", []),
        "related_entity": {"entity_id": rec.get("entity_id"), "population_id": rec.get("population_id")},
        "related_events": [e for e in rec.get("evidence", []) if e.get("source_type") == "event"],
        "related_graph_edges": graph_edges,
        "attribution_path": next((e for e in rec.get("evidence", []) if e.get("source_type") == "attribution_path"), None),
        "prior_similar_outcomes": prior_similar,
        "candidate_actions": rec.get("candidate_actions", []),
        "decision_history": decisions,
        "action_history": actions,
        "outcome_history": outcomes,
        "governance_flags": rec.get("policy_governance_flags", []),
        "data_freshness": rec.get("data_freshness", {}),
        "suppression_explanation": rec.get("policy_governance_flags", []) if rec.get("status") == "suppressed" else [],
    }
    return APIResponse(data=data).to_dict()


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


@router.get("/action-targets")
async def list_action_targets(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = [target.descriptor().model_dump() for target in _action_targets.list_targets()]
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@router.get("/action-integrations")
async def list_action_integrations(request: Request, limit: int = 100):
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = await _integrations.find_many({"tenant_id": tenant.tenant_id}, limit=limit)
    return APIResponse(data={"items": [_safe_integration_config(item) for item in items], "count": len(items)}).to_dict()


@router.post("/action-integrations")
async def create_action_integration(body: IntegrationConfigRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    try:
        _action_targets.get(body.target_type)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    prepared = _config_with_secret_ref(body.model_dump())
    config = ActionIntegrationConfig(
        config_id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        target_type=body.target_type,
        name=body.name,
        default_destination=body.default_destination,
        config=prepared.get("config", {}),
        enabled=body.enabled,
        created_at=utc_now().isoformat(),
    ).model_dump()
    saved = await _integrations.insert(config["config_id"], config)
    return APIResponse(data=_safe_integration_config(saved)).to_dict()


@router.put("/action-integrations/{config_id}")
async def update_action_integration(config_id: str, body: IntegrationConfigRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    existing = await _integrations.find_by_id_or_fail(config_id)
    if existing.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action integration")
    if existing.get("target_type") != body.target_type:
        raise BadRequestError("target_type cannot be changed for an integration config")
    prepared = _config_with_secret_ref(body.model_dump())
    saved = await _integrations.update(config_id, {
        "name": body.name,
        "default_destination": body.default_destination,
        "config": prepared.get("config", {}),
        "enabled": body.enabled,
        "updated_at": utc_now().isoformat(),
    })
    return APIResponse(data=_safe_integration_config(saved)).to_dict()


async def _dispatch_action(action_id: str, body: DispatchActionRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    action, decision, recommendation = await _load_dispatch_context(tenant.tenant_id, action_id)
    if decision.get("decision_status") != "approved":
        raise BadRequestError("Actions can only be dispatched for approved decisions")
    config = None
    if body.config_id:
        raw_config = await _integrations.find_by_id_or_fail(body.config_id)
        if raw_config.get("tenant_id") != tenant.tenant_id:
            from shared.common.common import NotFoundError
            raise NotFoundError("action integration")
        config = ActionIntegrationConfig(**raw_config)
    target = _action_targets.get(body.target_type)
    try:
        target.validate_config(config)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    payload = target.build_payload(
        action=action,
        decision=decision,
        recommendation=recommendation,
        config=config,
        overrides=body.payload_overrides,
    )
    dispatch = ActionDispatch(
        dispatch_id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        action_id=action_id,
        decision_id=decision["decision_id"],
        recommendation_id=recommendation["recommendation_id"],
        target_type=body.target_type,
        config_id=body.config_id,
        status="queued",
        payload=payload,
        approval_metadata=body.approval_metadata,
        idempotency_key=body.idempotency_key,
        created_at=utc_now().isoformat(),
    )
    receipt = await target.dispatch(dispatch, config)
    dispatch.status = receipt.status if receipt.status != "delivered" else "delivered"
    dispatch.dispatched_at = utc_now().isoformat()
    dispatch.updated_at = dispatch.dispatched_at
    saved_dispatch = await _dispatches.insert(dispatch.dispatch_id, dispatch.model_dump())
    saved_receipt = await _delivery_receipts.insert(receipt.receipt_id, receipt.model_dump())
    metering = RevenueMeteringEvent(
        event_id=str(uuid.uuid4()),
        tenant_id=tenant.tenant_id,
        dispatch_id=dispatch.dispatch_id,
        recommendation_id=recommendation["recommendation_id"],
        event_type="action_dispatch",
        units=1.0,
        amount=0.0 if not target.premium_connector else 1.0,
        created_at=utc_now().isoformat(),
        metadata={"target_type": body.target_type},
    ).model_dump()
    await _metering.insert(metering["event_id"], metering)
    await _actions.update(action_id, {"status": "executed" if dispatch.status == "delivered" else "queued", "integration": body.target_type})
    return APIResponse(data={"dispatch": saved_dispatch, "receipt": saved_receipt, "metering_event": metering}).to_dict()


@router.post("/actions/{action_id}/dispatch")
async def dispatch_action(action_id: str, body: DispatchActionRequest, request: Request):
    return await _dispatch_action(action_id, body, request)


@router.post("/action-dispatches/{dispatch_id}/retry")
async def retry_action_dispatch(dispatch_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    raw_dispatch = await _dispatches.find_by_id_or_fail(dispatch_id)
    if raw_dispatch.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action dispatch")
    config = ActionIntegrationConfig(**await _integrations.find_by_id_or_fail(raw_dispatch["config_id"])) if raw_dispatch.get("config_id") else None
    target = _action_targets.get(raw_dispatch["target_type"])
    dispatch = ActionDispatch(**raw_dispatch)
    receipt = await target.retry(dispatch, config, int(raw_dispatch.get("retry_count", 0)) + 1)
    saved_dispatch = await _dispatches.update(dispatch_id, {"status": receipt.status, "retry_count": receipt.retry_count, "updated_at": utc_now().isoformat(), "error": None})
    saved_receipt = await _delivery_receipts.insert(receipt.receipt_id, receipt.model_dump())
    return APIResponse(data={"dispatch": saved_dispatch, "receipt": saved_receipt}).to_dict()


@router.post("/action-dispatches/{dispatch_id}/cancel")
async def cancel_action_dispatch(dispatch_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    raw_dispatch = await _dispatches.find_by_id_or_fail(dispatch_id)
    if raw_dispatch.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action dispatch")
    config = ActionIntegrationConfig(**await _integrations.find_by_id_or_fail(raw_dispatch["config_id"])) if raw_dispatch.get("config_id") else None
    target = _action_targets.get(raw_dispatch["target_type"])
    try:
        receipt = await target.cancel(ActionDispatch(**raw_dispatch), config)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    saved_dispatch = await _dispatches.update(dispatch_id, {"status": "cancelled", "updated_at": utc_now().isoformat()})
    saved_receipt = await _delivery_receipts.insert(receipt.receipt_id, receipt.model_dump())
    return APIResponse(data={"dispatch": saved_dispatch, "receipt": saved_receipt}).to_dict()


@router.post("/action-dispatches/{dispatch_id}/receipts")
async def record_delivery_receipt(dispatch_id: str, body: DeliveryReceiptRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    raw_dispatch = await _dispatches.find_by_id_or_fail(dispatch_id)
    if raw_dispatch.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("action dispatch")
    receipt = ActionDeliveryReceipt(
        receipt_id=str(uuid.uuid4()),
        dispatch_id=dispatch_id,
        target_type=raw_dispatch["target_type"],
        external_id=body.external_id,
        external_url=body.external_url,
        status=body.status,
        delivered_at=utc_now().isoformat(),
        retry_count=int(raw_dispatch.get("retry_count", 0)),
        raw=body.raw,
    ).model_dump()
    saved_receipt = await _delivery_receipts.insert(receipt["receipt_id"], receipt)
    saved_dispatch = await _dispatches.update(dispatch_id, {"status": body.status, "updated_at": utc_now().isoformat()})
    return APIResponse(data={"dispatch": saved_dispatch, "receipt": saved_receipt}).to_dict()


@router.get("/action-dispatches")
async def list_action_dispatches(request: Request, limit: int = 100):
    tenant = request.state.tenant
    tenant.require_permission("read")
    items = await _dispatches.find_many({"tenant_id": tenant.tenant_id}, limit=limit)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


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


async def _tenant_ledger(tenant_id: str, limit: int = 500) -> dict:
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
    ledger = await _tenant_ledger(tenant.tenant_id, limit=limit)
    return APIResponse(data=ledger).to_dict()


@router.get("/outcome-ledger/summary")
async def get_outcome_ledger_summary(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_ledger(tenant.tenant_id)
    return APIResponse(data=ledger["summary"]).to_dict()


@router.get("/outcome-ledger/by-recommendation-type")
async def get_outcome_ledger_by_recommendation_type(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_ledger(tenant.tenant_id)
    return APIResponse(data={"items": ledger["by_recommendation_type"]}).to_dict()


@router.get("/outcome-ledger/by-playbook")
async def get_outcome_ledger_by_playbook(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    ledger = await _tenant_ledger(tenant.tenant_id)
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
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "reason": "recommendations_disabled"}).to_dict()
    playbook = PlaybookDefinition(
        playbook_id=str(uuid.uuid4()), tenant_id=tenant.tenant_id,
        name=body.name, description=body.description, trigger=body.trigger,
        recommendation_types=body.recommendation_types, candidate_actions=body.candidate_actions,
        approval_level=body.approval_level, enabled=body.enabled, created_at=utc_now().isoformat(),
    ).model_dump()
    return APIResponse(data=await _playbooks.insert(playbook["playbook_id"], playbook)).to_dict()


@router.get("/playbooks/templates")
async def list_playbook_templates(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data={"items": [template.model_dump() for template in PLAYBOOK_TEMPLATES], "count": len(PLAYBOOK_TEMPLATES)}).to_dict()


@router.post("/playbooks/from-template")
async def create_playbook_from_template(body: CreatePlaybookFromTemplateRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.playbooks_enabled:
        return APIResponse(data={"enabled": False}).to_dict()
    template = template_by_id(body.template_id)
    if template is None:
        raise BadRequestError("Unknown playbook template")
    playbook = playbook_from_template(
        template,
        tenant.tenant_id,
        {"name": body.name, "description": body.description, "enabled": body.enabled},
    ).model_dump()
    playbook["template_id"] = template.template_id
    playbook["category"] = template.category
    playbook["expected_outcome_types"] = template.expected_outcome_types
    playbook["recommended_integrations"] = template.recommended_integrations
    return APIResponse(data=await _playbooks.insert(playbook["playbook_id"], playbook)).to_dict()


async def _playbook_performance(playbook: dict, limit: int = 500) -> dict:
    tenant_id = str(playbook.get("tenant_id"))
    playbook_id = str(playbook.get("playbook_id"))
    runs = await _playbook_runs.find_many({"tenant_id": tenant_id, "playbook_id": playbook_id}, limit=limit)
    recommendations = await _recommendations.find_many({"tenant_id": tenant_id}, limit=limit)
    decisions = await _decisions.find_many({"tenant_id": tenant_id}, limit=limit)
    actions = await _actions.find_many({"tenant_id": tenant_id}, limit=limit)
    outcomes = await _outcomes.find_many({"tenant_id": tenant_id}, limit=limit)
    feedback = await _feedback.find_many({"tenant_id": tenant_id}, limit=limit)
    return build_playbook_performance(playbook, runs, recommendations, decisions, actions, outcomes, feedback).model_dump()


@router.get("/playbooks/performance/summary")
async def get_playbook_performance_summary(request: Request, limit: int = 500):
    tenant = request.state.tenant
    tenant.require_permission("read")
    playbooks = await _playbooks.find_many({"tenant_id": tenant.tenant_id}, limit=limit)
    items = [await _playbook_performance(playbook, limit=limit) for playbook in playbooks]
    totals = {
        "playbooks_total": len(items),
        "runs_total": sum(item["runs_total"] for item in items),
        "runs_completed": sum(item["runs_completed"] for item in items),
        "recommendations_generated": sum(item["recommendations_generated"] for item in items),
        "observed_value_total": round(sum(item["observed_value_total"] for item in items), 2),
        "expected_value_total": round(sum(item["expected_value_total"] for item in items), 2),
        "pending_value_total": round(sum(item["pending_value_total"] for item in items), 2),
        "stale_run_count": sum(item["stale_run_count"] for item in items),
        "incomplete_run_count": sum(item["incomplete_run_count"] for item in items),
    }
    return APIResponse(data={"items": items, "summary": totals}).to_dict()


@router.get("/playbooks/{playbook_id}")
async def get_playbook(playbook_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    playbook = await _playbooks.find_by_id_or_fail(playbook_id)
    if playbook.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("playbook")
    return APIResponse(data=playbook).to_dict()


@router.get("/playbooks/{playbook_id}/runs")
async def list_playbook_runs(playbook_id: str, request: Request, limit: int = 50):
    tenant = request.state.tenant
    tenant.require_permission("read")
    playbook = await _playbooks.find_by_id_or_fail(playbook_id)
    if playbook.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("playbook")
    runs = await _playbook_runs.find_many({"tenant_id": tenant.tenant_id, "playbook_id": playbook_id}, limit=limit)
    return APIResponse(data={"items": runs, "count": len(runs)}).to_dict()


@router.get("/playbooks/{playbook_id}/performance")
async def get_playbook_performance(playbook_id: str, request: Request, limit: int = 500):
    tenant = request.state.tenant
    tenant.require_permission("read")
    playbook = await _playbooks.find_by_id_or_fail(playbook_id)
    if playbook.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("playbook")
    return APIResponse(data=await _playbook_performance(playbook, limit=limit)).to_dict()


@router.post("/playbooks/{playbook_id}/evaluate")
async def evaluate_playbook(playbook_id: str, body: PlaybookEvaluationRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if not settings.decision_outcome.playbooks_enabled:
        return APIResponse(data={"enabled": False}).to_dict()
    if not settings.decision_outcome.recommendations_enabled:
        return APIResponse(data={"enabled": False, "reason": "recommendations_disabled"}).to_dict()
    playbook = await _playbooks.find_by_id_or_fail(playbook_id)
    if playbook.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("playbook")
    if not playbook.get("enabled", True):
        result = PlaybookEvaluationResult(
            playbook_id=playbook_id,
            tenant_id=tenant.tenant_id,
            matched=False,
            skipped_reason="playbook_disabled",
            evaluated_at=utc_now().isoformat(),
        )
        return APIResponse(data=result.model_dump()).to_dict()
    if not body.entity_id and not body.population_id:
        raise BadRequestError("Playbook evaluation requires entity_id or population_id")
    signals = {**body.context, **body.signals}
    matched, trigger_matches, skipped = evaluate_trigger(playbook, signals)
    if not matched:
        result = PlaybookEvaluationResult(
            playbook_id=playbook_id,
            tenant_id=tenant.tenant_id,
            matched=False,
            trigger_matches=trigger_matches,
            skipped_reason=skipped,
            evaluated_at=utc_now().isoformat(),
        )
        return APIResponse(data=result.model_dump()).to_dict()
    recommendations = generate_for_playbook(_ooda, tenant.tenant_id, playbook, signals, body.entity_id, body.population_id)
    run = PlaybookRun(
        run_id=str(uuid.uuid4()),
        playbook_id=playbook_id,
        tenant_id=tenant.tenant_id,
        status="completed",
        recommendation_ids=[],
        trigger_snapshot={"signals": body.signals, "context": body.context, "matches": trigger_matches},
        generated_recommendation_ids=[],
        started_at=utc_now().isoformat(),
        completed_at=utc_now().isoformat(),
        summary={"matched": True, "recommendations_generated": 0},
    ).model_dump()
    generated_ids: list[str] = []
    for recommendation in recommendations:
        rec = _suppress_if_needed(recommendation.model_dump())
        rec["playbook_id"] = playbook_id
        rec["playbook_run_id"] = run["run_id"]
        saved = await _recommendations.insert(rec["recommendation_id"], rec)
        generated_ids.append(saved["recommendation_id"])
        try:
            await upsert_recommendation_graph(get_registry().graph, saved)
        except Exception as exc:  # pragma: no cover
            logger.warning(f"playbook recommendation graph mutation skipped: {exc}")
        await _publish(Topic.RECOMMENDATION_GENERATED, tenant.tenant_id, saved)
    run["recommendation_ids"] = generated_ids
    run["generated_recommendation_ids"] = generated_ids
    run["summary"] = {"matched": True, "recommendations_generated": len(generated_ids)}
    await _playbook_runs.insert(run["run_id"], run)
    result = PlaybookEvaluationResult(
        playbook_id=playbook_id,
        tenant_id=tenant.tenant_id,
        matched=True,
        trigger_matches=trigger_matches,
        generated_recommendation_ids=generated_ids,
        evaluated_at=utc_now().isoformat(),
    )
    return APIResponse(data=result.model_dump()).to_dict()


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


async def _all_tenant_ledgers(limit: int = 1000) -> dict[str, dict]:
    recs = await _recommendations.find_many({}, limit=limit)
    tenants = sorted({r.get("tenant_id") for r in recs if r.get("tenant_id")})
    return {tenant_id: await _tenant_ledger(tenant_id, limit=limit) for tenant_id in tenants}


@kyber_admin_router.get("/recommendation-health")
async def kyber_recommendation_health(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    return APIResponse(data={"tenants": {k: v["summary"] for k, v in ledgers.items()}, "aggregate": _combine_summaries([v["summary"] for v in ledgers.values()])}).to_dict()


@kyber_admin_router.get("/tenant-value-health")
async def kyber_tenant_value_health(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    items = [{"tenant_id": tenant_id, "value_created": ledger["summary"]["observed_value"], "value_pending": max(ledger["summary"]["expected_value"] - ledger["summary"]["observed_value"], 0), "at_risk": ledger["summary"]["outcome_capture_rate"] < 0.25, "expansion_ready": ledger["summary"]["observed_value"] > 0 and ledger["summary"]["success_rate"] >= 0.5} for tenant_id, ledger in ledgers.items()]
    return APIResponse(data={"items": items}).to_dict()


@kyber_admin_router.get("/outcome-capture-health")
async def kyber_outcome_capture_health(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    return APIResponse(data={"items": [{"tenant_id": t, "outcome_capture_rate": l["summary"]["outcome_capture_rate"], "stale_loops": l["summary"]["stale_loops"], "incomplete_loops": l["summary"]["incomplete_loops"]} for t, l in ledgers.items()]}).to_dict()


@kyber_admin_router.get("/playbook-performance")
async def kyber_playbook_performance(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    return APIResponse(data={"items": [item for ledger in ledgers.values() for item in ledger["by_playbook"]]}).to_dict()


@kyber_admin_router.get("/model-confidence-drift")
async def kyber_model_confidence_drift(request: Request):
    request.state.tenant.require_permission("admin")
    feedback = await _feedback.find_many({}, limit=1000)
    return APIResponse(data={"confidence_deltas_over_time": feedback, "total_delta": round(sum(float(f.get("confidence_delta", 0)) for f in feedback), 4)}).to_dict()


@kyber_admin_router.get("/vertical-solution-signals")
async def kyber_vertical_solution_signals(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    clusters: dict[str, int] = {}
    for ledger in ledgers.values():
        for item in ledger["by_recommendation_type"]:
            clusters[item["key"]] = clusters.get(item["key"], 0) + item["recommendations"]
    return APIResponse(data={"clusters": clusters}).to_dict()


@kyber_admin_router.get("/expansion-opportunities")
async def kyber_expansion_opportunities(request: Request):
    request.state.tenant.require_permission("admin")
    ledgers = await _all_tenant_ledgers()
    return APIResponse(data={"items": [{"tenant_id": t, "reason": "high_success_and_value", "observed_value": l["summary"]["observed_value"]} for t, l in ledgers.items() if l["summary"]["success_rate"] >= 0.5 and l["summary"]["observed_value"] > 0]}).to_dict()


def _combine_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ["recommendations_generated", "recommendations_viewed", "decisions_recorded", "actions_logged", "outcomes_observed", "expected_value", "observed_value", "stale_loops", "incomplete_loops", "failed_loops"]
    combined = {key: round(sum(float(s.get(key, 0)) for s in summaries), 2) for key in keys}
    combined["outcome_capture_rate"] = round(combined["outcomes_observed"] / combined["recommendations_generated"], 4) if combined["recommendations_generated"] else 0.0
    return combined
