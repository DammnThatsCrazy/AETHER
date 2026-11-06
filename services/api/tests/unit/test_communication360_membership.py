"""Authenticated Conversation membership through exact readers and product frames."""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from services.api.tests.unit.test_communication360_composition import (
    NOW,
    TENANT,
    clean_stores,
    project,
    silver_row,
)
from services.api.tests.unit.test_communication360_participant_writer import (
    FakeEntityRepository,
    FakeIdentityResolver,
    _authoring,
    _evidence,
    _roster,
)
from journeys.comms import repository as silver_repository
from journeys.communication360 import repository
from journeys.communication360.contracts import ParticipantRosterAssertion
from journeys.communication360.membership import complete_latest_roster, valid_membership
from journeys.communication360.participant_writer import ParticipantBindingWriter
from journeys.communication360.provider import Communication360Provider, ProfileLinkRead, RiskFlagRead
from graph.operational_intelligence.models import EvidenceRef
from shared.common.common import BadRequestError
from shared.intelligence_projections import ProjectionRequest, ProjectionSubject, ProviderRegistry
from shared.intelligence_projections.contracts import (
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame


pytestmark = pytest.mark.usefixtures("clean_stores")


def roster(**changes):
    data = _roster().model_dump(mode="json", exclude_none=True)
    data.update({
        "conversation_id": "thread-a", "provider_account_id": "account-a",
        "membership": {
            "conversation_id": "canonical-conversation-a", "external_thread_id": "thread-a",
            "evidence_refs": [_evidence("membership-evidence")],
        },
        "context_links": {
            "campaign_id": "campaign-a", "source_id": "source-a",
            "profile_ids": ["canonical-recipient-1"],
            "evidence_refs": [_evidence("context-evidence")],
        },
    })
    data.update(changes)
    return ParticipantRosterAssertion.model_validate(data)


async def write_membership(assertion=None, **changes):
    entities = FakeEntityRepository()
    for row in entities.rows.values():
        row["tenant_id"] = TENANT
    writer = ParticipantBindingWriter(
        facts_repository=repository.Communication360FactsRepository(),
        entity_repository=entities, identity_resolver=FakeIdentityResolver(),
    )
    arguments = {
        "tenant_id": TENANT, "provider": "provider-a", "event_id": "membership-event",
        "event_type": "email_sent", "occurred_at": NOW,
        "roster": assertion or roster(), "authoring_context": _authoring(),
    }
    arguments.update(changes)
    return await writer.write_roster(**arguments)


@pytest.mark.asyncio
async def test_authenticated_membership_roundtrip_and_replay():
    rows = await write_membership()
    assert len(rows) == 4
    membership = next(row for row in rows if row["kind"] == "conversation_membership")
    assert valid_membership(membership, TENANT)
    assert await write_membership() == rows
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    context, complete = await repository.Communication360FactsRepository().conversation_context(
        TENANT, [("provider-a", "account-a", "thread-a")],
    )
    assert complete and len(context) == 5
    _, sections = await project()
    coverage = sections["summary"]["requiredSlotCoverage"]
    assert coverage["thread_summary"]["coverage"] == "complete"
    assert coverage["participants"]["coverage"] == "complete"
    thread = coverage["thread_summary"]["composition"]["threads"][0]
    assert thread["canonicalConversationId"] == "canonical-conversation-a"
    assert thread["membershipFactId"] == membership["fact_id"]
    assert thread["membershipEvidenceRefs"][0]["id"] == "membership-evidence"


@pytest.mark.asyncio
async def test_ids_alone_never_create_canonical_membership():
    await write_membership(roster(membership=None, context_links=None))
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    _, sections = await project()
    coverage = sections["summary"]["requiredSlotCoverage"]
    assert coverage["thread_summary"]["coverage"] != "complete"
    assert coverage["participants"]["coverage"] != "complete"
    assert not any(row["kind"] == "conversation" for row in repository._local_facts.values())


@pytest.mark.asyncio
async def test_conflicting_membership_reassignment_is_atomic():
    await write_membership()
    before = copy.deepcopy(repository._local_facts)
    assertion = roster().model_dump(mode="json")
    assertion["membership"]["conversation_id"] = "other-conversation"
    with pytest.raises(BadRequestError, match="already belongs"):
        await write_membership(ParticipantRosterAssertion.model_validate(assertion), event_id="new-event")
    assert repository._local_facts == before


@pytest.mark.asyncio
@pytest.mark.parametrize("scopes", [
    [("provider-a", "other-account", "thread-a")],
    [("other-provider", "account-a", "thread-a")],
    [("provider-a", "account-a", "thread")],
    [("provider-a", "account-a", " thread-a")],
])
async def test_context_reader_never_crosses_provider_scope(scopes):
    await write_membership()
    rows, _ = await repository.Communication360FactsRepository().conversation_context(TENANT, scopes)
    assert rows == []
    rows, _ = await repository.Communication360FactsRepository().conversation_context(
        "other-tenant", [("provider-a", "account-a", "thread-a")],
    )
    assert rows == []


@pytest.mark.asyncio
async def test_latest_partial_roster_cannot_be_hidden_by_old_complete_snapshot():
    await write_membership()
    partial = roster(completeness_state="partial", expected_binding_count=4)
    await write_membership(partial, event_id="partial-event", occurred_at="2026-11-05T11:00:00Z")
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    _, sections = await project()
    assert sections["summary"]["requiredSlotCoverage"]["participants"]["coverage"] != "complete"


@pytest.mark.asyncio
async def test_equal_time_conflicting_rosters_and_missing_binding_fail_closed():
    rows = await write_membership()
    bindings = [row for row in rows if row["kind"] == "participant_binding"]
    assert not complete_latest_roster({"one": bindings[:1]})
    assert not complete_latest_roster({"one": bindings, "two": copy.deepcopy(bindings)})
    assert not complete_latest_roster({"one": [bindings[0], bindings[0]]})
    assert complete_latest_roster({"one": bindings})


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["future", "event", "event_type", "auth", "actor", "tenant", "evidence", "context"])
async def test_membership_revalidates_persisted_provenance(mutation):
    rows = await write_membership()
    membership = next(row for row in rows if row["kind"] == "conversation_membership")
    payload = membership["payload"]
    if mutation == "future":
        payload["evidence_refs"][0]["observedAt"] = "2099-01-01T00:00:00Z"
    elif mutation == "event":
        payload["source_provenance"]["event_occurred_at"] = "2026-01-01T00:00:00Z"
    elif mutation == "event_type":
        membership["source_event_type"] = "other-event"
    elif mutation == "auth":
        payload["source_provenance"]["authentication"]["verified"] = False
    elif mutation == "actor":
        membership["actor_id"] = "someone-else"
    elif mutation == "tenant":
        payload["tenant_id"] = "other-tenant"
    elif mutation == "context":
        payload["context_link_evidence_refs"][0]["source"] = "other-provider"
    else:
        payload["evidence_refs"][0]["source"] = "other-provider"
    assert not valid_membership(membership, TENANT)
    assert await repository.Communication360FactsRepository().conversation_context(
        TENANT, [("provider-a", "account-a", "thread-a")],
    ) == ([], False)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["auth", "actor", "tenant", "opened_at", "evidence", "event_type"])
async def test_canonical_conversation_revalidates_authored_evidence(mutation):
    rows = await write_membership()
    conversation = next(row for row in rows if row["kind"] == "conversation")
    conversation["payload"] = copy.deepcopy(conversation["payload"])
    payload = conversation["payload"]
    if mutation == "auth":
        payload["source_provenance"]["authentication"]["verified"] = False
    elif mutation == "actor":
        conversation["actor_id"] = "other-actor"
    elif mutation == "tenant":
        payload["tenant_id"] = "other-tenant"
    elif mutation == "opened_at":
        payload["opened_at"] = "2099-01-01T00:00:00Z"
    elif mutation == "event_type":
        conversation["source_event_type"] = "other-event"
    else:
        payload["evidence_refs"][0]["source"] = "other-provider"
    assert await repository.Communication360FactsRepository().conversation_context(
        TENANT, [("provider-a", "account-a", "thread-a")],
    ) == ([], False)


@pytest.mark.asyncio
async def test_bounded_context_truncation_withholds_all_join_evidence():
    await write_membership()
    assert await repository.Communication360FactsRepository().conversation_context(
        TENANT, [("provider-a", "account-a", "thread-a")], limit=2,
    ) == ([], False)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,subject_id", [
    ("message", "original"), ("thread", "canonical-conversation-a"),
])
async def test_exact_message_and_canonical_conversation_routing(kind, subject_id):
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    _, sections = await project(kind, subject_id)
    assert sections["timeline"]["entries"][0]["messageId"] == "original"
    _, wrong = await project(kind, "thread-a" if kind == "thread" else "fact-original")
    assert wrong["timeline"]["entries"] == []


@pytest.mark.asyncio
async def test_campaign_context_producer_routes_message_without_silver_campaign_alias():
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row(campaign_id=None))
    _, sections = await project()
    assert sections["timeline"]["entries"][0]["messageId"] == "original"


@pytest.mark.asyncio
async def test_profile_subject_requires_exact_canonical_identity_not_provider_alias():
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    profiles = AsyncMock()
    profiles.resolve.return_value = ProfileLinkRead(
        state="resolved", profile_id="canonical-recipient-1",
        canonical_entity_id="canonical-recipient-1",
        evidence=(EvidenceRef(id="canonical-recipient-1", type="entity", source="entity_registry"),),
    )
    provider = Communication360Provider(profile_link_reader=profiles)
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind="profile", id="canonical-recipient-1"),
        includeSections=["message_inventory"],
    )
    context = await ProviderRegistry().build_context("communication360", request)
    result = await provider.project(request, context)
    assert result.sections[0].content["messages"][0]["messageId"] == "original"
    assert profiles.resolve.call_args.args == (TENANT, "canonical-recipient-1")
    profiles.resolve.return_value = ProfileLinkRead(
        state="resolved", profile_id="provider-alias", canonical_entity_id="canonical-recipient-1",
    )
    result = await provider.project(request, context)
    assert result.sections[0].content["messages"] == []
    profiles.resolve.reset_mock()
    historical = request.model_copy(update={"asOf": NOW})
    result = await provider.project(historical, context)
    assert result.sections[0].content["messages"] == []
    profiles.resolve.assert_not_called()


@pytest.mark.asyncio
async def test_exact_profile_routes_to_existing_recipient_risk_authority_only_when_requested():
    profiles = AsyncMock()
    profiles.resolve.return_value = ProfileLinkRead(
        state="resolved", profile_id="canonical-recipient-1",
        canonical_entity_id="canonical-recipient-1",
        evidence=(EvidenceRef(id="canonical-recipient-1", type="entity", source="entity_registry"),),
    )
    provider = Communication360Provider(profile_link_reader=profiles)
    provider._read_recipient_risk_flags = AsyncMock(return_value=RiskFlagRead(
        "unknown", "no_recipient_bound_risk_evidence_observed",
    ))
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind="profile", id="canonical-recipient-1"),
        includeSections=["risk_flags"],
    )
    context = await ProviderRegistry().build_context("communication360", request)
    result = await provider.project(request, context)
    assert [section.id for section in result.sections] == ["risk_flags"]
    provider._read_recipient_risk_flags.assert_awaited_once()
    provider._read_recipient_risk_flags.reset_mock()
    await provider.project(request.model_copy(update={"includeSections": ["message_inventory"]}), context)
    provider._read_recipient_risk_flags.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("poison", ["duplicate", "cross_scope", "missing_conversation", "unavailable"])
async def test_provider_revalidates_injected_context_reader(poison):
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    facts = repository.Communication360FactsRepository()
    rows, _ = await facts.conversation_context(TENANT, [("provider-a", "account-a", "thread-a")])
    provider = Communication360Provider()
    if poison == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif poison == "cross_scope":
        rows[0]["tenant_id"] = "other-tenant"
    elif poison == "missing_conversation":
        rows = [row for row in rows if row["kind"] != "conversation"]
    injected = AsyncMock(return_value=(rows, poison != "unavailable"))
    provider._canonical.conversation_context = injected
    _, sections = await project(provider=provider)
    assert sections["summary"]["requiredSlotCoverage"]["thread_summary"]["coverage"] != "complete"
    assert sections["summary"]["requiredSlotCoverage"]["participants"]["coverage"] != "complete"


@pytest.mark.asyncio
async def test_explicit_historical_request_does_not_claim_current_membership_replay():
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind="campaign", id="campaign-a"),
        asOf=NOW, includeSections=["thread_summary", "participants"],
    )
    provider = Communication360Provider()
    result = await provider.project(request, await ProviderRegistry().build_context("communication360", request))
    assert all(section.content["coverage"] != "complete" for section in result.sections)


@pytest.mark.asyncio
async def test_exact_entity_fact_query_is_not_truncated_by_unrelated_tenant_rows():
    await write_membership()
    facts = repository.Communication360FactsRepository()
    for index in range(10):
        await facts.upsert({
            "tenant_id": TENANT, "idempotency_key": f"unrelated-{index}", "kind": "conversation",
            "occurred_at": NOW, "payload": {"entity_id": "unrelated"},
        })
    rows, complete = await facts.facts_for_exact_reference(TENANT, "entity", "canonical-recipient-1", limit=2)
    assert complete and len(rows) == 1 and rows[0]["payload"]["entity_id"] == "canonical-recipient-1"


@pytest.mark.asyncio
async def test_isolated_inventory_does_not_read_sibling_authorities():
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    provider = Communication360Provider()
    for attribute in ("_read_profile_links", "_read_journey_links", "_read_risk_flags", "_read_policy_state"):
        setattr(provider, attribute, AsyncMock(side_effect=AssertionError("denied sibling read")))
    provider._delegations = AsyncMock()
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind="campaign", id="campaign-a"),
        includeSections=["message_inventory"],
    )
    result = await provider.project(request, await ProviderRegistry().build_context("communication360", request))
    assert [section.id for section in result.sections] == ["message_inventory"]
    assert result.sections[0].content["messages"][0]["messageId"] == "original"
    assert all(set(claim.domainSlotIds) <= {"message_inventory"} for claim in result.claims)
    provider._delegations.find_many.assert_not_called()


@pytest.mark.asyncio
async def test_context_producer_exposes_isolated_campaign_and_resolved_journey_links():
    journey_id = "dc4a5d5c-6b11-4ce3-b318-9a493a8ba001"
    version_id = "dc4a5d5c-6b11-4ce3-b318-9a493a8ba002"
    assertion = roster()
    assertion.context_links.journey_ids = [journey_id]
    await write_membership(assertion)
    await silver_repository.CommsFactsRepository().upsert(silver_row(campaign_id=None))
    reader = AsyncMock()
    reader.get_current.return_value = {
        "tenant_id": TENANT, "journey_id": journey_id,
        "journey_version_id": version_id, "is_current": True, "computed_at": NOW,
        "private_notes": "never expose",
    }
    provider = Communication360Provider(journey_reader=reader)
    provider._read_profile_links = AsyncMock(side_effect=AssertionError("denied profile read"))
    provider._read_risk_flags = AsyncMock(side_effect=AssertionError("denied risk read"))
    provider._read_policy_state = AsyncMock(side_effect=AssertionError("denied policy read"))
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind="thread", id="canonical-conversation-a"),
        includeSections=["campaign_links", "journey_links"],
    )
    result = await provider.project(request, await ProviderRegistry().build_context("communication360", request))
    sections = {section.id: section.content for section in result.sections}
    assert set(sections) == {"campaign_links", "journey_links"}
    assert sections["campaign_links"]["links"][0]["campaignId"] == "campaign-a"
    journey_link = sections["journey_links"]["links"][0]
    assert journey_link["journeyId"] == journey_id
    assert journey_link["currentVersionEvidenceRef"]["id"] == version_id
    assert journey_link["relationshipState"] == "explicit_reference_resolved"
    reader.get_current.assert_awaited_once_with(TENANT, journey_id)
    assert "never expose" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_real_registry_frame_membership_and_denied_sibling_isolation():
    await write_membership()
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    provider = Communication360Provider()
    provider._read_risk_flags = AsyncMock(side_effect=AssertionError("denied risk read"))
    provider._read_profile_links = AsyncMock(side_effect=AssertionError("denied profile read"))

    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="communications360", tenantId=TENANT, evaluatedAt=NOW,
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "thread_summary": Experience360PolicyDisposition(state="allowed"),
                    "risk_flags": Experience360PolicyDisposition(state="denied"),
                    "profile_links": Experience360PolicyDisposition(state="denied"),
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            return await provider.project(
                request, await ProviderRegistry().build_context("communication360", request),
            )

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="communications360", tenantId=TENANT,
            subject=ProjectionSubject(kind="campaign", id="campaign-a"),
            requestedSlotIds=["thread_summary", "risk_flags", "profile_links"], includeEvidence=True,
        ), policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    thread_slot = next(slot for slot in frame.slots if slot.id == "thread_summary")
    assert "canonical-conversation-a" in str(thread_slot.content)
    for slot in frame.slots:
        if slot.id in {"risk_flags", "profile_links"}:
            assert slot.state == "suppressed" and not slot.content and not slot.evidenceRefs


@pytest.mark.parametrize("field,value", [
    ("conversation_id", " thread-a"), ("provider_account_id", "account-a "),
])
def test_padded_provider_scope_is_not_an_alias(field, value):
    with pytest.raises(ValidationError):
        roster(**{field: value})


@pytest.mark.asyncio
async def test_postgres_membership_batch_rolls_back_as_one_transaction(monkeypatch):
    rows = await write_membership()
    conversation = next(row for row in rows if row["kind"] == "conversation")
    membership = next(row for row in rows if row["kind"] == "conversation_membership")
    bindings = [row for row in rows if row["kind"] == "participant_binding"]
    operations = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            operations.append("begin")
            try:
                yield
            except RuntimeError:
                operations.append("rollback")
                raise

        async def fetchrow(self, sql, *parameters):
            assert parameters == (TENANT, membership["idempotency_key"])
            return None

        async def execute(self, sql, *parameters):
            if "pg_advisory_xact_lock" in sql:
                operations.append("lock")
            else:
                operations.append("insert")
                if len(operations) == 5:
                    raise RuntimeError("write failed")

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    facts = repository.Communication360FactsRepository()
    monkeypatch.setattr(facts, "_pool", AsyncMock(return_value=Pool()))
    with pytest.raises(RuntimeError, match="write failed"):
        await facts.upsert_membership_roster(conversation, membership, bindings)
    assert operations == ["begin", "lock", "insert", "insert", "insert", "rollback"]


@pytest.mark.asyncio
async def test_postgres_membership_replay_returns_persisted_first_write(monkeypatch):
    stored = copy.deepcopy(await write_membership())
    for row in stored:
        row["occurred_at"] = datetime.fromisoformat(row["occurred_at"])
        row["received_at"] = datetime.fromisoformat(row["received_at"])
    membership = next(row for row in stored if row["kind"] == "conversation_membership")
    conversation = next(row for row in stored if row["kind"] == "conversation")
    bindings = [row for row in stored if row["kind"] == "participant_binding"]
    assert valid_membership(membership, TENANT)
    replacement = copy.deepcopy(membership)
    replacement["payload"]["evidence_refs"][0]["id"] = "replacement-not-persisted"

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            yield

        async def execute(self, sql, *parameters):
            pass

        async def fetchrow(self, sql, *parameters):
            return membership

        async def fetch(self, sql, *parameters):
            assert parameters == (TENANT, [row["idempotency_key"] for row in stored])
            return stored

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    facts = repository.Communication360FactsRepository()
    monkeypatch.setattr(facts, "_pool", AsyncMock(return_value=Pool()))
    result = await facts.upsert_membership_roster(conversation, replacement, bindings)
    assert result == stored
    assert next(row for row in result if row["kind"] == "conversation_membership")[
        "payload"
    ]["evidence_refs"][0]["id"] == "membership-evidence"


@pytest.mark.asyncio
async def test_postgres_exact_context_predicates_and_datetime_rows(monkeypatch):
    stored = copy.deepcopy(await write_membership())
    for row in stored:
        row["occurred_at"] = datetime.fromisoformat(row["occurred_at"])
        row["received_at"] = datetime.fromisoformat(row["received_at"])
    statements = []

    class Connection:
        async def fetch(self, sql, *parameters):
            statements.append((sql, parameters))
            assert parameters[0] == TENANT
            if "jsonb_to_recordset" in sql:
                assert "provider_account_id" in sql and "provider_conversation_id" in sql
                assert "thread-a" in parameters[1]
                return [row for row in stored if row["kind"] != "conversation"]
            assert "payload->>'conversation_id' = ANY" in sql
            assert parameters[1] == ["canonical-conversation-a"]
            return [row for row in stored if row["kind"] == "conversation"]

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    facts = repository.Communication360FactsRepository()
    monkeypatch.setattr(facts, "_pool", AsyncMock(return_value=Pool()))
    rows, complete = await facts.conversation_context(TENANT, [("provider-a", "account-a", "thread-a")])
    assert complete and len(rows) == 4 and len(statements) == 2


@pytest.mark.asyncio
async def test_signed_webhook_carries_explicit_membership_to_durable_writer(monkeypatch):
    import json

    from services.api.tests.unit.test_communication360_participant_writer import _WebhookRequest
    from governance.security.integration_security import sign_payload
    from journeys.comms.routes import CommsWebhookBody, generic_comms_webhook
    from journeys.communication360.participant_writer import ParticipantBindingAuthoringContext

    body = CommsWebhookBody(provider="provider-a", events=[{
        "event_type": "email_sent", "occurred_at": NOW, "external_id": "signed-event",
        "properties": {"provider_account_id": "account-a"},
        "participant_roster": roster().model_dump(mode="json", exclude_none=True),
    }])
    raw = json.dumps(body.model_dump(mode="json", exclude_none=True)).encode()
    request = _WebhookRequest(raw, sign_payload("whsec-test", raw))
    request.state.tenant.tenant_id = TENANT
    entities = FakeEntityRepository()
    for row in entities.rows.values():
        row["tenant_id"] = TENANT
    writer = ParticipantBindingWriter(
        facts_repository=repository.Communication360FactsRepository(),
        entity_repository=entities, identity_resolver=FakeIdentityResolver(),
    )

    async def ingest(tenant_id, events, *args, **kwargs):
        event = events[0]
        await writer.write_roster(
            tenant_id=tenant_id, provider="provider-a", event_id=event["external_id"],
            event_type=event["event_type"], occurred_at=event["occurred_at"],
            roster=event["participant_roster"],
            authoring_context=ParticipantBindingAuthoringContext(**event["participant_roster_authoring"]),
        )
        return {"communications": 1}

    monkeypatch.setattr("journeys.comms.ingest.ingest_normalized_events", ingest)
    await generic_comms_webhook(request, body)
    rows, complete = await repository.Communication360FactsRepository().conversation_context(
        TENANT, [("provider-a", "account-a", "thread-a")],
    )
    assert complete and len(rows) == 4
    assert all(row["source_event_id"] == "signed-event" for row in rows)
    assert all(row["actor_id"] == "user-author-1" for row in rows)
