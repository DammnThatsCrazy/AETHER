"""Focused tests for Support360 SLA and journey-link bindings."""

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

from journeys.support360.cases import (  # noqa: E402
    SupportCaseEventInput,
    SupportCaseEventType,
    SupportCaseRepository,
    reset_local_support_case_store,
)
from journeys.support360.context_authorities import (  # noqa: E402
    SupportCaseContextAuthorityError,
    SupportCaseContextIngestionService,
    SupportCaseContextRepository,
    SupportJourneyLinkEventInput,
    SupportJourneyLinkEventType,
    SupportSLAEventInput,
    SupportSLAEventType,
    SupportSLATimerKind,
    reset_local_support_case_context_store,
)
from journeys.support360.provider import Support360Provider, SupportFactsRead  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSection,
    ProjectionSubject,
)

TENANT = "tenant-support-context-a"
CONNECTION = "support-context-connection-a"
PROVIDER = "helpdesk-source"
ACTOR = "tenant-user-context-1"
ENTITY = "canonical-user-context-1"
NOW = datetime(2026, 10, 24, 16, 0, tzinfo=timezone.utc)


class FakeConnections:
    async def find(self, connection_id: str):
        if connection_id != CONNECTION:
            return None
        return SimpleNamespace(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            provider_identity=PROVIDER,
            state="verified",
            last_verified_at=NOW.isoformat(),
        )


class FakeEntities:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    async def find_many_for_tenant_entity_ids(self, tenant_id: str, entity_ids: list[str]):
        requested = set(entity_ids)
        return (
            [
                row
                for row in self.rows
                if row.get("tenant_id") == tenant_id and row.get("entity_id") in requested
            ],
            False,
        )


class FakeJourneys:
    def __init__(self, journey_id: str):
        self.journey_id = journey_id
        self.calls: list[tuple[str, str]] = []

    async def get_current(self, tenant_id: str, journey_id: str):
        self.calls.append((tenant_id, journey_id))
        if tenant_id != TENANT or journey_id != self.journey_id:
            return None
        return {
            "tenant_id": tenant_id,
            "journey_id": journey_id,
            "journey_version_id": "journey-version-current",
            "journey_state": "open",
            "is_current": True,
        }


class EmptyCaseFactsSource:
    async def support_facts_for_case(self, tenant_id, connection_id, source_case_id, **kwargs):
        return SupportFactsRead(
            rows=[],
            available=True,
            complete=True,
            subject_join="support_case_connection_and_source_case_id_exact_match",
        )

    async def support_participants_for_case(
        self, tenant_id, connection_id, source_case_id, provider_identity, *, limit
    ):
        assert tenant_id == TENANT
        assert connection_id == CONNECTION
        assert provider_identity == PROVIDER
        return SupportFactsRead(
            rows=[
                {
                    "fact_id": "communication360-participant-fact-1",
                    "tenant_id": TENANT,
                    "kind": "participant_binding",
                    "source_event_id": "authenticated-roster-event-1",
                    "actor_id": ACTOR,
                    "occurred_at": NOW.isoformat(),
                    "payload": {
                        "entity_id": ENTITY,
                        "role": "actor",
                        "claim_state": "observed",
                        "communication_scope_kind": "provider_conversation",
                        "communication_scope": "provider-conversation-1",
                        "provider_conversation_id": "provider-conversation-1",
                        "provider": PROVIDER,
                        "provider_account_id": "provider-account-1",
                        "roster_id": "roster-1",
                        "binding_id": "binding-1",
                        "entity_type": "user",
                        "source_identity": {
                            "identity_binding_id": "identity-binding-1",
                            "resolution_status": "resolved",
                        },
                        "role_evidence_refs": [
                            {
                                "id": "provider-role-evidence-1",
                                "type": "event",
                                "source": PROVIDER,
                                "observedAt": NOW.isoformat(),
                            }
                        ],
                        "source_provenance": {
                            "namespace": PROVIDER,
                            "provider_account_id": "provider-account-1",
                            "event_id": "authenticated-roster-event-1",
                            "authentication": {
                                "method": "tenant_webhook_hmac",
                                "verified": True,
                            },
                        },
                        "actor_attribution": {"actor_id": ACTOR},
                        "policy": {
                            "ingress_consent_outcome": "allowed",
                            "sensitive_message_fields_redacted": True,
                        },
                        "roster_completeness_state": "unknown",
                        "roster_binding_count": 1,
                    },
                }
            ],
            available=True,
            complete=True,
            subject_join=(
                "support_case_connection_source_case_to_provider_account_conversation_exact_match"
            ),
            join_reference_ids=(CONNECTION, "provider-conversation-1"),
            conversation_scopes=((PROVIDER, "provider-account-1", "provider-conversation-1"),),
        )


class RiskRegistry:
    async def project(self, projection_id, request, **kwargs):
        assert projection_id == "risk360"
        assert request.tenantId == TENANT
        assert request.subject.kind == "support_case"
        return SimpleNamespace(
            projectionId="risk360",
            tenantId=TENANT,
            sections=[
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={"subject": {"kind": "support_case", "id": request.subject.id}},
                ),
                ProjectionSection(
                    id="evidence",
                    state="empty",
                    content={"count": 0, "evidence": []},
                ),
            ],
        )


@pytest.fixture(autouse=True)
def clear_support_stores():
    reset_local_support_case_store()
    reset_local_support_case_context_store()
    yield
    reset_local_support_case_store()
    reset_local_support_case_context_store()


async def _case() -> tuple[SupportCaseRepository, dict]:
    repository = SupportCaseRepository()
    record = await repository.ingest_event(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        provider_identity=PROVIDER,
        connection_verified_at=NOW.isoformat(),
        event=SupportCaseEventInput(
            source_case_id="source-case-context-a",
            source_event_id="case-context-created",
            event_type=SupportCaseEventType.CREATED,
            occurred_at=NOW,
        ),
        observed_at=NOW,
    )
    return repository, record


@pytest.mark.asyncio
async def test_sla_and_journey_link_use_exact_authorities():
    cases, case = await _case()
    journey_id = str(uuid4())
    journeys = FakeJourneys(journey_id)
    repo = SupportCaseContextRepository()
    service = SupportCaseContextIngestionService(
        repository=repo,
        cases=cases,
        connections=FakeConnections(),
        journeys=journeys,
    )
    sla_event = SupportSLAEventInput(
        case_id=case["case_id"],
        source_sla_id="source-sla-1",
        source_revision_id="sla-rev-1",
        source_event_id="sla-event-1",
        event_type=SupportSLAEventType.TIMER_STARTED,
        timer_kind=SupportSLATimerKind.FIRST_RESPONSE,
        source_policy_id="policy-first-response",
        source_policy_version="v2",
        source_timer_state="running",
        due_at=NOW + timedelta(minutes=30),
        source_observed_at=NOW,
        effective_at=NOW,
    )
    sla = await service.ingest(
        "sla",
        TENANT,
        CONNECTION,
        sla_event,
        actor_id=ACTOR,
        actor_type="tenant_user",
    )
    link_event = SupportJourneyLinkEventInput(
        case_id=case["case_id"],
        source_link_id="source-link-1",
        source_revision_id="link-rev-1",
        source_event_id="journey-link-event-1",
        journey_id=journey_id,
        event_type=SupportJourneyLinkEventType.LINKED,
        source_observed_at=NOW,
        effective_at=NOW,
    )
    link = await service.ingest(
        "journey_links",
        TENANT,
        CONNECTION,
        link_event,
        actor_id=ACTOR,
        actor_type="tenant_user",
    )

    assert sla["payload"]["source_timer_state"] == "running"
    assert sla["payload"]["due_at"].startswith("2026-10-24T16:30:00")
    assert link["payload"]["journey_id"] == journey_id
    assert journeys.calls == [(TENANT, journey_id)]

    sla_read = await repo.list_for_case(
        TENANT, case["case_id"], connection_id=CONNECTION, kind="sla"
    )
    journey_read = await repo.list_for_case(
        TENANT, case["case_id"], connection_id=CONNECTION, kind="journey_links"
    )
    assert sla_read.complete and sla_read.events[0]["source_event_id"] == "sla-event-1"
    assert (
        journey_read.complete
        and journey_read.events[0]["source_event_id"] == "journey-link-event-1"
    )


@pytest.mark.asyncio
async def test_sla_replay_conflict_fails_closed():
    cases, case = await _case()
    service = SupportCaseContextIngestionService(
        repository=SupportCaseContextRepository(),
        cases=cases,
        connections=FakeConnections(),
    )
    event = SupportSLAEventInput(
        case_id=case["case_id"],
        source_sla_id="sla-1",
        source_revision_id="sla-r1",
        source_event_id="sla-event-replay",
        event_type=SupportSLAEventType.TIMER_STARTED,
        timer_kind=SupportSLATimerKind.FIRST_RESPONSE,
        source_policy_id="policy-first-response",
        source_policy_version="v1",
        source_timer_state="running",
        target_duration_seconds=900,
        source_observed_at=NOW,
        effective_at=NOW,
    )
    first = await service.ingest("sla", TENANT, CONNECTION, event, actor_id=ACTOR, actor_type="tenant_user")
    replay = await service.ingest("sla", TENANT, CONNECTION, event, actor_id=ACTOR, actor_type="tenant_user")
    assert replay["context_event_id"] == first["context_event_id"]

    conflicting = event.model_copy(update={"source_timer_state": "paused"})
    with pytest.raises(SupportCaseContextAuthorityError, match="replay payload"):
        await service.ingest("sla", TENANT, CONNECTION, conflicting, actor_id=ACTOR, actor_type="tenant_user")


def test_context_event_contract_rejects_tenant_actor_and_malformed_sla_claims():
    with pytest.raises(ValidationError, match="custom SLA timers"):
        SupportSLAEventInput(
            case_id=str(uuid4()),
            source_sla_id="sla-1",
            source_revision_id="r1",
            source_event_id="e1",
            event_type=SupportSLAEventType.CONTRACT_OBSERVED,
            timer_kind=SupportSLATimerKind.CUSTOM,
            source_policy_id="policy-1",
            source_policy_version="v1",
            source_observed_at=NOW,
            effective_at=NOW,
        )


@pytest.mark.asyncio
async def test_support360_binds_context_sla_journey_resolution_risk_and_evidence_slots():
    cases, case = await _case()
    journey_id = str(uuid4())
    journeys = FakeJourneys(journey_id)
    entities = FakeEntities([{"tenant_id": TENANT, "entity_id": ENTITY, "entity_type": "user"}])
    context_repo = SupportCaseContextRepository()
    service = SupportCaseContextIngestionService(
        repository=context_repo,
        cases=cases,
        connections=FakeConnections(),
        journeys=journeys,
    )
    await service.ingest(
        "sla",
        TENANT,
        CONNECTION,
        SupportSLAEventInput(
            case_id=case["case_id"],
            source_sla_id="source-sla-1",
            source_revision_id="sla-rev-1",
            source_event_id="sla-event-1",
            event_type=SupportSLAEventType.TIMER_STARTED,
            timer_kind=SupportSLATimerKind.FIRST_RESPONSE,
            source_policy_id="response-policy",
            source_policy_version="v2",
            source_timer_state="running",
            due_at=NOW + timedelta(minutes=30),
            source_observed_at=NOW,
            effective_at=NOW,
        ),
        actor_id=ACTOR,
        actor_type="tenant_user",
    )
    await service.ingest(
        "journey_links",
        TENANT,
        CONNECTION,
        SupportJourneyLinkEventInput(
            case_id=case["case_id"],
            source_link_id="source-link-1",
            source_revision_id="link-rev-1",
            source_event_id="journey-link-1",
            journey_id=journey_id,
            event_type=SupportJourneyLinkEventType.LINKED,
            source_observed_at=NOW,
            effective_at=NOW,
        ),
        actor_id=ACTOR,
        actor_type="tenant_user",
    )
    request = ProjectionRequest(
        projectionId="support360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="support_case", id=case["case_id"]),
    )
    context = ProjectionContext(
        projectionId="support360",
        tenantId=TENANT,
        registryState="in_flight",
        dependencyState=[],
        warnings=[],
    )
    result = await Support360Provider(
        EmptyCaseFactsSource(),
        case_repository=cases,
        case_context_repository=context_repo,
        canonical_agent_entity_repository=entities,
        canonical_journey_repository=journeys,
        risk_projection_registry=RiskRegistry(),
    ).project(request, context)
    state = next(section.content for section in result.sections if section.id == "state")
    slots = state["requiredSlots"]

    assert slots["case_summary"]["canonicalCaseId"] == case["case_id"]
    assert slots["participants"]["state"] == "degraded"
    assert slots["participants"]["participants"][0]["canonicalEntityId"] == ENTITY
    assert slots["participants"]["sourceAuthority"] == "communication360_facts"
    assert slots["participants"]["sourceAuthenticationState"] == "tenant_webhook_hmac_verified"
    assert slots["sla"]["state"] == "degraded"
    assert slots["sla"]["timers"][0]["sourceTimerState"] == "running"
    assert slots["sla"]["breachEvaluation"] == "source_reported_only_no_local_timer_inference"
    assert slots["journey_links"]["links"][0]["canonicalJourneyId"] == journey_id
    assert slots["resolution"]["resolutionState"] == "open"
    assert slots["resolution"]["resolutionOccurred"] is False
    assert slots["risk"]["state"] == "ready"
    assert slots["evidence_trace"]["count"] > 0
    assert any(claim.domainSlotIds == ["participants", "evidence_trace"] for claim in result.claims)


@pytest.mark.asyncio
async def test_sla_ingress_uses_authenticated_actor_and_rejects_payload_principal(monkeypatch):
    from journeys.support360 import routes
    from shared.auth.auth import Role

    captured: dict[str, object] = {}

    class CapturingService:
        async def ingest(self, kind, tenant_id, connection_id, event, **kwargs):
            captured.update(
                kind=kind, tenant_id=tenant_id, connection_id=connection_id, event=event, **kwargs
            )
            return {
                "context_event_id": "context-event-canonical",
                "case_id": event.case_id,
                "context_kind": kind,
                "event_type": event.event_type.value,
                "source_event_id": event.source_event_id,
                "source_observed_at": event.source_observed_at.isoformat(),
                "effective_at": event.effective_at.isoformat(),
                "received_at": NOW.isoformat(),
            }

    monkeypatch.setattr(routes, "SupportCaseContextIngestionService", CapturingService)
    monkeypatch.setattr(
        routes,
        "tenant_actor",
        lambda request: SimpleNamespace(tenant_id=TENANT, actor_id=ACTOR, actor_type="tenant_user"),
    )

    class Tenant:
        tenant_id = TENANT
        user_id = ACTOR
        role = Role.EDITOR

        def require_permission(self, permission):
            assert permission == "write"

    request = SimpleNamespace(state=SimpleNamespace(tenant=Tenant()))
    event = SupportSLAEventInput(
        case_id=str(uuid4()),
        source_sla_id="sla-route-1",
        source_revision_id="sla-route-revision-1",
        source_event_id="sla-route-event-1",
        event_type=SupportSLAEventType.TIMER_STARTED,
        timer_kind=SupportSLATimerKind.FIRST_RESPONSE,
        source_policy_id="policy-first-response",
        source_policy_version="v1",
        source_timer_state="running",
        target_duration_seconds=900,
        source_observed_at=NOW,
        effective_at=NOW,
    )
    body = routes.SupportContextIngestBody(connection_id=CONNECTION, event=event)
    response = await routes.ingest_support_case_sla_event(event.case_id, request, body)
    assert response["data"]["accepted"] is True
    assert captured["tenant_id"] == TENANT
    assert captured["actor_id"] == ACTOR

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        routes.SupportContextIngestBody.model_validate(
            {"connection_id": CONNECTION, "event": event.model_dump(), "actor_id": "forged"}
        )
