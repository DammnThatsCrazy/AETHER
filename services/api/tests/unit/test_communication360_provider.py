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

from journeys.communication360.contracts import (  # noqa: E402
    CommunicationConsentEvidence,
    CommunicationMessage,
)
from journeys.communication360.provider import (  # noqa: E402
    AgentIdentityRead,
    EntityIdentityRead,
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
from shared.intelligence_projections.composition import (  # noqa: E402
    compose_experience360_frame,
)
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    Experience360FrameRequest,
    Experience360PolicyDisposition,
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


class FakeJourneyReader:
    """Exact-current-journey reader double used by Communication360 join tests."""

    def __init__(self, records: dict[str, dict] | None = None, *, raises: bool = False) -> None:
        self.records = dict(records or {})
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def get_current(self, tenant_id: str, journey_id: str):
        self.calls.append((tenant_id, journey_id))
        if self.raises:
            raise RuntimeError("journey read failed: private backend detail")
        record = self.records.get(journey_id)
        return dict(record) if record is not None else None


class FakeRiskSignalReader:
    """Tenant and typed-subject risk reader double."""

    def __init__(self, rows: list[dict] | None = None, *, raises: bool = False) -> None:
        self.rows = list(rows or [])
        self.raises = raises
        self.calls: list[tuple[str, str, str, int]] = []

    async def signals(self, *, tenant_id, subject, limit):
        self.calls.append((tenant_id, subject.kind, subject.id, limit))
        if self.raises:
            raise RuntimeError("risk read failed: private backend detail")
        return list(self.rows)


class FakeEntityIdentityReader:
    """Exact tenant/entity registry read used by entity communication tests."""

    def __init__(self, *, state: str = "resolved", canonical_entity_id: str = "org-1") -> None:
        self.state = state
        self.canonical_entity_id = canonical_entity_id
        self.calls: list[tuple[str, str]] = []

    async def resolve(self, tenant_id: str, canonical_entity_id: str) -> EntityIdentityRead:
        self.calls.append((tenant_id, canonical_entity_id))
        if self.state != "resolved":
            return EntityIdentityRead(state=self.state, reason="entity_identity_binding_not_found")
        return EntityIdentityRead(
            state="resolved",
            canonical_entity_id=self.canonical_entity_id,
            evidence=(
                EvidenceRef(
                    id=self.canonical_entity_id,
                    type="entity",
                    source="entity_registry",
                    observedAt="2026-10-22T12:00:00Z",
                ),
            ),
        )


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
    provider: str | None = None,
    consent_evidence: CommunicationConsentEvidence | None = None,
) -> CommunicationMessage:
    return CommunicationMessage(
        message_id=mid,
        tenant_id=tenant,
        fact_id=f"fact-{mid}",
        provider=provider,
        channel=channel,
        direction=direction,
        communication_state=CommunicationState(state),
        sender_entity_id=sender_entity_id,
        recipient_entity_id=recipient_entity_id,
        campaign_id=campaign_id,
        occurred_at=occurred_at,
        received_at=occurred_at,
        consent_evidence=consent_evidence or CommunicationConsentEvidence(),
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


def _entity_bound_message(
    tenant: str,
    message_id: str,
    entity_id: str,
    *,
    side: str,
    binding_id: str | None = None,
    source: str | None = None,
) -> CommunicationMessage:
    """Create one message endpoint with an explicit identity binding record."""
    binding_id = binding_id or f"binding-{message_id}"
    source = source or {
        "sender": "agent_deployment_identity_bindings",
        "recipient": "comms_provider_identities",
    }[side]
    evidence_uri = {
        "agent_deployment_identity_bindings": "store://agent_identity_bindings/",
        "comms_provider_identities": "store://comms_provider_identities/",
    }[source]
    evidence = EvidenceRef(
        id=binding_id,
        type="entity",
        source=source,
        uri=f"{evidence_uri}{binding_id}",
    )
    endpoint = f"{side}_entity_id"
    return _msg(tenant, message_id, **{endpoint: entity_id}).model_copy(
        update={
            f"{side}_identity_binding_id": binding_id,
            f"{side}_identity_evidence_ref": evidence,
        }
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
    assert all(
        claim.domainSlotIds == ["campaign_links", "evidence_trace", "message_inventory"]
        for claim in result.claims
    )
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


async def test_entity_scope_joins_only_exact_tenant_entity_bound_communications() -> None:
    entity_id = "org-1"
    messages = [
        _entity_bound_message(TENANT_A, "m-sender", entity_id, side="sender"),
        _entity_bound_message(TENANT_A, "m-recipient", entity_id, side="recipient"),
        # Exact ID without its canonical identity binding is not enough.
        _msg(TENANT_A, "m-unbound", sender_entity_id=entity_id),
        # Binding evidence must name the same exact binding ID.
        _entity_bound_message(
            TENANT_A, "m-mismatched-binding", entity_id, side="recipient"
        ).model_copy(
            update={
                "recipient_identity_evidence_ref": EvidenceRef(
                    id="different-binding",
                    type="entity",
                    source="comms_provider_identities",
                    uri="store://comms_provider_identities/different-binding",
                )
            }
        ),
        _entity_bound_message(
            TENANT_A,
            "m-wrong-binding-authority",
            entity_id,
            side="recipient",
            source="agent_deployment_identity_bindings",
        ),
        # Same-tenant cross-entity traffic and member traffic are not fanned in.
        _entity_bound_message(TENANT_A, "m-other-org", "org-2", side="sender"),
        _entity_bound_message(TENANT_A, "m-member", "member-1", side="sender"),
        # A foreign tenant cannot bind the same canonical entity id into this frame.
        _entity_bound_message(TENANT_B, "m-foreign-tenant", entity_id, side="sender"),
    ]
    facts = [
        _fact(TENANT_A, "fact-actor", actor_id=entity_id),
        _fact(
            TENANT_A,
            "fact-participant",
            actor_id=None,
            payload={"participant_entity_id": entity_id},
        ),
        _fact(TENANT_A, "fact-other-org", actor_id="org-2"),
        _fact(
            TENANT_A,
            "fact-member",
            actor_id=None,
            payload={"participant_entity_id": "member-1"},
        ),
        _fact(TENANT_B, "fact-foreign-tenant", actor_id=entity_id),
    ]

    class UnscopedSource(FakeSource):
        """Return hostile cross-tenant rows to test provider-side filtering."""

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
            self.last_participant_entity_id = participant_entity_id
            return self._messages[:limit] if limit is not None else list(self._messages)

        async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
            self.fact_read_count += 1
            return self._facts[:limit] if limit is not None else list(self._facts)

    source = UnscopedSource(messages=messages, facts=facts)
    identity_reader = FakeEntityIdentityReader(canonical_entity_id=entity_id)
    provider = Communication360Provider(
        sources=source,
        entity_identity_reader=identity_reader,
    )
    request, context = await _make_context(
        ProviderRegistry(),
        tenant=TENANT_A,
        subject=ProjectionSubject(kind="entity", id=entity_id),
    )

    result = await provider.project(request, context)

    assert identity_reader.calls == [(TENANT_A, entity_id)]
    assert source.last_participant_entity_id == entity_id
    assert all(claim.claimState is EpistemicStatus.OBSERVED for claim in result.claims)
    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["counts"]["messages_total"] == 2
    timeline = next(section for section in result.sections if section.id == "timeline")
    assert {entry["messageId"] for entry in timeline.content["entries"]} == {
        "m-sender",
        "m-recipient",
    }
    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["count"] == 2
    serialized = result.model_dump_json()
    for excluded in (
        "m-unbound",
        "m-mismatched-binding",
        "m-wrong-binding-authority",
        "m-other-org",
        "m-member",
        "m-foreign-tenant",
        "fact-other-org",
        "fact-member",
        "fact-foreign-tenant",
        "tenant-b",
    ):
        assert excluded not in serialized
    state = next(section for section in result.sections if section.id == "state")
    policy_evaluation = state.content["sourcePolicyContext"]["policyEvaluation"]
    assert policy_evaluation["state"] == "unknown"
    assert policy_evaluation["authority"] == "experience360_frame_policy_runtime"
    assert state.content["sourcePolicyContext"]["freshness"]["state"] == "unknown"

    allowed = Experience360PolicyDisposition(state="allowed")
    account_request = Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind="entity", id=entity_id),
        requestedSlotIds=["communications"],
        includeEvidence=True,
    )
    frame = compose_experience360_frame(
        account_request,
        [result],
        frame_policy=allowed,
        policy_by_slot={"communications": allowed},
    )
    account_communications = next(
        slot for slot in frame.slots if slot.id == "communications"
    )
    assert {claim.id for claim in account_communications.claims} == {
        "timeline.m-sender",
        "timeline.m-recipient",
        "canonical_fact.fact-actor",
        "canonical_fact.fact-participant",
    }
    assert account_communications.state == "degraded"
    assert "slot_contains_partial_evidence" in account_communications.reasonCodes
    assert account_communications.freshness.state == "unknown"

    redacted = Experience360PolicyDisposition(
        state="redacted",
        redactedFieldPaths=["/sections/0/content/subject"],
        reasonCodes=["account_communications_policy_redacted"],
    )
    redacted_frame = compose_experience360_frame(
        account_request,
        [result],
        frame_policy=allowed,
        policy_by_slot={"communications": redacted},
    )
    redacted_communications = next(
        slot for slot in redacted_frame.slots if slot.id == "communications"
    )
    assert redacted_communications.state == "suppressed"
    assert redacted_communications.content is None
    assert redacted_communications.evidenceRefs == []
    assert redacted_communications.claims == []
    assert redacted_communications.policyDisposition.state == "redacted"
    assert redacted_communications.policyDisposition.redactedFieldPaths == [
        "/sections/0/content/subject"
    ]


async def test_entity_scope_does_not_match_untyped_text_that_mentions_entity_id() -> None:
    entity_id = "org-1"
    source = FakeSource(
        facts=[
            _fact(
                TENANT_A,
                "fact-text-only",
                actor_id=None,
                payload={"description": f"This message mentions {entity_id} as a participant."},
            )
        ]
    )
    provider = Communication360Provider(
        sources=source,
        entity_identity_reader=FakeEntityIdentityReader(canonical_entity_id=entity_id),
    )
    request, context = await _make_context(
        ProviderRegistry(),
        tenant=TENANT_A,
        subject=ProjectionSubject(kind="entity", id=entity_id),
    )

    result = await provider.project(request, context)

    interactions = next(section for section in result.sections if section.id == "interactions")
    assert interactions.content["count"] == 0
    assert "fact-text-only" not in result.model_dump_json()


async def test_entity_scope_fails_closed_without_canonical_entity_identity_evidence() -> None:
    source = FakeSource(
        messages=[
            _entity_bound_message(TENANT_A, "m-org", "org-1", side="recipient")
        ],
        facts=[_fact(TENANT_A, "fact-org", actor_id="org-1")],
    )
    identity_reader = FakeEntityIdentityReader(state="unresolved", canonical_entity_id="org-1")
    provider = Communication360Provider(sources=source, entity_identity_reader=identity_reader)
    request, context = await _make_context(
        ProviderRegistry(),
        tenant=TENANT_A,
        subject=ProjectionSubject(kind="entity", id="org-1"),
    )

    result = await provider.project(request, context)

    assert source.message_read_count == 0
    assert source.fact_read_count == 0
    assert result.claims == []
    assert "entity_identity_binding_not_found" in result.degradedReasons


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
    claims_by_id = {claim.id: claim for claim in result.claims}
    assert set(claims_by_id) == {
        "timeline.m-agent",
        "canonical_fact.act-agent",
        "canonical_fact.act-payload",
    }
    assert claims_by_id["canonical_fact.act-agent"].domainSlotIds == ["evidence_trace"]
    assert claims_by_id["canonical_fact.act-payload"].domainSlotIds == ["evidence_trace"]
    assert "act-other" not in result.model_dump_json()


async def test_communications_claims_use_exact_agent_authorship_and_response_slots() -> None:
    binding_ref = EvidenceRef(
        id="agent-sender-binding",
        type="entity",
        source="agent_deployment_identity_bindings",
        uri="store://agent_identity_bindings/agent-sender-binding",
    )
    message = _msg(TENANT_A, "agent-authored-message", sender_entity_id="agent-1").model_copy(
        update={
            "sender_identity_binding_id": binding_ref.id,
            "sender_identity_evidence_ref": binding_ref,
        }
    )
    facts = [
        _fact(
            TENANT_A,
            "agent-author-binding",
            kind="participant_binding",
            actor_id="agent-1",
            payload={
                "role": "author",
                "entity_id": "agent-1",
                "entity_type": "agent",
                "agent_id": "agent-1",
            },
        ),
        _fact(
            TENANT_A,
            "agent-response-act",
            kind="communication_act",
            actor_id="agent-1",
            payload={"act_type": "reply", "agent_id": "agent-1", "message_id": "m-1"},
        ),
        _fact(
            TENANT_A,
            "agent-response-expectation",
            kind="response_expectation",
            actor_id="agent-1",
            payload={"expectation_type": "reply_by", "agent_id": "agent-1"},
        ),
    ]

    class CanonicalAgentReader:
        async def resolve(self, tenant_id: str, source_agent_ref: str):
            return AgentIdentityRead(
                state="resolved",
                canonical_agent_entity_id="agent-1",
                evidence=(
                    EvidenceRef(
                        id="agent-1",
                        type="entity",
                        source="entities",
                    ),
                ),
            )

    provider = Communication360Provider(
        sources=FakeSource(messages=[message], facts=facts),
        agent_identity_reader=CanonicalAgentReader(),
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="agent", id="agent-1"),
    )

    result = await provider.project(request, context)

    claims_by_id = {claim.id: claim for claim in result.claims}
    assert claims_by_id["timeline.agent-authored-message"].domainSlotIds == [
        "agent_authorship",
        "evidence_trace",
        "message_inventory",
    ]
    assert binding_ref.id in {
        ref.id for ref in claims_by_id["timeline.agent-authored-message"].evidenceRefs
    }
    assert claims_by_id["canonical_fact.agent-author-binding"].domainSlotIds == [
        "agent_authorship",
        "evidence_trace",
        "participants",
    ]
    assert claims_by_id["canonical_fact.agent-response-act"].domainSlotIds == [
        "evidence_trace",
        "response_events",
    ]
    assert claims_by_id["canonical_fact.agent-response-expectation"].domainSlotIds == [
        "evidence_trace"
    ]
    assert all(
        not ({"profile_links", "journey_links", "policy_state", "risk_flags"}
             & set(claim.domainSlotIds or []))
        for claim in result.claims
    )


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
    ("subject_kind", "reference_key", "expected_slot_ids"),
    [
        ("episode", "episode_id", ["communications"]),
        ("journey", "journey_id", []),
        ("source", "source_id", []),
    ],
)
async def test_non_message_subjects_use_exact_tenant_canonical_communication_facts(
    subject_kind: str, reference_key: str, expected_slot_ids: list[str]
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
        "active_conversations": None,
        "open_requests": None,
        "open_commitments": None,
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
    canonical_claims = [claim for claim in result.claims if claim.id.startswith("canonical_fact.")]
    assert [claim.id for claim in canonical_claims] == [f"canonical_fact.{subject_kind}-act-1"]
    assert canonical_claims[0].domainSlotIds == expected_slot_ids
    assert canonical_claims[0].claimState is EpistemicStatus.OBSERVED
    assert [ref.id for ref in canonical_claims[0].evidenceRefs] == [f"{subject_kind}-act-1"]
    assert source.message_read_count == 0


async def test_canonical_campaign_fact_claim_uses_event_slot_and_store_evidence() -> None:
    fact = _fact(
        TENANT_A,
        "campaign-act-1",
        kind="communication_act",
        payload={"campaign_id": "camp_1", "act_type": "recorded"},
    )
    provider = Communication360Provider(sources=FakeSource(facts=[fact]))
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    assert [claim.id for claim in result.claims] == ["canonical_fact.campaign-act-1"]
    claim = result.claims[0]
    assert claim.domainSlotIds == ["campaign_links", "evidence_trace"]
    assert claim.claimState is EpistemicStatus.OBSERVED
    assert claim.evidenceRefs[0].source == (
        "services/api/journeys/communication360/communication360_facts"
    )
    assert claim.evidenceRefs[0].uri == "store://communication360_facts/campaign-act-1"


async def test_campaign_projects_supported_canonical_communication_object_families() -> None:
    facts = [
        _fact(
            TENANT_A,
            "conversation-1",
            kind="conversation",
            payload={
                "campaign_id": "camp_1",
                "conversation_id": "conversation-1",
                "kind": "conversation",
                "provider_thread_ids": ["thread-1"],
                "message_ids": ["message-1"],
                "state": "active",
                "topic": "PRIVATE TOPIC",
            },
        ),
        _fact(
            TENANT_A,
            "thread-1",
            kind="provider_thread",
            payload={
                "campaign_id": "camp_1",
                "thread_id": "thread-1",
                "provider": "mail.provider.v1",
                "message_ids": ["message-1"],
                "subject": "PRIVATE SUBJECT",
            },
        ),
        _fact(
            TENANT_A,
            "matter-1",
            kind="matter",
            payload={
                "matter_id": "matter-1",
                "campaign_ids": ["camp_1"],
                "conversation_ids": ["conversation-1"],
                "episode_ids": [],
            },
        ),
        _fact(
            TENANT_A,
            "request-1",
            kind="request",
            payload={
                "campaign_id": "camp_1",
                "requester_entity_id": "entity-1",
                "assignee_entity_id": "entity-2",
                "state": "open",
                "deadline": "2026-09-04T00:00:00Z",
                "description": "PRIVATE REQUEST",
            },
        ),
        _fact(
            TENANT_A,
            "commitment-1",
            kind="commitment",
            payload={
                "campaign_id": "camp_1",
                "committer_entity_id": "entity-1",
                "beneficiary_entity_id": "entity-2",
                "state": "open",
                "due_at": "2026-09-05T00:00:00Z",
                "description": "PRIVATE COMMITMENT",
            },
        ),
        _fact(
            TENANT_A,
            "response-1",
            kind="response_expectation",
            payload={
                "campaign_id": "camp_1",
                "expectation_type": "reply_by",
                "communication_ref": "message-1",
                "state": "met",
                "due_at": "2026-09-04T00:00:00Z",
            },
        ),
        _fact(
            TENANT_A,
            "binding-1",
            kind="participant_binding",
            payload={
                "campaign_id": "camp_1",
                "role": "author",
                "entity_id": "entity-1",
                "principal_entity_id": "entity-2",
                "delegation_grant_id": "grant-1",
                "valid_from": "2026-09-03T00:00:00Z",
            },
        ),
    ]
    provider = Communication360Provider(sources=FakeSource(facts=facts))
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    interactions = next(section for section in result.sections if section.id == "interactions")
    records = {item["kind"]: item for item in interactions.content["interactions"]}
    assert set(records) == {
        "conversation",
        "provider_thread",
        "matter",
        "request",
        "commitment",
        "response_expectation",
        "participant_binding",
    }
    assert records["conversation"]["conversationState"] == "active"
    assert records["conversation"]["messageIds"] == ["message-1"]
    assert records["provider_thread"]["messageIds"] == ["message-1"]
    assert records["matter"]["campaignIds"] == ["camp_1"]
    assert records["request"]["requestState"] == "open"
    assert records["commitment"]["commitmentState"] == "open"
    assert records["response_expectation"]["expectationState"] == "met"
    assert records["participant_binding"]["role"] == "author"
    assert all(item["evidenceRefIds"] for item in records.values())

    summary = next(section for section in result.sections if section.id == "summary")
    assert summary.content["counts"]["active_conversations"] == 1
    assert summary.content["counts"]["open_requests"] == 1
    assert summary.content["counts"]["open_commitments"] == 1
    canonical_claims = [claim for claim in result.claims if claim.id.startswith("canonical_fact.")]
    assert len(canonical_claims) == len(facts)
    slots_by_kind = {
        row["kind"]: next(
            claim.domainSlotIds
            for claim in canonical_claims
            if claim.id == f"canonical_fact.{row['fact_id']}"
        )
        for row in facts
    }
    assert slots_by_kind == {
        "conversation": ["campaign_links", "evidence_trace", "thread_summary"],
        "provider_thread": ["campaign_links", "evidence_trace", "thread_summary"],
        "matter": ["campaign_links", "evidence_trace"],
        "request": ["campaign_links", "evidence_trace"],
        "commitment": ["campaign_links", "evidence_trace"],
        # A response expectation is not an observed response event.
        "response_expectation": ["campaign_links", "evidence_trace"],
        "participant_binding": ["campaign_links", "evidence_trace", "participants"],
    }
    assert all(
        not ({"profile_links", "journey_links", "policy_state", "risk_flags"}
             & set(claim.domainSlotIds or []))
        for claim in canonical_claims
    )
    assert all(claim.evidenceRefs for claim in canonical_claims)
    assert "PRIVATE TOPIC" not in result.model_dump_json()
    assert "PRIVATE SUBJECT" not in result.model_dump_json()
    assert "PRIVATE REQUEST" not in result.model_dump_json()
    assert "PRIVATE COMMITMENT" not in result.model_dump_json()


async def test_canonical_fact_without_reusable_evidence_is_not_asserted_as_claim() -> None:
    row_without_evidence = {
        "tenant_id": TENANT_A,
        "kind": "communication_act",
        "occurred_at": "2026-09-03T11:00:00Z",
        "payload": {
            "campaign_id": "camp_1",
            "act_type": "recorded",
            "provider_id": "mail.provider.v1",
        },
    }
    provider = Communication360Provider(sources=FakeSource(facts=[row_without_evidence]))
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    assert result.claims == []
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["evidence"] == []
    source_policy = next(section for section in result.sections if section.id == "state").content[
        "sourcePolicyContext"
    ]
    assert source_policy["sourceLineage"]["state"] == "unknown"
    assert source_policy["sourceLineage"]["references"] == []


async def test_communications_ssot_slots_report_supported_evidence_and_unknown_authorities() -> None:
    message = _msg(
        TENANT_A,
        "message-coverage",
        sender_entity_id="agent-1",
        recipient_entity_id="profile-1",
    ).model_copy(update={"external_thread_id": "provider-thread-1"})
    facts = [
        _fact(
            TENANT_A,
            "conversation-coverage",
            kind="conversation",
            payload={
                "campaign_id": "camp_1",
                "profile_id": "profile-1",
                "journey_id": "journey-1",
                "conversation_id": "conversation-1",
                "message_ids": ["message-coverage"],
                "state": "active",
            },
        ),
        _fact(
            TENANT_A,
            "author-binding-coverage",
            kind="participant_binding",
            payload={
                "campaign_id": "camp_1",
                "role": "author",
                "entity_id": "agent-1",
                "entity_type": "agent",
            },
        ),
        _fact(
            TENANT_A,
            "response-act-coverage",
            kind="communication_act",
            payload={
                "campaign_id": "camp_1",
                "act_type": "acknowledge",
                "message_id": "message-coverage",
            },
        ),
    ]
    provider = Communication360Provider(
        sources=FakeSource(messages=[message], facts=facts)
    )
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert set(coverage) == {
        "thread_summary",
        "message_inventory",
        "participants",
        "campaign_links",
        "profile_links",
        "journey_links",
        "response_events",
        "agent_authorship",
        "policy_state",
        "risk_flags",
        "evidence_trace",
    }
    assert coverage["thread_summary"]["state"] == "degraded"
    assert coverage["thread_summary"]["evidenceRefs"]
    assert coverage["message_inventory"]["state"] == "available"
    assert coverage["message_inventory"]["evidenceRefs"][0]["id"] == "ev-message-coverage"
    assert coverage["participants"]["state"] == "degraded"
    assert coverage["campaign_links"]["state"] == "available"
    assert coverage["profile_links"]["state"] == "degraded"
    assert coverage["journey_links"]["state"] == "degraded"
    assert coverage["response_events"]["state"] == "degraded"
    assert coverage["agent_authorship"]["state"] == "degraded"
    assert coverage["agent_authorship"]["evidenceRefs"][0]["id"] == "author-binding-coverage"
    assert coverage["policy_state"]["state"] == "unknown"
    assert coverage["risk_flags"]["state"] == "unknown"
    assert coverage["evidence_trace"]["state"] == "degraded"
    assert {ref["id"] for ref in coverage["evidence_trace"]["evidenceRefs"]} >= {
        "ev-message-coverage",
        "conversation-coverage",
        "author-binding-coverage",
        "response-act-coverage",
    }
    interactions = next(section for section in result.sections if section.id == "interactions")
    rows_by_kind = {row["kind"]: row for row in interactions.content["interactions"]}
    assert rows_by_kind["conversation"]["campaignIds"] == ["camp_1"]
    assert rows_by_kind["conversation"]["profileIds"] == ["profile-1"]
    assert rows_by_kind["conversation"]["journeyIds"] == ["journey-1"]
    assert rows_by_kind["conversation"]["messageIds"] == ["message-coverage"]
    assert rows_by_kind["participant_binding"]["entityType"] == "agent"


async def test_communications_unsupported_slots_stay_unknown_without_exact_evidence() -> None:
    provider = Communication360Provider(sources=FakeSource())
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="journey", id="journey-without-comms"),
    )

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert coverage["message_inventory"]["state"] == "unknown"
    assert coverage["participants"]["state"] == "unknown"
    assert coverage["journey_links"]["state"] == "unknown"
    assert coverage["policy_state"]["state"] == "unknown"
    assert coverage["risk_flags"]["state"] == "unknown"


async def test_communication360_resolves_explicit_journey_reference_with_tenant_evidence() -> None:
    from uuid import uuid4

    journey_uuid = uuid4()
    version_uuid = uuid4()
    journey_id = str(journey_uuid)
    version_id = str(version_uuid)
    fact = _fact(
        TENANT_A,
        "communication-journey-reference",
        kind="conversation",
        payload={"campaign_id": "camp_1", "journey_id": journey_id},
    )
    journey = {
        "tenant_id": TENANT_A,
        "journey_id": journey_uuid,
        "journey_version_id": version_uuid,
        "is_current": True,
        "computed_at": "2026-10-20T12:34:56Z",
        "private_profile_notes": "must not enter the projection",
    }
    reader = FakeJourneyReader({journey_id: journey})
    provider = Communication360Provider(
        sources=FakeSource(facts=[fact]), journey_reader=reader
    )
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    journey_slot = coverage["journey_links"]
    assert journey_slot["state"] == "available"
    assert journey_slot["coverage"] == "complete"
    assert journey_slot["reason"] == "explicit_tenant_journey_reference_resolved_to_current_version"
    refs = {ref["id"]: ref for ref in journey_slot["evidenceRefs"]}
    assert refs["communication-journey-reference"]["source"].endswith(
        "communication360_facts"
    )
    assert refs[version_id]["source"].endswith("measurement/journey_versions")
    assert refs[version_id]["observedAt"] == "2026-10-20T12:34:56Z"
    assert reader.calls == [(TENANT_A, journey_id)]

    linked_claims = [claim for claim in result.claims if claim.kind == "communication_journey_link"]
    assert len(linked_claims) == 1
    assert {ref.id for ref in linked_claims[0].evidenceRefs} == {
        "communication-journey-reference",
        version_id,
    }
    assert linked_claims[0].claimState == EpistemicStatus.OBSERVED
    assert linked_claims[0].domainSlotIds == ["journey_links"]
    assert "must not enter" not in result.model_dump_json()


async def test_communication360_rejects_cross_tenant_current_journey_record() -> None:
    from uuid import uuid4

    journey_id = str(uuid4())
    foreign_version_id = str(uuid4())
    fact = _fact(
        TENANT_A,
        "cross-tenant-journey-reference",
        kind="conversation",
        payload={"campaign_id": "camp_1", "journey_id": journey_id},
    )
    reader = FakeJourneyReader(
        {
            journey_id: {
                "tenant_id": TENANT_B,
                "journey_id": journey_id,
                "journey_version_id": foreign_version_id,
                "is_current": True,
                "computed_at": "2026-10-20T12:34:56Z",
            }
        }
    )
    provider = Communication360Provider(
        sources=FakeSource(facts=[fact]), journey_reader=reader
    )
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    journey_slot = coverage["journey_links"]
    assert journey_slot["state"] == "degraded"
    assert journey_slot["reason"] == (
        "explicit_journey_reference_not_resolved_to_current_tenant_record"
    )
    assert {ref["id"] for ref in journey_slot["evidenceRefs"]} == {
        "cross-tenant-journey-reference"
    }
    assert not [claim for claim in result.claims if claim.kind == "communication_journey_link"]
    assert reader.calls == [(TENANT_A, journey_id)]


async def test_communication360_degrades_journey_link_when_current_authority_is_unavailable() -> None:
    from uuid import uuid4

    journey_id = str(uuid4())
    fact = _fact(
        TENANT_A,
        "unavailable-journey-reference",
        kind="conversation",
        payload={"campaign_id": "camp_1", "journey_id": journey_id},
    )
    reader = FakeJourneyReader(raises=True)
    provider = Communication360Provider(
        sources=FakeSource(facts=[fact]), journey_reader=reader
    )
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    journey_slot = coverage["journey_links"]
    assert journey_slot["state"] == "degraded"
    assert journey_slot["reason"] == "current_journey_authority_unavailable"
    assert {ref["id"] for ref in journey_slot["evidenceRefs"]} == {
        "unavailable-journey-reference"
    }
    assert not [claim for claim in result.claims if claim.kind == "communication_journey_link"]


async def test_communication360_reads_risk_flags_only_for_exact_source_subject() -> None:
    risk_rows = [
        {
            "signal_id": "source-risk-a",
            "tenant_id": TENANT_A,
            "subject_kind": "source",
            "subject_id": "source-a",
            "risk_dimension": "data_quality",
            "claim_state": "inferred",
            "confidence": 0.6,
            "evidence_refs": [
                {
                    "id": "source-risk-evidence-a",
                    "type": "event",
                    "source": "risk360/risk_signals",
                    "observedAt": "2026-10-20T12:30:00Z",
                }
            ],
            "source": "source_integrity_detector",
            "observed_at": "2026-10-20T12:30:00Z",
        },
    ]
    reader = FakeRiskSignalReader(risk_rows)
    provider = Communication360Provider(
        sources=FakeSource(), risk_signal_reader=reader
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="source", id="source-a"),
    )

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    risk_slot = coverage["risk_flags"]
    assert risk_slot["state"] == "available"
    assert risk_slot["reason"] == "tenant_scoped_risk_signals_observed_for_exact_subject"
    risk_evidence = {ref["id"]: ref for ref in risk_slot["evidenceRefs"]}
    assert risk_evidence["source-risk-evidence-a"]["observedAt"] == "2026-10-20T12:30:00Z"
    risk_claims = [claim for claim in result.claims if claim.kind == "communication_risk_signal_record"]
    assert len(risk_claims) == 1
    assert risk_claims[0].claimState == EpistemicStatus.INFERRED
    assert risk_claims[0].domainSlotIds == ["risk_flags"]
    assert {ref.id for ref in risk_claims[0].evidenceRefs} == {"source-risk-evidence-a"}
    assert reader.calls == [(TENANT_A, "source", "source-a", 101)]

    foreign = {
        **risk_rows[0],
        "signal_id": "source-risk-b",
        "tenant_id": TENANT_B,
        "evidence_refs": [
            {**risk_rows[0]["evidence_refs"][0], "id": "source-risk-evidence-b"}
        ],
    }
    leaking_reader = FakeRiskSignalReader([risk_rows[0], foreign])
    provider = Communication360Provider(
        sources=FakeSource(), risk_signal_reader=leaking_reader
    )
    result = await provider.project(request, context)
    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert coverage["risk_flags"]["state"] == "degraded"
    assert {ref["id"] for ref in coverage["risk_flags"]["evidenceRefs"]} == {
        "source-risk-evidence-a"
    }
    assert not any(
        ref.id == "source-risk-evidence-b"
        for claim in result.claims
        for ref in claim.evidenceRefs
    )
    assert leaking_reader.calls == [(TENANT_A, "source", "source-a", 101)]


async def test_communication360_keeps_risk_flags_unknown_for_unsupported_subject_and_degrades_on_outage() -> None:
    unsupported_reader = FakeRiskSignalReader()
    provider = Communication360Provider(
        sources=FakeSource(), risk_signal_reader=unsupported_reader
    )
    request, context = await _make_context(ProviderRegistry())
    result = await provider.project(request, context)
    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert coverage["risk_flags"]["state"] == "unknown"
    assert unsupported_reader.calls == []

    reader = FakeRiskSignalReader(raises=True)
    provider = Communication360Provider(sources=FakeSource(), risk_signal_reader=reader)
    request, context = await _make_context(
        ProviderRegistry(), subject=ProjectionSubject(kind="source", id="source-a")
    )
    result = await provider.project(request, context)
    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert coverage["risk_flags"]["state"] == "degraded"
    assert coverage["risk_flags"]["reason"] == "risk_signal_authority_unavailable"


async def test_communication360_does_not_join_current_journey_or_risk_for_as_of_request() -> None:
    from uuid import uuid4

    journey_uuid = uuid4()
    journey_id = str(journey_uuid)
    fact = _fact(
        TENANT_A,
        "historical-journey-reference",
        kind="conversation",
        payload={"source_id": "source-a", "journey_id": journey_id},
    )
    journey_reader = FakeJourneyReader(
        {
            journey_id: {
                "tenant_id": TENANT_A,
                "journey_id": journey_id,
                "journey_version_id": str(uuid4()),
                "is_current": True,
                "computed_at": "2026-10-20T12:34:56Z",
            }
        }
    )
    risk_reader = FakeRiskSignalReader()
    provider = Communication360Provider(
        sources=FakeSource(facts=[fact]),
        journey_reader=journey_reader,
        risk_signal_reader=risk_reader,
    )
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="source", id="source-a"),
        asOf="2026-10-20T13:00:00Z",
    )

    result = await provider.project(request, context)

    coverage = next(section for section in result.sections if section.id == "summary").content[
        "requiredSlotCoverage"
    ]
    assert coverage["journey_links"]["state"] == "unknown"
    assert coverage["journey_links"]["reason"] == "historical_current_journey_lookup_unavailable"
    assert coverage["risk_flags"]["state"] == "unknown"
    assert coverage["risk_flags"]["reason"] == "risk_signal_temporal_lookup_unavailable"
    assert journey_reader.calls == []
    assert risk_reader.calls == []


@pytest.mark.parametrize(
    ("subject_kind", "reference_key"),
    [("episode", "episode_id"), ("journey", "journey_id")],
)
async def test_source_policy_context_preserves_exact_provider_refs_for_episode_and_journey(
    subject_kind: str, reference_key: str
) -> None:
    subject_id = f"{subject_kind}-source-context"
    fact = _fact(
        TENANT_A,
        f"{subject_kind}-source-fact",
        payload={reference_key: subject_id, "provider_identity": "mail.provider.v1"},
    )
    source = FakeSource(facts=[fact])
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
    )

    result = await provider.project(request, context)

    state = next(section for section in result.sections if section.id == "state")
    source_policy = state.content["sourcePolicyContext"]
    assert source_policy["state"] == "partial"
    assert source_policy["sourceLineage"]["references"] == [
        {
            "providerIdentity": "mail.provider.v1",
            "referenceSource": "communication360_facts.provider_identity",
            "observedAt": fact["occurred_at"],
            "evidenceRefs": [
                {
                    "id": fact["fact_id"],
                    "type": "event",
                    "source": "services/api/journeys/communication360/communication360_facts",
                    "observedAt": fact["occurred_at"],
                    "uri": f"store://communication360_facts/{fact['fact_id']}",
                }
            ],
        }
    ]
    assert source_policy["sourceLineage"]["state"] == "observed_references"
    assert source_policy["policyEvaluation"]["state"] == "unknown"
    assert source_policy["policyEvaluation"]["authority"] == "experience360_frame_policy_runtime"
    assert source_policy["freshness"]["state"] == "unknown"
    assert source_policy["freshness"]["evaluation"] == "not_performed"
    assert (
        source_policy["freshness"]["reason"] == "freshness_window_not_evaluated_by_communication360"
    )


async def test_source_policy_context_is_tenant_filtered_and_keeps_recorded_consent_evidence() -> (
    None
):
    receipt_ref = EvidenceRef(
        id="consent-receipt-1",
        type="event",
        source="governance.consent.authority",
        observedAt="2026-09-03T10:00:00Z",
    )
    identity_ref = EvidenceRef(
        id="identity-binding-1",
        type="entity",
        source="comms_provider_identities",
        observedAt="2026-09-03T10:00:00Z",
    )
    message = _msg(
        TENANT_A,
        "consented-message",
        provider="mail.provider.v1",
        consent_evidence=CommunicationConsentEvidence(
            state="recorded",
            purpose="marketing",
            receipt_id=receipt_ref.id,
            subject_entity_id="recipient-1",
            identity_binding_id=identity_ref.id,
            evidence_refs=[receipt_ref, identity_ref],
        ),
    )
    foreign_fact = _fact(
        TENANT_B,
        "foreign-provider-fact",
        payload={"episode_id": "episode-policy", "provider_id": "foreign.provider.v1"},
    )

    class MisbehavingSource(FakeSource):
        async def facts(self, tenant_id, *, kind=None, since=None, limit=None):
            self.fact_read_count += 1
            return [foreign_fact]

    source = MisbehavingSource(messages=[message])
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(
        ProviderRegistry(),
        subject=ProjectionSubject(kind="campaign", id="camp_1"),
    )

    result = await provider.project(request, context)

    state = next(section for section in result.sections if section.id == "state")
    source_policy = state.content["sourcePolicyContext"]
    assert [item["providerIdentity"] for item in source_policy["sourceLineage"]["references"]] == [
        "mail.provider.v1"
    ]
    assert source_policy["historicalConsent"]["state"] == "recorded"
    assert source_policy["historicalConsent"]["receipts"][0]["receiptId"] == receipt_ref.id
    assert {
        ref["id"] for ref in source_policy["historicalConsent"]["receipts"][0]["evidenceRefs"]
    } == {receipt_ref.id, identity_ref.id}
    assert "foreign.provider.v1" not in str(source_policy)
    assert source_policy["freshness"]["state"] == "unknown"
    assert source_policy["freshness"]["evaluation"] == "not_performed"


async def test_source_policy_context_degrades_when_a_required_source_is_unavailable() -> None:
    provider = Communication360Provider(sources=FakeSource(raises="messages"))
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    state = next(section for section in result.sections if section.id == "state")
    source_policy = state.content["sourcePolicyContext"]
    assert source_policy["state"] == "degraded"
    assert source_policy["sourceLineage"]["state"] == "degraded"
    assert source_policy["historicalConsent"]["state"] == "degraded"
    assert source_policy["freshness"]["state"] == "unknown"


async def test_source_policy_context_does_not_infer_freshness_from_timestamps() -> None:
    provider = Communication360Provider(
        sources=FakeSource(
            messages=[_msg(TENANT_A, "timestamped-message", provider="mail.provider.v1")]
        )
    )
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    source_policy = next(section for section in result.sections if section.id == "state").content[
        "sourcePolicyContext"
    ]
    assert source_policy["sourceLineage"]["references"][0]["observedAt"]
    assert source_policy["historicalConsent"]["state"] == "unknown"
    assert source_policy["policyEvaluation"]["state"] == "unknown"
    assert source_policy["freshness"] == {
        "state": "unknown",
        "sourceTimestampsPreserved": True,
        "evaluation": "not_performed",
        "reason": "freshness_window_not_evaluated_by_communication360",
    }


async def test_source_lineage_preserves_evidence_for_each_provider_observation() -> None:
    source = FakeSource(
        messages=[
            _msg(TENANT_A, "message-one", provider="mail.provider.v1"),
            _msg(
                TENANT_A,
                "message-two",
                provider="mail.provider.v1",
                occurred_at="2026-09-03T10:05:00Z",
            ),
        ]
    )
    provider = Communication360Provider(sources=source)
    request, context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)

    source_policy = next(section for section in result.sections if section.id == "state").content[
        "sourcePolicyContext"
    ]
    references = source_policy["sourceLineage"]["references"]
    assert len(references) == 2
    assert {reference["providerIdentity"] for reference in references} == {"mail.provider.v1"}
    assert {reference["evidenceRefs"][0]["id"] for reference in references} == {
        "ev-message-one",
        "ev-message-two",
    }


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
