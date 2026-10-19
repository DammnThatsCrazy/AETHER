"""Unit tests for the Phase-4 Communication360 intelligence-projection provider.

The provider is a read-only, fail-isolated, tenant-scoped projection over the
shipped silver message spine (``services/api/journeys/comms``) + the Phase-3 canonical fact
store (``services/api/journeys/communication360``). These tests cover:

* a valid ``ProjectionResult`` with the six typed sections in registry order
  and ``extra="forbid"`` conformance (the plane fails closed);
* claims carry ``claimState`` capped at ``observed`` (never ``verified``) and
  reused ``EvidenceRef``s;
* available-but-empty silver -> ``summary``/``timeline`` available with REAL
  zero counts / present-empty; ``state`` dimensions that are ``missing`` /
  ``not_applicable`` never render a fabricated zero;
* an unavailable backing source -> degraded sections with typed short-string
  ``degradedReasons`` and NO fabricated numeric (no exception body leaks);
* ``dependencyState`` echoes the injected registry context verbatim and
  outcome360 (an in_flight sibling) degrades the outcomes section, never the
  result's ``degradedReasons``;
* tenant isolation — tenant A never surfaces tenant B's messages/evidence;
* campaign subject filters the silver spine by ``campaign_id``;
* registration via ``register_provider`` (success, duplicate, version
  mismatch, unknown id) — and importing the provider has no side effects.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.communication360.contracts import CommunicationMessage  # noqa: E402
from journeys.communication360.provider import (  # noqa: E402
    AgentIdentityRead,
    OUTPUT_SECTIONS,
    REASON_CANONICAL_SOURCE_UNAVAILABLE,
    REASON_SILVER_SOURCE_UNAVAILABLE,
    REASON_SOURCE_READ_TRUNCATED,
    Communication360Provider,
    register_provider,
)
from journeys.communication360.reader import to_message  # noqa: E402
from journeys.comms.contracts import CommunicationState, MessageCategory  # noqa: E402
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)

VALID_SECTION_STATES = {
    "available",
    "degraded",
    "empty",
    "missing",
    "not_applicable",
    "unknown",
    "suppressed",
    "stale",
}

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
_CATEGORY_OMITTED = object()


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class FakeSource:
    """CommunicationSource test double — no database, no default store."""

    def __init__(
        self,
        *,
        messages: list[CommunicationMessage] | None = None,
        facts: list[dict] | None = None,
        raises: str | None = None,
    ) -> None:
        self._messages = list(messages or [])
        self._facts = list(facts or [])
        self._raises = raises  # "messages" | "facts" | "all"
        self.last_campaign_id: str | None = None
        self.last_participant_entity_id: str | None = None
        self.message_read_count = 0
        self.fact_read_count = 0

    async def messages(
        self,
        tenant_id,
        *,
        campaign_id=None,
        participant_entity_id=None,
        since=None,
        limit=None,
    ):
        self.message_read_count += 1
        if self._raises in ("messages", "all"):
            raise RuntimeError("fake boom: secret-detail")
        self.last_campaign_id = campaign_id
        self.last_participant_entity_id = participant_entity_id
        out = [
            m
            for m in self._messages
            if m.tenant_id == tenant_id
            and (campaign_id is None or m.campaign_id == campaign_id)
            and (
                participant_entity_id is None
                or participant_entity_id in {m.sender_entity_id, m.recipient_entity_id}
            )
        ]
        out.sort(key=lambda m: m.occurred_at)
        if limit is not None:
            out = out[:limit]
        return out

    async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
        self.fact_read_count += 1
        if self._raises in ("facts", "all"):
            raise RuntimeError("fake boom: secret-detail")
        out = [
            r
            for r in self._facts
            if r.get("tenant_id") == tenant_id
            and (kind is None or r.get("kind") == kind)
            and (since is None or str(r.get("occurred_at") or "") >= str(since))
        ]
        if limit is not None:
            out = out[:limit]
        return out

    async def available(self, tenant_id):
        return self._raises is None


def _msg(
    tenant: str,
    mid: str,
    *,
    campaign_id: str = "camp_1",
    state: str = "delivered",
    direction: str = "outbound",
    channel: str = "email",
    occurred_at: str = "2026-09-03T10:00:00Z",
    ref_id: str | None = None,
    sender_entity_id: str | None = None,
    recipient_entity_id: str | None = None,
) -> CommunicationMessage:
    return CommunicationMessage(
        message_id=mid,
        tenant_id=tenant,
        fact_id=f"fact-{mid}",
        channel=channel,
        direction=direction,
        communication_state=CommunicationState(state),
        sender_entity_id=sender_entity_id,
        recipient_entity_id=recipient_entity_id,
        campaign_id=campaign_id,
        occurred_at=occurred_at,
        received_at=occurred_at,
        claim_state=EpistemicStatus.OBSERVED,
        evidence_refs=[
            EvidenceRef(
                id=ref_id or f"ev-{mid}",
                type="event",
                source="test/fake/silver",
                uri=f"store://test/{mid}",
            )
        ],
    )


def _fact(
    tenant: str,
    fact_id: str,
    kind: str = "communication_act",
    *,
    actor_id: str | None = "entity-1",
    occurred_at: str = "2026-09-03T11:00:00Z",
    payload: dict | None = None,
) -> dict:
    return {
        "fact_id": fact_id,
        "tenant_id": tenant,
        "kind": kind,
        "source_event_id": f"evt-{fact_id}",
        "actor_id": actor_id,
        "agent_id": None,
        "occurred_at": occurred_at,
        "received_at": occurred_at,
        "idempotency_key": f"key-{fact_id}",
        "payload": payload or {},
    }


def _request(tenant: str = TENANT_A, **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "communication360",
        "tenantId": tenant,
        "subject": ProjectionSubject(kind="campaign", id="camp_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _make_context(
    reg: ProviderRegistry,
    tenant: str = TENANT_A,
    **overrides: object,
) -> tuple[ProjectionRequest, ProjectionContext]:
    """A runtime context for a communication360 request (registry truth)."""
    request = _request(tenant=tenant, **overrides)
    context = await reg.build_context("communication360", request)
    return request, context


@pytest.fixture
def spine_source() -> FakeSource:
    return FakeSource(
        messages=[
            _msg(TENANT_A, "m1", state="sent", occurred_at="2026-09-03T10:00:00Z"),
            _msg(TENANT_A, "m2", state="delivered", occurred_at="2026-09-03T10:05:00Z"),
            _msg(TENANT_A, "m3", state="opened", occurred_at="2026-09-03T10:10:00Z"),
        ]
    )


@pytest.fixture
def act_source() -> FakeSource:
    return FakeSource(
        facts=[
            _fact(
                TENANT_A,
                "act-1",
                kind="communication_act",
                payload={
                    "campaign_id": "camp_1",
                    "act_type": "commit",
                    "actor_entity_id": "entity-1",
                    "target_entity_id": "entity-2",
                },
            ),
            _fact(
                TENANT_A,
                "pb-1",
                kind="participant_binding",
                payload={
                    "campaign_id": "camp_1",
                    "role": "actor",
                    "entity_id": "entity-1",
                    "communication_scope": "message:m1",
                },
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Valid result: six typed sections + evidence-grounded observed claims
# ---------------------------------------------------------------------------


async def test_project_returns_valid_result(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "communication360"
    assert result.tenantId == TENANT_A
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.generatedAt  # ISO-8601 UTC
    assert result.degradedReasons == []


async def test_project_emits_exact_registry_sections_in_order(
    spine_source: FakeSource,
) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    assert OUTPUT_SECTIONS == (
        "summary",
        "state",
        "timeline",
        "evidence",
        "interactions",
        "outcomes",
    )


async def test_section_states_are_typed(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    for section in result.sections:
        assert section.state in VALID_SECTION_STATES, section.id
    # Round-trip through the strict contract proves no unexpected fields leak.
    dumped = result.model_dump(mode="json")
    ProjectionResult(**dumped)


async def test_provider_result_conforms_to_extra_forbid(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)
    # extra="forbid" is validated by construction; round-trip also re-validates.
    ProjectionResult(**result.model_dump(mode="json"))


def test_projection_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="communication360",
            tenantId=TENANT_A,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            generatedAt="2026-09-03T12:00:00Z",
            degradedReasons=[],
            unexpectedField="nope",
        )


# ---------------------------------------------------------------------------
# Claims: observed cap + evidence grounding
# ---------------------------------------------------------------------------


async def test_claims_are_evidence_grounded_and_observed_capped(
    spine_source: FakeSource,
) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    assert result.claims, "expected timeline claims"
    assert all("communications" in (claim.domainSlotIds or []) for claim in result.claims)
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.claimState is EpistemicStatus.OBSERVED  # never verified
        assert claim.claimState is not EpistemicStatus.VERIFIED
        assert claim.evidenceRefs, f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        assert claim.confidence is None or 0.0 <= claim.confidence <= 1.0
        for ref in claim.evidenceRefs:
            assert isinstance(ref, EvidenceRef)
            assert ref.id
        # One claim per evidenced timeline message.
        assert claim.id.startswith("timeline.")


async def test_claims_include_each_spine_message(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    claim_ids = {c.id for c in result.claims}
    assert claim_ids == {"timeline.m1", "timeline.m2", "timeline.m3"}


@pytest.mark.parametrize(
    ("raw_category", "expected_category"),
    [
        ("marketing", MessageCategory.MARKETING),
        (_CATEGORY_OMITTED, None),
        ("future_private_category", None),
    ],
    ids=["canonical", "absent", "unrecognized"],
)
async def test_provider_treats_message_category_as_source_fact_only(
    raw_category: object, expected_category: MessageCategory | None
) -> None:
    row: dict[str, object] = {
        "tenant_id": TENANT_A,
        "fact_id": "fact-category",
        "message_id": "message-category",
        "campaign_id": "camp_1",
        "communication_state": "delivered",
        "occurred_at": "2026-09-03T10:00:00Z",
    }
    if raw_category is not _CATEGORY_OMITTED:
        row["message_category"] = raw_category
    message = to_message(row)
    assert message.message_category is expected_category

    provider = Communication360Provider(sources=FakeSource(messages=[message]))
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["counts"]["messages_total"] == 1
    timeline = next(section for section in result.sections if section.id == "timeline")
    assert timeline.content["entryCount"] == 1
    assert timeline.content["entries"][0]["messageId"] == "message-category"
    state = next(section for section in result.sections if section.id == "state")
    authority = next(
        dimension
        for dimension in state.content["dimensions"]
        if dimension["dimension"] == "authority"
    )
    assert authority["state"] == "missing"
    assert all(claim.claimState is EpistemicStatus.OBSERVED for claim in result.claims)


# ---------------------------------------------------------------------------
# summary — available-but-empty is a REAL zero; unavailable is degraded + typed
# ---------------------------------------------------------------------------


async def test_empty_available_spine_summary_is_available_with_real_zero() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "available"
    counts = summary.content["counts"]
    assert counts["messages_total"] == 0  # real zero, not a fabricated number
    assert counts["engagement"] == {"opened": 0, "clicked": 0, "replied": 0}
    assert counts["by_direction"]["outbound"] == 0
    # Honest absence for not-yet-derivable surface facts is None, never 0.
    assert counts["active_conversations"] is None
    assert result.degradedReasons == []


async def test_empty_available_spine_timeline_is_present_empty() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    timeline = next(s for s in result.sections if s.id == "timeline")
    assert timeline.state == "available"
    assert timeline.content["entryCount"] == 0
    assert timeline.content["entries"] == []
    assert timeline.content["orderLabeled"] is False  # no entries -> unlabeled
    assert timeline.content["causalRelationsDeclared"] == []
    assert result.claims == []


async def test_unavailable_source_degrades_summary_without_numeric() -> None:
    provider = Communication360Provider(sources=FakeSource(raises="all"))
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    assert result.projectionId == "communication360"
    assert result.degradedReasons == [
        REASON_SILVER_SOURCE_UNAVAILABLE,
        REASON_CANONICAL_SOURCE_UNAVAILABLE,
    ]
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None  # no fabricated numeric
    # Typed short-string codes, never the exception body.
    assert all(isinstance(r, str) and " " not in r for r in result.degradedReasons)
    assert "secret-detail" not in result.model_dump_json()
    assert "boom" not in result.model_dump_json()


async def test_only_silver_unavailable_degrades_summary() -> None:
    # A dict injection lets the two roles fail independently.
    provider = Communication360Provider(
        sources={
            "silver": FakeSource(raises="messages"),
            "canonical": FakeSource(facts=[_fact(TENANT_A, "act-1")]),
        }
    )
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    assert result.degradedReasons == [REASON_SILVER_SOURCE_UNAVAILABLE]
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None
    timeline = next(s for s in result.sections if s.id == "timeline")
    assert timeline.state == "degraded"


# ---------------------------------------------------------------------------
# state — the six dimensions, typed; missing/not_applicable never zero
# ---------------------------------------------------------------------------


async def test_state_has_exactly_the_six_dimensions(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    state = next(s for s in result.sections if s.id == "state")
    dimensions = state.content["dimensions"]
    assert [d["dimension"] for d in dimensions] == [
        "delivery",
        "engagement",
        "campaign-context",
        "information",
        "knowledge",
        "authority",
    ]
    for dim in dimensions:
        assert dim["state"] in VALID_SECTION_STATES, dim["dimension"]
        # missing/not_applicable/degraded dimensions never carry a fabricated 0.
        if dim["state"] in ("missing", "not_applicable", "degraded"):
            assert dim["observed"] is None


async def test_state_dimension_delivery_counts_from_spine(
    spine_source: FakeSource,
) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    state = next(s for s in result.sections if s.id == "state")
    delivery = state.content["dimensions"][0]
    assert delivery["state"] == "available"
    assert delivery["observed"] == 3
    assert delivery["breakdown"] == {
        "sent": 1,
        "delivered": 1,
        "opened": 1,
    }
    engagement = state.content["dimensions"][1]
    assert engagement["breakdown"] == {"opened": 1, "clicked": 0, "replied": 0}


async def test_state_canonical_dimensions_missing_when_store_empty() -> None:
    # Reachable canonical store with no rows -> the canonical-object families
    # are missing (never zero); campaign-context stays available for a campaign.
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    state = next(s for s in result.sections if s.id == "state")
    dims = {d["dimension"]: d for d in state.content["dimensions"]}
    assert dims["information"]["state"] == "missing"
    assert dims["knowledge"]["state"] == "missing"
    assert dims["authority"]["state"] == "missing"
    assert all(dims[k]["observed"] is None for k in ("information", "knowledge", "authority"))
    assert dims["campaign-context"]["state"] == "available"


async def test_state_canonical_dimensions_available_with_observed_rows() -> None:
    source = FakeSource(
        facts=[
            _fact(
                TENANT_A,
                "info-1",
                kind="information",
                payload={"campaign_id": "camp_1", "information_id": "i1"},
            ),
            _fact(
                TENANT_A,
                "know-1",
                kind="knowledge_state",
                actor_id="entity-1",
                payload={"campaign_id": "camp_1", "state": "included_in_context"},
            ),
            _fact(
                TENANT_A,
                "auth-1",
                kind="authority_evaluation",
                actor_id="entity-1",
                payload={"campaign_id": "camp_1", "decision": "granted"},
            ),
        ]
    )
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    state = next(s for s in result.sections if s.id == "state")
    dims = {d["dimension"]: d for d in state.content["dimensions"]}
    assert dims["information"]["state"] == "available"
    assert dims["information"]["observed"] == 1
    assert dims["knowledge"]["state"] == "available"
    assert dims["authority"]["state"] == "available"
    assert dims["authority"]["observed"] == 1


# ---------------------------------------------------------------------------
# interactions — act/participant rows; absent -> missing
# ---------------------------------------------------------------------------


async def test_interactions_present_from_act_and_participant_facts(
    act_source: FakeSource,
) -> None:
    provider = Communication360Provider(sources=act_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    interactions = next(s for s in result.sections if s.id == "interactions")
    assert interactions.state == "available"
    assert interactions.content["count"] == 2
    rows = {r["interactionId"]: r for r in interactions.content["interactions"]}
    assert rows["act-1"]["kind"] == "communication_act"
    assert rows["act-1"]["actType"] == "commit"
    assert rows["pb-1"]["kind"] == "participant_binding"
    assert rows["pb-1"]["role"] == "actor"


async def test_interactions_missing_when_no_act_rows() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    interactions = next(s for s in result.sections if s.id == "interactions")
    assert interactions.state == "missing"
    assert interactions.content["count"] == 0


# ---------------------------------------------------------------------------
# evidence — deduped EvidenceRefs by id
# ---------------------------------------------------------------------------


async def test_evidence_dedupes_refs_by_id(spine_source: FakeSource) -> None:
    # m1 and m2 share one evidence id on purpose -> must appear once.
    shared = EvidenceRef(id="shared-ev", type="event", source="test/fake/silver")
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "m1", ref_id="shared-ev"),
            _msg(TENANT_A, "m2", ref_id="ev-m2"),
        ]
    )
    source._messages[0].evidence_refs.append(shared)
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    evidence = next(s for s in result.sections if s.id == "evidence")
    ids = [e["id"] for e in evidence.content["evidence"]]
    assert ids == ["shared-ev", "ev-m2"]  # deduped, stable first-occurrence order
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# dependencyState echoes context verbatim; outcomes degrade (never raises)
# ---------------------------------------------------------------------------


async def test_dependency_state_echoes_injected_context(
    spine_source: FakeSource,
) -> None:
    reg = ProviderRegistry()  # nothing registered -> all siblings missing
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(reg)
    assert {d.projectionId for d in context.dependencyState} == {
        "profile360",
        "relationship360",
        "episode360",
        "outcome360",
    }
    result = await provider.project(request, context)

    assert result.dependencyState == context.dependencyState
    # Sibling in_flight degradation is NOT a provider degraded-reason.
    assert result.degradedReasons == []


async def test_outcomes_section_degraded_until_outcome360_lands(
    spine_source: FakeSource,
) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)

    outcomes = next(s for s in result.sections if s.id == "outcomes")
    assert outcomes.state == "degraded"
    assert "outcome360" in outcomes.content["reason"]
    deps = {d["projectionId"] for d in outcomes.content["dependencies"]}
    assert deps == {"profile360", "relationship360", "episode360", "outcome360"}
    assert outcomes.content["outcomeLinks"] is None


async def test_sibling_degradation_never_raises(spine_source: FakeSource) -> None:
    provider = Communication360Provider(sources=spine_source)
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)
    assert result.projectionId == "communication360"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)


# ---------------------------------------------------------------------------
# Tenant isolation — tenant A never surfaces tenant B
# ---------------------------------------------------------------------------


async def test_tenant_a_never_surfaces_tenant_b_communication() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "a1", campaign_id="camp_1"),
            _msg(TENANT_B, "b1", campaign_id="camp_1"),
            _msg(TENANT_B, "b2", campaign_id="camp_1"),
        ],
        facts=[
            _fact(TENANT_A, "act-a", payload={"campaign_id": "camp_1"}),
            _fact(TENANT_B, "act-b", payload={"campaign_id": "camp_1"}),
        ],
    )
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(ProviderRegistry(), tenant=TENANT_A)
    result = await provider.project(request, context)

    assert result.tenantId == TENANT_A
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.content["counts"]["messages_total"] == 1
    serialized = result.model_dump_json()
    assert "tenant-b" not in serialized
    assert "b1" not in serialized and "b2" not in serialized


# ---------------------------------------------------------------------------
# campaign subject filters the spine by campaign_id
# ---------------------------------------------------------------------------


async def test_campaign_subject_filters_spine_by_campaign_id() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "m1", campaign_id="camp_1"),
            _msg(TENANT_A, "m2", campaign_id="camp_2"),
        ]
    )
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(
        ProviderRegistry(), subject=ProjectionSubject(kind="campaign", id="camp_1")
    )
    result = await provider.project(request, context)

    assert source.last_campaign_id == "camp_1"  # spine asked for the campaign
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.content["counts"]["messages_total"] == 1
    claim_ids = {c.id for c in result.claims}
    assert claim_ids == {"timeline.m1"}
    assert "camp_2" not in result.model_dump_json()


async def test_agent_subject_filters_messages_and_canonical_facts_by_exact_actor_ref() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "m-agent", sender_entity_id="agent-1"),
            _msg(TENANT_A, "m-other", sender_entity_id="prefix-agent-1-suffix"),
        ],
        facts=[
            _fact(TENANT_A, "act-agent", actor_id="agent-1"),
            _fact(TENANT_A, "act-other", actor_id="prefix-agent-1-suffix"),
            _fact(
                TENANT_A,
                "act-payload",
                actor_id=None,
                payload={"actor_entity_id": "agent-1"},
            ),
        ],
    )

    class CanonicalAgentReader:
        async def resolve(self, tenant_id: str, source_agent_ref: str):
            assert (tenant_id, source_agent_ref) == (TENANT_A, "agent-1")
            return AgentIdentityRead(
                state="resolved",
                canonical_agent_entity_id="agent-1",
                evidence=(
                    EvidenceRef(
                        id="agent-1",
                        type="entity",
                        source="entities",
                        observedAt="2026-09-01T00:00:00Z",
                    ),
                ),
            )

    provider = Communication360Provider(
        sources=source, agent_identity_reader=CanonicalAgentReader()
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="agent", id="agent-1"),
    )
    result = await provider.project(request, context)

    assert source.last_participant_entity_id == "agent-1"
    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["counts"]["messages_total"] == 1
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["count"] == 2
    assert {claim.id for claim in result.claims} == {"timeline.m-agent"}
    assert "act-other" not in result.model_dump_json()


async def test_agent_source_alias_resolves_before_communication_reads() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "m-canonical", sender_entity_id="canonical-agent-1"),
            _msg(TENANT_A, "m-prefix", sender_entity_id="prefix-agent-source-1"),
        ],
        facts=[
            _fact(TENANT_A, "act-canonical", actor_id="canonical-agent-1"),
            _fact(TENANT_A, "act-source-ref", actor_id="agent-source-1"),
            _fact(TENANT_A, "act-prefix", actor_id="prefix-agent-source-1"),
        ],
    )

    class CanonicalAgentReader:
        async def resolve(self, tenant_id: str, source_agent_ref: str):
            assert (tenant_id, source_agent_ref) == (TENANT_A, "agent-source-1")
            return AgentIdentityRead(
                state="resolved",
                canonical_agent_entity_id="canonical-agent-1",
                evidence=(
                    EvidenceRef(
                        id="binding-1",
                        type="entity",
                        source="agent_deployment_identity_bindings",
                        observedAt="2026-09-01T00:00:00Z",
                    ),
                ),
            )

    provider = Communication360Provider(
        sources=source, agent_identity_reader=CanonicalAgentReader()
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="agent", id="agent-source-1"),
    )

    result = await provider.project(request, context)

    assert source.last_participant_entity_id == "canonical-agent-1"
    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["scope"]["identityResolutionState"] == "resolved"
    assert summary.content["scope"]["participantEntityId"] == "canonical-agent-1"
    timeline = next(section for section in result.sections if section.id == "timeline")
    assert [entry["messageId"] for entry in timeline.content["entries"]] == ["m-canonical"]
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["count"] == 1
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert any(ref["id"] == "binding-1" for ref in evidence.content["evidence"])
    assert any(ref.id == "binding-1" for ref in result.claims[0].evidenceRefs)
    assert "act-prefix" not in result.model_dump_json()


async def test_unresolved_agent_identity_does_not_scan_communications() -> None:
    class NoReadSource:
        async def messages(self, *args, **kwargs):
            raise AssertionError("unresolved Agent identity must not read messages")

        async def facts(self, *args, **kwargs):
            raise AssertionError("unresolved Agent identity must not scan tenant facts")

    class UnresolvedAgentReader:
        async def resolve(self, tenant_id: str, source_agent_ref: str):
            return AgentIdentityRead(state="unresolved", reason="agent_identity_binding_not_found")

    provider = Communication360Provider(
        sources=NoReadSource(), agent_identity_reader=UnresolvedAgentReader()
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="agent", id="unbound-agent"),
    )

    result = await provider.project(request, context)

    assert result.claims == []
    assert "agent_identity_binding_not_found" in result.degradedReasons
    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None


async def test_communication360_caps_reads_and_marks_partial_source_coverage() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "m-1"),
            _msg(TENANT_A, "m-2"),
            _msg(TENANT_A, "m-3"),
        ],
        facts=[
            _fact(TENANT_A, "act-1"),
            _fact(TENANT_A, "act-2"),
            _fact(TENANT_A, "act-3"),
        ],
    )
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(
        ProviderRegistry(),
        page={"limit": 1},
    )

    result = await provider.project(request, context)

    assert REASON_SOURCE_READ_TRUNCATED in result.degradedReasons
    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None
    assert summary.content["sourceCompleteness"] == "partial"
    state = next(section for section in result.sections if section.id == "state")
    assert state.state == "degraded"
    assert (
        next(d for d in state.content["dimensions"] if d["dimension"] == "delivery")["state"]
        == "degraded"
    )
    timeline = next(section for section in result.sections if section.id == "timeline")
    assert timeline.state == "degraded"
    assert timeline.content["sourceTruncated"] is True
    assert timeline.content["entryCount"] == 1
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.state == "degraded"
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.state == "degraded"
    assert interactions.content["sourceTruncated"] is True


# ---------------------------------------------------------------------------
# Non-message subjects use exact canonical facts and keep message state unknown.
# ---------------------------------------------------------------------------


async def test_episode_subject_without_canonical_facts_is_missing_not_zero() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="episode", id="ep_1"),
    )
    result = await provider.project(request, context)

    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "missing"
    assert summary.content["counts"] is None
    assert "no_exact_scope_communication_facts_observed" in summary.content["reasons"]
    timeline = next(s for s in result.sections if s.id == "timeline")
    assert timeline.state == "missing"


async def test_source_subject_without_canonical_facts_is_missing_not_zero() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="source", id="src_1"),
    )
    result = await provider.project(request, context)
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "missing"
    assert summary.content["counts"] is None


@pytest.mark.parametrize(
    ("subject_kind", "reference_key"),
    [("episode", "episode_id"), ("journey", "journey_id"), ("source", "source_id")],
)
async def test_non_message_subjects_use_exact_tenant_canonical_communication_facts(
    subject_kind: str, reference_key: str
) -> None:
    subject_id = f"{subject_kind}-canonical-1"
    exact = _fact(
        TENANT_A,
        f"{subject_kind}-act-1",
        payload={reference_key: subject_id, "act_type": "recorded"},
    )
    wrong_reference = _fact(
        TENANT_A,
        f"{subject_kind}-act-2",
        payload={reference_key: f"{subject_id}-other", "act_type": "wrong-reference"},
    )
    wrong_tenant = _fact(
        TENANT_B,
        f"{subject_kind}-act-3",
        payload={reference_key: subject_id, "act_type": "wrong-tenant"},
    )

    class TenantMisbehavingSource(FakeSource):
        async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
            self.fact_read_count += 1
            rows = [exact, wrong_reference, wrong_tenant]
            if limit is not None:
                rows = rows[:limit]
            return rows

    source = TenantMisbehavingSource()
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
    )

    result = await provider.project(request, context)

    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.state == "available"
    assert summary.content["counts"] == {
        "messages_total": None,
        "communication_facts_total": 1,
        "communication_fact_kinds": {"communication_act": 1},
    }
    assert summary.content["sourceCompleteness"] == "canonical_facts_only"
    timeline = next(section for section in result.sections if section.id == "timeline")
    assert timeline.state == "available"
    assert [entry["factId"] for entry in timeline.content["entries"]] == [f"{subject_kind}-act-1"]
    assert timeline.content["entries"][0]["evidenceRefIds"] == [f"{subject_kind}-act-1"]
    assert timeline.content["causalRelationsDeclared"] == []
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["count"] == 1
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert [ref["id"] for ref in evidence.content["evidence"]] == [f"{subject_kind}-act-1"]
    assert source.message_read_count == 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    assert "communication360" in reg.sources()
    assert reg.sources()["communication360"] == "services/api/journeys/communication360"
    provider = reg.require("communication360")
    assert isinstance(provider, Communication360Provider)


def test_importing_provider_does_not_self_register() -> None:
    # register_provider is the wiring seam — importing never mutates a registry.
    reg = ProviderRegistry()
    assert "communication360" not in reg.sources()
    assert reg.get("communication360") is None


def test_register_duplicate_different_object_raises() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(reg)  # a NEW Communication360Provider object
    assert excinfo.value.projection_id == "communication360"


def test_register_same_object_is_idempotent() -> None:
    reg = ProviderRegistry()
    provider = Communication360Provider()
    reg.register(provider, source="services/api/journeys/communication360")
    assert (
        reg.register(provider, source="services/api/journeys/communication360")
        == "communication360"
    )
    assert len(reg.list()) == 1


def test_register_version_mismatch_raises() -> None:
    class _WrongVersion:
        projection_id = "communication360"
        contract_version = "2.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible):
        reg.register(_WrongVersion())


def test_register_unknown_id_raises() -> None:
    class _UnknownId:
        projection_id = "no_such_projection"
        contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound) as excinfo:
        reg.register(_UnknownId())
    assert excinfo.value.projection_id == "no_such_projection"


def test_provider_contract_version_matches_registry() -> None:
    assert Communication360Provider.contract_version == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
