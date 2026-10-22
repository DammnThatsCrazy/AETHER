"""Focused tests for the Account360 product-frame provider."""

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
from identity.account360_provider import (  # noqa: E402
    ACCOUNT_AGENTS_SLOT,
    ACCOUNT_MEMBERS_SLOT,
    ACCOUNT_PROFILES_SLOT,
    ACCOUNT_RISK_SLOT,
    ACCOUNT_IDENTITY_SLOT,
    Account360Provider,
    AccountIdentityRead,
    AccountMember,
    AccountMembersRead,
    LEGACY_ACCOUNT_IDENTITY_SLOT,
    RepositoryAccount360Source,
)
from shared.intelligence_projections.composition import (  # noqa: E402
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


TENANT_ID = "tenant-account360-test"
SUBJECT = ProjectionSubject(kind="entity", id="organization-1")
EVIDENCE = EvidenceRef(
    id="account360-evidence-1",
    type="entity",
    source="account360/test-fixture",
    observedAt="2026-10-17T10:00:00Z",
)
IDENTITY_EVIDENCE = EvidenceRef(
    id=SUBJECT.id,
    type="entity",
    source="entity_registry",
    observedAt="2026-10-17T09:59:00Z",
)


class _Source:
    def __init__(self, response: AccountIdentityRead) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def canonical_entity(
        self, tenant_id: str, entity_id: str
    ) -> AccountIdentityRead:
        self.calls.append((tenant_id, entity_id))
        return self.response


class _MembersSource(_Source):
    def __init__(
        self,
        identity: AccountIdentityRead,
        members: AccountMembersRead,
    ) -> None:
        super().__init__(identity)
        self.members_response = members
        self.member_calls: list[tuple[str, str]] = []

    async def account_members(
        self, tenant_id: str, organization_entity_id: str
    ) -> AccountMembersRead:
        self.member_calls.append((tenant_id, organization_entity_id))
        return self.members_response


class _RiskProvider:
    def __init__(self, response: ProjectionResult) -> None:
        self.response = response
        self.calls: list[tuple[object, object]] = []

    async def project(self, request, context) -> ProjectionResult:
        self.calls.append((request, context))
        return self.response


def _risk_result(
    *,
    tenant_id: str = TENANT_ID,
    subject: ProjectionSubject = SUBJECT,
    with_evidence: bool = True,
) -> ProjectionResult:
    risk_evidence = EvidenceRef(
        id="risk-assessment-1",
        type="model_output",
        source="risk_assessments",
        observedAt="2026-10-17T09:55:00Z",
    )
    return ProjectionResult(
        projectionId="risk360",
        tenantId=tenant_id,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            ProjectionSection(
                id="summary",
                state="degraded",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "assessment": {
                        "assessmentId": "risk-assessment-1",
                        "evidenceRefs": (
                            [risk_evidence.model_dump(mode="json", by_alias=True)]
                            if with_evidence
                            else []
                        ),
                    },
                },
                warnings=["profile context is unavailable"],
            ),
            ProjectionSection(
                id="state",
                state="degraded",
                content={
                    "tenantId": tenant_id,
                    "subject": {"kind": subject.kind, "id": subject.id},
                    "dimensionStates": [],
                },
                warnings=["cluster context is unavailable"],
            ),
        ],
        claims=(
            [
                ClaimEnvelope(
                    id="risk360.assessment.risk-assessment-1",
                    kind="risk_assessment",
                    subject=subject,
                    evidenceRefs=[risk_evidence],
                    claims=["A canonical risk assessment was observed."],
                    claimState="observed",
                    domainSlotIds=["risk_summary", "evidence_trace"],
                )
            ]
            if with_evidence
            else []
        ),
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        degradedReasons=[],
    )


def _request(
    *,
    as_of: str | None = None,
    include_evidence: bool = True,
    subject: ProjectionSubject = SUBJECT,
    requested_slot_ids: list[str] | None = None,
) -> Experience360FrameRequest:
    return Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT_ID,
        subject=subject,
        asOf=as_of,
        includeEvidence=include_evidence,
        requestedSlotIds=requested_slot_ids,
    )


def _section(section_id: str, *, state: str = "available") -> ProjectionSection:
    return ProjectionSection(
        id=section_id,
        state=state,
        content=(
            {
                "observed": True,
                "evidenceRefs": [EVIDENCE.model_dump(mode="json", by_alias=True)],
            }
            if state == "available"
            else None
        ),
        warnings=["outcome_projection_unavailable"] if state == "degraded" else None,
    )


def _projection(
    projection_id: str,
    section_ids: list[str],
    *,
    tenant_id: str = TENANT_ID,
) -> ProjectionResult:
    slot_ids = {
        "relationship360": ["relationships"],
        "profile360": ["evidence_trace"],
    }.get(projection_id, [])
    return ProjectionResult(
        projectionId=projection_id,
        tenantId=tenant_id,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            _section(section_id, state="degraded" if section_id == "outcomes" else "available")
            for section_id in section_ids
        ],
        claims=[
            ClaimEnvelope(
                id=f"{projection_id}.fixture.{slot_id}",
                kind="fixture_observation",
                subject=SUBJECT,
                evidenceRefs=[EVIDENCE],
                claims=["A fixture source explicitly supports this slot."],
                domainSlotIds=[slot_id],
            )
            for slot_id in slot_ids
        ],
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        asOf="2026-10-17T10:00:00Z",
        degradedReasons=[],
    )


def _results(*, tenant_id: str = TENANT_ID) -> list[ProjectionResult]:
    sections_by_projection: dict[str, set[str]] = {}
    definition = PRODUCT_360_SURFACE_DEFINITIONS["account360"]
    for slot in definition["domainSlots"]:
        for binding in slot.get("projectionBindings", []):
            projection_id = binding.get("projectionId")
            if not isinstance(projection_id, str):
                continue
            sections = binding.get("sectionIds", [])
            sections_by_projection.setdefault(projection_id, set()).update(
                section for section in sections if isinstance(section, str)
            )
    return [
        _projection(projection_id, sorted(section_ids), tenant_id=tenant_id)
        for projection_id, section_ids in sorted(sections_by_projection.items())
    ]


def _allowed_slots() -> dict[str, Experience360PolicyDisposition]:
    slots = PRODUCT_360_SURFACE_DEFINITIONS["account360"]["domainSlots"]
    return {
        slot["id"]: Experience360PolicyDisposition(state="allowed")
        for slot in slots
    }


def _identity_slot_id() -> str:
    slot_ids = {
        slot["id"]
        for slot in PRODUCT_360_SURFACE_DEFINITIONS["account360"]["domainSlots"]
    }
    return (
        ACCOUNT_IDENTITY_SLOT
        if ACCOUNT_IDENTITY_SLOT in slot_ids
        else LEGACY_ACCOUNT_IDENTITY_SLOT
    )


def _catalog_slot_id(*candidates: str) -> str:
    slot_ids = {
        slot["id"]
        for slot in PRODUCT_360_SURFACE_DEFINITIONS["account360"]["domainSlots"]
    }
    return next(slot_id for slot_id in candidates if slot_id in slot_ids)


def _ensure_members_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise exact §11.13 membership slots before catalog integration lands."""

    definition = PRODUCT_360_SURFACE_DEFINITIONS["account360"]
    slots = definition["domainSlots"]
    slot_ids = {slot.get("id") for slot in slots}
    missing = {ACCOUNT_MEMBERS_SLOT, ACCOUNT_AGENTS_SLOT} - slot_ids
    if not missing:
        return
    additions = []
    if ACCOUNT_MEMBERS_SLOT in missing:
        additions.append(
            {
                "id": ACCOUNT_MEMBERS_SLOT,
                "requirement": "required",
                "description": "Known tenant-scoped account membership facts.",
                "canonicalAuthorityRefs": ["graph", "entity_registry"],
            }
        )
    if ACCOUNT_AGENTS_SLOT in missing:
        additions.append(
            {
                "id": ACCOUNT_AGENTS_SLOT,
                "requirement": "required",
                "description": "Known tenant-scoped agent membership facts.",
                "canonicalAuthorityRefs": ["graph", "entity_registry"],
            }
        )
    monkeypatch.setitem(
        definition,
        "domainSlots",
        [*slots, *additions],
    )


def _account_member(
    entity_id: str,
    entity_type: str,
    edge_id: str,
    *,
    role: str | None = None,
) -> AccountMember:
    return AccountMember(
        tenant_id=TENANT_ID,
        organization_entity_id=SUBJECT.id,
        entity_id=entity_id,
        entity_type=entity_type,
        role=role,
        membership_evidence_ref=EvidenceRef(
            id=edge_id,
            type="relationship",
            source="graph",
            observedAt="2026-10-17T09:50:00Z",
            uri=f"graph://edges/{edge_id}",
        ),
        entity_evidence_ref=EvidenceRef(
            id=entity_id,
            type="entity",
            source="entity_registry",
            observedAt="2026-10-17T09:45:00Z",
        ),
    )


@pytest.mark.asyncio
async def test_account360_composes_only_canonical_tenant_scoped_projection_results():
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
            display_name="Aether Org",
        )
    )
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
        generated_at="2026-10-17T10:02:00Z",
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert frame.surfaceId == "account360"
    assert frame.tenantId == TENANT_ID
    assert frame.subject == SUBJECT
    assert frame.ownsCanonicalTruth is False
    slots = {slot.id: slot for slot in frame.slots}
    identity_slot = slots[_identity_slot_id()]
    assert identity_slot.state == "degraded"
    assert identity_slot.content["canonicalEntity"] == {
        "kind": "entity",
        "id": SUBJECT.id,
        "entityType": "organization",
        "identityState": "resolved",
        "displayName": "Aether Org",
    }
    assert identity_slot.content["accountState"] == {
        "state": "unknown",
        "reason": "account_lifecycle_state_not_exposed_by_entity_registry",
    }
    assert "account_lifecycle_state_not_exposed_by_entity_registry" in identity_slot.reasonCodes
    assert identity_slot.freshness.state == "unknown"
    assert identity_slot.freshness.sourceAsOf == IDENTITY_EVIDENCE.observedAt
    assert EVIDENCE not in identity_slot.evidenceRefs
    assert IDENTITY_EVIDENCE in identity_slot.evidenceRefs
    assert any(
        provenance.sourceKind == "authority"
        and provenance.canonicalAuthorityRefs == ["entity_registry"]
        and IDENTITY_EVIDENCE in provenance.evidenceRefs
        for provenance in identity_slot.provenance
    )
    relationship_slot = slots[
        _catalog_slot_id("relationships", "account_relationships")
    ]
    value_slot = slots[_catalog_slot_id("value", "economic_context")]
    evidence_slot = slots[_catalog_slot_id("evidence_trace", "evidence_and_limitations")]
    assert relationship_slot.state == "available"
    assert EVIDENCE in relationship_slot.evidenceRefs
    assert IDENTITY_EVIDENCE not in relationship_slot.evidenceRefs
    assert value_slot.state == "unknown"
    assert value_slot.content is None
    assert "exact_slot_claim_missing" in value_slot.reasonCodes
    assert evidence_slot.state == "available"
    assert all(slot.provenance for slot in frame.slots if slot.content is not None)
    assert all(slot.evidenceRefs for slot in frame.slots if slot.content is not None)
    assert frame.freshness.state == "unknown"
    assert "surface_contract_pending_source_alignment" not in frame.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["account", "workspace"])
async def test_non_entity_account_aliases_return_typed_unknown_without_source_reads(
    subject_kind: str,
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    subject = ProjectionSubject(kind=subject_kind, id=f"{subject_kind}-identifier")
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead(
            "degraded",
            TENANT_ID,
            subject.id,
            members=(_account_member("agent-private", "agent", "agent-private-edge"),),
        ),
    )

    frame = await Account360Provider(source).compose(
        _request(subject=subject),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    reason = f"account_{subject_kind}_identity_resolution_unavailable"
    assert source.calls == []
    assert source.member_calls == []
    assert frame.subject == subject
    assert frame.state == "unknown"
    assert reason in frame.warnings
    assert all(slot.state == "unknown" for slot in frame.slots)
    assert all(reason in slot.reasonCodes for slot in frame.slots)
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)
    assert all(slot.provenance == [] for slot in frame.slots)
    assert "agent-private" not in str(frame.model_dump(mode="json", by_alias=True))


@pytest.mark.asyncio
async def test_members_slot_projects_only_evidenced_tenant_member_of_facts(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    member_edge = EvidenceRef(
        id="member-edge-key",
        type="relationship",
        source="graph",
        observedAt="2026-10-17T09:50:00Z",
        uri="graph://edges/member-edge-key",
    )
    member_entity = EvidenceRef(
        id="human-member-1",
        type="entity",
        source="entity_registry",
        observedAt="2026-10-17T09:45:00Z",
    )
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead(
            "degraded",
            TENANT_ID,
            SUBJECT.id,
            members=(
                AccountMember(
                    tenant_id=TENANT_ID,
                    organization_entity_id=SUBJECT.id,
                    entity_id="human-member-1",
                    entity_type="human",
                    role="billing_admin",
                    membership_evidence_ref=member_edge,
                    entity_evidence_ref=member_entity,
                ),
            ),
            reason_codes=("account_member_edge_completeness_unproven",),
            source_as_of="2026-10-17T09:50:00Z",
        ),
    )

    frame = await Account360Provider(source).compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert source.member_calls == [(TENANT_ID, SUBJECT.id)]
    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_MEMBERS_SLOT)
    assert slot.state == "degraded"
    assert slot.content == {
        "subject": {"kind": "entity", "id": SUBJECT.id},
        "membershipRelation": "MEMBER_OF",
        "members": [
            {
                "entity": {
                    "kind": "entity",
                    "id": "human-member-1",
                    "entityType": "human",
                },
                "role": "billing_admin",
                "evidenceRefIds": ["member-edge-key", "human-member-1"],
            }
        ],
        "coverage": {
            "state": "unknown",
            "reason": "account_member_edge_completeness_unproven",
        },
    }
    assert member_edge in slot.evidenceRefs
    assert member_entity in slot.evidenceRefs
    assert slot.freshness.state == "unknown"
    assert slot.freshness.sourceAsOf == "2026-10-17T09:50:00Z"
    assert any(
        item.sourceKind == "authority"
        and item.canonicalAuthorityRefs == ["graph", "entity_registry"]
        and member_edge in item.evidenceRefs
        for item in slot.provenance
    )
    assert "email" not in str(slot.content).lower()


@pytest.mark.asyncio
async def test_members_slot_does_not_read_when_slot_policy_is_denied(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead("unknown", TENANT_ID, SUBJECT.id),
    )
    policy = _allowed_slots()
    policy[ACCOUNT_MEMBERS_SLOT] = Experience360PolicyDisposition(state="denied")
    policy[ACCOUNT_AGENTS_SLOT] = Experience360PolicyDisposition(state="denied")
    policy[ACCOUNT_PROFILES_SLOT] = Experience360PolicyDisposition(state="denied")

    frame = await Account360Provider(source).compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert source.member_calls == []
    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_MEMBERS_SLOT)
    assert slot.state == "suppressed"
    assert slot.content is None
    assert slot.evidenceRefs == []


@pytest.mark.asyncio
async def test_membership_slots_stay_unknown_without_evidence_and_skip_member_read(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead("degraded", TENANT_ID, SUBJECT.id),
    )

    frame = await Account360Provider(source).compose(
        _request(
            include_evidence=False,
            requested_slot_ids=[ACCOUNT_MEMBERS_SLOT, ACCOUNT_AGENTS_SLOT],
        ),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.member_calls == []
    for slot_id in (ACCOUNT_MEMBERS_SLOT, ACCOUNT_AGENTS_SLOT):
        slot = next(slot for slot in frame.slots if slot.id == slot_id)
        assert slot.state == "unknown"
        assert slot.content is None
        assert slot.evidenceRefs == []
        assert "account_membership_evidence_not_requested" in slot.reasonCodes


@pytest.mark.asyncio
async def test_agents_slot_projects_only_validated_agent_membership_facts(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    agent = _account_member("agent-1", "agent", "agent-member-edge", role="operator")
    human = _account_member("human-1", "human", "human-member-edge", role="owner")
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead(
            "degraded",
            TENANT_ID,
            SUBJECT.id,
            members=(human, agent),
            reason_codes=("account_member_edge_completeness_unproven",),
            source_as_of="2026-10-17T09:50:00Z",
        ),
    )

    frame = await Account360Provider(source).compose(
        _request(requested_slot_ids=[ACCOUNT_AGENTS_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_AGENTS_SLOT)
    assert source.member_calls == [(TENANT_ID, SUBJECT.id)]
    assert slot.state == "degraded"
    assert slot.content == {
        "subject": {"kind": "entity", "id": SUBJECT.id},
        "membershipRelation": "MEMBER_OF",
        "agents": [
            {
                "entity": {"kind": "entity", "id": "agent-1", "entityType": "agent"},
                "role": "operator",
                "evidenceRefIds": ["agent-member-edge", "agent-1"],
            }
        ],
        "coverage": {
            "state": "unknown",
            "reason": "account_agent_member_edge_completeness_unproven",
        },
    }
    assert {ref.id for ref in slot.evidenceRefs} == {"agent-member-edge", "agent-1"}
    assert slot.freshness.state == "unknown"
    assert slot.freshness.sourceAsOf == "2026-10-17T09:50:00Z"
    assert any(
        provenance.canonicalAuthorityRefs == ["graph", "entity_registry"]
        and {ref.id for ref in provenance.evidenceRefs}
        == {"agent-member-edge", "agent-1"}
        for provenance in slot.provenance
    )
    assert "delegation" not in str(slot.content).lower()
    assert "authority" not in str(slot.content).lower()


@pytest.mark.asyncio
async def test_agents_slot_policy_cannot_be_bypassed_through_members_slot(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    agent = _account_member("agent-private", "agent", "agent-private-edge")
    human = _account_member("human-visible", "human", "human-visible-edge")
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead(
            "degraded",
            TENANT_ID,
            SUBJECT.id,
            members=(human, agent),
            source_as_of="2026-10-17T09:50:00Z",
        ),
    )
    policy = _allowed_slots()
    policy[ACCOUNT_AGENTS_SLOT] = Experience360PolicyDisposition(state="denied")

    frame = await Account360Provider(source).compose(
        _request(requested_slot_ids=[ACCOUNT_MEMBERS_SLOT, ACCOUNT_AGENTS_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
    )

    members_slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_MEMBERS_SLOT)
    agents_slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_AGENTS_SLOT)
    assert source.member_calls == [(TENANT_ID, SUBJECT.id)]
    assert members_slot.state == "degraded"
    assert [item["entity"]["id"] for item in members_slot.content["members"]] == [
        "human-visible"
    ]
    assert {ref.id for ref in members_slot.evidenceRefs} == {
        "human-visible-edge",
        "human-visible",
    }
    assert agents_slot.state == "suppressed"
    assert agents_slot.content is None
    assert agents_slot.evidenceRefs == []
    assert "agent-private" not in str(frame.model_dump(mode="json", by_alias=True))


@pytest.mark.asyncio
async def test_agents_without_validated_agent_members_remain_unknown_not_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead(
            "degraded",
            TENANT_ID,
            SUBJECT.id,
            members=(_account_member("human-1", "human", "human-edge"),),
        ),
    )

    frame = await Account360Provider(source).compose(
        _request(requested_slot_ids=[ACCOUNT_AGENTS_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_AGENTS_SLOT)
    assert source.member_calls == [(TENANT_ID, SUBJECT.id)]
    assert slot.state == "unknown"
    assert slot.content is None
    assert slot.evidenceRefs == []
    assert "account_agent_membership_not_observed_completeness_unknown" in slot.reasonCodes


@pytest.mark.asyncio
async def test_account_profiles_policy_denial_skips_membership_and_profile_reads(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)
    member = _account_member("member-profile-denied", "human", "member-edge-denied")
    source = _MembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
            tenant_id=TENANT_ID,
            entity_id=SUBJECT.id,
        ),
        AccountMembersRead(
            "degraded", TENANT_ID, SUBJECT.id, members=(member,)
        ),
    )
    profile_reader_calls: list[str] = []

    async def profile_reader(member, _request):
        profile_reader_calls.append(member.entity_id)
        raise AssertionError("denied Account360 profile slot must not read profiles")

    policy = _allowed_slots()
    policy[ACCOUNT_PROFILES_SLOT] = Experience360PolicyDisposition(state="denied")
    frame = await Account360Provider(source).compose(
        _request(requested_slot_ids=[ACCOUNT_PROFILES_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
        member_profile_reader=profile_reader,
    )

    assert source.member_calls == []
    assert profile_reader_calls == []
    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_PROFILES_SLOT)
    assert slot.policyDisposition.state == "denied"
    assert slot.content is None


@pytest.mark.asyncio
async def test_repository_member_read_uses_tenant_edges_and_exact_entity_joins(
    monkeypatch: pytest.MonkeyPatch,
):
    from repositories.repos import EntityRepository
    from shared.graph.graph import Edge, EdgeType

    class _Graph:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, list[str]]] = []

        async def get_edges_for_tenant(
            self, tenant_id: str, *, limit: int, edge_types: list[str]
        ):
            self.calls.append((tenant_id, limit, edge_types))
            return [
                Edge(
                    EdgeType.MEMBER_OF,
                    "human-member-1",
                    SUBJECT.id,
                    {
                        "tenant_id": TENANT_ID,
                        "role": "billing_admin",
                        "idempotency_key": "member-edge-key",
                        "recorded_at": "2026-10-17T09:50:00Z",
                    },
                ),
                Edge(
                    EdgeType.MEMBER_OF,
                    "agent-member-1",
                    SUBJECT.id,
                    {
                        "tenant_id": TENANT_ID,
                        "role": "operator",
                        "idempotency_key": "agent-edge-key",
                        "recorded_at": "2026-10-17T09:49:00Z",
                    },
                ),
                Edge(
                    EdgeType.MEMBER_OF,
                    "foreign-member",
                    SUBJECT.id,
                    {
                        "tenant_id": "tenant-foreign",
                        "role": "owner",
                        "idempotency_key": "foreign-edge-key",
                    },
                ),
                Edge(
                    EdgeType.MEMBER_OF,
                    "other-account-member",
                    "another-organization",
                    {
                        "tenant_id": TENANT_ID,
                        "role": "owner",
                        "idempotency_key": "other-account-edge-key",
                    },
                ),
            ], False

    graph = _Graph()
    entity_calls: list[tuple[str, set[str]]] = []

    async def find_many_for_tenant_entity_ids(self, tenant_id, entity_ids):
        entity_calls.append((tenant_id, set(entity_ids)))
        return [
            {
                "tenant_id": TENANT_ID,
                "entity_id": "human-member-1",
                "entity_type": "human",
                "display_name": "Private member name",
                "email": "private@example.test",
                "updated_at": "2026-10-17T09:45:00Z",
            },
            {
                "tenant_id": TENANT_ID,
                "entity_id": "agent-member-1",
                "entity_type": "agent",
                "display_name": "Private agent name",
                "updated_at": "2026-10-17T09:44:00Z",
            },
        ], False

    monkeypatch.setattr(
        EntityRepository,
        "find_many_for_tenant_entity_ids",
        find_many_for_tenant_entity_ids,
    )
    result = await RepositoryAccount360Source(graph=graph).account_members(
        TENANT_ID,
        SUBJECT.id,
    )

    assert graph.calls == [(TENANT_ID, 10_000, [EdgeType.MEMBER_OF])]
    assert entity_calls == [(TENANT_ID, {"human-member-1", "agent-member-1"})]
    assert result.state == "degraded"
    assert len(result.members) == 2
    members_by_id = {member.entity_id: member for member in result.members}
    member = members_by_id["human-member-1"]
    assert member.entity_id == "human-member-1"
    assert member.entity_type == "human"
    assert member.role == "billing_admin"
    assert member.membership_evidence_ref.id == "member-edge-key"
    assert member.entity_evidence_ref.id == "human-member-1"
    agent_member = members_by_id["agent-member-1"]
    assert agent_member.entity_type == "agent"
    assert agent_member.role == "operator"
    assert agent_member.membership_evidence_ref.id == "agent-edge-key"
    assert agent_member.entity_evidence_ref.id == "agent-member-1"
    assert "account_member_graph_scope_mismatch" in result.reason_codes
    assert "Private member name" not in str(member)
    assert "Private agent name" not in str(agent_member)
    assert "private@example.test" not in str(member)


@pytest.mark.asyncio
async def test_members_without_verified_edges_remain_unknown_not_empty(
    monkeypatch: pytest.MonkeyPatch,
):
    _ensure_members_slot(monkeypatch)

    class _EmptyMembersSource(_MembersSource):
        async def account_members(self, tenant_id: str, organization_entity_id: str):
            self.member_calls.append((tenant_id, organization_entity_id))
            return AccountMembersRead(
                "unknown",
                tenant_id,
                organization_entity_id,
                reason_codes=("account_member_edges_not_observed_completeness_unknown",),
            )

    source = _EmptyMembersSource(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        ),
        AccountMembersRead("unknown", TENANT_ID, SUBJECT.id),
    )

    frame = await Account360Provider(source).compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    slot = next(slot for slot in frame.slots if slot.id == ACCOUNT_MEMBERS_SLOT)
    assert source.member_calls == [(TENANT_ID, SUBJECT.id)]
    assert slot.state == "unknown"
    assert slot.content is None
    assert "account_member_edges_not_observed_completeness_unknown" in slot.reasonCodes


@pytest.mark.asyncio
async def test_account_summary_uses_registry_identity_when_profile_sections_are_unknown():
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        )
    )
    results = _results()
    for index, result in enumerate(results):
        if result.projectionId != "profile360":
            continue
        results[index] = result.model_copy(
            update={
                "sections": [
                    section.model_copy(update={"state": "unknown", "content": None})
                    if section.id in {"summary", "state"}
                    else section
                    for section in result.sections
                ]
            }
        )

    frame = await Account360Provider(source).compose(
        _request(),
        results,
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    summary = next(slot for slot in frame.slots if slot.id == _identity_slot_id())
    assert summary.state == "degraded"
    assert summary.content["sections"] == []
    assert summary.content["canonicalEntity"]["id"] == SUBJECT.id
    assert summary.content["accountState"]["state"] == "unknown"
    assert IDENTITY_EVIDENCE in summary.evidenceRefs
    assert any(
        provenance.canonicalAuthorityRefs == ["entity_registry"]
        and IDENTITY_EVIDENCE in provenance.evidenceRefs
        for provenance in summary.provenance
    )


@pytest.mark.asyncio
async def test_missing_policy_defaults_to_unknown_and_does_not_read_or_expose_results():
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        )
    )
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot={
            _identity_slot_id(): Experience360PolicyDisposition(
                state="allowed"
            )
        },
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    slots = {slot.id: slot for slot in frame.slots}
    assert slots[_identity_slot_id()].state == "degraded"
    assert slots[_identity_slot_id()].content is not None
    for slot in frame.slots:
        if slot.id == _identity_slot_id():
            continue
        slot_id = slot.id
        assert slots[slot_id].state == "suppressed"
        assert slots[slot_id].content is None
        assert "policy_not_evaluated" in slots[slot_id].reasonCodes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_evidence", "identity_policy"),
    [(True, "denied"), (False, "allowed")],
)
async def test_account_identity_evidence_respects_slot_policy_and_evidence_request(
    include_evidence: bool, identity_policy: str
):
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        )
    )
    policy = _allowed_slots()
    policy[_identity_slot_id()] = Experience360PolicyDisposition(state=identity_policy)

    frame = await Account360Provider(source).compose(
        _request(include_evidence=include_evidence),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
    )

    identity_slot = next(slot for slot in frame.slots if slot.id == _identity_slot_id())
    assert IDENTITY_EVIDENCE not in identity_slot.evidenceRefs


@pytest.mark.asyncio
async def test_frame_policy_unknown_skips_entity_read_and_suppresses_all_content():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(
            state="unknown", reasonCodes=["policy_not_evaluated"]
        ),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == []
    assert all(slot.state == "suppressed" for slot in frame.slots)
    assert all(slot.content is None for slot in frame.slots)


@pytest.mark.asyncio
async def test_unresolved_canonical_subject_discards_projection_results():
    source = _Source(AccountIdentityRead("unknown", "account_entity_scope_mismatch"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert "account_entity_scope_mismatch" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)
    assert all(slot.state in {"missing", "unknown"} for slot in frame.slots)


@pytest.mark.asyncio
async def test_resolved_entity_without_registry_evidence_does_not_expose_sibling_projections():
    source = _Source(AccountIdentityRead("resolved", entity_type="organization"))

    frame = await Account360Provider(source).compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert "account_entity_identity_evidence_missing_or_unscoped" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)


@pytest.mark.asyncio
async def test_pre_resolved_identity_from_another_tenant_is_rejected():
    source = _Source(AccountIdentityRead("resolved"))
    foreign_identity = AccountIdentityRead(
        "resolved",
        evidence_refs=(IDENTITY_EVIDENCE,),
        entity_type="organization",
        tenant_id="tenant-foreign",
        entity_id=SUBJECT.id,
    )

    frame = await Account360Provider(source).compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        identity_read=foreign_identity,
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == []
    assert "account_entity_scope_mismatch" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)


@pytest.mark.asyncio
async def test_current_entity_identity_is_not_reused_for_historical_account_frame():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(as_of="2026-10-01T00:00:00Z"),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == []
    assert "account_entity_temporal_identity_unavailable" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)


@pytest.mark.asyncio
async def test_projection_from_another_tenant_is_rejected_after_subject_validation():
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        )
    )
    provider = Account360Provider(source)

    with pytest.raises(ProjectionError, match="projection result tenant"):
        await provider.compose(
            _request(),
            _results(tenant_id="tenant-foreign"),
            frame_policy=Experience360PolicyDisposition(state="allowed"),
            policy_by_slot=_allowed_slots(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ["account", "organization"])
async def test_repository_source_resolves_canonical_organization_account_and_discards_raw_fields(
    monkeypatch: pytest.MonkeyPatch, entity_type: str
):
    from repositories.repos import EntityRepository

    calls: list[tuple[dict[str, str], int]] = []

    async def find_many(self, *, filters, limit=50, **_kwargs):
        calls.append((filters, limit))
        return [
            {
                "tenant_id": TENANT_ID,
                "entity_id": SUBJECT.id,
                "entity_type": entity_type,
                "display_name": "Aether Org",
                "updated_at": "2026-10-17T09:59:00Z",
                "email": "private@example.test",
                "metadata": {"secret": "must-not-project"},
            }
        ]

    monkeypatch.setattr(EntityRepository, "find_many", find_many)
    identity = await RepositoryAccount360Source().canonical_entity(TENANT_ID, SUBJECT.id)

    assert calls == [({"tenant_id": TENANT_ID, "entity_id": SUBJECT.id}, 2)]
    assert identity.state == "resolved"
    assert identity.reason_code is None
    assert identity.evidence_refs == (IDENTITY_EVIDENCE,)
    assert identity.entity_type == entity_type
    assert identity.display_name == "Aether Org"
    assert identity.tenant_id == TENANT_ID
    assert identity.entity_id == SUBJECT.id
    assert "private@example.test" not in str(identity)
    assert "must-not-project" not in str(identity)


@pytest.mark.asyncio
async def test_same_tenant_non_account_entity_cannot_expose_account_projection_data(
    monkeypatch: pytest.MonkeyPatch,
):
    from repositories.repos import EntityRepository

    calls: list[tuple[dict[str, str], int]] = []

    async def find_many(self, *, filters, limit=50, **_kwargs):
        calls.append((filters, limit))
        return [
            {
                "tenant_id": TENANT_ID,
                "entity_id": SUBJECT.id,
                "entity_type": "agent",
                "display_name": "Private agent profile",
            }
        ]

    monkeypatch.setattr(EntityRepository, "find_many", find_many)
    provider = Account360Provider(RepositoryAccount360Source())
    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert calls == [({"tenant_id": TENANT_ID, "entity_id": SUBJECT.id}, 2)]
    assert "account_entity_type_mismatch" in frame.warnings
    assert all(slot.state in {"missing", "unknown"} for slot in frame.slots)
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)
    assert "Private agent profile" not in str(frame.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_account_risk_reuses_exact_entity_risk_provider_under_slot_policy():
    risk_provider = _RiskProvider(_risk_result())
    source = _Source(
        AccountIdentityRead(
            "resolved",
            evidence_refs=(IDENTITY_EVIDENCE,),
            entity_type="organization",
        )
    )

    frame = await Account360Provider(
        source,
        risk_provider=risk_provider,
    ).compose(
        _request(requested_slot_ids=[ACCOUNT_RISK_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert len(risk_provider.calls) == 1
    projection_request, projection_context = risk_provider.calls[0]
    assert projection_request.projectionId == "risk360"
    assert projection_request.tenantId == TENANT_ID
    assert projection_request.subject == ProjectionSubject(kind="entity", id=SUBJECT.id)
    assert projection_request.temporalMode == "window"
    assert projection_context.tenantId == TENANT_ID
    assert {
        item.projectionId: item.state for item in projection_context.dependencyState
    } == {"profile360": "unknown", "cluster360": "unknown"}

    slot = next(item for item in frame.slots if item.id == ACCOUNT_RISK_SLOT)
    risk_evidence = EvidenceRef(
        id="risk-assessment-1",
        type="model_output",
        source="risk_assessments",
        observedAt="2026-10-17T09:55:00Z",
    )
    assert slot.state == "degraded"
    assert slot.content["scope"] == "direct_account_entity_only"
    assert slot.content["coverage"] == {
        "state": "partial",
        "reason": "account_risk_related_entity_join_not_available",
    }
    assert risk_evidence in slot.evidenceRefs
    assert slot.claims[0].domainSlotIds == [ACCOUNT_RISK_SLOT]
    assert any(
        provenance.projectionId == "risk360"
        and provenance.canonicalAuthorityRefs == ["risk_outputs"]
        for provenance in slot.provenance
    )
    assert slot.freshness.state == "unknown"
    assert "account_risk_freshness_sla_unconfigured" in slot.reasonCodes


@pytest.mark.asyncio
async def test_account_risk_read_is_skipped_when_slot_policy_denies_it():
    risk_provider = _RiskProvider(_risk_result())
    policy = _allowed_slots()
    policy[ACCOUNT_RISK_SLOT] = Experience360PolicyDisposition(state="denied")

    frame = await Account360Provider(
        _Source(
            AccountIdentityRead(
                "resolved",
                evidence_refs=(IDENTITY_EVIDENCE,),
                entity_type="organization",
            )
        ),
        risk_provider=risk_provider,
    ).compose(
        _request(requested_slot_ids=[ACCOUNT_RISK_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
    )

    slot = next(item for item in frame.slots if item.id == ACCOUNT_RISK_SLOT)
    assert risk_provider.calls == []
    assert slot.state == "suppressed"
    assert slot.content is None
    assert slot.evidenceRefs == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("as_of", "include_evidence", "expected_reason"),
    [
        (
            "2026-10-01T00:00:00Z",
            True,
            "account_entity_temporal_identity_unavailable",
        ),
        (None, False, "account_risk_evidence_not_requested"),
    ],
)
async def test_account_risk_read_stays_unknown_when_time_or_evidence_is_unsupported(
    as_of: str | None,
    include_evidence: bool,
    expected_reason: str,
):
    risk_provider = _RiskProvider(_risk_result())

    frame = await Account360Provider(
        _Source(
            AccountIdentityRead(
                "resolved",
                evidence_refs=(IDENTITY_EVIDENCE,),
                entity_type="organization",
            )
        ),
        risk_provider=risk_provider,
    ).compose(
        _request(
            as_of=as_of,
            include_evidence=include_evidence,
            requested_slot_ids=[ACCOUNT_RISK_SLOT],
        ),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    slot = next(item for item in frame.slots if item.id == ACCOUNT_RISK_SLOT)
    assert risk_provider.calls == []
    assert slot.state == "unknown"
    assert slot.content is None
    assert expected_reason in slot.reasonCodes


@pytest.mark.asyncio
async def test_account_risk_result_without_evidenced_claims_remains_unknown():
    risk_provider = _RiskProvider(_risk_result(with_evidence=False))

    frame = await Account360Provider(
        _Source(
            AccountIdentityRead(
                "resolved",
                evidence_refs=(IDENTITY_EVIDENCE,),
                entity_type="organization",
            )
        ),
        risk_provider=risk_provider,
    ).compose(
        _request(requested_slot_ids=[ACCOUNT_RISK_SLOT]),
        [],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    slot = next(item for item in frame.slots if item.id == ACCOUNT_RISK_SLOT)
    assert slot.state == "unknown"
    assert slot.content is None
    assert slot.evidenceRefs == []
    assert "account_risk_evidence_missing" in slot.reasonCodes
