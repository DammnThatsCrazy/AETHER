from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tests.unit.test_risk360_provider import (
    TENANT_A, _available_registry, _context, _request, _risk_intervention_record,
)
from intelligence.intelligence import routes
from intelligence.intelligence.repositories import ActionFeedbackRepository, DecisionRepository, RecommendationRepository
from intelligence.risk360.provider import Risk360Provider
from intelligence.risk360.store import RiskInterventionRepository
from repositories.repos import reset_in_memory_stores
from shared.intelligence_projections.contracts import (
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
    ProjectionReadAuthorization, ProjectionResult, ProjectionSection, ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame
from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()


@pytest.mark.parametrize("slot_state,dispatch_state,expected", [
    ("allowed", "allowed", True), ("allowed", "denied", False),
    ("allowed", "missing", False), ("allowed", "error", False),
    ("allowed", "no_proof", False), ("denied", "allowed", False),
])
async def test_frame_requires_explicit_actions_policy(slot_state, dispatch_state, expected):
    subject = ProjectionSubject(kind="agent", id="agent-1")
    request = Experience360FrameRequest(surfaceId="risk360", tenantId=TENANT_A, subject=subject,
                                        requestedSlotIds=["interventions"])
    seen = []

    class Policy:
        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId="risk360", tenantId=TENANT_A, evaluatedAt="2026-10-27T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"interventions": Experience360PolicyDisposition(
                    state=slot_state, policyIds=["slot"], evaluatedAt="2026-10-27T10:00:00Z")},
            )

    async def dispatch_policy(frame_request):
        if dispatch_state == "error":
            raise RuntimeError("unavailable")
        return Experience360PolicyDisposition(
            state="allowed" if dispatch_state == "no_proof" else dispatch_state,
            policyIds=[] if dispatch_state == "no_proof" else ["actions"],
            evaluatedAt="2026-10-27T10:00:00Z",
        )

    policy = Policy()
    if dispatch_state != "missing":
        policy.evaluate_risk_dispatch_read = dispatch_policy

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend(kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId, tenantId=TENANT_A,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-10-27T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=policy, projection_runtime=Runtime())
    authorizations = [item for item in seen if item.capabilityKey == "actions.dispatch.read"]
    assert len(authorizations) == int(expected)
    if expected:
        auth = authorizations[0]
        assert (auth.tenantId, auth.sourceSubject, auth.sourceSlotId) == (TENANT_A, subject, "interventions")
        assert (auth.consumerProjectionId, auth.targetProjectionId, auth.policyIds) == ("risk360", "risk360", ["actions"])


async def _produce_dispatch(*, recommendation_subject="entity-1", subject_kind="entity", population_id=None):
    record = _risk_intervention_record("risk-decision", subject_kind=subject_kind, subject_id="entity-1", observed_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    await RiskInterventionRepository().create(record)
    recommendation = {"recommendation_id": "rec-1", "tenant_id": TENANT_A, "entity_id": recommendation_subject, "population_id": population_id, "candidate_actions": []}
    decision = {"decision_id": "dec-1", "tenant_id": TENANT_A, "recommendation_id": "rec-1",
                "decision_status": "approved", "selected_action": {
                    "action_key": record.intervention_type, "action_type": "review", "requires_approval_level": "none"}}
    action = {"action_id": "action-1", "tenant_id": TENANT_A, "decision_id": "dec-1",
              "recommendation_id": "rec-1", "action_type": "review", "status": "planned"}
    await RecommendationRepository().insert("rec-1", recommendation)
    await DecisionRepository().insert("dec-1", decision)
    await ActionFeedbackRepository().insert("action-1", action)
    tenant = SimpleNamespace(tenant_id=TENANT_A, user_id="operator", require_permission=lambda permission: None)
    response = await routes._dispatch_action(
        "action-1", routes.DispatchActionRequest(
            target_type="agent_assist", idempotency_key="risk-dispatch",
            risk_action_reference={"record_id": record.record_id, "subject_kind": record.subject_kind,
                                   "subject_id": record.subject_id}),
        SimpleNamespace(state=SimpleNamespace(tenant=tenant)),
    )
    return record, response["data"]["dispatch"]


@pytest.mark.parametrize("recommendation_subject,subject_kind,population_id", [
    ("other", "entity", None), (None, "entity", None),
    ("entity-1", "entity", "population-1"), ("entity-1", "agent", None),
])
async def test_dispatch_rejects_unbound_or_ambiguous_recommendation_subject(
    recommendation_subject, subject_kind, population_id
):
    from shared.common.common import BadRequestError

    with pytest.raises(BadRequestError):
        await _produce_dispatch(recommendation_subject=recommendation_subject,
                                subject_kind=subject_kind, population_id=population_id)


async def test_dispatch_rejects_same_tenant_cross_subject_reference():
    from shared.common.common import BadRequestError

    record = _risk_intervention_record(
        "risk-cross-subject", subject_kind="entity", subject_id="entity-1",
        observed_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    await RiskInterventionRepository().create(record)
    await RecommendationRepository().insert("rec-cross-subject", {
        "recommendation_id": "rec-cross-subject", "tenant_id": TENANT_A,
        "entity_id": "entity-1", "candidate_actions": [],
    })
    await DecisionRepository().insert("dec-cross-subject", {
        "decision_id": "dec-cross-subject", "tenant_id": TENANT_A,
        "recommendation_id": "rec-cross-subject", "decision_status": "approved",
        "selected_action": {"action_key": record.intervention_type, "action_type": "review"},
    })
    await ActionFeedbackRepository().insert("action-cross-subject", {
        "action_id": "action-cross-subject", "tenant_id": TENANT_A,
        "decision_id": "dec-cross-subject", "recommendation_id": "rec-cross-subject",
        "action_type": "review", "status": "planned",
    })
    tenant = SimpleNamespace(tenant_id=TENANT_A, user_id="operator", require_permission=lambda permission: None)
    with pytest.raises(BadRequestError):
        await routes._dispatch_action(
            "action-cross-subject",
            routes.DispatchActionRequest(
                target_type="agent_assist", idempotency_key="cross-subject",
                risk_action_reference={"record_id": record.record_id, "subject_kind": "entity",
                                       "subject_id": "entity-2"},
            ),
            SimpleNamespace(state=SimpleNamespace(tenant=tenant)),
        )


async def test_idempotent_replay_rejects_risk_subject_rebinding():
    from shared.common.common import ConflictError

    record, _dispatch = await _produce_dispatch()
    tenant = SimpleNamespace(tenant_id=TENANT_A, user_id="operator", require_permission=lambda permission: None)
    with pytest.raises(ConflictError):
        await routes._dispatch_action(
            "action-1",
            routes.DispatchActionRequest(
                target_type="agent_assist", idempotency_key="risk-dispatch",
                risk_action_reference={"record_id": record.record_id, "subject_kind": "entity",
                                       "subject_id": "entity-2"},
            ),
            SimpleNamespace(state=SimpleNamespace(tenant=tenant)),
        )


def _authorization(subject):
    return ProjectionReadAuthorization(
        tenantId=TENANT_A, sourceSurfaceId="risk360", sourceSubject=subject, sourceSlotId="interventions",
        consumerProjectionId="risk360", targetProjectionId="risk360", capabilityKey="actions.dispatch.read",
        policyState="allowed", policyIds=["actions"], policyEvaluatedAt="2026-10-27T10:00:00Z",
    )


@pytest.mark.parametrize("scope", ["allowed", "missing", "tenant", "subject", "denied"])
async def test_producer_dispatch_reaches_only_authorized_subject(scope):
    record, dispatch = await _produce_dispatch()
    request = _request(subject=ProjectionSubject(kind="entity", id=record.subject_id))
    context = await _context(_available_registry())
    auth = _authorization(request.subject)
    if scope == "tenant":
        auth = auth.model_copy(update={"tenantId": "tenant-b"})
    elif scope == "subject":
        auth = auth.model_copy(update={"sourceSubject": ProjectionSubject(kind="agent", id="other")})
    elif scope == "denied":
        auth = auth.model_copy(update={"policyState": "denied"})
    context.experience360ReadAuthorizations = [] if scope == "missing" else [auth]
    result = await Risk360Provider().project(request, context)
    findings = next(section for section in result.sections if section.id == "findings")
    summary = findings.content["interventions"]
    row = next(item for item in summary["records"] if item["recordId"] == record.record_id)
    if scope == "allowed":
        assert [item["dispatchId"] for item in row["dispatches"]] == [dispatch["dispatch_id"]]
        assert row["dispatches"][0]["externalEffect"] == "not_independently_verified"
        assert {item["source"] for item in row["dispatches"][0]["evidenceRefs"]} == {
            "action_dispatches", "action_feedback", "decision_records", "recommendations",
            "security_policy_decisions"}
        assert dispatch["dispatch_policy_decision_id"]
    else:
        assert row["dispatches"] == []
        assert summary["dispatchAssociation"]["state"] == "unknown"


async def test_reader_rejects_same_tenant_recommendation_rebound_to_another_subject():
    record, dispatch = await _produce_dispatch()
    recommendations = RecommendationRepository()
    recommendation = await recommendations.find_by_id("rec-1")
    assert recommendation["tenant_id"] == TENANT_A

    # Simulate a persisted join whose recommendation now names a different
    # entity in the same tenant. A matching tenant and dispatch ID cannot
    # carry the dispatch across subjects.
    recommendation["entity_id"] = "entity-2"
    await recommendations.insert("rec-1", recommendation)

    request = _request(subject=ProjectionSubject(kind="entity", id=record.subject_id))
    context = await _context(_available_registry())
    context.experience360ReadAuthorizations = [_authorization(request.subject)]
    result = await Risk360Provider().project(request, context)

    findings = next(section for section in result.sections if section.id == "findings")
    summary = findings.content["interventions"]
    row = next(item for item in summary["records"] if item["recordId"] == record.record_id)
    assert row["dispatches"] == []
    assert summary["dispatchAssociation"]["state"] == "degraded"
    assert dispatch["dispatch_id"] not in str(result.model_dump())


async def test_unavailable_dispatch_reader_degrades_without_disclosure(monkeypatch):
    record, dispatch = await _produce_dispatch()
    from actions.agent import risk_dispatch_association

    async def unavailable(**kwargs):
        return [], False

    monkeypatch.setattr(risk_dispatch_association, "read_risk_dispatches", unavailable)
    request = _request(subject=ProjectionSubject(kind="entity", id=record.subject_id))
    context = await _context(_available_registry())
    context.experience360ReadAuthorizations = [_authorization(request.subject)]
    result = await Risk360Provider().project(request, context)
    findings = next(section for section in result.sections if section.id == "findings")
    summary = findings.content["interventions"]
    row = next(item for item in summary["records"] if item["recordId"] == record.record_id)
    assert row["dispatches"] == []
    assert summary["dispatchAssociation"]["state"] == "degraded"
    assert dispatch["dispatch_id"] not in str(result.model_dump())


async def test_incomplete_dispatch_read_discards_rows_and_degrades(monkeypatch):
    record, dispatch = await _produce_dispatch()
    from actions.agent import risk_dispatch_association

    async def incomplete(**kwargs):
        return ([{"dispatchId": dispatch["dispatch_id"], "status": "queued", "evidenceRefs": []}], False)

    monkeypatch.setattr(risk_dispatch_association, "read_risk_dispatches", incomplete)
    request = _request(subject=ProjectionSubject(kind="entity", id=record.subject_id))
    context = await _context(_available_registry())
    context.experience360ReadAuthorizations = [_authorization(request.subject)]
    result = await Risk360Provider().project(request, context)
    findings = next(section for section in result.sections if section.id == "findings")
    summary = findings.content["interventions"]
    row = next(item for item in summary["records"] if item["recordId"] == record.record_id)
    assert row["dispatches"] == []
    assert summary["dispatchAssociation"]["state"] == "degraded"
    assert dispatch["dispatch_id"] not in str(result.model_dump())
