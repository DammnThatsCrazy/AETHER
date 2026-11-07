"""The Agent360 social join accepts only correlated exact-subject risk evidence."""
from __future__ import annotations

import pytest
from actions.agent.social_risk_context import read_agent_social_risk_context
from graph.operational_intelligence.models import EvidenceRef
from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import ClaimEnvelope, ProjectionResult, ProjectionSection, ProjectionSubject
from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["valid", "foreign_subject", "missing_signal", "suppressed", "foreign_tenant"])
async def test_social_risk_context_admits_only_exact_correlated_evidence(mode):
    refs = [EvidenceRef(id="edge-1", type="relationship", source="entity_graph"),
            EvidenceRef(id="fact-1", type="event", source="relationship_facts"),
            EvidenceRef(id="risk-1", type="model_output", source="risk_signals:risk360")]
    if mode == "missing_signal": refs.pop()
    class Provider:
        async def project(self, request, context):
            assert request.subject == ProjectionSubject(kind="entity", id="agent-entity")
            assert request.includeSections == ["risk_edges"]
            return ProjectionResult(projectionId="social360", tenantId="foreign" if mode == "foreign_tenant" else "tenant-a",
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id="risk_edges", state="suppressed" if mode == "suppressed" else "available", content={})],
                claims=[ClaimEnvelope(id="risk-edge-1", kind="social_risk_context_edge_association",
                    subject=ProjectionSubject(kind="entity", id="other" if mode == "foreign_subject" else "agent-entity"),
                    evidenceRefs=refs, claims=["correlation"], claimState=EpistemicStatus.CORRELATED,
                    domainSlotIds=["risk_edges"])], dependencyState=[], generatedAt="2026-10-18T00:00:00Z", degradedReasons=[])
    rows = await read_agent_social_risk_context(tenant_id="tenant-a", canonical_agent_id="agent-entity", provider=Provider())
    assert len(rows) == (1 if mode == "valid" else 0)
