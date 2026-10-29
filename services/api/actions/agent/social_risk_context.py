"""Exact current Social360 risk-context evidence for a resolved Agent entity."""
from __future__ import annotations

from typing import Any

from shared.contracts_models.epistemic import EpistemicStatus
from shared.intelligence_projections.contracts import ProjectionContext, ProjectionRequest, ProjectionSubject


async def read_agent_social_risk_context(*, tenant_id: str, canonical_agent_id: str,
                                         provider: Any = None) -> list[dict[str, Any]]:
    """Return only evidence-linked correlations; never infer risk or contagion."""
    if not tenant_id or not canonical_agent_id:
        return []
    if provider is None:
        from services.social360.provider import Social360Provider
        provider = Social360Provider()
    subject = ProjectionSubject(kind="entity", id=canonical_agent_id)
    request = ProjectionRequest(projectionId="social360", tenantId=tenant_id, subject=subject,
                                includeSections=["risk_edges"], includeClaims=True)
    context = ProjectionContext(projectionId="social360", tenantId=tenant_id,
                                registryState="in_flight", dependencyState=[], warnings=[])
    result = await provider.project(request, context)
    if result.tenantId != tenant_id or result.projectionId != "social360":
        return []
    sections = [section for section in result.sections if section.id == "risk_edges"]
    if len(sections) != 1 or sections[0].state not in {"available", "degraded"}:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for claim in result.claims:
        if (claim.kind != "social_risk_context_edge_association" or claim.subject != subject
                or claim.claimState != EpistemicStatus.CORRELATED
                or "risk_edges" not in claim.domainSlotIds or not claim.evidenceRefs
                or not claim.id or claim.id in seen):
            continue
        sources = {ref.source for ref in claim.evidenceRefs}
        if ("entity_graph" not in sources or "relationship_facts" not in sources
                or not any(source.startswith("risk_signals:") for source in sources)
                or any(not ref.id or not ref.source for ref in claim.evidenceRefs)):
            continue
        rows.append({"tenant_id": tenant_id, "canonical_agent_entity_id": canonical_agent_id,
                     "social_claim_id": claim.id,
                     "evidence_refs": [ref.model_dump(mode="json") for ref in claim.evidenceRefs]})
        seen.add(claim.id)
    return rows[:100]
