"""Support-only slot dispatch, scoped reads, and frame integration regressions."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.assignments import SupportAgentAssignmentRead  # noqa: E402
from journeys.support360.callbacks import SupportCallbacksRead  # noqa: E402
from journeys.support360.cases import (  # noqa: E402
    SupportCaseAuthorityRead,
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseRepository,
    reset_local_support_case_store,
)
from journeys.support360.context_authorities import SupportCaseContextRead  # noqa: E402
from journeys.support360.provider import (  # noqa: E402
    SUPPORT_SLOT_SECTIONS,
    Support360Provider,
    SupportFactsRead,
)
from journeys.support360.sla_measurement import SupportSLAMeasurementContractRead  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    PRODUCT_360_SURFACE_DEFINITIONS,
)

TENANT = "support-slot-tenant"
CONNECTION = "support-slot-connection"
OBSERVED = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def reset_cases():
    reset_local_support_case_store()
    yield
    reset_local_support_case_store()


async def _case():
    repository = SupportCaseRepository()
    record = await repository.ingest_event(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        provider_identity="helpdesk",
        connection_verified_at=OBSERVED.isoformat(),
        event=SupportCaseEventInput(
            source_case_id="external-case",
            source_event_id="case-created",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=OBSERVED,
        ),
        observed_at=OBSERVED,
    )
    return repository, record


def _request(case_id, *slots):
    return ProjectionRequest(
        projectionId="support360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="support_case", id=case_id),
        includeSections=[SUPPORT_SLOT_SECTIONS[slot] for slot in slots],
    )


def _context():
    return ProjectionContext(
        projectionId="support360", tenantId=TENANT, registryState="in_flight",
        dependencyState=[], warnings=[],
    )


class Dependencies:
    def __init__(self):
        self.calls = []

    async def list_for_case(self, *args, **kwargs):
        kind = kwargs.get("kind")
        self.calls.append(kind or "agents" if "connection_id" in kwargs else "callbacks")
        if kind:
            return SupportCaseContextRead([], True, True)
        if "connection_id" in kwargs:
            return SupportAgentAssignmentRead([], True, True)
        return SupportCallbacksRead([], True, True)

    async def read_for_case(self, *args):
        self.calls.append("sla_contract")
        return SupportSLAMeasurementContractRead((), True, True)

    async def support_participants_for_case(self, *args, **kwargs):
        self.calls.append("participants")
        return SupportFactsRead([], False)

    async def support_facts_for_case(self, tenant_id, connection_id, source_case_id, **kwargs):
        self.calls.append("conversation_history")
        return SupportFactsRead([
            {
                "fact_id": "support-message", "tenant_id": tenant_id,
                "source_connector_id": connection_id, "support_case_id": source_case_id,
                "provider": "helpdesk", "message_category": "support",
                "occurred_at": OBSERVED.isoformat(), "received_at": OBSERVED.isoformat(),
                "payload": {"body": "private-message-must-not-leak"},
            }
        ], True, complete=True)

    async def project(self, *args, **kwargs):
        self.calls.append("risk")
        raise AssertionError("risk must be separately policy dispatched")


def _provider(cases, dependencies):
    return Support360Provider(
        dependencies, case_repository=cases, callback_repository=dependencies,
        agent_assignment_repository=dependencies, case_context_repository=dependencies,
        sla_measurement_repository=dependencies, risk_projection_registry=dependencies,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("slot_id", "expected_reads"), [
    ("case_summary", []), ("resolution", []), ("evidence_trace", []),
    ("conversation_history", ["conversation_history"]), ("callbacks", ["callbacks"]),
    ("agents", ["agents"]), ("sla", ["sla", "sla_contract"]),
    ("journey_links", ["journey_links"]), ("participants", ["participants"]),
])
async def test_required_slot_reads_only_its_exact_authority(slot_id, expected_reads):
    cases, case = await _case()
    dependencies = Dependencies()
    result = await _provider(cases, dependencies).project(
        _request(case["case_id"], slot_id), _context()
    )
    assert dependencies.calls == expected_reads
    assert [section.id for section in result.sections] == [SUPPORT_SLOT_SECTIONS[slot_id]]
    assert "private-message-must-not-leak" not in repr(result.model_dump())
    assert all(slot_id in claim.domainSlotIds for claim in result.claims)
    if slot_id in {"case_summary", "resolution", "evidence_trace", "conversation_history"}:
        assert result.sections[0].state == "available"
        assert result.sections[0].content["scope"] == "bounded_current_store_observations"
        assert result.sections[0].content["evidenceRefs"]


def test_every_required_support_owned_slot_has_an_isolated_dispatch_section():
    slots = PRODUCT_360_SURFACE_DEFINITIONS["support360"]["domainSlots"]
    owned_required_slots = {
        slot["id"] for slot in slots
        if slot["requirement"] == "required"
        and any(binding["projectionId"] == "support360" for binding in slot["projectionBindings"])
    }
    assert set(SUPPORT_SLOT_SECTIONS) == owned_required_slots
    for slot in slots:
        if slot["id"] in SUPPORT_SLOT_SECTIONS:
            for binding in slot["projectionBindings"]:
                if binding["projectionId"] == "support360":
                    assert tuple(binding["sectionIds"]) == (SUPPORT_SLOT_SECTIONS[slot["id"]],)
    risk = next(slot for slot in slots if slot["id"] == "risk")
    assert {binding["projectionId"] for binding in risk["projectionBindings"]} == {"risk360"}


@pytest.mark.asyncio
@pytest.mark.parametrize("update", [
    {"asOf": "2026-11-01T00:00:00Z"},
    {"temporalMode": "as_of"},
    {"temporalMode": "window", "timeRange": {}},
])
async def test_isolated_observations_do_not_relax_historical_or_explicit_window_checks(update):
    cases, case = await _case()
    dependencies = Dependencies()
    request = ProjectionRequest.model_validate({
        **_request(case["case_id"], "resolution").model_dump(by_alias=True), **update,
    })
    result = await _provider(cases, dependencies).project(request, _context())
    assert dependencies.calls == []
    assert result.sections[0].state == "unknown"
    assert result.sections[0].content is None
    assert result.claims == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [
    ("tenant_id", "other-tenant"), ("case_id", "other-case"),
    ("source_connection_id", "other-connection"), ("tenant_id", None),
])
async def test_case_event_scope_mismatch_fails_before_sibling_reads(field, value):
    cases, case = await _case()
    read = await cases.get_case(TENANT, case["case_id"])
    events = deepcopy(read.events)
    events[0][field] = value

    class ContaminatedCases:
        async def get_case(self, *args, **kwargs):
            return SupportCaseAuthorityRead(read.record, events, True, True)

    dependencies = Dependencies()
    result = await _provider(ContaminatedCases(), dependencies).project(
        _request(case["case_id"], "resolution"), _context()
    )
    assert dependencies.calls == []
    assert result.sections[0].state == "unknown"
    assert result.sections[0].content is None
    assert result.claims == []
    assert result.degradedReasons == ["support_case_event_scope_mismatch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["other-provider", None])
async def test_case_communication_provider_identity_is_rechecked(provider):
    cases, case = await _case()

    class WrongProvider(Dependencies):
        async def support_facts_for_case(self, *args, **kwargs):
            read = await super().support_facts_for_case(*args, **kwargs)
            read.rows[0]["provider"] = provider
            return read

    result = await _provider(cases, WrongProvider()).project(
        _request(case["case_id"], "conversation_history"), _context()
    )
    assert result.sections[0].state == "unknown"
    assert result.sections[0].content is None
    assert result.claims == []
    assert "support_case_conversation_tenant_scope_mismatch" in result.degradedReasons


@pytest.mark.asyncio
async def test_frame_preserves_structured_resolution_and_denies_sibling_reads():
    cases, case = await _case()
    dependencies = Dependencies()
    provider = _provider(cases, dependencies)
    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="support360", tenantId=TENANT, evaluatedAt=OBSERVED.isoformat(),
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "resolution": Experience360PolicyDisposition(state="allowed"),
                    "sla": Experience360PolicyDisposition(state="denied"),
                    "participants": Experience360PolicyDisposition(state="denied"),
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            assert request.includeSections == ["support_resolution"]
            return await provider.project(request, _context())

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="support360", tenantId=TENANT,
            subject=ProjectionSubject(kind="support_case", id=case["case_id"]),
            requestedSlotIds=["resolution", "sla", "participants"], includeEvidence=True,
        ),
        policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    slots = {slot.id: slot for slot in frame.slots}
    resolution = slots["resolution"]
    assert resolution.state in {"available", "degraded"}
    observed = resolution.content["sections"][0]["content"]
    assert observed["resolutionState"] == "open"
    assert observed["resolutionOccurred"] is False
    assert observed["businessOutcomeState"] == "unknown"
    assert resolution.evidenceRefs and resolution.claims
    assert slots["sla"].content is None
    assert slots["participants"].content is None
    assert dependencies.calls == []
