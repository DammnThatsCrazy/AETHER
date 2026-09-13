"""Unit tests for the Phase-4 Communication360 intelligence-projection provider.

The provider is a read-only, fail-isolated, tenant-scoped projection over the
shipped silver message spine (``services/comms``) + the Phase-3 canonical fact
store (``services/communication360``). These tests cover:

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

from services.communication360.contracts import CommunicationMessage  # noqa: E402
from services.communication360.provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    REASON_CANONICAL_SOURCE_UNAVAILABLE,
    REASON_SILVER_SOURCE_UNAVAILABLE,
    Communication360Provider,
    register_provider,
)
from services.comms.contracts import CommunicationState  # noqa: E402
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
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
    "available", "degraded", "empty", "missing", "not_applicable",
    "unknown", "suppressed", "stale",
}

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


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

    async def messages(self, tenant_id, *, campaign_id=None, since=None, limit=None):
        if self._raises in ("messages", "all"):
            raise RuntimeError("fake boom: secret-detail")
        self.last_campaign_id = campaign_id
        out = [
            m for m in self._messages
            if m.tenant_id == tenant_id
            and (campaign_id is None or m.campaign_id == campaign_id)
        ]
        out.sort(key=lambda m: m.occurred_at)
        if limit is not None:
            out = out[:limit]
        return out

    async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
        if self._raises in ("facts", "all"):
            raise RuntimeError("fake boom: secret-detail")
        out = [
            r for r in self._facts
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
) -> CommunicationMessage:
    return CommunicationMessage(
        message_id=mid,
        tenant_id=tenant,
        fact_id=f"fact-{mid}",
        channel=channel,
        direction=direction,
        communication_state=CommunicationState(state),
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
                TENANT_A, "act-1", kind="communication_act",
                payload={
                    "campaign_id": "camp_1",
                    "act_type": "commit",
                    "actor_entity_id": "entity-1",
                    "target_entity_id": "entity-2",
                },
            ),
            _fact(
                TENANT_A, "pb-1", kind="participant_binding",
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
        "summary", "state", "timeline", "evidence", "interactions", "outcomes",
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
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.claimState is EpistemicStatus.OBSERVED  # never verified
        assert claim.claimState is not EpistemicStatus.VERIFIED
        assert claim.evidenceRefs, (
            f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        )
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
    provider = Communication360Provider(
        sources=FakeSource(raises="all")
    )
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
        "delivery", "engagement", "campaign-context",
        "information", "knowledge", "authority",
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
        "sent": 1, "delivered": 1, "opened": 1,
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
                TENANT_A, "info-1", kind="information",
                payload={"campaign_id": "camp_1", "information_id": "i1"},
            ),
            _fact(
                TENANT_A, "know-1", kind="knowledge_state",
                actor_id="entity-1",
                payload={"campaign_id": "camp_1", "state": "included_in_context"},
            ),
            _fact(
                TENANT_A, "auth-1", kind="authority_evaluation",
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
        "profile360", "relationship360", "episode360", "outcome360",
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


# ---------------------------------------------------------------------------
# episode/source subjects degrade honestly instead of erroring
# ---------------------------------------------------------------------------


async def test_episode_subject_degrades_sections_not_error() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="episode", id="ep_1"),
    )
    result = await provider.project(request, context)

    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None
    assert summary.content["reasons"]  # honest section-level note
    timeline = next(s for s in result.sections if s.id == "timeline")
    assert timeline.state == "degraded"
    # The note names the in-flight sibling that will enable the binding.
    assert "episode360" in summary.content["reasons"][0]


async def test_source_subject_degrades_sections_not_error() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="source", id="src_1"),
    )
    result = await provider.project(request, context)
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "degraded"
    assert summary.content["counts"] is None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    assert "communication360" in reg.sources()
    assert reg.sources()["communication360"] == "services/communication360"
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
    reg.register(provider, source="services/communication360")
    assert reg.register(provider, source="services/communication360") == "communication360"
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
    assert (
        Communication360Provider.contract_version
        == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    )
