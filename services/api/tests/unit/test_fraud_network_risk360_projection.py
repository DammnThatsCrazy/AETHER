"""Agentic fraud-network detections converge into canonical agent Risk360."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from intelligence.fraud_networks.detectors import detect_agentic_delegation_abuse  # noqa: E402
from intelligence.fraud_networks.evidence import build_evidence_refs  # noqa: E402
from intelligence.fraud_networks.risk360_projection import (  # noqa: E402
    persist_agentic_delegation_assessments,
)
from intelligence.risk360.contracts import EpistemicStatus  # noqa: E402
from intelligence.risk360.provider import Risk360Provider  # noqa: E402
from intelligence.risk360.store import RiskAssessmentRepository, RiskSignalRepository  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)


@pytest.mark.asyncio
async def test_agentic_delegation_detection_persists_and_reads_through_risk360() -> None:
    reset_in_memory_stores()
    tenant_id = "tenant-agentic-risk-integration"
    agent_id = "agent-risk-hub"
    observed_at = "2026-10-18T12:30:00+00:00"
    detector_results = detect_agentic_delegation_abuse(
        delegations=[
            {"agent_id": agent_id, "principal_id": "principal-1"},
            {"agent_id": agent_id, "principal_id": "principal-2"},
        ],
        transfers=[
            {
                "attributed_agent_id": agent_id,
                "to_entity_id": f"target-{index}",
            }
            for index in range(5)
        ],
    )
    assert len(detector_results) == 1
    network_evidence = build_evidence_refs(
        detector_results,
        network_id="network-agent-risk",
        tenant_id=tenant_id,
        observed_at=observed_at,
    )

    class AgentIdentityReader:
        async def actor_identity(self, requested_tenant: str, source_agent_ref: str):
            assert (requested_tenant, source_agent_ref) == (tenant_id, agent_id)

            class Batch:
                rows = [
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "canonical_agent_entity_id": "canonical-agent-risk-hub",
                        "identity_evidence_id": "agent-binding-risk-hub",
                        "identity_evidence_source": "agent_deployment_identity_bindings",
                        "identity_bound_at": "2026-10-17T12:00:00+00:00",
                    }
                ]
                truncated = False
                scope_mismatch = False

            return Batch()

    persisted = await persist_agentic_delegation_assessments(
        tenant_id=tenant_id,
        detector_results=detector_results,
        evidence_refs=network_evidence,
        observed_at=observed_at,
        agent_identity_reader=AgentIdentityReader(),
    )

    assert persisted == 1
    stored_assessments = await RiskAssessmentRepository().list_by_subject(
        tenant_id, "agent", "canonical-agent-risk-hub"
    )
    stored_signals = await RiskSignalRepository().list_by_subject(
        tenant_id, "agent", "canonical-agent-risk-hub"
    )
    assert len(stored_assessments) == 1
    assert stored_assessments[0]["exposure"] is None
    assert stored_assessments[0]["vector"]["components"][0]["score"] is None
    assert len(stored_signals) == 1
    assert stored_signals[0]["risk_dimension"] == "agentic"
    assert stored_signals[0]["claim_state"] == EpistemicStatus.INFERRED.value
    assert stored_signals[0]["score"] is None
    assert stored_signals[0]["evidence_refs"][0]["id"] == network_evidence[0].id
    assert stored_signals[0]["evidence_refs"][0]["source"] == network_evidence[0].source
    assert stored_signals[0]["evidence_refs"][1]["id"] == "agent-binding-risk-hub"
    assert stored_signals[0]["evidence_refs"][1]["source"] == "agent_deployment_identity_bindings"

    request = ProjectionRequest(
        projectionId="risk360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind="agent", id="canonical-agent-risk-hub"),
    )
    context = ProjectionContext(
        projectionId="risk360",
        tenantId=tenant_id,
        registryState="implemented",
        dependencyState=[],
        warnings=[],
    )
    result = await Risk360Provider().project(request, context)

    evidence_section = next(section for section in result.sections if section.id == "evidence")
    assert evidence_section.state == "available"
    evidence_rows = evidence_section.content["evidence"]
    assert any(row["id"] == network_evidence[0].id for row in evidence_rows)
    state_section = next(section for section in result.sections if section.id == "state")
    agentic_dimension = next(
        row for row in state_section.content["dimensionStates"] if row["dimension"] == "agentic"
    )
    assert agentic_dimension["score"] is None
    assert agentic_dimension["state"] == "insufficient_data"
    assert agentic_dimension["claimState"] == EpistemicStatus.UNKNOWN.value
    claims = {claim.id: claim for claim in result.claims}
    signal_claim = next(claim for claim in result.claims if claim.kind == "risk_signal_context")
    assert signal_claim.claimState == EpistemicStatus.INFERRED
    assert [ref.id for ref in signal_claim.evidenceRefs] == [
        network_evidence[0].id,
        "agent-binding-risk-hub",
    ]
    observed_source_claim = claims["risk360.health.aether.fraud.detector.delegation"]
    assert observed_source_claim.claimState == EpistemicStatus.OBSERVED
    health_section = next(section for section in result.sections if section.id == "health")
    agentic_context = health_section.content["signalContext"][0]
    assert agentic_context["dimension"] == "agentic"
    assert agentic_context["claimState"] == EpistemicStatus.INFERRED.value
    assert agentic_context["observedAt"] == observed_at
    assert agentic_context["score"] is None
    assert [ref["id"] for ref in agentic_context["evidenceRefs"]] == [
        network_evidence[0].id,
        "agent-binding-risk-hub",
    ]


@pytest.mark.parametrize(
    "identity_bound_at",
    [
        None,
        "not-a-timestamp",
        "2026-10-18T12:30:01+00:00",
    ],
    ids=["missing", "invalid", "after-detector-observation"],
)
@pytest.mark.asyncio
async def test_agentic_risk_attribution_requires_identity_binding_at_or_before_detection(
    identity_bound_at: str | None,
) -> None:
    reset_in_memory_stores()
    tenant_id = "tenant-agentic-risk-temporal"
    source_agent_ref = "source-agent-temporal"
    observed_at = "2026-10-18T12:30:00+00:00"
    detector_results = [
        (
            "agentic_delegation_abuse",
            [source_agent_ref],
            {"agent_id": source_agent_ref, "target_count": 5},
        )
    ]
    evidence = build_evidence_refs(
        detector_results,
        network_id="network-agent-risk-temporal",
        tenant_id=tenant_id,
        observed_at=observed_at,
    )

    identity_row = {
        "tenant_id": tenant_id,
        "agent_id": source_agent_ref,
        "canonical_agent_entity_id": "canonical-agent-temporal",
        "identity_evidence_id": "binding-temporal",
        "identity_evidence_source": "agent_deployment_identity_bindings",
        "identity_bound_at": identity_bound_at,
    }

    class AgentIdentityReader:
        async def actor_identity(self, requested_tenant: str, requested_agent: str):
            assert (requested_tenant, requested_agent) == (tenant_id, source_agent_ref)

            class Batch:
                rows = [identity_row]
                truncated = False
                scope_mismatch = False

            return Batch()

    persisted = await persist_agentic_delegation_assessments(
        tenant_id=tenant_id,
        detector_results=detector_results,
        evidence_refs=evidence,
        observed_at=observed_at,
        agent_identity_reader=AgentIdentityReader(),
    )

    assert persisted == 0
    assert (
        await RiskAssessmentRepository().list_by_subject(
            tenant_id, "agent", "canonical-agent-temporal"
        )
        == []
    )
    assert (
        await RiskSignalRepository().list_by_subject(
            tenant_id, "agent", "canonical-agent-temporal"
        )
        == []
    )


@pytest.mark.asyncio
async def test_unresolved_agent_reference_does_not_create_risk_subject() -> None:
    reset_in_memory_stores()
    detector_results = [
        (
            "agentic_delegation_abuse",
            ["source-agent-ref"],
            {"agent_id": "source-agent-ref", "target_count": 5},
        )
    ]
    evidence = [
        build_evidence_refs(
            detector_results,
            network_id="network-unresolved-agent",
            tenant_id="tenant-unresolved-agent",
            observed_at="2026-10-18T12:30:00+00:00",
        )[0]
    ]

    class UnresolvedIdentityReader:
        async def actor_identity(self, tenant_id: str, source_agent_ref: str):
            class Batch:
                rows = []
                truncated = False
                scope_mismatch = False

            return Batch()

    persisted = await persist_agentic_delegation_assessments(
        tenant_id="tenant-unresolved-agent",
        detector_results=detector_results,
        evidence_refs=evidence,
        observed_at="2026-10-18T12:30:00+00:00",
        agent_identity_reader=UnresolvedIdentityReader(),
    )

    assert persisted == 0
    assert (
        await RiskAssessmentRepository().list_by_subject(
            "tenant-unresolved-agent", "agent", "source-agent-ref"
        )
        == []
    )


@pytest.mark.parametrize(
    "identity_read_state",
    [
        "ambiguous_canonical_agent",
        "ambiguous_binding_evidence",
        "truncated",
        "scope_mismatch",
        "cross_tenant",
    ],
)
@pytest.mark.asyncio
async def test_incomplete_or_ambiguous_agent_identity_never_persists_risk(
    identity_read_state: str,
) -> None:
    reset_in_memory_stores()
    tenant_id = "tenant-incomplete-agent-risk"
    source_agent_ref = "source-agent-ref"
    valid_row = {
        "tenant_id": tenant_id,
        "agent_id": source_agent_ref,
        "canonical_agent_entity_id": "canonical-agent-1",
        "identity_evidence_id": "binding-1",
        "identity_evidence_source": "agent_deployment_identity_bindings",
    }
    rows = [valid_row]
    truncated = False
    scope_mismatch = False
    if identity_read_state == "ambiguous_canonical_agent":
        rows.append({**valid_row, "canonical_agent_entity_id": "canonical-agent-2"})
    elif identity_read_state == "ambiguous_binding_evidence":
        rows.append({**valid_row, "identity_evidence_id": "binding-2"})
    elif identity_read_state == "truncated":
        truncated = True
    elif identity_read_state == "scope_mismatch":
        scope_mismatch = True
    elif identity_read_state == "cross_tenant":
        rows[0] = {**valid_row, "tenant_id": "tenant-other"}

    detector_results = [
        (
            "agentic_delegation_abuse",
            [source_agent_ref],
            {"agent_id": source_agent_ref, "target_count": 5},
        )
    ]
    evidence = build_evidence_refs(
        detector_results,
        network_id="network-incomplete-agent-risk",
        tenant_id=tenant_id,
        observed_at="2026-10-18T12:30:00+00:00",
    )

    class IncompleteIdentityReader:
        async def actor_identity(self, requested_tenant: str, requested_agent: str):
            assert (requested_tenant, requested_agent) == (tenant_id, source_agent_ref)

            class Batch:
                pass

            batch = Batch()
            batch.rows = rows
            batch.truncated = truncated
            batch.scope_mismatch = scope_mismatch
            return batch

    persisted = await persist_agentic_delegation_assessments(
        tenant_id=tenant_id,
        detector_results=detector_results,
        evidence_refs=evidence,
        observed_at="2026-10-18T12:30:00+00:00",
        agent_identity_reader=IncompleteIdentityReader(),
    )

    assert persisted == 0
    for subject_id in {source_agent_ref, "canonical-agent-1", "canonical-agent-2"}:
        assert await RiskAssessmentRepository().list_by_subject(tenant_id, "agent", subject_id) == []
        assert await RiskSignalRepository().list_by_subject(tenant_id, "agent", subject_id) == []
