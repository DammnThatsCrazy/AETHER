"""Slot-scoped partial composition must preserve only evidenced content."""

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

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections.composition import (  # noqa: E402
    _compose_slot_content,
    compose_experience360_frame,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    Experience360FrameRequest,
    Experience360PolicyEvaluation,
    Experience360PolicyDisposition,
    ProjectionDegradation,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from identity.account360_provider import (  # noqa: E402
    Account360Provider,
    AccountIdentityRead,
    AccountMember,
    AccountMembersRead,
)
from identity.identity.identity360_provider import (  # noqa: E402
    Identity360Result,
    Identity360Slot,
)
from identity.profile.profile360_provider import (  # noqa: E402
    IdentityBindingRead,
    Profile360Provider,
    ProfileRead,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402


TENANT = "tenant-compose-360"
SUBJECT = ProjectionSubject(kind="entity", id="entity-compose-1")
SLOT_ID = "entity_identity"
EVIDENCE = EvidenceRef(
    id="profile-event-1",
    type="event",
    source="profile360/test",
    observedAt="2026-10-16T10:00:00Z",
)


def test_explicitly_unbound_required_slot_remains_unknown_with_gap_reason() -> None:
    slot, reasons, missing = _compose_slot_content(
        slot_id="contracts",
        slot_definition={
            "id": "contracts",
            "canonicalAuthorityRefs": ["contract_registry"],
            "projectionBindings": [],
            "unboundReason": "contract_registry_provider_not_connected",
        },
        results={},
        include_evidence=True,
        tenant_id=TENANT,
        requested_as_of=None,
        subject_kind="entity",
    )

    assert slot["state"] == "unknown"
    assert slot["content"] is None
    assert "slot_provider_not_connected" in reasons
    assert "contract_registry_provider_not_connected" in slot["limitations"]
    assert missing == set()


def test_required_source_aligned_slot_needs_an_exact_evidence_backed_claim() -> None:
    definition = {
        "id": "identity_spine",
        "requirement": "required",
        "canonicalAuthorityRefs": ["identity"],
        "projectionBindings": [
            {
                "projectionId": "profile360",
                "role": "primary",
                "sectionIds": ["summary"],
                "subjectKinds": ["entity"],
            }
        ],
    }
    result = _result([
        ProjectionSection(
            id="summary",
            state="available",
            content={"evidenceRefs": [EVIDENCE.model_dump(mode="json")]},
        )
    ])
    kwargs = {
        "slot_id": "identity_spine",
        "slot_definition": definition,
        "results": {"profile360": result},
        "include_evidence": True,
        "tenant_id": TENANT,
        "requested_as_of": None,
        "subject_kind": "entity",
        "requires_exact_claim": True,
    }
    unclaimed, reasons, _ = _compose_slot_content(**kwargs)
    assert unclaimed["state"] == "unknown"
    assert unclaimed["content"] is None
    assert unclaimed["evidenceRefs"] == []
    assert "exact_slot_claim_missing" in reasons

    claim = ClaimEnvelope(
        id="profile360.identity.fixture",
        kind="canonical_identity",
        subject=SUBJECT,
        evidenceRefs=[EVIDENCE],
        claims=["Exact identity fixture."],
        domainSlotIds=["identity_spine"],
    )
    claimed = result.model_copy(update={"claims": [claim]})
    supported, reasons, _ = _compose_slot_content(
        **{**kwargs, "results": {"profile360": claimed}}
    )
    assert supported["state"] == "available"
    assert supported["claims"] == [claim]
    assert "exact_slot_claim_missing" not in reasons


def _request() -> Experience360FrameRequest:
    return Experience360FrameRequest(
        surfaceId="profile360",
        tenantId=TENANT,
        subject=SUBJECT,
        requestedSlotIds=[SLOT_ID],
        includeEvidence=True,
    )


def _result(
    sections: list[ProjectionSection],
    *,
    degradation: ProjectionDegradation | None = None,
    claims: list[ClaimEnvelope] | None = None,
) -> ProjectionResult:
    return ProjectionResult(
        projectionId="profile360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=sections,
        claims=claims or [],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        asOf="2026-10-16T10:00:00Z",
        degradedReasons=[],
        degradation=degradation,
    )


def _compose(result: ProjectionResult):
    return compose_experience360_frame(
        _request(),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-16T10:02:00Z",
    )


def test_projection_provenance_uses_only_slot_aligned_authorities() -> None:
    request = Experience360FrameRequest(
        surfaceId="risk360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id="risk-entity-1"),
        requestedSlotIds=["relationship_network_context"],
        includeEvidence=True,
    )
    relationship = ProjectionResult(
        projectionId="relationship360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id=section_id,
                state="available",
                content={"evidenceRefs": [EVIDENCE]},
            )
            for section_id in ("summary", "interactions", "evidence")
        ],
        claims=[],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        degradedReasons=[],
    )
    risk = ProjectionResult(
        projectionId="risk360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id=section_id,
                state="available",
                content={"evidenceRefs": [EVIDENCE]},
            )
            for section_id in ("summary", "evidence")
        ],
        claims=[],
        dependencyState=[],
        generatedAt="2026-10-16T10:01:00Z",
        degradedReasons=[],
    )

    frame = compose_experience360_frame(
        request,
        [relationship, risk],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-16T10:02:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "available"
    authority_refs_by_projection = {
        item.projectionId: set(item.canonicalAuthorityRefs)
        for item in slot.provenance
        if item.sourceKind == "section"
    }
    assert authority_refs_by_projection == {
        "relationship360": {"graph", "relationship_facts"},
        "risk360": {"entity_graph"},
    }


def test_degraded_sibling_section_keeps_evidenced_slot_content() -> None:
    claim = ClaimEnvelope(
        id="profile-claim-1",
        kind="identity_observation",
        subject=SUBJECT,
        evidenceRefs=[EVIDENCE],
        claims=["The entity has an observed profile record."],
        domainSlotIds=[SLOT_ID],
    )
    frame = _compose(
        _result(
            [
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={"entityId": SUBJECT.id, "evidenceRefs": [EVIDENCE]},
                ),
                ProjectionSection(id="state", state="degraded"),
            ],
            degradation=ProjectionDegradation(level="partial", reasons=["dependency_unavailable"]),
            claims=[claim],
        )
    )

    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert [section["sectionId"] for section in slot.content["sections"]] == ["summary"]
    assert [item.id for item in slot.claims] == [claim.id]
    assert {item.id for item in slot.evidenceRefs} == {EVIDENCE.id}
    assert {item.sectionId for item in slot.provenance if item.sourceKind == "section"} == {
        "summary",
        "state",
    }
    assert "slot_contains_partial_evidence" in slot.reasonCodes
    assert frame.state == "partial"


def test_partial_degradation_outside_bound_sections_does_not_taint_slot() -> None:
    frame = _compose(
        _result(
            [
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={"entityId": SUBJECT.id, "evidenceRefs": [EVIDENCE]},
                ),
                ProjectionSection(id="state", state="available", content={"status": "active"}),
                ProjectionSection(id="timeline", state="degraded"),
            ],
            degradation=ProjectionDegradation(
                level="partial", reasons=["unbound_timeline_dependency_unavailable"]
            ),
        )
    )

    slot = frame.slots[0]
    assert slot.state == "available"
    assert slot.content is not None
    assert "projection_provider_degraded" not in slot.reasonCodes
    assert "unbound_timeline_dependency_unavailable" not in slot.reasonCodes


def test_suppressed_bound_source_closes_aggregate_slot() -> None:
    frame = _compose(
        _result(
            [
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={"entityId": SUBJECT.id, "evidenceRefs": [EVIDENCE]},
                ),
                ProjectionSection(id="state", state="suppressed"),
            ]
        )
    )

    slot = frame.slots[0]
    assert slot.state == "suppressed"
    assert slot.content is None
    assert slot.claims == []
    assert slot.evidenceRefs == []
    assert "bound_source_policy_suppressed" in slot.reasonCodes


def test_claim_subject_must_match_the_requested_frame_subject() -> None:
    claim = ClaimEnvelope(
        id="wrong-subject-claim",
        kind="identity_observation",
        subject=ProjectionSubject(kind="entity", id="other-entity"),
        evidenceRefs=[EVIDENCE],
        claims=["This claim belongs to a different entity."],
        domainSlotIds=[SLOT_ID],
    )

    with pytest.raises(ProjectionError, match="claim subject"):
        _compose(
            _result(
                [
                    ProjectionSection(
                        id="summary",
                        state="available",
                        content={"entityId": SUBJECT.id, "evidenceRefs": [EVIDENCE]},
                    ),
                    ProjectionSection(id="state", state="available", content={"status": "active"}),
                ],
                claims=[claim],
            )
        )


def test_binding_for_an_unsupported_subject_stays_unknown_without_missing_dependency() -> None:
    request = Experience360FrameRequest(
        surfaceId="workflow360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="workflow", id="workflow-1"),
        requestedSlotIds=["runs"],
        includeEvidence=True,
    )
    frame = compose_experience360_frame(
        request,
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-16T10:02:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "unknown"
    assert slot.content is None
    assert "projection_binding_subject_kind_unsupported" in slot.reasonCodes
    assert frame.degradation.missingDependencies is None


@pytest.mark.asyncio
async def test_frame_runtime_does_not_execute_provider_for_unsupported_binding_subject() -> None:
    calls: list[str] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "runs": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, *args, **kwargs):
            calls.append("executed")
            raise AssertionError("unsupported provider must not execute")

    request = Experience360FrameRequest(
        surfaceId="workflow360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="workflow", id="workflow-1"),
        requestedSlotIds=["runs"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-16T10:02:00Z",
    )

    assert calls == []
    assert frame.slots[0].state == "unknown"
    assert "projection_binding_subject_kind_unsupported" in frame.slots[0].reasonCodes


@pytest.mark.asyncio
async def test_frame_runtime_routes_journey_subject_to_episode360() -> None:
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "events_and_episode_context": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            section_ids = tuple(request.includeSections or [])
            calls.append((request.projectionId, request.subject.kind, section_ids))
            sections = [
                ProjectionSection(
                    id=section_id,
                    state="available",
                    content={"evidenceRefs": [EVIDENCE]},
                )
                for section_id in section_ids
            ]
            return ProjectionResult(
                projectionId=request.projectionId,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=sections,
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-16T10:02:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="journey360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="journey", id="journey-1"),
        requestedSlotIds=["events_and_episode_context"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-16T10:02:00Z",
    )

    assert len(calls) == 1
    assert calls[0][0:2] == ("episode360", "journey")
    assert set(calls[0][2]) == {"evidence", "timeline"}
    assert frame.slots[0].state == "available"


@pytest.mark.asyncio
async def test_signals360_unjoined_risk_flags_do_not_query_risk360() -> None:
    projection_calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"risk_flags": Experience360PolicyDisposition(state="allowed")},
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(projection_request.includeSections or ())
            projection_calls.append(
                (projection_request.projectionId, projection_request.subject.id, section_ids)
            )
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE], "status": "observed"},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-18T10:02:00Z",
                asOf="2026-10-18T10:00:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="signals360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="signal", id="signal-1"),
        requestedSlotIds=["risk_flags"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
    )

    assert projection_calls == []
    assert frame.slots[0].state == "unknown"
    assert "slot_provider_not_connected" in frame.slots[0].reasonCodes
    assert frame.slots[0].evidenceRefs == []


@pytest.mark.asyncio
async def test_agent360_risk_slot_routes_agent_subject_to_canonical_risk360() -> None:
    calls: list[tuple[str, str, tuple[str, ...]]] = []
    risk_claim = ClaimEnvelope(
        id="risk360.agent-assessment-1",
        kind="risk_assessment",
        subject=ProjectionSubject(kind="agent", id="agent-frame-1"),
        evidenceRefs=[EVIDENCE],
        claims=["Canonical Risk360 assessment evidence is available for this agent."],
        domainSlotIds=["risk_summary"],
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "risk_summary": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            section_ids = tuple(request.includeSections or [])
            calls.append((request.projectionId, request.subject.kind, section_ids))
            sections = [
                ProjectionSection(
                    id=section_id,
                    state="available",
                    content={"evidenceRefs": [EVIDENCE]},
                )
                for section_id in section_ids
            ]
            return ProjectionResult(
                projectionId=request.projectionId,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=sections,
                claims=[risk_claim] if request.projectionId == "risk360" else [],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id="agent-frame-1"),
        requestedSlotIds=["risk_summary"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:30:00Z",
    )

    assert calls == [("risk360", "agent", ("evidence", "findings"))]
    assert frame.slots[0].state == "degraded"
    assert "slot_canonical_authority_gap" in frame.slots[0].reasonCodes
    assert "exact_subject_authority_join_not_implemented" in frame.slots[0].reasonCodes
    risk_payload = next(
        payload
        for payload in frame.slots[0].content["sections"]
        if payload["projectionId"] == "risk360"
    )
    risk_evidence = risk_payload["content"]["evidenceRefs"][0]
    assert risk_evidence.id == EVIDENCE.id
    assert risk_evidence.source == EVIDENCE.source
    assert [claim.id for claim in frame.slots[0].claims] == [risk_claim.id]
    assert frame.slots[0].claims[0].evidenceRefs == [EVIDENCE]
    assert EVIDENCE in frame.slots[0].evidenceRefs


def test_partial_financial_contagion_claim_does_not_complete_risk_slot() -> None:
    subject = ProjectionSubject(kind="contagion_path", id="path-1")
    request = Experience360FrameRequest(
        surfaceId="risk360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["financial_contagion"],
        includeEvidence=True,
    )
    result = ProjectionResult(
        projectionId="risk360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="findings",
                state="available",
                content={"evidenceRefs": [EVIDENCE]},
            )
        ],
        claims=[
            ClaimEnvelope(
                id="risk360.path-1.transfer-risk-link",
                kind="financial_flow_risk_link",
                subject=subject,
                evidenceRefs=[EVIDENCE],
                claims=["A transfer path and risk evidence are linked."],
                domainSlotIds=["financial_contagion"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-18T12:30:00Z",
        degradedReasons=[],
    )

    slot = compose_experience360_frame(
        request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    ).slots[0]

    assert slot.state == "degraded"
    assert "slot_partial_implementation" in slot.reasonCodes
    assert "causal_contagion_exposure_and_loss_model_not_available" in slot.reasonCodes
    assert slot.evidenceRefs == [EVIDENCE]


def test_value_conversion_inventory_routes_exact_conversion_claim_with_partial_state() -> None:
    subject = ProjectionSubject(kind="conversion", id="conversion-1")
    conversion_ref = EvidenceRef(
        id="conversion-1",
        type="transaction",
        source="canonical_conversions",
        observedAt="2026-10-18T12:00:00Z",
        uri="store://canonical_conversions/conversion-1",
    )
    request = Experience360FrameRequest(
        surfaceId="value360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["conversion_inventory"],
        includeEvidence=True,
    )
    result = ProjectionResult(
        projectionId="economic360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="evidence",
                state="available",
                content={"conversion_inventory": {"evidenceRefs": [conversion_ref]}},
            )
        ],
        claims=[
            ClaimEnvelope(
                id="economic360.conversion-1.inventory",
                kind="canonical_conversion_inventory",
                subject=subject,
                evidenceRefs=[conversion_ref],
                claims=["The canonical conversion row is linked to this exact subject."],
                domainSlotIds=["conversion_inventory", "evidence_trace"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-18T12:30:00Z",
        degradedReasons=[],
    )

    slot = compose_experience360_frame(
        request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
    ).slots[0]

    assert slot.state == "degraded"
    assert "slot_partial_implementation" in slot.reasonCodes
    assert "value_subject_wallet_cluster_and_historical_inventory_joins_not_available" in slot.reasonCodes
    assert [claim.kind for claim in slot.claims] == ["canonical_conversion_inventory"]
    assert slot.evidenceRefs == [conversion_ref]


def test_agent360_value_slot_preserves_cost_evidence_and_unknown_freshness():
    subject = ProjectionSubject(kind="agent", id="agent-cost-frame-1")
    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["economic_cost_and_settlement"],
        includeEvidence=True,
    )
    cost_evidence = EvidenceRef(
        id="agent-invocation-cost-1",
        type="event",
        source="services/api/value/economic/ai_aggregation",
        observedAt="2026-10-18T10:00:00Z",
        uri="store://ai_execution_facts/agent-invocation-cost-1",
    )
    result = ProjectionResult(
        projectionId="economic360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="summary",
                state="available",
                content={
                    "metrics": {
                        "ai_execution_cost": {
                            "metricName": "agent_execution_cost",
                            "usd_value": "1.25",
                            "observedAt": {
                                "field": "observed_at",
                                "timestampCount": 1,
                                "timestampCoverage": 1.0,
                                "oldest": "2026-10-18T10:00:00Z",
                                "latest": "2026-10-18T10:00:00Z",
                            },
                            "freshness": {
                                "state": "unknown",
                                "reason": "freshness_threshold_not_configured",
                            },
                        }
                    }
                },
            ),
            ProjectionSection(
                id="evidence",
                state="available",
                content={"evidence": [cost_evidence]},
            ),
        ],
        claims=[
            ClaimEnvelope(
                id="agent-cost-claim",
                kind="agent_execution_cost_observation",
                subject=subject,
                evidenceRefs=[cost_evidence],
                claims=["A measured agent execution cost was observed."],
                domainSlotIds=["economic_cost_and_settlement"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-18T10:01:00Z",
        degradedReasons=[],
    )

    frame = compose_experience360_frame(
        request,
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-18T10:02:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "available"
    assert slot.freshness.state == "unknown"
    assert slot.evidenceRefs[0].observedAt == "2026-10-18T10:00:00Z"
    assert "freshness_threshold_not_configured" in slot.reasonCodes
    summary = next(
        section["content"]
        for section in slot.content["sections"]
        if section["sectionId"] == "summary"
    )
    assert summary["metrics"]["ai_execution_cost"]["metricName"] == "agent_execution_cost"


@pytest.mark.asyncio
async def test_account360_resolves_canonical_entity_before_projection_reads() -> None:
    projection_calls: list[str] = []
    identity_calls: list[tuple[str, str]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "account_identity_and_state": Experience360PolicyDisposition(state="allowed")
                },
            )

    class AccountSource:
        async def canonical_entity(self, tenant_id: str, entity_id: str):
            identity_calls.append((tenant_id, entity_id))
            return AccountIdentityRead("missing", "account_entity_identity_unresolved")

    class Runtime:
        async def execute_projection(self, *args, **kwargs):
            projection_calls.append("executed")
            raise AssertionError("account identity must resolve before projection reads")

    request = Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id="account-1"),
        requestedSlotIds=["account_identity_and_state"],
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        account360_provider=Account360Provider(AccountSource()),
    )

    assert identity_calls == [(TENANT, "account-1")]
    assert projection_calls == []
    assert frame.slots[0].state == "unknown"
    assert "account_entity_identity_unresolved" in frame.slots[0].reasonCodes
    assert "account_entity_identity_unresolved" in frame.warnings


@pytest.mark.asyncio
async def test_account360_composes_sibling_projection_after_identity_resolution() -> None:
    projection_calls: list[tuple[str, str, tuple[str, ...]]] = []
    identity_calls: list[tuple[str, str]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "account_identity_and_state": Experience360PolicyDisposition(state="allowed")
                },
            )

    class AccountSource:
        async def canonical_entity(self, tenant_id: str, entity_id: str):
            identity_calls.append((tenant_id, entity_id))
            return AccountIdentityRead(
                "resolved",
                evidence_refs=(
                    EvidenceRef(
                        id=entity_id,
                        type="entity",
                        source="entity_registry",
                        observedAt="2026-10-16T10:00:00Z",
                    ),
                ),
                entity_type="organization",
                tenant_id=tenant_id,
                entity_id=entity_id,
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(projection_request.includeSections or ())
            projection_calls.append(
                (projection_request.projectionId, projection_request.subject.id, section_ids)
            )
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE]},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-16T10:02:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id="account-1"),
        requestedSlotIds=["account_identity_and_state"],
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        account360_provider=Account360Provider(AccountSource()),
    )

    assert identity_calls == [(TENANT, "account-1")]
    assert projection_calls == [("profile360", "account-1", ("state", "summary"))]
    assert frame.slots[0].state == "degraded"
    assert frame.slots[0].content["canonicalEntity"]["entityType"] == "organization"
    assert frame.slots[0].content["accountState"]["state"] == "unknown"
    assert "account_lifecycle_state_not_exposed_by_entity_registry" in frame.slots[0].limitations
    assert frame.slots[0].provenance
    assert frame.slots[0].evidenceRefs


@pytest.mark.asyncio
async def test_identity360_scopes_direct_authority_reads_and_attaches_lineage() -> None:
    authority_calls: list[tuple[str, str, str, frozenset[str] | None]] = []
    projection_calls: list[tuple[str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "identifier_inventory": Experience360PolicyDisposition(state="allowed")
                },
            )

    class IdentityProvider:
        async def read(self, tenant_id, subject_kind, subject_id, *, requested_slot_ids=None):
            authority_calls.append(
                (
                    tenant_id,
                    subject_kind,
                    subject_id,
                    frozenset(requested_slot_ids) if requested_slot_ids is not None else None,
                )
            )
            return Identity360Result(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="available",
                slots=(
                    Identity360Slot(
                        id="identifier_inventory",
                        state="available",
                        content={
                            "state": "available",
                            "canonicalEntity": {"id": subject_id, "kind": "human"},
                        },
                        evidence_refs=(
                            EvidenceRef(
                                id="identity-subject-1",
                                type="entity",
                                source="identity_subjects",
                                observedAt="2026-10-16T10:00:00Z",
                            ),
                        ),
                    ),
                ),
                generated_at="2026-10-16T10:01:00Z",
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(projection_request.includeSections or ())
            projection_calls.append((projection_request.projectionId, section_ids))
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE]},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-16T10:02:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="identity360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id="identity-entity-1"),
        requestedSlotIds=["identifier_inventory"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        identity360_provider=IdentityProvider(),
    )

    assert authority_calls == [
        (TENANT, "entity", "identity-entity-1", frozenset({"identifier_inventory"}))
    ]
    assert projection_calls == []
    slot = frame.slots[0]
    authority = [item for item in slot.provenance if item.sourceKind == "authority"]
    assert len(authority) == 1, (
        slot.id,
        slot.state,
        slot.policyDisposition.state,
        slot.reasonCodes,
        slot.provenance,
        frame.warnings,
    )
    assert set(authority[0].canonicalAuthorityRefs) == {
        "identity",
        "source_provenance",
        "evidence",
    }
    assert [item.id for item in authority[0].evidenceRefs] == ["identity-subject-1"]
    assert slot.content["identityAuthorityRead"]["content"]["canonicalEntity"]["id"] == (
        "identity-entity-1"
    )


@pytest.mark.asyncio
async def test_identity360_preserves_partial_direct_authority_slot_state() -> None:
    evidence = EvidenceRef(
        id="wallet-proof-1",
        type="annotation",
        source="identity_verification_evidence",
        observedAt="2026-10-16T10:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "wallets": Experience360PolicyDisposition(state="allowed")
                },
            )

    class IdentityProvider:
        async def read(self, tenant_id, subject_kind, subject_id, *, requested_slot_ids=None):
            return Identity360Result(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="partial",
                slots=(
                    Identity360Slot(
                        id="wallets",
                        state="partial",
                        content={
                            "state": "partial",
                            "ownershipState": "unknown",
                            "currentControl": "unknown",
                        },
                        evidence_refs=(evidence,),
                    ),
                ),
                generated_at="2026-10-16T10:01:00Z",
            )

    class Runtime:
        async def execute_projection(self, *args, **kwargs):
            raise AssertionError("the direct Identity360 provider owns the requested slot")

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="identity360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="entity", id="identity-entity-1"),
            requestedSlotIds=["wallets"],
            includeEvidence=True,
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        identity360_provider=IdentityProvider(),
    )

    slot = frame.slots[0]
    assert frame.state == "partial"
    assert slot.state == "partial"
    assert slot.content["identityAuthorityRead"]["state"] == "partial"
    assert slot.content["identityAuthorityRead"]["content"]["currentControl"] == "unknown"
    assert [(item.source, item.id) for item in slot.evidenceRefs] == [
        ("identity_verification_evidence", "wallet-proof-1")
    ]


@pytest.mark.asyncio
async def test_identity360_source_subject_uses_identity_record_not_provider_source_id() -> None:
    authority_calls: list[tuple[str, str, str, frozenset[str] | None]] = []
    projection_calls: list[str] = []
    source_evidence = EvidenceRef(
        id="source-identity-claim-1",
        type="annotation",
        source="identity_claims",
        observedAt="2026-10-18T12:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    slot_id: Experience360PolicyDisposition(state="allowed")
                    for slot_id in (
                        "identifier_inventory",
                    )
                },
            )

    class IdentityProvider:
        async def read(self, tenant_id, subject_kind, subject_id, *, requested_slot_ids=None):
            authority_calls.append(
                (
                    tenant_id,
                    subject_kind,
                    subject_id,
                    frozenset(requested_slot_ids) if requested_slot_ids is not None else None,
                )
            )
            return Identity360Result(
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                state="partial",
                slots=(
                    Identity360Slot(
                        id="identifier_inventory",
                        state="available",
                        content={
                            "state": "available",
                            "subject": {"kind": "source", "id": subject_id},
                            "canonicalEntity": {"id": "canonical-entity-1", "kind": "human"},
                            "resolution": {"state": "resolved", "exactIdMatch": False},
                        },
                        evidence_refs=(source_evidence,),
                    ),
                ),
                generated_at="2026-10-18T12:00:00Z",
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            projection_calls.append(projection_request.projectionId)
            raise AssertionError("source identity records must not be queried as provider sources")

    requested_slots = ["identifier_inventory"]
    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="identity360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="source", id="source-record-1"),
            requestedSlotIds=requested_slots,
            includeEvidence=True,
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        identity360_provider=IdentityProvider(),
        generated_at="2026-10-18T12:30:00Z",
    )

    assert authority_calls == [(TENANT, "source", "source-record-1", frozenset(requested_slots))]
    assert projection_calls == []
    slots = {slot.id: slot for slot in frame.slots}
    assert slots["identifier_inventory"].state == "available"
    assert (
        slots["identifier_inventory"].content["identityAuthorityRead"]["content"][
            "canonicalEntity"
        ]["id"]
        == "canonical-entity-1"
    )


@pytest.mark.asyncio
async def test_agent360_partial_request_does_not_attach_unrequested_actor_metadata() -> None:
    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-16T10:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "identity": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE]},
                    )
                    for section_id in projection_request.includeSections or []
                ],
                claims=[
                    ClaimEnvelope(
                        id="agent360.identity.fixture",
                        kind="canonical_agent_identity",
                        subject=projection_request.subject,
                        evidenceRefs=[EVIDENCE],
                        claims=["An exact agent identity fixture is present."],
                        domainSlotIds=["identity"],
                    )
                ] if projection_request.projectionId == "agent360" else [],
                dependencyState=[],
                generatedAt="2026-10-16T10:02:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id="agent-partial-1"),
        requestedSlotIds=["identity"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
    )

    assert len(frame.slots) == 1
    assert frame.slots[0].id == "identity"
    assert frame.slots[0].state == "available"
    assert frame.slots[0].actorAttribution is None


@pytest.mark.asyncio
async def test_social360_population_frame_routes_relationship_and_social_authorities() -> None:
    calls: list[tuple[str, str, tuple[str, ...]]] = []
    requested_slots = ["relationship_graph", "social_observations_and_sources"]

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    slot_id: Experience360PolicyDisposition(state="allowed")
                    for slot_id in requested_slots
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            calls.append(
                (projection_request.projectionId, projection_request.subject.kind, section_ids)
            )
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE]},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                asOf="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="social360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="population", id="population-frame-1"),
        requestedSlotIds=requested_slots,
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
    )

    assert calls == [
        ("relationship360", "population", ("evidence", "interactions", "summary")),
        ("social360", "population", ("evidence", "interactions", "summary", "timeline")),
    ]
    assert {slot.id: slot.state for slot in frame.slots} == {
        "relationship_graph": "available",
        "social_observations_and_sources": "available",
    }
    assert all(slot.provenance for slot in frame.slots)


@pytest.mark.asyncio
async def test_social360_source_frame_routes_identity_bound_relationship_and_social_authorities() -> (
    None
):
    calls: list[tuple[str, str, tuple[str, ...]]] = []
    requested_slots = ["relationship_graph", "social_observations_and_sources"]

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    slot_id: Experience360PolicyDisposition(state="allowed")
                    for slot_id in requested_slots
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            calls.append(
                (projection_request.projectionId, projection_request.subject.kind, section_ids)
            )
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [EVIDENCE]},
                    )
                    for section_id in section_ids
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="social360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="source", id="source-1"),
        requestedSlotIds=requested_slots,
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
    )

    assert calls == [
        ("relationship360", "source", ("evidence", "interactions", "summary")),
        ("social360", "source", ("evidence", "interactions", "summary", "timeline")),
    ]
    assert {slot.id: slot.state for slot in frame.slots} == {
        "relationship_graph": "available",
        "social_observations_and_sources": "available",
    }
    assert all(slot.provenance for slot in frame.slots)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject_kind,subject_id",
    [("agent", "agent-temporal-1"), ("execution", "execution-temporal-1")],
)
async def test_execution360_frame_routes_plan_steps_for_agent_and_exact_execution_subjects(
    subject_kind: str,
    subject_id: str,
) -> None:
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "plan_steps": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            calls.append(
                (projection_request.projectionId, projection_request.subject.kind, section_ids)
            )
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="unknown" if section_id == "episode_context" else "available",
                        content=(
                            {"state": "unknown", "evidenceRefs": []}
                            if section_id == "episode_context"
                            else {"evidenceRefs": [EVIDENCE]}
                        ),
                    )
                    for section_id in section_ids
                ],
                claims=[
                    ClaimEnvelope(
                        id="execution360.plan_steps.fixture",
                        kind="execution_linked_plan_step",
                        subject=projection_request.subject,
                        evidenceRefs=[EVIDENCE],
                        claims=["An exact execution plan step fixture is present."],
                        domainSlotIds=["plan_steps"],
                    )
                ] if projection_request.projectionId == "execution360" else [],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        requestedSlotIds=["plan_steps"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
    )

    assert {(projection_id, routed_kind) for projection_id, routed_kind, _ in calls} == {
        ("execution360", subject_kind),
    }
    execution_sections = next(
        sections for projection_id, _, sections in calls if projection_id == "execution360"
    )
    assert set(execution_sections) == {
        "episode_context",
        "evidence",
        "state",
        "summary",
        "timeline",
    }
    assert frame.slots[0].state == "degraded"
    assert "slot_contains_partial_evidence" in frame.slots[0].reasonCodes
    assert frame.slots[0].evidenceRefs == [EVIDENCE]


@pytest.mark.asyncio
async def test_journey360_entity_context_composes_exact_linked_user_profile() -> None:
    profile_id = "user-profile-journey-1"

    class Source:
        async def identity_binding(self, tenant_id, subject):
            assert (tenant_id, subject.kind, subject.id) == (TENANT, "journey", "journey-1")
            return IdentityBindingRead(
                tenant_id=tenant_id,
                resolved_subject=ProjectionSubject(kind="entity", id=profile_id),
                evidence_ref=EvidenceRef(
                    id="journey-version-1",
                    type="relationship",
                    source="journey_versions",
                    observedAt="2026-10-18T10:00:00Z",
                ),
                authority="journey_versions",
                relationship="journey_profile_id",
                observed_at="2026-10-18T10:00:00Z",
                available=True,
                scope_known=True,
            )

        async def identity_record(self, tenant_id, subject):
            assert (tenant_id, subject.kind, subject.id) == (TENANT, "entity", profile_id)
            return ProfileRead(
                record={
                    "tenant_id": tenant_id,
                    "user_id": profile_id,
                    "status": "active",
                    "updated_at": "2026-10-18T10:00:00Z",
                },
                available=True,
                scope_known=True,
            )

    class Policy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "entity_context": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            context = await ProviderRegistry().build_context("profile360", projection_request)
            return await Profile360Provider(Source()).project(projection_request, context)

    request = Experience360FrameRequest(
        surfaceId="journey360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="journey", id="journey-1"),
        requestedSlotIds=["entity_context"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=Policy(),
        projection_runtime=Runtime(),
    )

    slot = frame.slots[0]
    assert frame.subject == ProjectionSubject(kind="journey", id="journey-1")
    assert slot.state == "available"
    assert {item.id for item in slot.evidenceRefs} == {
        "journey-version-1",
        profile_id,
    }
    summary = next(section for section in slot.content["sections"] if section["sectionId"] == "summary")
    assert summary["content"]["subject"] == {"kind": "journey", "id": "journey-1"}
    assert summary["content"]["relatedEntityContext"]["resolvedEntity"]["id"] == profile_id
    assert {
        tuple(item.canonicalAuthorityRefs)
        for item in slot.provenance
        if item.sourceKind == "section"
    } == {("identity", "journeys")}


@pytest.mark.asyncio
async def test_episode360_entity_context_joins_exact_user_and_episode_evidence() -> None:
    profile_id = "user-profile-episode-1"
    episode_evidence = EvidenceRef(
        id="episode-event-1",
        type="event",
        source="episode_records",
        observedAt="2026-10-18T10:10:00Z",
    )

    class Source:
        async def identity_binding(self, tenant_id, subject):
            assert (tenant_id, subject.kind, subject.id) == (TENANT, "episode", "episode-1")
            return IdentityBindingRead(
                tenant_id=tenant_id,
                resolved_subject=ProjectionSubject(kind="entity", id=profile_id),
                evidence_ref=EvidenceRef(
                    id="episode-1",
                    type="relationship",
                    source="episode_records",
                    observedAt="2026-10-18T10:00:00Z",
                ),
                authority="episode_records",
                relationship="episode_user_subject",
                observed_at="2026-10-18T10:00:00Z",
                available=True,
                scope_known=True,
            )

        async def identity_record(self, tenant_id, subject):
            assert (tenant_id, subject.id) == (TENANT, profile_id)
            return ProfileRead(
                record={
                    "tenant_id": tenant_id,
                    "user_id": profile_id,
                    "status": "active",
                    "updated_at": "2026-10-18T10:00:00Z",
                },
                available=True,
                scope_known=True,
            )

    class Policy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "entity_and_relationship_context": Experience360PolicyDisposition(
                        state="allowed"
                    )
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            if projection_request.projectionId == "profile360":
                context = await ProviderRegistry().build_context("profile360", projection_request)
                return await Profile360Provider(Source()).project(projection_request, context)
            if projection_request.projectionId == "relationship360":
                return ProjectionResult(
                    projectionId="relationship360",
                    tenantId=TENANT,
                    contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                    sections=[
                        ProjectionSection(
                            id="interactions",
                            state="available",
                            content={"edges": [], "evidenceRefs": []},
                            canonicalAuthorityRefs=["graph", "relationship_facts"],
                        ),
                        ProjectionSection(
                            id="evidence",
                            state="available",
                            content={"evidenceRefs": [episode_evidence]},
                            canonicalAuthorityRefs=[
                                "graph",
                                "identity",
                                "relationship_facts",
                            ],
                        ),
                    ],
                    claims=[],
                    dependencyState=[],
                    generatedAt="2026-10-18T12:30:00Z",
                    degradedReasons=[],
                )
            return ProjectionResult(
                projectionId="episode360",
                tenantId=TENANT,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id="episode_context",
                        state="available",
                        content={"episodeId": "episode-1", "evidenceRefs": [episode_evidence]},
                    )
                ],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    request = Experience360FrameRequest(
        surfaceId="episode360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="episode", id="episode-1"),
        requestedSlotIds=["entity_and_relationship_context"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=Policy(),
        projection_runtime=Runtime(),
    )

    slot = frame.slots[0]
    assert frame.subject == ProjectionSubject(kind="episode", id="episode-1")
    assert slot.state == "available"
    assert {ref.id for ref in slot.evidenceRefs} == {
        "episode-1",
        "episode-event-1",
        profile_id,
    }
    authority_refs = {
        (item.projectionId, item.sectionId): tuple(item.canonicalAuthorityRefs)
        for item in slot.provenance
        if item.sourceKind == "section"
    }
    assert authority_refs == {
        ("episode360", "episode_context"): ("episode_facts", "graph"),
        ("profile360", "evidence"): ("episode_facts", "identity"),
        ("profile360", "state"): ("episode_facts", "identity"),
        ("profile360", "summary"): ("episode_facts", "identity"),
        ("relationship360", "evidence"): ("graph", "identity", "relationship_facts"),
        ("relationship360", "interactions"): ("graph", "relationship_facts"),
    }


@pytest.mark.asyncio
async def test_account360_member_profiles_use_exact_per_member_profile_policy() -> None:
    account_id = "organization-profile-parent"
    allowed_member_id = "member-profile-allowed"
    denied_member_id = "member-profile-denied"
    events: list[tuple[str, str, str]] = []

    def member(entity_id: str, edge_id: str) -> AccountMember:
        return AccountMember(
            tenant_id=TENANT,
            organization_entity_id=account_id,
            entity_id=entity_id,
            entity_type="human",
            role=None,
            membership_evidence_ref=EvidenceRef(
                id=edge_id,
                type="relationship",
                source="graph",
                observedAt="2026-10-18T12:00:00Z",
            ),
            entity_evidence_ref=EvidenceRef(
                id=entity_id,
                type="entity",
                source="entity_registry",
                observedAt="2026-10-18T12:00:00Z",
            ),
        )

    class AccountSource:
        async def canonical_entity(self, tenant_id: str, entity_id: str):
            assert (tenant_id, entity_id) == (TENANT, account_id)
            return AccountIdentityRead(
                "resolved",
                evidence_refs=(
                    EvidenceRef(
                        id=account_id,
                        type="entity",
                        source="entity_registry",
                        observedAt="2026-10-18T12:00:00Z",
                    ),
                ),
                entity_type="organization",
                tenant_id=tenant_id,
                entity_id=entity_id,
            )

        async def account_members(self, tenant_id: str, organization_entity_id: str):
            assert (tenant_id, organization_entity_id) == (TENANT, account_id)
            events.append(("membership", "account360", organization_entity_id))
            return AccountMembersRead(
                "degraded",
                TENANT,
                account_id,
                members=(
                    member(allowed_member_id, "member-allowed-edge"),
                    member(denied_member_id, "member-denied-edge"),
                ),
                reason_codes=("account_member_edge_completeness_unproven",),
            )

    class Policy:
        async def evaluate(self, request: Experience360FrameRequest):
            events.append(("policy", request.surfaceId, request.subject.id))
            if request.surfaceId == "account360":
                return Experience360PolicyEvaluation(
                    surfaceId=request.surfaceId,
                    tenantId=request.tenantId,
                    evaluatedAt="2026-10-18T12:30:00Z",
                    frameDisposition=Experience360PolicyDisposition(state="allowed"),
                    slotDispositions={
                        "profiles": Experience360PolicyDisposition(state="allowed")
                    },
                )

            dispositions = {
                slot["id"]: Experience360PolicyDisposition(state="denied")
                for slot in PRODUCT_360_SURFACE_DEFINITIONS["profile360"]["domainSlots"]
            }
            frame_state = "allowed"
            if request.subject.id == allowed_member_id:
                dispositions["entity_identity"] = Experience360PolicyDisposition(
                    state="allowed"
                )
            else:
                frame_state = "denied"
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:30:00Z",
                frameDisposition=Experience360PolicyDisposition(state=frame_state),
                slotDispositions=dispositions,
            )

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[str, ...]]] = []

        async def execute_projection(self, projection_request, **_kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            self.calls.append(
                (projection_request.projectionId, projection_request.subject.id, section_ids)
            )
            events.append(("projection", projection_request.projectionId, projection_request.subject.id))
            return ProjectionResult(
                projectionId=projection_request.projectionId,
                tenantId=projection_request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=section_id, state="empty") for section_id in section_ids],
                claims=[],
                dependencyState=[],
                generatedAt="2026-10-18T12:30:00Z",
                degradedReasons=[],
            )

    runtime = Runtime()
    request = Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=account_id),
        requestedSlotIds=["profiles"],
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=Policy(),
        projection_runtime=runtime,
        account360_provider=Account360Provider(AccountSource()),
        generated_at="2026-10-18T12:30:00Z",
    )

    account_policy_index = events.index(("policy", "account360", account_id))
    membership_index = events.index(("membership", "account360", account_id))
    profile_policy_index = events.index(("policy", "profile360", allowed_member_id))
    profile_projection_index = events.index(("projection", "profile360", allowed_member_id))
    assert account_policy_index < membership_index < profile_policy_index < profile_projection_index
    assert ("policy", "profile360", denied_member_id) in events
    assert all(subject_id == allowed_member_id for _, subject_id, _ in runtime.calls)
    assert runtime.calls == [("profile360", allowed_member_id, ("state", "summary"))]

    slot = next(slot for slot in frame.slots if slot.id == "profiles")
    assert slot.state == "degraded"
    assert [entry["member"]["id"] for entry in slot.content["profiles"]] == [
        allowed_member_id
    ]
    assert denied_member_id not in str(slot.content)
    nested_frame = slot.content["profiles"][0]["profileFrame"]
    assert nested_frame["surfaceId"] == "profile360"
    assert nested_frame["subject"]["id"] == allowed_member_id
    assert nested_frame["policyDisposition"]["state"] == "denied"
    nested_slots = {item["id"]: item for item in nested_frame["slots"]}
    assert nested_slots["entity_identity"]["policyDisposition"]["state"] == "allowed"
    assert nested_slots["identity_spine"]["policyDisposition"]["state"] == "denied"
    assert nested_slots["identity_spine"].get("content") is None


@pytest.mark.asyncio
async def test_profile_risk_summary_routes_exact_entity_to_risk360_after_policy():
    events: list[tuple[str, str, str]] = []
    entity_id = "profile-risk-entity-1"
    subject = ProjectionSubject(kind="entity", id=entity_id)
    risk_evidence = EvidenceRef(
        id="risk-assessment-profile-1",
        type="model_output",
        source="risk_assessments",
        observedAt="2026-10-18T12:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            events.append(("policy", request.surfaceId, request.subject.id))
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "risk_summary": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[str, ...]]] = []

        async def execute_projection(self, projection_request, **_kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            self.calls.append(
                (
                    projection_request.projectionId,
                    projection_request.subject.id,
                    section_ids,
                )
            )
            events.append(
                ("projection", projection_request.projectionId, projection_request.subject.id)
            )
            assert projection_request.tenantId == TENANT
            assert projection_request.subject == subject
            claim = ClaimEnvelope(
                id="risk360.assessment.profile-risk-entity-1",
                kind="risk_assessment",
                subject=subject,
                evidenceRefs=[risk_evidence],
                claims=["A tenant-scoped risk assessment records this exact entity subject."],
                domainSlotIds=["risk_summary"],
            )
            return ProjectionResult(
                projectionId="risk360",
                tenantId=projection_request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"subjectId": entity_id, "evidenceRefs": [risk_evidence]},
                        canonicalAuthorityRefs=["evidence", "risk_outputs"],
                    )
                    for section_id in section_ids
                ],
                claims=[claim],
                dependencyState=[],
                generatedAt="2026-10-18T12:00:30Z",
                degradedReasons=[],
            )

    runtime = Runtime()
    request = Experience360FrameRequest(
        surfaceId="profile360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["risk_summary"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=runtime,
        generated_at="2026-10-18T12:01:00Z",
    )

    assert events[0] == ("policy", "profile360", entity_id)
    assert runtime.calls == [
        ("risk360", entity_id, ("evidence", "findings", "state", "summary"))
    ]
    assert events[1] == ("projection", "risk360", entity_id)
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert [claim.id for claim in slot.claims] == [
        "risk360.assessment.profile-risk-entity-1"
    ]
    assert slot.evidenceRefs == [risk_evidence]
    assert {item.sectionId for item in slot.provenance if item.sourceKind == "section"} == {
        "evidence",
        "findings",
        "state",
        "summary",
    }
    assert "slot_partial_implementation" in slot.reasonCodes


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["entity", "agent"])
async def test_profile_value_summary_routes_exact_subject_to_economic360_after_policy(
    subject_kind: str,
):
    events: list[tuple[str, str, str]] = []
    subject_id = f"profile-value-{subject_kind}-1"
    subject = ProjectionSubject(kind=subject_kind, id=subject_id)
    value_evidence = EvidenceRef(
        id=f"economic-record-{subject_kind}-1",
        type="transaction",
        source="canonical_conversions",
        observedAt="2026-10-18T12:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            events.append(("policy", request.surfaceId, request.subject.id))
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "value_summary": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[str, ...]]] = []

        async def execute_projection(self, projection_request, **_kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            self.calls.append(
                (
                    projection_request.projectionId,
                    projection_request.subject.id,
                    section_ids,
                )
            )
            events.append(
                ("projection", projection_request.projectionId, projection_request.subject.id)
            )
            assert projection_request.tenantId == TENANT
            assert projection_request.subject == subject
            claim = ClaimEnvelope(
                id=f"economic360.summary.{subject_id}",
                kind="economic_rollup",
                subject=subject,
                evidenceRefs=[value_evidence],
                claims=["A tenant-scoped economic fact records this exact subject."],
                domainSlotIds=["value_summary"],
            )
            return ProjectionResult(
                projectionId="economic360",
                tenantId=projection_request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"subjectId": subject_id, "evidenceRefs": [value_evidence]},
                        canonicalAuthorityRefs=["economic_facts", "evidence"],
                    )
                    for section_id in section_ids
                ],
                claims=[claim],
                dependencyState=[],
                generatedAt="2026-10-18T12:00:30Z",
                degradedReasons=[],
            )

    runtime = Runtime()
    request = Experience360FrameRequest(
        surfaceId="profile360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["value_summary"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=runtime,
        generated_at="2026-10-18T12:01:00Z",
    )

    assert events[0] == ("policy", "profile360", subject_id)
    assert runtime.calls == [("economic360", subject_id, ("evidence", "summary"))]
    assert events[1] == ("projection", "economic360", subject_id)
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert [claim.id for claim in slot.claims] == [f"economic360.summary.{subject_id}"]
    assert slot.evidenceRefs == [value_evidence]
    assert {item.sectionId for item in slot.provenance if item.sourceKind == "section"} == {
        "evidence",
        "summary",
    }
    assert "slot_partial_implementation" in slot.reasonCodes


@pytest.mark.asyncio
async def test_profile_relationships_routes_exact_entity_to_relationship360_after_policy():
    events: list[tuple[str, str, str]] = []
    entity_id = "profile-relationship-entity-1"
    subject = ProjectionSubject(kind="entity", id=entity_id)
    relationship_evidence = EvidenceRef(
        id="profile-relationship-mutation-1",
        type="relationship",
        source="graph_mutation_ledger",
        observedAt="2026-10-18T12:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            events.append(("policy", request.surfaceId, request.subject.id))
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "relationships": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[str, ...]]] = []

        async def execute_projection(self, projection_request, **_kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            self.calls.append(
                (
                    projection_request.projectionId,
                    projection_request.subject.id,
                    section_ids,
                )
            )
            events.append(
                ("projection", projection_request.projectionId, projection_request.subject.id)
            )
            assert projection_request.tenantId == TENANT
            assert projection_request.subject == subject
            claim = ClaimEnvelope(
                id="relationship360.graph-event.profile-relationship-1",
                kind="relationship_graph_event",
                subject=subject,
                evidenceRefs=[relationship_evidence],
                claims=["The canonical graph ledger records a relationship for this exact entity."],
                domainSlotIds=["relationships"],
            )
            return ProjectionResult(
                projectionId="relationship360",
                tenantId=projection_request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"subjectId": entity_id, "evidenceRefs": [relationship_evidence]},
                        canonicalAuthorityRefs=["graph", "relationship_facts"],
                    )
                    for section_id in section_ids
                ],
                claims=[claim],
                dependencyState=[],
                generatedAt="2026-10-18T12:00:30Z",
                degradedReasons=["ledger_replay_completeness_is_unknown"],
            )

    runtime = Runtime()
    request = Experience360FrameRequest(
        surfaceId="profile360",
        tenantId=TENANT,
        subject=subject,
        requestedSlotIds=["relationships"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=runtime,
        generated_at="2026-10-18T12:01:00Z",
    )

    assert events[0] == ("policy", "profile360", entity_id)
    assert runtime.calls == [
        ("relationship360", entity_id, ("evidence", "interactions", "summary"))
    ]
    assert events[1] == ("projection", "relationship360", entity_id)
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert [claim.id for claim in slot.claims] == [
        "relationship360.graph-event.profile-relationship-1"
    ]
    assert slot.evidenceRefs == [relationship_evidence]
    assert {item.sectionId for item in slot.provenance if item.sourceKind == "section"} == {
        "evidence",
        "interactions",
        "summary",
    }
    assert "slot_partial_implementation" in slot.reasonCodes


@pytest.mark.asyncio
async def test_profile_relationships_do_not_infer_entity_from_profile_alias():
    profile_subject = ProjectionSubject(kind="profile", id="profile-alias-not-entity-1")

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "relationships": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, projection_request, **_kwargs):
            raise AssertionError("profile alias must not be projected as an entity")

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="profile360",
            tenantId=TENANT,
            subject=profile_subject,
            requestedSlotIds=["relationships"],
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:01:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "unknown"
    assert slot.content is None
    assert "projection_binding_subject_kind_unsupported" in slot.reasonCodes


@pytest.mark.asyncio
async def test_profile_location_temporal_routes_exact_entity_to_geographic360_after_policy():
    events: list[tuple[str, str, str]] = []
    entity_id = "profile-location-entity-1"
    subject = ProjectionSubject(kind="entity", id=entity_id)
    location_evidence = EvidenceRef(
        id="location:profile-location-fact-1",
        type="relationship",
        source="location_facts",
        observedAt="2026-10-18T12:00:00Z",
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            events.append(("policy", request.surfaceId, request.subject.id))
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "location_temporal": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[str, ...]]] = []

        async def execute_projection(self, projection_request, **_kwargs):
            section_ids = tuple(sorted(projection_request.includeSections or []))
            self.calls.append(
                (
                    projection_request.projectionId,
                    projection_request.subject.id,
                    section_ids,
                )
            )
            events.append(
                ("projection", projection_request.projectionId, projection_request.subject.id)
            )
            assert projection_request.tenantId == TENANT
            assert projection_request.subject == subject
            claim = ClaimEnvelope(
                id="profile_location_temporal.entity.profile-location-entity-1",
                kind="profile_location_temporal_evidence",
                subject=subject,
                evidenceRefs=[location_evidence],
                claims=[
                    "Canonical location facts record a time-scoped observation for this exact subject; this is not a continuous physical trajectory."
                ],
                domainSlotIds=["location_temporal"],
            )
            return ProjectionResult(
                projectionId="geographic360",
                tenantId=projection_request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[
                    ProjectionSection(
                        id=section_id,
                        state="available",
                        content={"evidenceRefs": [location_evidence]},
                        canonicalAuthorityRefs=["geo_observations", "temporal"],
                    )
                    for section_id in section_ids
                ],
                claims=[claim],
                dependencyState=[],
                generatedAt="2026-10-18T12:00:30Z",
                degradedReasons=[],
            )

    runtime = Runtime()
    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="profile360",
            tenantId=TENANT,
            subject=subject,
            requestedSlotIds=["location_temporal"],
            includeEvidence=True,
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=runtime,
        generated_at="2026-10-18T12:01:00Z",
    )

    assert events[0] == ("policy", "profile360", entity_id)
    assert runtime.calls == [("geographic360", entity_id, ("evidence", "timeline"))]
    assert events[1] == ("projection", "geographic360", entity_id)
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert [claim.id for claim in slot.claims] == [
        "profile_location_temporal.entity.profile-location-entity-1"
    ]
    assert slot.evidenceRefs == [location_evidence]
    assert {item.sectionId for item in slot.provenance if item.sourceKind == "section"} == {
        "evidence",
        "timeline",
    }
    assert "slot_partial_implementation" in slot.reasonCodes
