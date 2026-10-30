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
    SupportCaseContextRead,
    SupportCaseContextRepository,
    SupportJourneyLinkEventInput,
    SupportJourneyLinkEventType,
    SupportSLAEventInput,
    SupportSLAEventType,
    SupportSLATimerKind,
    reset_local_support_case_context_store,
)
from journeys.support360.provider import (  # noqa: E402
    Support360Provider,
    SupportFactsRead,
    _validated_case_journey_episodes,
)
from journeys.support360.sla_measurement import (  # noqa: E402
    SupportSLAMeasurementContract,
    SupportSLAMeasurementContractError,
    SupportSLAMeasurementContractRepository,
    SupportSLAMeasurementContractService,
    reset_local_support_sla_contract_store,
)
from graph.operational_intelligence.models import EntityRef, EvidenceRef, TimeRangeFilter  # noqa: E402
from shared.backend_interpretation.primitives import EpisodeRecord  # noqa: E402
from shared.backend_interpretation.stores import EpisodePageRead  # noqa: E402
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
    reset_local_support_sla_contract_store()
    yield
    reset_local_support_case_store()
    reset_local_support_case_context_store()
    reset_local_support_sla_contract_store()


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


def _contract(case_id: str, *, target: int = 1800) -> SupportSLAMeasurementContract:
    return SupportSLAMeasurementContract(
        tenant_id=TENANT,
        case_id=case_id,
        source_connection_id=CONNECTION,
        source_provider_identity=PROVIDER,
        source_sla_id="source-sla-1",
        source_policy_id="response-policy",
        source_policy_version="v2",
        timer_kind="first_response",
        target_duration_seconds=target,
        registered_by=ACTOR,
        registered_at=NOW,
    )


@pytest.mark.asyncio
async def test_registered_sla_contract_is_immutable_and_case_provider_scoped():
    cases, case = await _case()
    repository = SupportSLAMeasurementContractRepository()
    service = SupportSLAMeasurementContractService(
        repository=repository, cases=cases, connections=FakeConnections()
    )
    contract = _contract(case["case_id"])
    assert (await service.register(contract)).contract_id == contract.contract_id
    assert (await service.register(contract)).contract_id == contract.contract_id
    replay = contract.model_copy(update={"registered_at": datetime.now(timezone.utc), "registered_by": "another-admin"})
    stored = await service.register(replay)
    assert stored.registered_at == contract.registered_at
    assert stored.registered_by == contract.registered_by
    read = await repository.read_for_case(TENANT, case["case_id"], CONNECTION)
    assert read.available and read.complete and len(read.rows) == 1
    assert read.rows[0]["target_duration_seconds"] == 1800
    with pytest.raises(SupportSLAMeasurementContractError, match="immutable"):
        await service.register(_contract(case["case_id"], target=1200))
    with pytest.raises(SupportSLAMeasurementContractError, match="exact tenant case"):
        await service.register(_contract(str(uuid4())))
    assert not (await repository.read_for_case("foreign-tenant", case["case_id"], CONNECTION)).rows


@pytest.mark.asyncio
async def test_sla_contract_target_conflict_does_not_bind_source_timer():
    cases, case = await _case()
    context_repository = SupportCaseContextRepository()
    await SupportCaseContextIngestionService(
        repository=context_repository, cases=cases, connections=FakeConnections()
    ).ingest(
        "sla", TENANT, CONNECTION,
        SupportSLAEventInput(
            case_id=case["case_id"], source_sla_id="source-sla-1",
            source_revision_id="sla-rev-1", source_event_id="sla-target-conflict",
            event_type=SupportSLAEventType.TIMER_STARTED,
            timer_kind=SupportSLATimerKind.FIRST_RESPONSE,
            source_policy_id="response-policy", source_policy_version="v2",
            source_timer_state="running", target_duration_seconds=1800,
            source_observed_at=NOW, effective_at=NOW,
        ), actor_id=ACTOR, actor_type="tenant_user",
    )
    contracts = SupportSLAMeasurementContractRepository()
    await SupportSLAMeasurementContractService(
        repository=contracts, cases=cases, connections=FakeConnections()
    ).register(_contract(case["case_id"], target=1200))
    request = ProjectionRequest(
        projectionId="support360", tenantId=TENANT,
        subject=ProjectionSubject(kind="support_case", id=case["case_id"]),
    )
    context = ProjectionContext(
        projectionId="support360", tenantId=TENANT,
        registryState="in_flight", dependencyState=[], warnings=[],
    )
    result = await Support360Provider(
        EmptyCaseFactsSource(), case_repository=cases,
        case_context_repository=context_repository, sla_measurement_repository=contracts,
    ).project(request, context)
    state = next(section.content for section in result.sections if section.id == "state")
    sla = state["requiredSlots"]["sla"]
    assert sla["policyAuthority"] == "source_reported_not_joined_to_measurement_contract"
    assert sla["measurementContractJoin"]["boundTimerCount"] == 0
    assert sla["measurementContractJoin"]["reasonCode"] == (
        "support_sla_source_target_conflicts_with_registered_contract"
    )
    assert "measurementContract" not in sla["timers"][0]


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
    sla_contract_repository = SupportSLAMeasurementContractRepository()
    registered_contract = await SupportSLAMeasurementContractService(
        repository=sla_contract_repository, cases=cases, connections=FakeConnections()
    ).register(_contract(case["case_id"]))
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
            target_duration_seconds=1800,
            due_at=NOW + timedelta(minutes=30),
            source_observed_at=NOW,
            effective_at=NOW,
        ),
        actor_id=ACTOR,
        actor_type="tenant_user",
    )
    link = await service.ingest(
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
    context_ref = next(
        EvidenceRef.model_validate(ref)
        for ref in link["evidence_refs"]
        if ref["source"] == "support_case_context_events"
    )
    episode = EpisodeRecord(
        episode_id="support-episode-exact-1",
        tenant_id=TENANT,
        subject=EntityRef(kind="user", id=ENTITY),
        kind="support",
        journey_id=journey_id,
        evidence_refs=[context_ref],
    )

    class ExactEpisodeStore:
        async def list_page_by_tenant(self, tenant_id, *, limit):
            assert (tenant_id, limit) == (TENANT, 100)
            return EpisodePageRead(records=(episode,), next_cursor=None, truncated=False)

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
    provider = Support360Provider(
        EmptyCaseFactsSource(),
        case_repository=cases,
        case_context_repository=context_repo,
        sla_measurement_repository=sla_contract_repository,
        canonical_agent_entity_repository=entities,
        canonical_journey_repository=journeys,
        canonical_episode_store=ExactEpisodeStore(),
        risk_projection_registry=RiskRegistry(),
    )
    result = await provider.project(request, context)
    state = next(section.content for section in result.sections if section.id == "state")
    slots = state["requiredSlots"]

    assert slots["case_summary"]["canonicalCaseId"] == case["case_id"]
    assert slots["participants"]["state"] == "degraded"
    assert slots["participants"]["participants"][0]["canonicalEntityId"] == ENTITY
    assert slots["participants"]["sourceAuthority"] == "communication360_facts"
    assert slots["participants"]["sourceAuthenticationState"] == "tenant_webhook_hmac_verified"
    assert slots["sla"]["state"] == "degraded"
    assert slots["sla"]["timers"][0]["sourceTimerState"] == "running"
    assert slots["sla"]["timers"][0]["measurementContract"]["contractId"] == registered_contract.contract_id
    assert slots["sla"]["measurementContractJoin"]["boundTimerCount"] == 1
    assert slots["sla"]["policyAuthority"] == "tenant_registered_source_policy_revision_partial"
    assert any(ref.id == registered_contract.contract_id for ref in slots["sla"]["evidenceRefs"])
    assert slots["sla"]["breachEvaluation"] == "source_reported_only_no_local_timer_inference"
    assert slots["journey_links"]["links"][0]["canonicalJourneyId"] == journey_id
    episode_facts = slots["journey_links"]["episodeFacts"]
    assert episode_facts["state"] == "degraded"
    assert episode_facts["populationComplete"] is False
    assert episode_facts["policy"]["state"] == "unknown"
    assert episode_facts["freshness"]["state"] == "unknown"
    assert episode_facts["relations"][0]["canonicalEpisodeId"] == episode.episode_id
    assert episode_facts["relations"][0]["contextEventId"] == link["context_event_id"]
    assert state["journeyLinkage"]["episodeFacts"] == episode_facts
    assert "episode_facts" in next(
        section.canonicalAuthorityRefs for section in result.sections if section.id == "state"
    )
    assert "episode_facts" in next(
        section.canonicalAuthorityRefs for section in result.sections if section.id == "evidence"
    )
    assert any(
        claim.kind == "support_case_episode_journey_observation"
        and claim.evidenceRefs[0].id == episode.episode_id
        for claim in result.claims
    )
    assert slots["resolution"]["resolutionState"] == "open"
    assert slots["resolution"]["resolutionOccurred"] is False
    assert slots["risk"]["state"] == "ready"
    assert slots["evidence_trace"]["count"] > 0
    assert any(claim.domainSlotIds == ["participants", "evidence_trace"] for claim in result.claims)

    windowed_request = request.model_copy(
        update={
            "timeRange": TimeRangeFilter(
                from_="2026-10-24T15:00:00Z", to="2026-10-24T17:00:00Z"
            ),
            "temporalMode": "window",
        }
    )
    windowed_result = await provider.project(windowed_request, context)
    windowed_state = next(section for section in windowed_result.sections if section.id == "state")
    assert windowed_state.content["requiredSlots"]["journey_links"]["episodeFacts"]["state"] == "unknown"
    assert "episode_facts" not in windowed_state.canonicalAuthorityRefs
    assert not any(
        claim.kind == "support_case_episode_journey_observation"
        for claim in windowed_result.claims
    )

    class TruncatedContextRepository:
        async def list_for_case(self, *args, **kwargs):
            read = await context_repo.list_for_case(*args, **kwargs)
            if kwargs.get("kind") == "journey_links":
                return SupportCaseContextRead(read.events, True, False, True)
            return read

    class EpisodeStoreMustNotRead:
        async def list_page_by_tenant(self, *args, **kwargs):
            raise AssertionError("a partial link ledger cannot prove the current relation")

    partial_result = await Support360Provider(
        EmptyCaseFactsSource(),
        case_repository=cases,
        case_context_repository=TruncatedContextRepository(),
        canonical_agent_entity_repository=entities,
        canonical_journey_repository=journeys,
        canonical_episode_store=EpisodeStoreMustNotRead(),
        risk_projection_registry=RiskRegistry(),
    ).project(request, context)
    partial_state = next(section for section in partial_result.sections if section.id == "state")
    assert partial_state.content["requiredSlots"]["journey_links"]["episodeFacts"] == {
        "state": "unknown",
        "reasonCode": "support_case_context_read_truncated",
        "relations": None,
    }
    assert "episode_facts" not in partial_state.canonicalAuthorityRefs


@pytest.mark.asyncio
async def test_support_case_episode_join_rejects_shared_journey_without_exact_event_evidence():
    journey_id = str(uuid4())
    event_id = "verified-case-journey-link-event"
    context_ref = EvidenceRef(
        id=event_id,
        type="event",
        source="support_case_context_events",
        uri=f"store://support_case_context_events/{event_id}",
        observedAt=NOW.isoformat(),
    )
    link = {
        "canonicalJourneyId": journey_id,
        "contextEventId": event_id,
        "evidenceRefs": [context_ref],
    }

    def episode(episode_id, *, tenant_id=TENANT, linked_journey=journey_id, ref=None):
        return EpisodeRecord(
            episode_id=episode_id,
            tenant_id=tenant_id,
            subject=EntityRef(kind="user", id=ENTITY),
            kind="support",
            journey_id=linked_journey,
            evidence_refs=[ref] if ref is not None else [],
        )

    class IncompleteEpisodeStore:
        calls = 0

        async def list_page_by_tenant(self, tenant_id, *, limit):
            self.calls += 1
            assert (tenant_id, limit) == (TENANT, 100)
            return EpisodePageRead(
                records=(
                    episode("shared-journey-only"),
                    episode("wrong-tenant", tenant_id="tenant-other", ref=context_ref),
                    episode("wrong-journey", linked_journey=str(uuid4()), ref=context_ref),
                    episode("wrong-source", ref=context_ref.model_copy(update={"source": "other"})),
                    episode("other-case-event", ref=context_ref.model_copy(update={"id": "other-case-event"})),
                    episode("wrong-uri", ref=context_ref.model_copy(update={"uri": "store://other"})),
                    episode("wrong-time", ref=context_ref.model_copy(update={"observedAt": "2026-10-23T16:00:00Z"})),
                ),
                next_cursor="next-page",
                truncated=True,
            )

    store = IncompleteEpisodeStore()
    slot, refs, reasons = await _validated_case_journey_episodes(
        tenant_id=TENANT,
        links=[link],
        episode_store=store,
        windowed=False,
    )
    assert slot["state"] == "unknown"
    assert slot["relations"] == []
    assert refs == []
    assert "support_case_journey_episode_exact_relation_unavailable" in reasons
    assert "support_case_journey_episode_read_truncated" in reasons

    windowed, refs, reasons = await _validated_case_journey_episodes(
        tenant_id=TENANT,
        links=[link],
        episode_store=store,
        windowed=True,
    )
    assert windowed["state"] == "unknown"
    assert windowed["relations"] is None
    assert reasons == ["support_case_journey_episode_window_read_unavailable"]
    assert refs == []
    assert store.calls == 1


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
