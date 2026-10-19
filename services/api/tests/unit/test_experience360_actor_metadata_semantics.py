"""Reviewable semantics for explicit unknown actor metadata on 360 slots."""

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
    compose_experience360_frame,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360ActorAttribution,
    Experience360AuthorityDecision,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ClaimEnvelope,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    _derive_agent_actor_metadata,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


TENANT = "tenant-actor-metadata"
AGENT_ID = "agent-metadata-1"


def _agent_decision_result(
    decisions: list[dict[str, object]],
    claims: list[ClaimEnvelope],
) -> ProjectionResult:
    return ProjectionResult(
        projectionId="agent360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "dimensions": [
                        {
                            "id": "authority_and_delegation",
                            "state": "available",
                            "content": {"actionScopedDecisions": decisions},
                        }
                    ]
                },
            )
        ],
        claims=claims,
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        asOf="2026-10-17T10:00:00Z",
        degradedReasons=[],
    )


def _agent_decision(
    *,
    execution_id: str = "execution-1",
    decision: str = "allow",
    evidence: EvidenceRef | None = None,
) -> dict[str, object]:
    evidence = evidence or EvidenceRef(
        id=execution_id,
        type="event",
        source="agent_executions",
        observedAt="2026-10-17T10:00:00Z",
    )
    return {
        "executionId": execution_id,
        "decision": decision,
        "delegationId": "delegation-1",
        "action": "read_record",
        "resource": "customer:123",
        "evidenceRef": evidence.model_dump(mode="json"),
    }


def _agent_decision_claim(
    *,
    execution_id: str = "execution-1",
    subject: ProjectionSubject | None = None,
    kind: str = "server_recorded_delegation_decision",
    claim_state: EpistemicStatus = EpistemicStatus.OBSERVED,
    domain_slot_ids: list[str] | None = None,
    evidence: EvidenceRef | None = None,
    claim_id: str | None = None,
) -> ClaimEnvelope:
    evidence = evidence or EvidenceRef(
        id=execution_id,
        type="event",
        source="agent_executions",
        observedAt="2026-10-17T10:00:00Z",
    )
    return ClaimEnvelope(
        id=claim_id or f"agent_execution_delegation_decision.{execution_id}",
        kind=kind,
        subject=subject or ProjectionSubject(kind="agent", id=AGENT_ID),
        evidenceRefs=[evidence],
        claims=["A delegation decision was recorded for one execution."],
        claimState=claim_state,
        domainSlotIds=domain_slot_ids or ["authority_and_delegation"],
    )


def _agent_decision_request() -> Experience360FrameRequest:
    return Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["authority_and_delegation"],
        includeEvidence=True,
    )


def test_agent360_action_scoped_decision_is_included_with_exact_evidence() -> None:
    decision = _agent_decision()
    claim = _agent_decision_claim()

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result([decision], [claim])],
    )["authority_and_delegation"]

    assert metadata.resolutionState == "unknown"
    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "allow"
    assert metadata.authorityDecision.authorityRef == "aether.agent_delegation_engine"
    assert metadata.authorityDecision.actionRefs == ["read_record"]
    assert metadata.authorityDecision.resourceRefs == ["customer:123"]
    assert metadata.authorityDecision.delegationRefs == ["delegation-1"]
    assert metadata.authorityDecision.executionRefs == ["execution-1"]
    assert metadata.authorityDecision.evidenceRefs == [claim.evidenceRefs[0]]
    assert metadata.authorityDecision.reasonCodes == [
        "recorded_execution_scoped_decision_not_standing_authority"
    ]


@pytest.mark.parametrize(
    ("decision_overrides", "claim_overrides"),
    [
        ({"decision": "maybe"}, {}),
        ({"action": " "}, {}),
        ({"executionId": " "}, {}),
        (
            {
                "evidenceRef": EvidenceRef(
                    id="other-execution",
                    type="event",
                    source="agent_executions",
                    observedAt="2026-10-17T10:00:00Z",
                ).model_dump(mode="json")
            },
            {},
        ),
        (
            {
                "evidenceRef": EvidenceRef(
                    id="execution-1",
                    type="event",
                    source="delegations",
                    observedAt="2026-10-17T10:00:00Z",
                ).model_dump(mode="json")
            },
            {},
        ),
        (
            {
                "evidenceRef": EvidenceRef(
                    id="execution-1",
                    type="entity",
                    source="agent_executions",
                    observedAt="2026-10-17T10:00:00Z",
                ).model_dump(mode="json")
            },
            {},
        ),
        ({}, {"claim_id": "agent_execution_delegation_decision.other"}),
        ({}, {"kind": "asserted_delegation_decision"}),
        ({}, {"claim_state": EpistemicStatus.INFERRED}),
        ({}, {"subject": ProjectionSubject(kind="agent", id="other-agent")}),
        ({}, {"domain_slot_ids": ["authority_and_delegation", "state"]}),
        (
            {},
            {
                "evidence": EvidenceRef(
                    id="execution-1",
                    type="event",
                    source="delegations",
                    observedAt="2026-10-17T10:00:00Z",
                )
            },
        ),
    ],
)
def test_agent360_action_scoped_decision_mismatches_fail_closed(
    decision_overrides: dict[str, object],
    claim_overrides: dict[str, object],
) -> None:
    decision = {**_agent_decision(), **decision_overrides}
    claim = _agent_decision_claim(**claim_overrides)

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result([decision], [claim])],
    )["authority_and_delegation"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == ["no_action_scoped_decision_available"]


def test_agent360_action_scoped_decisions_reject_cross_tenant_result() -> None:
    decision = _agent_decision()
    claim = _agent_decision_claim()
    result = _agent_decision_result([decision], [claim])

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [result.model_copy(update={"tenantId": "another-tenant"})],
    )["authority_and_delegation"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == ["no_action_scoped_decision_available"]


def test_agent360_duplicate_matching_decision_claims_fail_closed() -> None:
    decision = _agent_decision()
    claim = _agent_decision_claim()

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result([decision], [claim, claim])],
    )["authority_and_delegation"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == ["no_action_scoped_decision_available"]


def test_conflicting_agent360_action_decisions_remain_unknown() -> None:
    decisions = [
        _agent_decision(execution_id="execution-1", decision="allow"),
        _agent_decision(execution_id="execution-2", decision="deny"),
    ]
    claims = [
        _agent_decision_claim(execution_id="execution-1"),
        _agent_decision_claim(execution_id="execution-2"),
    ]

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result(decisions, claims)],
    )["authority_and_delegation"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == [
        "multiple_action_scoped_decisions_not_collapsed"
    ]


@pytest.mark.parametrize(
    ("surface_id", "slot_id", "projection_ids"),
    [
        ("agent360", "authority_and_delegation", ["agent360"]),
        ("execution360", "actor_and_delegation", ["agent360", "execution360"]),
    ],
)
def test_unknown_actor_and_authority_metadata_remains_explicit_on_available_slot(
    surface_id: str,
    slot_id: str,
    projection_ids: list[str],
) -> None:
    """Available describes evidenced slot content; metadata stays explicitly unknown.

    The reconstructed product catalog requires these metadata objects, but does
    not specify that actor resolution or an action-scoped decision must be
    known before evidence-backed slot content is available.
    """
    request = Experience360FrameRequest(
        surfaceId=surface_id,
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id="agent-metadata-1"),
        requestedSlotIds=[slot_id],
        includeEvidence=True,
    )
    results = [
        ProjectionResult(
            projectionId=projection_id,
            tenantId=TENANT,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[
                ProjectionSection(
                    id=section_id,
                    state="available",
                    content={
                        "status": "observed",
                        "evidenceRefs": [
                            EvidenceRef(
                                id=f"{projection_id}-{section_id}-evidence",
                                type="event",
                                source=f"{projection_id}/metadata-semantics-test",
                                observedAt="2026-10-17T10:00:00Z",
                            )
                        ],
                    },
                )
                for section_id in ("state", "evidence")
            ],
            claims=[],
            dependencyState=[],
            generatedAt="2026-10-17T10:01:00Z",
            asOf="2026-10-17T10:00:00Z",
            degradedReasons=[],
        )
        for projection_id in projection_ids
    ]
    actor_metadata = Experience360ActorAttribution(
        tenantId=TENANT,
        resolutionState="unknown",
        authorityDecision=Experience360AuthorityDecision(
            tenantId=TENANT,
            outcome="unknown",
            reasonCodes=["no_action_scoped_decision_available"],
        ),
    )

    frame = compose_experience360_frame(
        request,
        results,
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        actor_attribution_by_slot={slot_id: actor_metadata},
        generated_at="2026-10-17T10:02:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "available"
    assert slot.content is not None
    assert slot.evidenceRefs
    assert slot.provenance
    assert slot.actorAttribution is not None
    assert slot.actorAttribution.resolutionState == "unknown"
    assert slot.actorAttribution.resolvedCanonicalActor is None
    assert slot.actorAttribution.authorityDecision is not None
    assert slot.actorAttribution.authorityDecision.outcome == "unknown"
    assert slot.actorAttribution.authorityDecision.authorityRef is None
