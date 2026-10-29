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
    seen.clear()
    await build_experience360_frame(request, policy_evaluator=Policy("denied"), projection_runtime=Runtime())
    assert not seen
