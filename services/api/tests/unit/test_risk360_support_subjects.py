"""Persisted Support aliases gate exact case-risk reads and frame evidence."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from connectors.provider_runtime.connection import (  # noqa: E402
    ProviderConnection, ProviderConnectionRepository,
)
from intelligence.risk360.provider import Risk360Provider  # noqa: E402
from intelligence.risk360.pipeline import compute_assessment, persist_assessment  # noqa: E402
from journeys.support360.cases import (  # noqa: E402
    SupportCaseAuthorityRead, SupportCaseEventInput, SupportCaseEventType,
    SupportCaseRepository, reset_local_support_case_store,
)
from journeys.support360.subjects import (  # noqa: E402
    SupportSubjectIngestionService, SupportSubjectInput, SupportSubjectRead,
    SupportSubjectRepository, reset_local_support_subject_store,
)
from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.intelligence_projections import generated_registry  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402
from tests.unit.test_risk360_provider import (  # noqa: E402
    TENANT_A, _FakeReader, _assessment, _available_registry, _context, _request, _seed, _signal,
)

OBSERVED = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
CONNECTION = "support-risk-connection"


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    reset_local_support_case_store()
    reset_local_support_subject_store()
    yield
    reset_in_memory_stores()
    reset_local_support_case_store()
    reset_local_support_subject_store()


async def setup_subject(kind):
    connections = ProviderConnectionRepository()
    await connections.upsert(ProviderConnection(
        connection_id=CONNECTION, tenant_id=TENANT_A, provider_identity="helpdesk",
        state="connected", selected_accounts=["account-1"],
        last_verified_at=OBSERVED.isoformat(),
    ))
    cases = SupportCaseRepository()
    case = await cases.ingest_event(
        tenant_id=TENANT_A, connection_id=CONNECTION, provider_identity="helpdesk",
        connection_verified_at=OBSERVED.isoformat(),
        event=SupportCaseEventInput(
            source_case_id="source-case", source_event_id="created",
            event_type=SupportCaseEventType.CREATED, occurred_at=OBSERVED,
        ),
    )
    subjects = SupportSubjectRepository(cases=cases)
    binding = await SupportSubjectIngestionService(
        subjects=subjects, connections=connections,
    ).ingest(
        TENANT_A, CONNECTION,
        SupportSubjectInput(
            kind=kind, case_id=case["case_id"], source_case_id="source-case",
            source_subject_id="source-subject", source_account_id="account-1",
            source_event_id="mapped", occurred_at=OBSERVED,
        ), actor_id="operator-1", actor_type="tenant_user",
    )
    signal = _signal("mapped-signal", TENANT_A, subject_id=case["case_id"]).model_copy(
        update={"subject_kind": "support_case"},
    )
    computed = compute_assessment(
        tenant_id=TENANT_A, subject_kind="support_case", subject_id=case["case_id"],
        signals=[signal], observed_at=OBSERVED,
    )
    persisted = await persist_assessment(computed, tenant_id=TENANT_A, signals=[signal])
    assessment = persisted.assessment
    provider = Risk360Provider(
        support_case_repository=cases, support_subject_repository=subjects,
        support_connection_repository=connections,
    )
    request = _request(subject=ProjectionSubject(kind=kind, id=binding["subject_id"]))
    return provider, request, binding, cases, connections, assessment, signal


class SubjectRead:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def read(self, *args):
        self.calls.append(args)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class NoRiskReads:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def unexpected(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError("risk authority must not be read")
        return unexpected


def scope_of(result):
    return next(section for section in result.sections if section.id == "findings").content[
        "supportCaseScope"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_persisted_alias_reads_only_canonical_case_risk(kind):
    provider, request, binding, _, _, assessment, signal = await setup_subject(kind)
    for subject_kind, subject_id in (
        (kind, request.subject.id), ("support_case", request.subject.id),
        ("support_case", "source-case"), ("support_case", "source-subject"),
    ):
        decoy = _assessment(f"decoy-{subject_kind}-{subject_id}", subject_id=subject_id).model_copy(
            update={"subject_kind": subject_kind, "subject_ref": None, "exposure": None},
        )
        await _seed(decoy)
    result = await provider.project(request, await _context(_available_registry()))
    assert {claim.kind for claim in result.claims} >= {"risk_assessment", "risk_signal_context"}
    assert all(claim.subject == request.subject for claim in result.claims)
    assert all("risk" in claim.domainSlotIds for claim in result.claims)
    assessment_claim = next(claim for claim in result.claims if claim.kind == "risk_assessment")
    signal_claim = next(claim for claim in result.claims if claim.kind == "risk_signal_context")
    assert assessment_claim.claimState == assessment.claim_state
    assert signal_claim.claimState == signal.claim_state
    assert signal_claim.confidence == signal.confidence
    assert "decoy-" not in result.model_dump_json()
    scope = scope_of(result)
    assert scope["riskRead"]["subjectId"] == binding["case_id"]
    join = scope["subjectCaseJoin"]
    assert (join["sourceProvider"], join["sourceConnectionId"], join["sourceAccountId"]) == (
        "helpdesk", CONNECTION, "account-1",
    )
    assert join["canonicalSubjectId"] == request.subject.id
    assert join["canonicalCaseId"] == binding["case_id"]
    assert join["sourceAuthenticity"] == "unverified"
    assert join["freshnessState"] == join["businessOutcomeState"] == "unknown"
    for claim in result.claims:
        assert {ref.source for ref in claim.evidenceRefs} >= {
            "support_cases", "support_case_subjects", "provider_connections", "helpdesk",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
@pytest.mark.parametrize("field,value", [
    ("tenant_id", "other-tenant"), ("subject_kind", "entity"),
    ("subject_id", str(uuid4())), ("case_id", "source-case"),
    ("source_connection_id", "other-connection"), ("source_provider_identity", "other-provider"),
    ("source_account_id", "other-account"), ("source_subject_id", " padded"),
    ("source_case_id", "other-case"), ("source_event_id", "other-event"),
    ("actor_id", ""), ("received_at", "not-a-date"), ("connection_verified_at", None),
    ("source_occurred_at", "2999-01-01T00:00:00Z"), ("evidence_refs", []),
])
async def test_malformed_or_conflicting_binding_prevents_every_risk_read(kind, field, value):
    provider, request, binding, _, _, _, _ = await setup_subject(kind)
    provider._support_subject_repository = SubjectRead(SupportSubjectRead(
        {**binding, field: value}, True, True,
    ))
    provider._sources = NoRiskReads()
    result = await provider.project(request, await _context(_available_registry()))
    assert provider._sources.calls == []
    assert result.claims == []
    assert scope_of(result)["state"] == "unknown"
    assert "support_case_subjects" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("read", [
    None, SupportSubjectRead(None, False, True), SupportSubjectRead(None, True, False),
    SupportSubjectRead(None, True, True), RuntimeError("private dependency error"),
])
async def test_missing_ambiguous_or_unavailable_binding_fails_closed(read):
    provider, request, _, _, _, _, _ = await setup_subject("ticket")
    provider._support_subject_repository = SubjectRead(read)
    provider._sources = NoRiskReads()
    result = await provider.project(request, await _context(_available_registry()))
    assert provider._sources.calls == [] and not result.claims
    assert "private dependency error" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("tenant_id", "other-tenant"), ("connection_id", "other-connection"),
    ("provider_identity", "other-provider"), ("state", "disconnected"),
    ("selected_accounts", []), ("selected_accounts", "account-1"),
    ("last_verified_at", None), ("last_verified_at", "not-a-date"),
    ("last_verified_at", "2999-01-01T00:00:00Z"),
    ("last_verified_at", (OBSERVED - timedelta(seconds=1)).isoformat()),
])
async def test_current_connection_account_scope_must_still_match(field, value):
    provider, request, _, _, connections, _, _ = await setup_subject("conversation")
    connection = (await connections.find(CONNECTION)).model_dump()

    class Connections:
        async def find(self, connection_id):
            return SimpleNamespace(**{**connection, field: value})

    provider._support_connection_repository = Connections()
    provider._sources = NoRiskReads()
    result = await provider.project(request, await _context(_available_registry()))
    assert provider._sources.calls == [] and not result.claims
    assert scope_of(result)["reason"] == "support_subject_connection_account_scope_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    "tenant", "case", "connection", "provider", "source_case", "truncated", "expired",
    "malformed_events", "foreign_event", "missing", "unavailable", "exception",
])
async def test_mapped_case_scope_is_revalidated_before_risk_reads(failure):
    provider, request, binding, cases, _, _, _ = await setup_subject("ticket")
    read = await cases.get_case(TENANT_A, binding["case_id"])
    record = dict(read.record)
    key = {
        "tenant": "tenant_id", "case": "case_id", "connection": "source_connection_id",
        "provider": "source_provider_identity", "source_case": "source_case_id",
    }.get(failure)
    if key:
        record[key] = "other"

    class Cases:
        async def get_case(self, tenant_id, case_id):
            if failure == "exception":
                raise RuntimeError("private case diagnostic")
            events = None if failure == "malformed_events" else read.events
            if failure == "foreign_event":
                events = [{**read.events[0], "source_connection_id": "other"}]
            return SupportCaseAuthorityRead(
                None if failure == "missing" else record, events,
                failure != "unavailable", failure != "truncated", expired=failure == "expired",
            )

    provider._support_case_repository = Cases()
    provider._sources = NoRiskReads()
    result = await provider.project(request, await _context(_available_registry()))
    assert provider._sources.calls == [] and not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["tenant", "as_of", "context_as_of", "compare", "case_id", "source_id"])
async def test_no_id_or_historical_fallback(failure):
    provider, request, binding, _, _, _, _ = await setup_subject("ticket")
    context = await _context(_available_registry())
    if failure == "tenant":
        context = context.model_copy(update={"tenantId": "other-tenant"})
    elif failure in {"as_of", "context_as_of"}:
        target = context if failure == "context_as_of" else request
        target.asOf = OBSERVED.isoformat()
    elif failure == "compare":
        request.temporalMode = "compare"
    else:
        request.subject.id = binding["case_id"] if failure == "case_id" else "source-subject"
    provider._sources = NoRiskReads()
    result = await provider.project(request, context)
    assert provider._sources.calls == [] and not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["overflow", "wrong_scope", "malformed", "not_list", "duplicate"])
async def test_incomplete_signal_read_releases_no_partial_signal_evidence(failure):
    provider, request, _, _, _, assessment, signal = await setup_subject("ticket")
    raw = signal.model_dump(mode="json")
    raw["evidence_refs"] = [{"id": "partial-signal-only", "type": "event", "source": "test"}]
    rows = {
        "overflow": [raw] * 101,
        "wrong_scope": [raw, {**raw, "subject_id": "other-case"}],
        "malformed": [raw, None],
        "not_list": None,
        "duplicate": [raw, raw],
    }[failure]

    class Signals(_FakeReader):
        async def signals(self, **kwargs):
            return rows

    provider._sources = Signals(assessment=assessment.model_dump(mode="json"))
    result = await provider.project(request, await _context(_available_registry()))
    assert not any(claim.kind == "risk_signal_context" for claim in result.claims)
    assert "partial-signal-only" not in result.model_dump_json()
    assert any(claim.kind == "risk_assessment" for claim in result.claims)
    assert scope_of(result)["riskRead"]["signalRead"] == "degraded"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_default_authorities_reread_persisted_account_revocation(kind):
    _, request, _, _, connections, _, _ = await setup_subject(kind)
    provider = Risk360Provider()
    result = await provider.project(request, await _context(_available_registry()))
    assert any(claim.kind == "risk_assessment" for claim in result.claims)
    connection = await connections.find(CONNECTION)
    await connections.upsert(connection.model_copy(update={"selected_accounts": []}))
    provider._sources = NoRiskReads()
    result = await provider.project(request, await _context(_available_registry()))
    assert not result.claims and provider._sources.calls == []


@pytest.mark.asyncio
async def test_mapping_identity_alone_does_not_invent_risk():
    provider, request, _, _, _, _, _ = await setup_subject("ticket")
    provider._sources = _FakeReader()
    result = await provider.project(request, await _context(_available_registry()))
    assert result.claims == []
    assert scope_of(result)["riskRead"]["assessmentPresent"] is False
    assert scope_of(result)["riskRead"]["signalCount"] == 0
    assert scope_of(result)["riskRead"]["signalCoverage"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
@pytest.mark.parametrize("proposed,allowed,binding_valid", [
    (False, True, True), (True, True, True), (True, False, True), (True, True, False),
])
async def test_real_support_frame_preserves_policy_subject_and_registry_boundary(
    kind, proposed, allowed, binding_valid, monkeypatch,
):
    provider, request, _, _, _, _, _ = await setup_subject(kind)
    if not binding_valid:
        provider._support_subject_repository = SubjectRead(SupportSubjectRead(None, True, False))
        provider._sources = NoRiskReads()
    if proposed:
        surface = deepcopy(generated_registry.PRODUCT_360_SURFACE_DEFINITIONS["support360"])
        definition = deepcopy(generated_registry.INTELLIGENCE_PROJECTION_DEFINITIONS["risk360"])
        definition["subjectKinds"] = [*definition["subjectKinds"], "ticket", "conversation"]
        definition["canonicalAuthorities"] = [
            *definition["canonicalAuthorities"], "support_case_subjects", "provider_connections",
        ]
        risk_slot = next(slot for slot in surface["domainSlots"] if slot["id"] == "risk")
        risk_slot["canonicalAuthorityRefs"] = [
            *risk_slot["canonicalAuthorityRefs"], "support_case_subjects", "provider_connections",
        ]
        binding = risk_slot["projectionBindings"][0]
        binding["subjectKinds"] = [*binding["subjectKinds"], "ticket", "conversation"]
        monkeypatch.setitem(generated_registry.PRODUCT_360_SURFACE_DEFINITIONS, "support360", surface)
        monkeypatch.setitem(generated_registry.INTELLIGENCE_PROJECTION_DEFINITIONS, "risk360", definition)
    registry = _available_registry()
    registry.register(provider)
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    calls = []

    class Policy:
        async def evaluate(self, frame_request):
            assert frame_request.subject == request.subject
            return Experience360PolicyEvaluation(
                surfaceId="support360", tenantId=TENANT_A, evaluatedAt=OBSERVED.isoformat(),
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"risk": Experience360PolicyDisposition(
                    state="allowed" if allowed else "denied",
                )},
            )

    class Runtime:
        async def execute_projection(self, projection_request, **kwargs):
            calls.append(projection_request)
            assert projection_request.subject == request.subject
            assert set(projection_request.includeSections) == {"summary", "state", "evidence", "findings"}
            return await runtime.execute_projection(projection_request, **kwargs)

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="support360", tenantId=TENANT_A, subject=request.subject,
            requestedSlotIds=["risk"], includeEvidence=True,
        ), policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    slot = frame.slots[0]
    if proposed and allowed and binding_valid:
        assert len(calls) == 1
        assert slot.content and slot.claims and slot.evidenceRefs
        assert all(claim.subject == request.subject and "risk" in claim.domainSlotIds for claim in slot.claims)
        assert {ref.source for ref in slot.evidenceRefs} >= {"support_case_subjects", "support_cases"}
    elif proposed and allowed:
        assert len(calls) == 1
        assert provider._sources.calls == []
        assert not slot.claims and not slot.evidenceRefs
        assert "subjectCaseJoin" not in frame.model_dump_json()
    else:
        assert calls == []
        assert slot.content is None and not slot.claims and not slot.evidenceRefs
