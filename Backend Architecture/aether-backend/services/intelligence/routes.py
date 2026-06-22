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
from collections import Counter
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
    AuditExportRepository,
)
from services.lake.features import materialize_wallet_features

from services.intelligence.solution_packages import (
    AUDIT_EXPORT_TYPES,
    BUYER_PERSONAS,
    DEPLOYMENT_MODES,
    GTM_MATERIALS,
    PRICING_MODELS,
    ROI_CALCULATORS,
    SOLUTION_PACKAGES,
    AuditExportRequest,
    gtm_materials_for_package,
    audit_export_type_map,
    personas_for_package,
    roi_calculators_for_package,
    make_export_record,
    pdf_summary_payload,
    redact_secrets,
    to_csv_payload,
)

logger = get_logger("aether.service.intelligence")
router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])
kyber_admin_router = APIRouter(prefix="/v1/admin/kyber", tags=["Admin — Kyber Strategic Observability"])

# Anti-distillation: imported lazily at use site to avoid circular init
_anti_distillation_service = None


def _get_anti_distillation():
    global _anti_distillation_service
    if _anti_distillation_service is None and settings.provider_corpus.anti_distillation_enabled:
        from services.security.anti_distillation import anti_distillation_service
        _anti_distillation_service = anti_distillation_service
    return _anti_distillation_service


def _check_anti_distillation(request: Request, entity_id: str, endpoint: str):
    """Run anti-distillation check when the feature flag is on. Raises on honeypot."""
    svc = _get_anti_distillation()
    if svc is None:
        return
    tenant_id = getattr(getattr(request.state, "tenant", None), "tenant_id", "unknown")
    result = svc.check_query_pattern(tenant_id, endpoint, {"entity_id": entity_id, "address": entity_id})
    if result.is_suspicious and result.pattern_type == "honeypot_wallet_query":
        from shared.common.common import ForbiddenError
        raise ForbiddenError("Access denied")
    if result.is_suspicious:
        logger.warning(
            f"Anti-distillation: suspicious pattern tenant={tenant_id} endpoint={endpoint}",
            extra={"entity_id": entity_id, "pattern": result.pattern_type},
        )


@router.get("/wallet/{address}/risk")
async def wallet_risk_score(address: str, request: Request):
    """
    Compute wallet risk score using trust scorer + graph + lake data.
    Returns composite risk from fraud, identity, and behavioral components.
    """
    request.state.tenant.require_permission("read")
    _check_anti_distillation(request, address, "wallet_risk_score")

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
    _check_anti_distillation(request, address, "wallet_profile")

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
_audit_exports = AuditExportRepository()
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
    # Governance policy: elevated/critical dispatch requires an approval_id. This
    # mirrors the check on POST /actions and routes the decision through the
    # security policy engine (which records a SecurityAuditEvent on block).
    from services.security.policy_engine import policy_engine
    selected_action = decision.get("selected_action") or {}
    approval_level = selected_action.get("requires_approval_level", "none")
    approval_id = (
        (body.approval_metadata or {}).get("approval_id")
        or (action.get("authorization_metadata") or {}).get("approval_id")
    )
    dispatch_policy = await policy_engine.check_action_dispatch(
        actor_id=tenant.user_id or tenant.tenant_id, actor_type='tenant_user',
        tenant_id=tenant.tenant_id, decision_status="approved", action_id=action_id,
        is_elevated=approval_level in {"elevated", "critical"}, approval_id=approval_id,
    )
    if not dispatch_policy.allowed:
        raise BadRequestError(dispatch_policy.reason)
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

# ── Enterprise + Government Packaging, Audit Exports, Deployment Readiness ──

def _markets(pkg: dict[str, Any]) -> list[str]:
    market = pkg.get("market", [])
    return market if isinstance(market, list) else [str(market)]


def _package_by_id(package_id: str) -> dict[str, Any] | None:
    return next((p.model_dump() for p in SOLUTION_PACKAGES if p.package_id == package_id), None)


def _readiness_for_package(pkg: dict[str, Any]) -> dict[str, Any]:
    gaps = []
    if "government_planning" in _markets(pkg):
        gaps.append("Government/public-sector package is planning-only and has no certification or authorization claim.")
    if pkg.get("readiness_status") not in {"sales_ready", "enterprise_ready"}:
        gaps.append("Additional customer evidence, docs, and tests required before sales-ready positioning.")
    return {
        "package_id": pkg["package_id"],
        "readiness_status": pkg["readiness_status"],
        "feature_completeness": "core_modules_mapped" if pkg.get("included_modules") else "missing_modules",
        "documentation_completeness": "documented_with_known_gaps",
        "test_coverage_status": "backend_contract_and_route_coverage_added",
        "audit_export_support": "available" if pkg.get("required_audit_exports") else "not_required",
        "access_control_status": "tenant_scoped_permissions_required",
        "integration_support_status": "recommended_integrations_identified",
        "deployment_support_status": "planning" if "government_planning" in _markets(pkg) else "mapped",
        "pricing_defined": bool(pkg.get("pricing_levers")),
        "sales_collateral_status": "package_definition_ready" if pkg.get("readiness_status") in {"sales_ready", "pilot_ready"} else "planning_only",
        "known_gaps": gaps,
        "recommended_next_actions": ["Validate package with target tenant usage", "Complete missing deployment artifacts before raising readiness", "Review required audit exports with buyer security team"],
        "generated_at": utc_now().isoformat(),
    }


async def _tenant_usage_metrics(tenant_id: str, limit: int = 1000) -> dict[str, Any]:
    recs = await _recommendations.find_many({"tenant_id": tenant_id}, limit=limit)
    decisions = await _decisions.find_many({"tenant_id": tenant_id}, limit=limit)
    actions = await _actions.find_many({"tenant_id": tenant_id}, limit=limit)
    dispatches = await _dispatches.find_many({"tenant_id": tenant_id}, limit=limit)
    outcomes = await _outcomes.find_many({"tenant_id": tenant_id}, limit=limit)
    playbooks = await _playbooks.find_many({"tenant_id": tenant_id}, limit=limit)
    type_counts = Counter(str(r.get("recommendation_type", "unknown")) for r in recs)
    outcome_types = Counter(str(o.get("outcome_type", "unknown")) for o in outcomes)
    return {"recommendations": len(recs), "decisions": len(decisions), "actions": len(actions), "dispatches": len(dispatches), "outcomes": len(outcomes), "playbooks": len(playbooks), "recommendation_types": dict(type_counts), "outcome_types": dict(outcome_types), "success_outcomes": sum(1 for o in outcomes if o.get("label") == "success"), "failure_outcomes": sum(1 for o in outcomes if o.get("label") == "failure"), "observed_value": round(sum(float(o.get("value") or 0) for o in outcomes), 2)}


def _tenant_package_fit_from_metrics(tenant_id: str, metrics_data: dict[str, Any]) -> list[dict[str, Any]]:
    rt = metrics_data.get("recommendation_types", {})
    ot = metrics_data.get("outcome_types", {})
    profiles = {
        "revenue_intelligence_graph": rt.get("retention", 0) + rt.get("expansion", 0) + rt.get("attribution_optimization", 0) + rt.get("journey_optimization", 0) + ot.get("revenue", 0),
        "fraud_risk_intelligence_graph": rt.get("fraud_review", 0) + ot.get("avoided_loss", 0) + metrics_data.get("decisions", 0),
        "agent_governance_graph": rt.get("agent_governance", 0) + metrics_data.get("dispatches", 0) + metrics_data.get("failure_outcomes", 0),
        "operational_decision_intelligence": rt.get("operational_failure", 0) + metrics_data.get("playbooks", 0) + metrics_data.get("actions", 0),
        "program_integrity_graph": rt.get("fraud_review", 0) + rt.get("case_prioritization", 0) + metrics_data.get("decisions", 0),
        "critical_infrastructure_coordination_graph": rt.get("operational_failure", 0) + metrics_data.get("actions", 0) + metrics_data.get("dispatches", 0),
    }
    max_score = max([*profiles.values(), 1])
    rows = []
    for package_id, raw in profiles.items():
        pkg = _package_by_id(package_id) or {"name": package_id}
        score = round(min(1.0, raw / max_score), 4)
        rows.append({"tenant_id": tenant_id, "package_id": package_id, "package_name": pkg.get("name"), "package_fit_score": score, "suggested_package": score >= 0.75, "supporting_metrics": metrics_data, "recommended_sales_motion": "expansion_or_pilot" if score >= 0.75 else "nurture_with_readiness_discovery"})
    return sorted(rows, key=lambda r: r["package_fit_score"], reverse=True)


async def _all_tenant_fits() -> list[dict[str, Any]]:
    recs = await _recommendations.find_many({}, limit=2000)
    tenants = sorted({r.get("tenant_id") for r in recs if r.get("tenant_id")})
    fits = []
    for tenant_id in tenants:
        fits.extend(_tenant_package_fit_from_metrics(tenant_id, await _tenant_usage_metrics(tenant_id)))
    return fits


def _export_matches(item: dict[str, Any], body: AuditExportRequest) -> bool:
    if body.entity_id and item.get("entity_id") != body.entity_id:
        return False
    if body.recommendation_id and item.get("recommendation_id") != body.recommendation_id:
        return False
    if body.playbook_id and item.get("playbook_id") != body.playbook_id:
        return False
    return True


async def _build_audit_payload(tenant_id: str, body: AuditExportRequest) -> Any:
    recs = [r for r in await _recommendations.find_many({"tenant_id": tenant_id}, limit=1000) if _export_matches(r, body)]
    decisions = [d for d in await _decisions.find_many({"tenant_id": tenant_id}, limit=1000) if _export_matches(d, body) or not body.recommendation_id]
    actions = await _actions.find_many({"tenant_id": tenant_id}, limit=1000)
    dispatches = await _dispatches.find_many({"tenant_id": tenant_id}, limit=1000)
    receipts = await _delivery_receipts.find_many({}, limit=1000)
    outcomes = [o for o in await _outcomes.find_many({"tenant_id": tenant_id}, limit=1000) if _export_matches(o, body)]
    playbooks = [p for p in await _playbooks.find_many({"tenant_id": tenant_id}, limit=1000) if not body.playbook_id or p.get("playbook_id") == body.playbook_id]
    runs = [r for r in await _playbook_runs.find_many({"tenant_id": tenant_id}, limit=1000) if not body.playbook_id or r.get("playbook_id") == body.playbook_id]
    if not body.include_evidence:
        recs = [{k: v for k, v in r.items() if k != "evidence"} for r in recs]
    if not body.include_confidence_deltas:
        outcomes = [{k: v for k, v in o.items() if k != "confidence_delta"} for o in outcomes]
    if body.export_type == "recommendation_audit":
        payload = recs
    elif body.export_type == "decision_audit":
        payload = decisions
    elif body.export_type == "action_dispatch_audit":
        receipt_by_dispatch = {r.get("dispatch_id"): r for r in receipts} if body.include_dispatch_receipts else {}
        payload = [{"action": a, "dispatches": [d for d in dispatches if d.get("action_id") == a.get("action_id")], "delivery_receipts": [receipt_by_dispatch[d.get("dispatch_id")] for d in dispatches if d.get("action_id") == a.get("action_id") and d.get("dispatch_id") in receipt_by_dispatch], "authorization_metadata_present": bool(a.get("authorization_metadata")), "idempotency_keys": [d.get("idempotency_key") for d in dispatches if d.get("action_id") == a.get("action_id") and d.get("idempotency_key")], "status_transitions": [a.get("status"), *[d.get("status") for d in dispatches if d.get("action_id") == a.get("action_id")]]} for a in actions]
    elif body.export_type == "outcome_audit":
        payload = outcomes
    elif body.export_type == "playbook_run_audit":
        payload = {"playbooks": playbooks, "runs": runs, "generated_recommendations": recs, "linked_decisions": decisions, "linked_actions": actions, "linked_outcomes": outcomes, "roi_metrics": (await _tenant_ledger(tenant_id)).get("by_playbook", [])}
    elif body.export_type == "agent_governance_audit":
        agent_recs = [r for r in recs if r.get("recommendation_type") == "agent_governance" or "agent" in str(r.get("policy_governance_flags", [])).lower()]
        payload = {"recommendations": agent_recs, "approvals": decisions, "actions": actions, "dispatches": dispatches, "outcomes": outcomes, "governance_notes": "Tenant-scoped agent governance audit; raw secrets excluded."}
    elif body.export_type == "tenant_value_audit":
        ledger = await _tenant_ledger(tenant_id)
        labels = Counter(o.get("label", "unknown") for o in outcomes)
        payload = {"outcome_ledger_summary": ledger.get("summary"), "playbook_roi": ledger.get("by_playbook"), "recommendation_family_performance": ledger.get("by_recommendation_type"), "observed_value": ledger.get("summary", {}).get("observed_value"), "pending_value": max(float(ledger.get("summary", {}).get("expected_value", 0)) - float(ledger.get("summary", {}).get("observed_value", 0)), 0), "counts": dict(labels)}
    elif body.export_type == "package_readiness_audit":
        payload = {"solution_packages": [p.model_dump() for p in SOLUTION_PACKAGES], "readiness_reports": [_readiness_for_package(p.model_dump()) for p in SOLUTION_PACKAGES], "deployment_modes": [m.model_dump() for m in DEPLOYMENT_MODES]}
    else:
        raise BadRequestError("Unknown audit export type")
    payload = redact_secrets(payload)
    if body.format == "csv":
        rows = payload if isinstance(payload, list) else [payload]
        return to_csv_payload(rows)
    if body.format == "pdf_summary":
        return pdf_summary_payload(body.export_type, payload)
    return payload


@router.get("/audit-exports/types")
async def list_audit_export_types(request: Request):
    request.state.tenant.require_permission("read")
    return APIResponse(data={"items": [t.model_dump() for t in AUDIT_EXPORT_TYPES], "count": len(AUDIT_EXPORT_TYPES)}).to_dict()


@router.post("/audit-exports")
async def create_audit_export(body: AuditExportRequest, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("write")
    if body.tenant_id and body.tenant_id != tenant.tenant_id:
        raise BadRequestError("Audit export tenant_id must match the authenticated tenant")
    export_type = audit_export_type_map().get(body.export_type)
    if export_type is None:
        raise BadRequestError("Unknown audit export type")
    if body.format not in export_type.supported_formats:
        raise BadRequestError("Unsupported format for export type")
    payload = await _build_audit_payload(tenant.tenant_id, body)
    requested_by = getattr(tenant, "user_id", None) or getattr(tenant, "actor_id", None) or "tenant_user"
    record = make_export_record(tenant_id=tenant.tenant_id, requested_by=requested_by, request=body, payload=payload)
    saved = record.model_dump()
    saved["payload"] = payload
    await _audit_exports.insert(record.export_id, saved)
    public = record.model_dump()
    return APIResponse(data=public).to_dict()


@router.get("/audit-exports/{export_id}")
async def get_audit_export(export_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _audit_exports.find_by_id_or_fail(export_id)
    if record.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("audit export")
    return APIResponse(data={k: v for k, v in record.items() if k != "payload"}).to_dict()


@router.get("/audit-exports/{export_id}/download")
async def download_audit_export(export_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _audit_exports.find_by_id_or_fail(export_id)
    if record.get("tenant_id") != tenant.tenant_id:
        from shared.common.common import NotFoundError
        raise NotFoundError("audit export")
    return APIResponse(data={"export_id": export_id, "format": record.get("format"), "integrity_hash": record.get("integrity_hash"), "payload": record.get("payload")}).to_dict()


@kyber_admin_router.get("/solution-packages")
async def kyber_solution_packages(request: Request):
    request.state.tenant.require_permission("admin")
    fits = await _all_tenant_fits()
    demand = Counter(f["package_id"] for f in fits if f["suggested_package"])
    return APIResponse(data={"items": [{**p.model_dump(), "active_tenant_demand": demand.get(p.package_id, 0), "known_gaps": _readiness_for_package(p.model_dump())["known_gaps"]} for p in SOLUTION_PACKAGES], "tenant_package_fit": fits}).to_dict()


@kyber_admin_router.get("/solution-packages/{package_id}")
async def kyber_solution_package_detail(package_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    pkg = _package_by_id(package_id)
    if not pkg:
        from shared.common.common import NotFoundError
        raise NotFoundError("solution package")
    fits = [f for f in await _all_tenant_fits() if f["package_id"] == package_id]
    return APIResponse(data={**pkg, "readiness_report": _readiness_for_package(pkg), "deployment_modes_detail": [m.model_dump() for m in DEPLOYMENT_MODES if m.name in pkg.get("deployment_modes", [])], "tenants_matching": [f for f in fits if f["suggested_package"]]}).to_dict()


@kyber_admin_router.get("/package-readiness")
async def kyber_package_readiness(request: Request):
    request.state.tenant.require_permission("admin")
    reports = [_readiness_for_package(p.model_dump()) for p in SOLUTION_PACKAGES]
    return APIResponse(data={"items": reports, "count": len(reports)}).to_dict()


@kyber_admin_router.get("/deployment-modes")
async def kyber_deployment_modes(request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data={"items": [m.model_dump() for m in DEPLOYMENT_MODES], "count": len(DEPLOYMENT_MODES)}).to_dict()


@kyber_admin_router.get("/deployment-readiness")
async def kyber_deployment_readiness(request: Request):
    request.state.tenant.require_permission("admin")
    items = [m.model_dump() | {"checklist": {"access_controls": "required", "audit_exports": "implemented", "logging": "required", "tenant_isolation": "required", "integration_security": "secret_refs_only", "incident_response_docs": "required", "data_retention_docs": "required", "ai_risk_management_docs": "required", "deployment_documentation": "required", "known_gaps": m.known_gaps}} for m in DEPLOYMENT_MODES]
    return APIResponse(data={"items": items}).to_dict()


@kyber_admin_router.get("/audit-export-health")
async def kyber_audit_export_health(request: Request):
    request.state.tenant.require_permission("admin")
    exports = await _audit_exports.find_many({}, limit=1000)
    return APIResponse(data={"export_volume": len(exports), "export_success": sum(1 for e in exports if e.get("status") == "generated"), "export_failure": sum(1 for e in exports if e.get("status") == "failed"), "stale_or_expired_exports": sum(1 for e in exports if e.get("status") == "expired"), "export_types_used": dict(Counter(e.get("export_type") for e in exports)), "tenants_requesting_exports": sorted({e.get("tenant_id") for e in exports if e.get("tenant_id")})}).to_dict()



@kyber_admin_router.get("/gtm/materials")
async def kyber_gtm_materials(request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data={"items": [m.model_dump() for m in GTM_MATERIALS], "count": len(GTM_MATERIALS)}).to_dict()


@kyber_admin_router.get("/gtm/materials/{material_id}")
async def kyber_gtm_material_detail(material_id: str, request: Request):
    request.state.tenant.require_permission("admin")
    material = next((m.model_dump() for m in GTM_MATERIALS if m.material_id == material_id), None)
    if not material:
        from shared.common.common import NotFoundError
        raise NotFoundError("gtm material")
    return APIResponse(data=material).to_dict()


@kyber_admin_router.get("/gtm/buyer-personas")
async def kyber_gtm_buyer_personas(request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data={"items": [p.model_dump() for p in BUYER_PERSONAS], "count": len(BUYER_PERSONAS)}).to_dict()


@kyber_admin_router.get("/gtm/pricing-models")
async def kyber_gtm_pricing_models(request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data={"items": [p.model_dump() for p in PRICING_MODELS], "count": len(PRICING_MODELS)}).to_dict()


@kyber_admin_router.get("/gtm/roi-calculators")
async def kyber_gtm_roi_calculators(request: Request):
    request.state.tenant.require_permission("admin")
    return APIResponse(data={"items": [c.model_dump() for c in ROI_CALCULATORS], "count": len(ROI_CALCULATORS)}).to_dict()


@kyber_admin_router.get("/gtm/sales-readiness")
async def kyber_gtm_sales_readiness(request: Request):
    request.state.tenant.require_permission("admin")
    items = []
    for pkg_model in SOLUTION_PACKAGES:
        pkg = pkg_model.model_dump()
        readiness = _readiness_for_package(pkg)
        materials = gtm_materials_for_package(pkg_model.package_id)
        personas = personas_for_package(pkg_model.package_id)
        calculators = roi_calculators_for_package(pkg_model.package_id)
        has_audit = bool(pkg.get("required_audit_exports"))
        deployment_ready = pkg.get("readiness_status") in {"sales_ready", "enterprise_ready", "pilot_ready"}
        ready = pkg.get("readiness_status") == "sales_ready" and bool(materials) and bool(personas) and bool(calculators) and has_audit and deployment_ready
        next_actions = []
        if not materials:
            next_actions.append("Create package collateral before sales motion.")
        if not calculators:
            next_actions.append("Add ROI calculator or mark calculator gap in sales notes.")
        if not has_audit:
            next_actions.append("Map required audit exports for procurement/security review.")
        if not deployment_ready:
            next_actions.append("Complete deployment readiness artifacts; use planning language only.")
        if "government_planning" in _markets(pkg):
            next_actions.append("Keep public-sector language planning-only; do not claim certification, authorization, FedRAMP, StateRAMP, or ATO.")
        items.append({"package_id": pkg_model.package_id, "package_name": pkg_model.name, "readiness_status": pkg_model.readiness_status, "ready_to_sell": ready, "material_count": len(materials), "persona_count": len(personas), "roi_calculator_count": len(calculators), "missing_collateral": not bool(materials), "missing_roi_calculator": not bool(calculators), "missing_audit_export_support": not has_audit, "missing_deployment_readiness": not deployment_ready, "known_gaps": readiness["known_gaps"], "recommended_next_sales_actions": next_actions or ["Use approved sales-ready collateral and capture buyer feedback."]})
    return APIResponse(data={"items": items, "ready_to_sell_count": sum(1 for i in items if i["ready_to_sell"]), "generated_at": utc_now().isoformat()}).to_dict()

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


# ── Commerce Lifecycle Trace ──────────────────────────────────────────────────


@router.get("/commerce/lifecycle/{challenge_id}")
async def trace_payment_lifecycle(challenge_id: str, request: Request):
    """
    Full lifecycle trace for one payment challenge.
    Returns the graph-linked chain: requirement → policy_decision → approval →
    authorization → receipt → settlement → entitlement → grant → fulfillment.
    Used by Kyber Noesis, Review page, and compliance audit.
    """
    request.state.tenant.require_permission("x402:read")
    tenant_id = request.state.tenant.tenant_id

    from services.x402.commerce_store import get_commerce_store
    store = get_commerce_store()

    requirement = await store.get_requirement(tenant_id, challenge_id)
    if requirement is None:
        from shared.common.common import NotFoundError
        raise NotFoundError("PaymentRequirement")

    authorization = await store.get_authorization(tenant_id, challenge_id)
    receipt = await store.get_receipt(tenant_id, challenge_id)
    settlement = await store.get_settlement(tenant_id, challenge_id) if receipt else None
    entitlement = None
    if authorization:
        entitlement = await store.find_active_entitlement(
            tenant_id,
            authorization.holder_id,
            requirement.resource_id,
        )

    trace = {
        "challenge_id": challenge_id,
        "tenant_id": tenant_id,
        "requirement": requirement.model_dump() if requirement else None,
        "authorization": authorization.model_dump() if authorization else None,
        "receipt": receipt.model_dump() if receipt else None,
        "settlement": settlement.model_dump() if settlement else None,
        "entitlement": entitlement.model_dump() if entitlement else None,
        "lifecycle_stage": _lifecycle_stage(requirement, authorization, receipt, settlement, entitlement),
        "computed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    }

    # Fetch approval request by challenge_id reference
    approvals = await store.list_approvals(tenant_id)
    approval = next(
        (a for a in approvals if a.reference_id == challenge_id), None
    )
    if approval:
        trace["approval"] = approval.model_dump()

    metrics.increment("intelligence_commerce_lifecycle_trace")
    return APIResponse(data=trace).to_dict()


def _lifecycle_stage(requirement, authorization, receipt, settlement, entitlement) -> str:
    """Derive the most advanced lifecycle stage from available objects."""
    if entitlement:
        return "access_granted"
    if settlement:
        return f"settled:{settlement.state.value}"
    if receipt:
        return "receipt_verified"
    if authorization:
        return "authorized"
    if requirement:
        return "challenged"
    return "unknown"


# ── Gold Intelligence Extensions ──────────────────────────────────────────────
# Each endpoint aggregates Silver fact tables into tenant-scoped intelligence
# metrics. All accept ?window=30d|60d|90d|lifetime (default 30d).
# Degrade gracefully to empty metrics when Silver data is absent.

_WINDOW_DAYS = {"30d": 30, "60d": 60, "90d": 90, "lifetime": 36500}


def _window_days(window: str) -> int:
    return _WINDOW_DAYS.get(window, 30)


async def _query_silver(table: str, tenant_id: str, entity_id: str | None, limit: int = 500) -> list[dict]:
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        filters: dict = {"tenant_id": tenant_id}
        if entity_id:
            filters["user_id"] = entity_id
        return await repo.query_silver(table, filters, limit=limit)
    except Exception:
        return []


@router.get("/account-health")
async def get_account_health(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """Account health score with activation, adoption, seat utilization, and churn signals."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    from services.intelligence.customer_success import (
        CustomerSuccessService,
        CustomerSuccessAccountRepository,
    )

    try:
        repo = CustomerSuccessAccountRepository()
        account = await repo.get_for_tenant(tenant_id, entity_id=entity_id)
        health = {
            "health_score": account.get("health_score", 0.0),
            "lifecycle_stage": account.get("lifecycle_stage", "unknown"),
            "expansion_score": account.get("expansion_score", 0.0),
            "renewal_risk_score": account.get("renewal_risk_score", 0.0),
            "activation_score": account.get("activation_score"),
            "adoption_depth": account.get("adoption_depth"),
            "seat_utilization": account.get("seat_utilization"),
            "churn_likelihood": account.get("churn_likelihood"),
        }
    except Exception:
        health = {}

    activity = await _query_silver("silver_account_activity_facts", tenant_id, entity_id, limit=200)
    health["activity_count_in_window"] = len(activity)
    health["window"] = window

    metrics.increment("intelligence_account_health")
    return APIResponse(data={"tenant_id": tenant_id, "entity_id": entity_id, "metrics": health}).to_dict()


@router.get("/revenue-intelligence")
async def get_revenue_intelligence(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """GMV, MRR, ARR, NRR, churn, and expansion metrics from Silver revenue facts."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await _query_silver("silver_revenue_facts", tenant_id, entity_id)

    gmv = sum(float(r.get("amount", 0) or 0) for r in rows if r.get("revenue_type") in (None, "order"))
    mrr = sum(float(r.get("mrr_delta", 0) or 0) for r in rows)
    arr = mrr * 12
    expansion = sum(float(r.get("amount", 0) or 0) for r in rows if r.get("revenue_type") == "expansion")
    churn_count = sum(1 for r in rows if r.get("revenue_type") == "churn")
    total = len(rows)

    metrics.increment("intelligence_revenue")
    return APIResponse(data={
        "tenant_id": tenant_id, "entity_id": entity_id, "window": window,
        "metrics": {
            "gmv": gmv, "mrr": mrr, "arr": arr,
            "expansion_revenue": expansion,
            "churn_events": churn_count,
            "nrr": (1 - churn_count / max(total, 1)) * 100,
            "record_count": total,
        },
    }).to_dict()


@router.get("/experience-intelligence")
async def get_experience_intelligence(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """Journey completion, friction score, and dead/rage click hotspots from Silver friction facts."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await _query_silver("silver_friction_facts", tenant_id, entity_id)
    payload = rows[0].get("payload", {}) if rows else {}

    dead_clicks = sum(int((r.get("payload") or {}).get("dead_click_count", 0)) for r in rows)
    rage_clicks = sum(int((r.get("payload") or {}).get("rage_click_count", 0)) for r in rows)
    form_abandons = sum(1 for r in rows if (r.get("payload") or {}).get("form_abandoned"))
    total = len(rows)
    friction_score = min(1.0, (dead_clicks + rage_clicks * 2 + form_abandons * 3) / max(total * 10, 1))

    metrics.increment("intelligence_experience")
    return APIResponse(data={
        "tenant_id": tenant_id, "entity_id": entity_id, "window": window,
        "metrics": {
            "friction_score": round(friction_score, 4),
            "dead_click_count": dead_clicks,
            "rage_click_count": rage_clicks,
            "form_abandon_count": form_abandons,
            "friction_event_count": total,
        },
    }).to_dict()


@router.get("/exposure-intelligence")
async def get_exposure_intelligence(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """Exposure-to-action rate and recommendation acceptance from Silver exposure facts."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await _query_silver("silver_exposure_facts", tenant_id, entity_id)
    total = len(rows)
    accepted = sum(1 for r in rows if (r.get("payload") or {}).get("accepted"))
    rejected = sum(1 for r in rows if (r.get("payload") or {}).get("rejected"))
    action_taken = sum(1 for r in rows if (r.get("payload") or {}).get("action_taken"))

    metrics.increment("intelligence_exposure")
    return APIResponse(data={
        "tenant_id": tenant_id, "entity_id": entity_id, "window": window,
        "metrics": {
            "exposure_count": total,
            "accepted_count": accepted,
            "rejected_count": rejected,
            "action_taken_count": action_taken,
            "acceptance_rate": round(accepted / max(total, 1), 4),
            "exposure_to_action_rate": round(action_taken / max(total, 1), 4),
        },
    }).to_dict()


@router.get("/agent-intelligence")
async def get_agent_intelligence(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """Cost per outcome, reliability rate, escalation rate, and human override rate from Silver agent facts."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await _query_silver("silver_agent_execution_facts", tenant_id, entity_id)
    total = len(rows)
    succeeded = sum(1 for r in rows if (r.get("payload") or {}).get("outcome") == "success")
    escalated = sum(1 for r in rows if (r.get("payload") or {}).get("escalated"))
    overridden = sum(1 for r in rows if (r.get("payload") or {}).get("human_override"))
    total_cost = sum(float((r.get("payload") or {}).get("cost_usd", 0) or 0) for r in rows)
    outcome_count = max(succeeded, 1)

    metrics.increment("intelligence_agent")
    return APIResponse(data={
        "tenant_id": tenant_id, "entity_id": entity_id, "window": window,
        "metrics": {
            "execution_count": total,
            "reliability_rate": round(succeeded / max(total, 1), 4),
            "escalation_rate": round(escalated / max(total, 1), 4),
            "human_override_rate": round(overridden / max(total, 1), 4),
            "total_cost_usd": round(total_cost, 4),
            "cost_per_outcome_usd": round(total_cost / outcome_count, 4),
        },
    }).to_dict()


@router.get("/integration-intelligence")
async def get_integration_intelligence(
    request: Request,
    entity_id: str | None = None,
    window: str = "30d",
):
    """Integration health: adoption, failure rate, and latency from Silver server operation facts."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    tenant_id = tenant.tenant_id

    rows = await _query_silver("silver_server_operation_facts", tenant_id, entity_id)
    total = len(rows)
    failed = sum(1 for r in rows if (r.get("payload") or {}).get("status") in ("failed", "error"))
    latencies = [
        float((r.get("payload") or {}).get("duration_ms", 0) or 0)
        for r in rows
        if (r.get("payload") or {}).get("duration_ms") is not None
    ]
    avg_latency = sum(latencies) / max(len(latencies), 1)

    metrics.increment("intelligence_integration")
    return APIResponse(data={
        "tenant_id": tenant_id, "entity_id": entity_id, "window": window,
        "metrics": {
            "operation_count": total,
            "failure_count": failed,
            "failure_rate": round(failed / max(total, 1), 4),
            "avg_latency_ms": round(avg_latency, 2),
            "integrations_active": len({(r.get("payload") or {}).get("integration_id") for r in rows if r.get("payload")} - {None}),
        },
    }).to_dict()
