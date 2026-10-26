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
    _agent360_observed_delegation_chain,
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
        "decisionAt": "2026-10-17T10:00:30Z",
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
        domainSlotIds=domain_slot_ids or ["authority_envelope", "authority_check"],
    )


def _agent_decision_request() -> Experience360FrameRequest:
    return Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["authority_envelope"],
        includeEvidence=True,
    )


def test_agent360_action_scoped_decision_is_included_with_exact_evidence() -> None:
    decision = _agent_decision()
    claim = _agent_decision_claim()

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result([decision], [claim])],
    )["authority_envelope"]

    assert metadata.resolutionState == "unknown"
    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "allow"
    assert metadata.authorityDecision.authorityRef == "aether.agent_delegation_engine"
    assert metadata.authorityDecision.actionRefs == ["read_record"]
    assert metadata.authorityDecision.resourceRefs == ["customer:123"]
    assert metadata.authorityDecision.delegationRefs == ["delegation-1"]
    assert metadata.authorityDecision.executionRefs == ["execution-1"]
    assert metadata.authorityDecision.evidenceRefs == [claim.evidenceRefs[0]]
    assert metadata.authorityDecision.decidedAt == "2026-10-17T10:00:30+00:00"
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
        ({}, {"domain_slot_ids": ["authority_envelope", "state"]}),
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
    )["authority_envelope"]

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
    )["authority_envelope"]

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
    )["authority_envelope"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == ["no_action_scoped_decision_available"]


def _delegation_path_fixture() -> tuple[dict[str, object], list[ClaimEnvelope]]:
    delegation_ids = ["delegation-in", "delegation-out"]
    party_ids = ["human-owner", AGENT_ID, "system-recipient"]
    party_kinds = ["human", "agent", "system"]
    records = [
        {
            "delegationId": delegation_id,
            "evidenceRef": EvidenceRef(
                id=delegation_id,
                type="event",
                source="delegations",
                observedAt="2026-10-17T09:00:00Z",
            ).model_dump(mode="json"),
            "grantorEntityId": party_ids[index],
            "granteeEntityId": party_ids[index + 1],
            "scope": {"actions": [f"action-{index}"], "resources": [f"resource-{index}"]},
            "startsAt": "2026-10-17T09:00:00Z",
            "endsAt": None,
            "revokedAt": None,
            "recordState": (
                "active_as_reported_by_repository" if index == 0 else "not_evaluated"
            ),
            "authorizationDecision": "unknown",
        }
        for index, delegation_id in enumerate(delegation_ids)
    ]
    claims: list[ClaimEnvelope] = []
    path_refs: dict[tuple[str, str], EvidenceRef] = {}
    for record in records:
        record_id = record["delegationId"]
        record_ref = EvidenceRef.model_validate(record["evidenceRef"])
        path_refs[(record_ref.source, record_ref.id)] = record_ref
        claims.append(
            ClaimEnvelope(
                id=f"delegation.{record_id}",
                kind="agent_delegation_record",
                subject=ProjectionSubject(kind="agent", id=AGENT_ID),
                evidenceRefs=[record_ref],
                claims=["A tenant-scoped delegation record is stored."],
                claimState=EpistemicStatus.OBSERVED,
            )
        )
        for side, entity_id in (
            ("grantor", record["grantorEntityId"]),
            ("grantee", record["granteeEntityId"]),
        ):
            identity_ref = EvidenceRef(
                id=entity_id,
                type="entity",
                source="entities",
                observedAt="2026-10-17T09:00:00Z",
            )
            path_refs[(identity_ref.source, identity_ref.id)] = identity_ref
            claims.append(
                ClaimEnvelope(
                    id=f"delegation_party.{record_id}.{side}",
                    kind="canonically_resolved_delegation_party",
                    subject=ProjectionSubject(kind="agent", id=AGENT_ID),
                    evidenceRefs=[record_ref, identity_ref],
                    claims=["The delegation party resolves to a tenant-owned entity."],
                    claimState=EpistemicStatus.RESOLVED,
                    domainSlotIds=["owner_delegator", "delegation_chain", "actor_attribution"],
                )
            )

    path = {
        "kind": "observed_adjacent_delegation_records",
        "delegationRecordIds": delegation_ids,
        "partyEntityIds": party_ids,
        "partyIdentities": [
            {
                "entityId": entity_id,
                "state": "resolved",
                "party": {"kind": party_kind, "id": entity_id},
                "evidenceRefs": [],
            }
            for entity_id, party_kind in zip(party_ids, party_kinds)
        ],
        "evidenceRefs": [ref.model_dump(mode="json") for ref in path_refs.values()],
    }
    authority_content: dict[str, object] = {
        "delegationRecords": records,
        "delegationChain": {
            "state": "partial",
            "intermediateCanonicalAgentEntityId": AGENT_ID,
            "observedAdjacentPaths": [path],
            "boundedReadComplete": True,
            "transitiveAuthority": "unknown",
            "effectiveAuthorizationDecision": "unknown",
        },
    }
    return authority_content, claims


def test_agent360_exact_adjacent_delegation_path_becomes_typed_metadata() -> None:
    authority_content, claims = _delegation_path_fixture()

    chain, delegator, delegatee = _agent360_observed_delegation_chain(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        canonical_agent_id=AGENT_ID,
        authority_content=authority_content,
        claims=claims,
    )

    assert len(chain) == 2
    assert chain[0].delegator.id == "human-owner"
    assert chain[0].delegatee.id == AGENT_ID
    assert chain[1].delegator.id == AGENT_ID
    assert chain[1].delegatee.id == "system-recipient"
    assert chain[0].scope == ["action:action-0", "resource:resource-0"]
    assert chain[0].status == "granted"
    assert chain[1].status == "unknown"
    assert {ref.source for ref in chain[0].evidenceRefs} == {"delegations", "entities"}
    assert delegator is not None and delegator.id == "human-owner"
    assert delegatee is not None and delegatee.id == "system-recipient"


def test_agent360_frame_runtime_attaches_exact_delegation_path_metadata() -> None:
    authority_content, claims = _delegation_path_fixture()
    identity_ref = EvidenceRef(
        id=AGENT_ID,
        type="entity",
        source="entities",
        observedAt="2026-10-17T09:00:00Z",
    )
    claims.append(
        ClaimEnvelope(
            id="agent360.canonical-agent-identity",
            kind="canonically_resolved_agent_identity",
            subject=ProjectionSubject(kind="agent", id=AGENT_ID),
            evidenceRefs=[identity_ref],
            claims=["The requested Agent resolves to a tenant-owned canonical Agent."],
            claimState=EpistemicStatus.RESOLVED,
            domainSlotIds=["identity", "actor_attribution"],
        )
    )
    result = ProjectionResult(
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
                            "id": "actor_attribution",
                            "state": "available",
                            "content": {"resolvedCanonicalActor": AGENT_ID},
                        },
                        {
                            "id": "authority_and_delegation",
                            "state": "partial",
                            "content": authority_content,
                        },
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
    request = Experience360FrameRequest(
        surfaceId="agent360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["delegation_chain", "actor_attribution"],
    )

    attribution = _derive_agent_actor_metadata(request, [result])["delegation_chain"]

    assert [edge.id for edge in attribution.delegationChain] == [
        "delegation-in",
        "delegation-out",
    ]
    assert attribution.authorityEdgeIds == ["delegation-in", "delegation-out"]
    assert attribution.actorKind == "agent"
    assert attribution.driverScore.agentDriven == 0.0
    assert attribution.driverScore.unknown == 1.0


@pytest.mark.parametrize("failure", ["duplicate_path", "missing_party_evidence", "wrong_subject"])
def test_agent360_delegation_path_ambiguity_or_provenance_fails_closed(failure: str) -> None:
    authority_content, claims = _delegation_path_fixture()
    chain_content = authority_content["delegationChain"]
    path = chain_content["observedAdjacentPaths"][0]
    if failure == "duplicate_path":
        chain_content["observedAdjacentPaths"].append(path)
    elif failure == "missing_party_evidence":
        claims = [
            claim
            for claim in claims
            if claim.id != "delegation_party.delegation-in.grantee"
        ]
    else:
        claims = [
            claim.model_copy(
                update={"subject": ProjectionSubject(kind="agent", id="other-agent")}
            )
            if claim.id == "delegation.delegation-out"
            else claim
            for claim in claims
        ]

    chain, delegator, delegatee = _agent360_observed_delegation_chain(
        tenant_id=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        canonical_agent_id=AGENT_ID,
        authority_content=authority_content,
        claims=claims,
    )

    assert chain == []
    assert delegator is None
    assert delegatee is None


def test_execution_driver_score_requires_canonical_server_execution_evidence() -> None:
    execution_ref = EvidenceRef(
        id="execution-actor-1",
        type="event",
        source="agent_executions",
        observedAt="2026-10-17T10:00:00Z",
    )
    result = ProjectionResult(
        projectionId="execution360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "sourceStates": {"serverRecordedLifecycle": "available"},
                    "serverRecordedExecutions": [
                        {
                            "executionId": execution_ref.id,
                            "agentId": AGENT_ID,
                            "canonicalActorResolved": True,
                        }
                    ],
                },
            )
        ],
        claims=[
            ClaimEnvelope(
                id=f"execution360:server-actor:{execution_ref.id}",
                kind="canonically_resolved_server_agent_actor",
                subject=ProjectionSubject(kind="agent", id=AGENT_ID),
                evidenceRefs=[execution_ref],
                claims=["The canonical execution actor is resolved."],
                claimState=EpistemicStatus.RESOLVED,
                domainSlotIds=["actor_attribution"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        asOf="2026-10-17T10:00:00Z",
        degradedReasons=[],
    )
    request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["actor_attribution"],
    )

    attribution = _derive_agent_actor_metadata(request, [result])["actor_attribution"]

    assert attribution.actorKind == "agent"
    assert attribution.actorSubjectId == AGENT_ID
    assert attribution.driverScore.agentDriven == 1.0
    assert attribution.driverScore.unknown == 0.0
    assert attribution.confidence == "high"


def test_source_reported_agent_actor_does_not_establish_execution_driver() -> None:
    source_ref = EvidenceRef(
        id="source-event-actor-1",
        type="event",
        source="silver_semantic_observations",
        observedAt="2026-10-17T10:00:00Z",
    )
    result = ProjectionResult(
        projectionId="execution360",
        tenantId=TENANT,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="state",
                state="available",
                content={
                    "sourceStates": {
                        "serverRecordedLifecycle": "available",
                        "sourceReportedTelemetry": "available",
                    },
                    "serverRecordedExecutions": [],
                },
            ),
            ProjectionSection(
                id="interactions",
                state="available",
                content={"interactions": [{"actorAgentId": AGENT_ID, "sourceEventId": source_ref.id}]},
            ),
        ],
        claims=[
            ClaimEnvelope(
                id=f"execution360:actor:{source_ref.id}",
                kind="canonically_resolved_execution_actor",
                subject=ProjectionSubject(kind="agent", id=AGENT_ID),
                evidenceRefs=[source_ref],
                claims=["The source-reported actor resolves to a tenant-bound Agent."],
                claimState=EpistemicStatus.RESOLVED,
                domainSlotIds=["actor_attribution"],
            )
        ],
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        asOf="2026-10-17T10:00:00Z",
        degradedReasons=[],
    )
    request = Experience360FrameRequest(
        surfaceId="execution360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="agent", id=AGENT_ID),
        requestedSlotIds=["actor_attribution"],
    )

    attribution = _derive_agent_actor_metadata(request, [result])["actor_attribution"]

    assert attribution.resolutionState == "resolved"
    assert attribution.resolvedCanonicalActor is not None
    assert attribution.resolvedCanonicalActor.id == AGENT_ID
    assert attribution.actorKind == "unknown"
    assert attribution.driverScore.agentDriven == 0.0
    assert attribution.driverScore.unknown == 1.0


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
    )["authority_envelope"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "unknown"
    assert metadata.authorityDecision.authorityRef is None
    assert metadata.authorityDecision.reasonCodes == [
        "multiple_action_scoped_decisions_not_collapsed"
    ]


def test_agent360_multiple_matching_decisions_do_not_claim_one_timestamp() -> None:
    decisions = [
        _agent_decision(execution_id="execution-1"),
        _agent_decision(execution_id="execution-2"),
    ]
    claims = [
        _agent_decision_claim(execution_id="execution-1"),
        _agent_decision_claim(execution_id="execution-2"),
    ]

    metadata = _derive_agent_actor_metadata(
        _agent_decision_request(),
        [_agent_decision_result(decisions, claims)],
    )["authority_envelope"]

    assert metadata.authorityDecision is not None
    assert metadata.authorityDecision.outcome == "allow"
    assert metadata.authorityDecision.decidedAt is None


@pytest.mark.parametrize(
    ("surface_id", "slot_id", "projection_ids"),
    [
        ("agent360", "authority_envelope", ["agent360"]),
        ("execution360", "authority_check", ["execution360"]),
    ],
)
def test_unknown_actor_and_authority_metadata_remains_explicit_on_available_slot(
    surface_id: str,
    slot_id: str,
    projection_ids: list[str],
) -> None:
    """Unknown metadata must not erase content backed by explicit evidence.

    The catalog requires the metadata objects, not positive resolutions. The
    Execution360 authority slot is globally partial, so its content can remain
    present in a degraded slot while actor and decision resolution are unknown.
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
            claims=[
                ClaimEnvelope(
                    id=f"{projection_id}.{slot_id}.observed-context",
                    kind="observed_authority_context",
                    subject=request.subject,
                    evidenceRefs=[
                        EvidenceRef(
                            id=f"{projection_id}-state-evidence",
                            type="event",
                            source=f"{projection_id}/metadata-semantics-test",
                            observedAt="2026-10-17T10:00:00Z",
                        )
                    ],
                    claims=["A recorded authority context exists; no action decision was resolved."],
                    domainSlotIds=[slot_id],
                )
            ],
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
    assert slot.state == ("degraded" if surface_id == "execution360" else "available")
    assert slot.content is not None
    assert slot.evidenceRefs
    assert slot.provenance
    assert slot.actorAttribution is not None
    assert slot.actorAttribution.resolutionState == "unknown"
    assert slot.actorAttribution.resolvedCanonicalActor is None
    assert slot.actorAttribution.authorityDecision is not None
    assert slot.actorAttribution.authorityDecision.outcome == "unknown"
    assert slot.actorAttribution.authorityDecision.authorityRef is None
