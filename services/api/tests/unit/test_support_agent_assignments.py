"""Focused authority, route, and projection tests for Support360 assignments."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.assignments import (  # noqa: E402
    SupportAgentAssignmentAuthorityError,
    SupportAgentAssignmentEventInput,
    SupportAgentAssignmentEventType,
    SupportAgentAssignmentIngestionService,
    SupportAgentAssignmentRepository,
    reset_local_support_agent_assignment_store,
)
from journeys.support360.cases import (  # noqa: E402
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseRepository,
    reset_local_support_case_store,
)
from journeys.support360.provider import (  # noqa: E402
    Support360Provider,
    SupportFactsRead,
)
from shared.auth.auth import Role  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)

TENANT_A = "tenant-support-assignment-a"
TENANT_B = "tenant-support-assignment-b"
CONNECTION_A = "support-assignment-connection-a"
PROVIDER = "support-desk"
PRINCIPAL = "authenticated-user-17"
AGENT_A = "canonical-agent-a"
AGENT_B = "canonical-agent-b"
NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


class FakeConnections:
    def __init__(self, rows: dict[str, SimpleNamespace]) -> None:
        self.rows = rows

    async def find(self, connection_id: str):
        return self.rows.get(connection_id)


class FakeEntities:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, list[str]]] = []

    async def find_many_for_tenant_entity_ids(self, tenant_id: str, entity_ids: list[str]):
        self.calls.append((tenant_id, list(entity_ids)))
        requested = set(entity_ids)
        return (
            [
                row
                for row in self.rows
                if row.get("tenant_id") == tenant_id and row.get("entity_id") in requested
            ],
            False,
        )


class CaseFactsSource:
    async def support_facts_for_case(self, tenant_id, connection_id, source_case_id, **kwargs):
        return SupportFactsRead(
            rows=[],
            available=True,
            complete=True,
            subject_join="support_case_connection_and_source_case_id_exact_match",
        )


def _connection(tenant_id: str = TENANT_A, *, state: str = "verified") -> SimpleNamespace:
    return SimpleNamespace(
        tenant_id=tenant_id,
        connection_id=CONNECTION_A,
        provider_identity=PROVIDER,
        state=state,
        last_verified_at="2026-10-24T14:00:00Z",
    )


def _case_event(event_id: str, event_type: SupportCaseEventType) -> SupportCaseEventInput:
    return SupportCaseEventInput(
        source_case_id="external-case-a",
        source_event_id=event_id,
        event_type=event_type,
        occurred_at=NOW,
    )


def _assignment_event(
    event_id: str,
    *,
    event_type: SupportAgentAssignmentEventType = SupportAgentAssignmentEventType.ASSIGNED,
    case_id: str,
    agent_id: str | None = AGENT_A,
    previous_agent_id: str | None = None,
    source_assignment_id: str = "source-assignment-a",
    source_revision_id: str = "rev-1",
    source_observed_at: datetime = NOW,
    effective_at: datetime = NOW,
) -> SupportAgentAssignmentEventInput:
    return SupportAgentAssignmentEventInput(
        case_id=case_id,
        source_assignment_id=source_assignment_id,
        source_revision_id=source_revision_id,
        source_event_id=event_id,
        event_type=event_type,
        agent_entity_id=agent_id,
        previous_agent_entity_id=previous_agent_id,
        source_observed_at=source_observed_at,
        effective_at=effective_at,
    )


@pytest.fixture(autouse=True)
def clear_support_stores():
    reset_local_support_case_store()
    reset_local_support_agent_assignment_store()
    yield
    reset_local_support_case_store()
    reset_local_support_agent_assignment_store()


async def _case_and_service(*, entities: FakeEntities | None = None):
    cases = SupportCaseRepository()
    case = await cases.ingest_event(
        tenant_id=TENANT_A,
        connection_id=CONNECTION_A,
        provider_identity=PROVIDER,
        connection_verified_at="2026-10-24T14:00:00Z",
        event=_case_event("case-created-assignment", SupportCaseEventType.CREATED),
        observed_at=NOW,
    )
    assignments = SupportAgentAssignmentRepository()
    identity = entities or FakeEntities(
        [
            {"tenant_id": TENANT_A, "entity_id": AGENT_A, "entity_type": "agent"},
            {"tenant_id": TENANT_A, "entity_id": AGENT_B, "entity_type": "agent"},
        ]
    )
    service = SupportAgentAssignmentIngestionService(
        assignments=assignments,
        cases=cases,
        connections=FakeConnections({CONNECTION_A: _connection()}),
        entities=identity,
    )
    return cases, case, assignments, service, identity


@pytest.mark.asyncio
async def test_assignment_is_exact_canonical_append_only_and_idempotent() -> None:
    _, case, repository, service, identity = await _case_and_service()
    event = _assignment_event("assignment-event-1", case_id=case["case_id"])

    created = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        event,
        assigning_principal_id=PRINCIPAL,
    )
    replay = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        event,
        assigning_principal_id=PRINCIPAL,
    )

    assert replay["assignment_event_id"] == created["assignment_event_id"]
    assert created["assigning_principal_id"] == PRINCIPAL
    assert created["agent_entity_id"] == AGENT_A
    assert created["source_revision_id"] == "rev-1"
    assert {ref["source"] for ref in created["evidence_refs"]} >= {
        PROVIDER,
        "provider_connections",
        "support_cases",
        "entities",
        "authenticated_principal",
    }
    assert identity.calls == [(TENANT_A, [AGENT_A]), (TENANT_A, [AGENT_A])]

    read = await repository.list_for_case(TENANT_A, case["case_id"], connection_id=CONNECTION_A)
    assert read.available and read.complete and len(read.events) == 1


@pytest.mark.asyncio
async def test_source_revision_and_event_id_conflicts_are_rejected() -> None:
    _, case, _, service, _ = await _case_and_service()
    original = _assignment_event("assignment-event-1", case_id=case["case_id"])
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        original,
        assigning_principal_id=PRINCIPAL,
    )

    with pytest.raises(SupportAgentAssignmentAuthorityError, match="revision"):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _assignment_event(
                "different-event-same-revision",
                case_id=case["case_id"],
            ),
            assigning_principal_id=PRINCIPAL,
        )
    with pytest.raises(SupportAgentAssignmentAuthorityError, match="replay payload"):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            _assignment_event(
                "assignment-event-1",
                case_id=case["case_id"],
                effective_at=NOW + timedelta(minutes=1),
            ),
            assigning_principal_id=PRINCIPAL,
        )


@pytest.mark.asyncio
async def test_handoff_records_both_canonical_agents_and_unassignment_stays_observed() -> None:
    _, case, repository, service, _ = await _case_and_service()
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _assignment_event("assignment-event-1", case_id=case["case_id"]),
        assigning_principal_id=PRINCIPAL,
    )
    handoff = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _assignment_event(
            "assignment-event-2",
            event_type=SupportAgentAssignmentEventType.HANDOFF,
            case_id=case["case_id"],
            agent_id=AGENT_B,
            previous_agent_id=AGENT_A,
            source_revision_id="rev-2",
            source_observed_at=NOW + timedelta(minutes=1),
            effective_at=NOW + timedelta(minutes=1),
        ),
        assigning_principal_id=PRINCIPAL,
    )
    unassigned = await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _assignment_event(
            "assignment-event-3",
            event_type=SupportAgentAssignmentEventType.UNASSIGNED,
            case_id=case["case_id"],
            agent_id=None,
            previous_agent_id=AGENT_B,
            source_revision_id="rev-3",
            source_observed_at=NOW + timedelta(minutes=2),
            effective_at=NOW + timedelta(minutes=2),
        ),
        assigning_principal_id=PRINCIPAL,
    )

    assert handoff["event_type"] == SupportAgentAssignmentEventType.HANDOFF.value
    assert handoff["previous_agent_entity_id"] == AGENT_A
    assert unassigned["agent_entity_id"] is None
    assert unassigned["previous_agent_entity_id"] == AGENT_B
    read = await repository.list_for_case(TENANT_A, case["case_id"], connection_id=CONNECTION_A)
    assert [event["event_type"] for event in read.events] == [
        SupportAgentAssignmentEventType.UNASSIGNED.value,
        SupportAgentAssignmentEventType.HANDOFF.value,
        SupportAgentAssignmentEventType.ASSIGNED.value,
    ]


@pytest.mark.asyncio
async def test_unverified_connection_or_noncanonical_agent_fails_closed() -> None:
    _, case, _, service, _ = await _case_and_service(
        entities=FakeEntities(
            [{"tenant_id": TENANT_B, "entity_id": AGENT_A, "entity_type": "agent"}]
        )
    )
    event = _assignment_event("assignment-event-1", case_id=case["case_id"])
    with pytest.raises(SupportAgentAssignmentAuthorityError, match="tenant-owned canonical agent"):
        await service.ingest(
            TENANT_A,
            CONNECTION_A,
            event,
            assigning_principal_id=PRINCIPAL,
        )
    with pytest.raises(SupportAgentAssignmentAuthorityError, match="verified tenant"):
        await SupportAgentAssignmentIngestionService(
            cases=SupportCaseRepository(),
            connections=FakeConnections({CONNECTION_A: _connection(state="disconnected")}),
            entities=FakeEntities([]),
        ).ingest(
            TENANT_A,
            CONNECTION_A,
            event,
            assigning_principal_id=PRINCIPAL,
        )


@pytest.mark.asyncio
async def test_support360_exposes_only_evidence_backed_assignment_observations() -> None:
    cases, case, assignments, service, identity = await _case_and_service()
    await service.ingest(
        TENANT_A,
        CONNECTION_A,
        _assignment_event("assignment-event-1", case_id=case["case_id"]),
        assigning_principal_id=PRINCIPAL,
    )
    request = ProjectionRequest(
        projectionId="support360",
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind="support_case", id=case["case_id"]),
    )
    context = ProjectionContext(
        projectionId="support360",
        tenantId=TENANT_A,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )
    result = await Support360Provider(
        CaseFactsSource(),
        case_repository=cases,
        agent_assignment_repository=assignments,
        canonical_agent_entity_repository=identity,
    ).project(request, context)

    state = next(section.content for section in result.sections if section.id == "state")
    slot = state["requiredSlots"]["agents"]
    assert slot["state"] == "degraded"
    assert slot["count"] == 1
    assert slot["assignmentEvents"][0]["canonicalAgentEntityId"] == AGENT_A
    assert slot["assignmentEvents"][0]["assigningPrincipal"]["id"] == PRINCIPAL
    assert slot["executionState"] == "not_joined"
    assert slot["outcomeState"] == "not_joined"
    assert any(claim.kind == "support_agent_assignment_observation" for claim in result.claims)
    assert "source_history_coverage_unverified" in " ".join(slot["reasonCodes"])


def test_assignment_ingress_rejects_payload_actor_or_tenant_claims() -> None:
    from journeys.support360.routes import SupportAgentAssignmentIngestBody

    values = {
        "connection_id": CONNECTION_A,
        "source_assignment_id": "source-assignment-a",
        "source_revision_id": "rev-1",
        "source_event_id": "assignment-event-1",
        "event_type": SupportAgentAssignmentEventType.ASSIGNED,
        "agent_entity_id": AGENT_A,
        "source_observed_at": NOW,
        "effective_at": NOW,
        "actor_id": "forged-actor",
        "tenant_id": "forged-tenant",
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SupportAgentAssignmentIngestBody.model_validate(values)


@pytest.mark.asyncio
async def test_assignment_route_uses_authenticated_request_principal(monkeypatch) -> None:
    from journeys.support360 import routes

    captured: dict[str, object] = {}

    class CapturingService:
        async def ingest(self, tenant_id, connection_id, event, **kwargs):
            captured.update(
                tenant_id=tenant_id,
                connection_id=connection_id,
                event=event,
                **kwargs,
            )
            return {
                "assignment_event_id": "assignment-canonical-1",
                "case_id": event.case_id,
                "source_assignment_id": event.source_assignment_id,
                "source_revision_id": event.source_revision_id,
                "event_type": event.event_type.value,
                "agent_entity_id": event.agent_entity_id,
                "previous_agent_entity_id": event.previous_agent_entity_id,
                "source_observed_at": event.source_observed_at.isoformat(),
                "effective_at": event.effective_at.isoformat(),
                "received_at": NOW.isoformat(),
            }

    monkeypatch.setattr(routes, "SupportAgentAssignmentIngestionService", CapturingService)

    class Tenant:
        tenant_id = TENANT_A
        user_id = PRINCIPAL
        role = Role.EDITOR
        permissions = ["write"]

        def require_permission(self, permission):
            assert permission == "write"

    request = SimpleNamespace(
        state=SimpleNamespace(tenant=Tenant()),
        client=None,
        headers={},
    )
    body = routes.SupportAgentAssignmentIngestBody(
        connection_id=CONNECTION_A,
        source_assignment_id="source-assignment-a",
        source_revision_id="rev-1",
        source_event_id="assignment-event-route-1",
        event_type=SupportAgentAssignmentEventType.ASSIGNED,
        agent_entity_id=AGENT_A,
        source_observed_at=NOW,
        effective_at=NOW,
    )
    response = await routes.ingest_support_agent_assignment_event(
        str(uuid4()),
        request,
        body,
    )
    assert captured["tenant_id"] == TENANT_A
    assert captured["assigning_principal_id"] == PRINCIPAL
    assert captured["assigning_principal_type"] == "tenant_user"
    assert response["data"]["assignment_event_id"] == "assignment-canonical-1"
