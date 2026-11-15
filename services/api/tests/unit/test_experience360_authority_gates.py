"""Slot-scoped authority envelopes do not exist for denied or unrelated reads."""
from __future__ import annotations

import pytest

from shared.intelligence_projections.contracts import (
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
    ProjectionResult, ProjectionSection, ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame
from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("surface,kind,slot,consumer,target,capability", [
    ("profile360", "entity", "likely_next_states", "profile360", "outcome360", "outcome_facts.read"),
    ("campaign360", "campaign", "cohorts_syndicates", "campaign360", "population360", "population360.read"),
    ("campaign360", "campaign", "cohorts_syndicates", "campaign360", "social360", "social360.read"),
    ("journey360", "journey", "recommended_actions", "episode360", "agent360", "agent360.read"),
    ("risk360", "agent", "interventions", "risk360", "agent360", "agent360.read"),
    ("workflow360", "workflow_run", "approvals", "workflow360", "agent360", "agent360.read"),
    ("workflow360", "workflow_run", "actions", "workflow360", "agent360", "agent360.read"),
    ("workflow360", "workflow_run", "actions", "workflow360", "commerce360", "commerce360.read"),
    ("agent360", "agent", "risk_summary", "agent360", "social360", "social360.read"),
])
async def test_nested_authority_requires_exact_allowed_slot(surface, kind, slot, consumer, target, capability):
    seen = []
    subject = ProjectionSubject(kind=kind, id="subject-1")
    request = Experience360FrameRequest(surfaceId=surface, tenantId="tenant-a", subject=subject, requestedSlotIds=[slot])

    class Policy:
        def __init__(self, state):
            self.state = state

        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId=surface, tenantId="tenant-a", evaluatedAt="2026-10-27T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={slot: Experience360PolicyDisposition(
                    state=self.state, policyIds=["policy-1"], evaluatedAt="2026-10-27T10:00:00Z"
                )},
            )

        async def evaluate_profile_prediction_outcome_read(self, frame_request):
            return Experience360PolicyDisposition(
                state="allowed",
                policyIds=["outcomes-policy"],
                evaluatedAt="2026-10-27T10:00:00Z",
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend(kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId, tenantId="tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-10-27T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=Policy("allowed"), projection_runtime=Runtime())
    matches = [item for item in seen if item.sourceSlotId == slot and item.consumerProjectionId == consumer
               and item.targetProjectionId == target]
    assert len(matches) == 1
    assert (matches[0].targetProjectionId, matches[0].capabilityKey) == (target, capability)
    assert matches[0].sourceSubject == subject and matches[0].tenantId == "tenant-a"
    if surface == "journey360":
        assert not any(item.targetProjectionId == "episode360" for item in seen)
    seen.clear()
    await build_experience360_frame(request, policy_evaluator=Policy("denied"), projection_runtime=Runtime())
    assert not seen


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome_state,expected", [("allowed", True), ("denied", False), ("error", False)])
async def test_profile_outcome_read_requires_independent_outcomes_permission(outcome_state, expected):
    seen = []
    request = Experience360FrameRequest(
        surfaceId="profile360",
        tenantId="tenant-a",
        subject=ProjectionSubject(kind="entity", id="entity-1"),
        requestedSlotIds=["likely_next_states"],
    )

    class Policy:
        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId="profile360",
                tenantId="tenant-a",
                evaluatedAt="2026-10-27T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"likely_next_states": Experience360PolicyDisposition(
                    state="allowed", policyIds=["profile-policy"], evaluatedAt="2026-10-27T10:00:00Z"
                )},
            )

        async def evaluate_profile_prediction_outcome_read(self, frame_request):
            if outcome_state == "error":
                raise RuntimeError("outcome policy unavailable")
            return Experience360PolicyDisposition(
                state=outcome_state,
                policyIds=["outcomes-policy"],
                evaluatedAt="2026-10-27T10:00:00Z",
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend(kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId="tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-10-27T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=Policy(), projection_runtime=Runtime())
    outcome_authorizations = [item for item in seen if item.capabilityKey == "outcome_facts.read"]
    assert bool(outcome_authorizations) is expected
    if expected:
        authorization = outcome_authorizations[0]
        assert authorization.sourceSubject == request.subject
        assert authorization.tenantId == request.tenantId
        assert authorization.policyIds == ["outcomes-policy"]


@pytest.mark.asyncio
@pytest.mark.parametrize("slot_state,dispatch_state,expected", [
    ("allowed", "allowed", True), ("allowed", "denied", False),
    ("allowed", "error", False), ("denied", "allowed", False),
])
async def test_journey_dispatch_requires_separate_policy(slot_state, dispatch_state, expected):
    seen = []
    subject = ProjectionSubject(kind="journey", id="journey-1")
    request = Experience360FrameRequest(surfaceId="journey360", tenantId="tenant-a", subject=subject,
                                        requestedSlotIds=["recommended_actions"])

    class Policy:
        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId="journey360", tenantId="tenant-a", evaluatedAt="2026-10-27T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"recommended_actions": Experience360PolicyDisposition(
                    state=slot_state, policyIds=["slot-policy"], evaluatedAt="2026-10-27T10:00:00Z")},
            )

        async def evaluate_journey_dispatch_read(self, frame_request):
            if dispatch_state == "error":
                raise RuntimeError("unavailable")
            return Experience360PolicyDisposition(state=dispatch_state, policyIds=["actions-policy"],
                                                   evaluatedAt="2026-10-27T10:00:00Z")

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend(kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId, tenantId="tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-10-27T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=Policy(), projection_runtime=Runtime())
    dispatch = [item for item in seen if item.capabilityKey == "actions.dispatch.read"]
    assert bool(dispatch) is expected
    if expected:
        assert len(dispatch) == 1
        assert dispatch[0].tenantId == "tenant-a" and dispatch[0].sourceSubject == subject
        assert dispatch[0].policyIds == ["actions-policy"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,slot_state,behavior_state,expected", [
    ("agent", "allowed", "allowed", True), ("agent", "allowed", "denied", False),
    ("agent", "allowed", "error", False), ("agent", "denied", "allowed", False),
    ("entity", "allowed", "allowed", False),
])
async def test_agent_behavior_requires_slot_and_agent_manage(kind, slot_state, behavior_state, expected):
    seen = []
    subject = ProjectionSubject(kind=kind, id="agent-1")
    request = Experience360FrameRequest(surfaceId="agent360", tenantId="tenant-a", subject=subject,
                                        requestedSlotIds=["agent_behavior"])

    class Policy:
        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId="agent360", tenantId="tenant-a", evaluatedAt="2026-11-14T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"agent_behavior": Experience360PolicyDisposition(
                    state=slot_state, policyIds=["slot-policy"], evaluatedAt="2026-11-14T10:00:00Z")},
            )

        async def evaluate_agent_behavior_read(self, frame_request):
            if behavior_state == "error":
                raise RuntimeError("unavailable")
            return Experience360PolicyDisposition(state=behavior_state,
                                                   policyIds=["tenant_permission:agent:manage"],
                                                   evaluatedAt="2026-11-14T10:00:00Z")

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend(kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId, tenantId="tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-11-14T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=Policy(), projection_runtime=Runtime())
    behavior = [item for item in seen if item.capabilityKey == "agent_behavior"]
    assert bool(behavior) is expected
    if expected:
        [auth] = behavior
        assert auth.tenantId == "tenant-a" and auth.sourceSubject == subject
        assert auth.targetProjectionId == "agent360" and auth.consumerProjectionId == "agent360"
        assert auth.policyIds == ["tenant_permission:agent:manage"]


@pytest.mark.asyncio
@pytest.mark.parametrize("granted,tenant,expected", [
    (True, "tenant-a", "allowed"), (False, "tenant-a", "denied"), (True, "tenant-b", "denied"),
])
async def test_request_evaluator_agent_behavior_mirrors_agent_manage(monkeypatch, granted, tenant, expected):
    from types import SimpleNamespace

    from shared.intelligence_projections import policy

    monkeypatch.setattr(policy, "tenant_actor", lambda _r: SimpleNamespace(tenant_id="tenant-a"))
    state_tenant = SimpleNamespace(tenant_id=tenant, has_permission=lambda p: granted and p == "agent:manage")
    evaluator = policy.RequestAccessPolicyEvaluator(SimpleNamespace(state=SimpleNamespace(tenant=state_tenant)))
    frame = Experience360FrameRequest(surfaceId="agent360", tenantId="tenant-a",
                                      subject=ProjectionSubject(kind="agent", id="a1"),
                                      requestedSlotIds=["agent_behavior"])
    decision = await evaluator.evaluate_agent_behavior_read(frame)
    assert decision.state == expected
    with pytest.raises(ValueError):
        await evaluator.evaluate_agent_behavior_read(frame.model_copy(update={"surfaceId": "risk360"}))



@pytest.mark.asyncio
@pytest.mark.parametrize("behavior_state,expected", [("allowed", True), ("denied", False)])
async def test_profile360_agent_delegations_issue_agent_behavior_for_people(behavior_state, expected):
    seen = []
    subject = ProjectionSubject(kind="entity", id="person-1")
    request = Experience360FrameRequest(surfaceId="profile360", tenantId="tenant-a", subject=subject,
                                        requestedSlotIds=["agent_delegations"])

    class Policy:
        async def evaluate(self, frame_request):
            return Experience360PolicyEvaluation(
                surfaceId="profile360", tenantId="tenant-a", evaluatedAt="2026-11-14T10:00:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"agent_delegations": Experience360PolicyDisposition(
                    state="allowed", policyIds=["slot-policy"], evaluatedAt="2026-11-14T10:00:00Z")},
            )

        async def evaluate_agent_behavior_read(self, frame_request):
            return Experience360PolicyDisposition(state=behavior_state,
                                                   policyIds=["tenant_permission:agent:manage"],
                                                   evaluatedAt="2026-11-14T10:00:00Z")

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            seen.extend((projection_request.projectionId, a)
                        for a in kwargs.get("experience360_read_authorizations", []))
            return ProjectionResult(
                projectionId=projection_request.projectionId, tenantId="tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section, state="unknown", content={})
                          for section in projection_request.includeSections or []],
                claims=[], dependencyState=[], generatedAt="2026-11-14T10:00:00Z", degradedReasons=[],
            )

    await build_experience360_frame(request, policy_evaluator=Policy(), projection_runtime=Runtime())
    behavior = [(pid, a) for pid, a in seen if a.capabilityKey == "agent_behavior"]
    assert bool(behavior) is expected
    if expected:
        [(pid, auth)] = behavior
        assert pid == "profile360" and auth.targetProjectionId == "profile360"
        assert auth.sourceSlotId == "agent_delegations" and auth.sourceSubject == subject
