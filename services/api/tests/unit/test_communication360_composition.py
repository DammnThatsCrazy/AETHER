"""Durable Silver-to-Communication360 composition and negative-scope proofs."""

from __future__ import annotations

import copy
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from ingestion.silver.writer import SilverFactWriter  # noqa: E402
from journeys.comms import repository as silver_repository  # noqa: E402
from journeys.comms.projector import CommsProjector  # noqa: E402
from journeys.communication360 import reader, repository  # noqa: E402
from journeys.communication360.composition import compose_threads, read_reply_target  # noqa: E402
from journeys.communication360.observations import provider_thread_observation  # noqa: E402
from journeys.communication360.provider import Communication360Provider  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionRequest, ProjectionSubject, ProviderRegistry,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame  # noqa: E402


TENANT = "composition-tenant"
NOW = "2026-11-05T10:00:00+00:00"


def silver_row(**overrides):
    row = {
        "fact_id": "fact-original", "tenant_id": TENANT,
        "idempotency_key": "original-event", "message_id": "original",
        "provider": "provider-a", "provider_account_id": "account-a",
        "external_thread_id": "thread-a", "external_message_id": "original",
        "source_connector_id": "source-a", "occurred_at": NOW,
        "received_at": NOW, "campaign_id": "campaign-a",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def clean_stores(monkeypatch):
    async def no_pool():
        return None

    for module in (silver_repository, repository, reader):
        monkeypatch.setattr(module, "get_pool", no_pool)
    silver_repository.reset_local_stores()
    repository.reset_local_stores()
    yield
    silver_repository.reset_local_stores()
    repository.reset_local_stores()


async def project(kind="campaign", subject_id="campaign-a", provider=None):
    request = ProjectionRequest(
        projectionId="communication360", tenantId=TENANT,
        subject=ProjectionSubject(kind=kind, id=subject_id),
    )
    context = await ProviderRegistry().build_context("communication360", request)
    result = await (provider or Communication360Provider()).project(request, context)
    return result, {section.id: section.content for section in result.sections}


@pytest.mark.asyncio
async def test_silver_writer_to_thread_inventory_and_response_without_synthetic_act():
    projected = CommsProjector().project({
        "id": "reply-event", "messageId": "reply-event", "tenantId": TENANT,
        "type": "email_replied", "timestamp": "2026-11-05T11:00:00+00:00",
        "properties": {
            "provider": "provider-a", "provider_account_id": "account-a",
            "external_thread_id": "thread-a", "external_message_id": "reply",
            "reply_to_external_message_id": "original",
            "reply_correlation_method": "in_reply_to", "source_connector_id": "source-a",
        },
    })
    assert projected is not None and projected.rows
    projected.rows[0]["campaign_id"] = "campaign-a"
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    assert await SilverFactWriter().persist([projected]) == 1
    facts = await repository.Communication360FactsRepository().query(TENANT)
    assert {fact["kind"] for fact in facts} == {"provider_thread"}
    assert len({fact["payload"]["thread_id"] for fact in facts}) == 1
    result, sections = await project()
    coverage = sections["summary"]["requiredSlotCoverage"]
    composition = coverage["thread_summary"]["composition"]
    assert composition["threads"][0]["messageIds"] == ["original", "reply"]
    assert composition["historyCompleteness"] == "unknown"
    assert composition["canonicalConversationMembership"] == "unknown"
    links = sections["interactions"]["responseEventLinks"]
    assert len(links) == 1
    assert links[0]["responseToMessageId"] == "original"
    assert links[0]["state"] == "observed"
    assert links[0]["causalStatus"] == "unverified"
    assert coverage["response_events"]["state"] == "degraded"
    assert any(claim.kind == "provider_reported_reply_association" for claim in result.claims)
    _, source_sections = await project("source", "source-a")
    assert {entry["messageId"] for entry in source_sections["timeline"]["entries"]} == {
        "original", "reply",
    }
    assert source_sections["summary"]["requiredSlotCoverage"]["message_inventory"]["coverage"] == "complete"


@pytest.mark.asyncio
async def test_observation_replay_uses_persisted_first_write_not_replacement_claims():
    repo = silver_repository.CommsFactsRepository()
    await repo.upsert(silver_row())
    await repo.upsert(silver_row(provider_account_id="forged", source_connector_id="forged"))
    facts = await repository.Communication360FactsRepository().query(TENANT)
    assert len(facts) == 1
    assert facts[0]["payload"]["provider_account_id"] == "account-a"
    assert facts[0]["payload"]["source_id"] == "source-a"
    _, sections = await project("source", "forged")
    assert not sections["timeline"]["entries"]


@pytest.mark.asyncio
async def test_source_query_filters_before_limit_without_claiming_upstream_coverage():
    repo = repository.Communication360FactsRepository()
    for index in range(105):
        await repo.upsert({
            "tenant_id": TENANT, "idempotency_key": f"unrelated-{index}",
            "kind": "provider_thread", "occurred_at": NOW,
            "payload": {"source_id": "other"},
        })
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    _, sections = await project("source", "source-a")
    assert [entry["messageId"] for entry in sections["timeline"]["entries"]] == ["original"]
    assert sections["summary"]["requiredSlotCoverage"]["thread_summary"]["composition"]["historyCompleteness"] == "unknown"


@pytest.mark.parametrize("field", [
    "tenant_id", "fact_id", "message_id", "provider", "provider_account_id",
    "external_thread_id", "external_message_id", "occurred_at",
])
def test_thread_producer_requires_exact_scope(field):
    assert provider_thread_observation(silver_row(**{field: None})) is None


def test_thread_producer_handles_postgres_uuid_and_timestamp_types():
    fact_id = uuid4()
    observation = provider_thread_observation(silver_row(
        fact_id=fact_id, occurred_at=datetime(2026, 11, 5, 10, tzinfo=timezone.utc),
        received_at=datetime(2026, 11, 5, 10, tzinfo=timezone.utc),
    ))
    assert observation["payload"]["silver_fact_id"] == str(fact_id)
    assert observation["occurred_at"] == NOW


@pytest.mark.parametrize("field", ["provider", "provider_account_id", "external_thread_id"])
def test_threads_never_merge_equal_ids_across_namespaces(field):
    original = reader.to_message(silver_row())
    other = reader.to_message(silver_row(**{field: "other", "message_id": "other"}))
    composed = compose_threads(TENANT, [other, original], truncated=False)
    assert len(composed["threads"]) == 2
    assert all(len(thread["messageIds"]) == 1 for thread in composed["threads"])


@pytest.mark.parametrize("case", [
    "cross_tenant", "cross_provider", "cross_account", "cross_thread", "future",
    "duplicate", "truncated", "bad_complete", "mixed", "invalid", "no_evidence", "naive",
])
@pytest.mark.asyncio
async def test_direct_durable_reply_target_fails_closed(case):
    target = reader.to_message(silver_row())
    reply = reader.to_message(silver_row(
        fact_id="reply-fact", message_id="reply", external_message_id="reply",
        occurred_at="2026-11-05T11:00:00+00:00",
        payload={"reply_to_external_message_id": "original", "reply_correlation_method": "in_reply_to"},
    ))
    modifications = {
        "cross_tenant": {"tenant_id": "other"}, "cross_provider": {"provider": "other"},
        "cross_account": {"provider_account_id": "other"},
        "cross_thread": {"external_thread_id": "other"},
        "future": {"occurred_at": "2026-11-05T12:00:00+00:00"},
        "no_evidence": {"evidence_refs": []}, "naive": {"occurred_at": "2026-11-05T10:00:00"},
    }
    target = target.model_copy(update=modifications.get(case, {}))
    candidates = [target, target] if case == "duplicate" else [target]
    if case == "mixed":
        candidates.append(target.model_copy(update={"tenant_id": "other"}))
    if case == "invalid":
        candidates = None
    complete = False if case == "truncated" else "true" if case == "bad_complete" else True
    source = AsyncMock()
    source.reply_targets.return_value = (candidates, complete)
    resolved, reason = await read_reply_target(reply, source)
    assert resolved is None
    assert reason != "exact_provider_reply_target_joined"


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "other"), ("provider", "other"), ("provider_account_id", "other"),
    ("external_thread_id", "other"), ("silver_fact_id", "other"),
    ("external_message_id", "other"), ("message_occurred_at", "2026-11-05T12:00:00Z"),
    ("message_ids", ["other"]),
])
@pytest.mark.asyncio
async def test_linked_source_inventory_rejects_mismatched_canonical_evidence(field, value):
    message = reader.to_message(silver_row())
    observation = provider_thread_observation(silver_row())
    observation["payload"][field] = value
    source = AsyncMock()
    source.messages_by_ids.return_value = ([message], True)
    provider = Communication360Provider(sources={"silver": source, "canonical": AsyncMock()})
    up, messages, truncated = await provider._read_linked_messages(TENANT, [observation], limit=100)
    assert up and truncated and messages == []


@pytest.mark.asyncio
async def test_source_reader_outage_is_not_an_available_empty():
    source = reader.SilverCommsSource()
    source._rows = AsyncMock(side_effect=RuntimeError("offline"))
    with pytest.raises(RuntimeError, match="offline"):
        await source.messages(TENANT)


@pytest.mark.parametrize("case", ["missing", "duplicate", "truncated", "bad_complete", "unavailable"])
@pytest.mark.asyncio
async def test_linked_inventory_withholds_incomplete_or_ambiguous_reads(case):
    message = reader.to_message(silver_row())
    observation = provider_thread_observation(silver_row())
    source = AsyncMock()
    messages = [] if case == "missing" else [message, message] if case == "duplicate" else [message]
    complete = False if case == "truncated" else "true" if case == "bad_complete" else True
    source.messages_by_ids.return_value = (messages, complete)
    if case == "unavailable":
        source.messages_by_ids.side_effect = RuntimeError("offline")
    provider = Communication360Provider(sources={"silver": source, "canonical": AsyncMock()})
    up, result, truncated = await provider._read_linked_messages(TENANT, [observation], limit=100)
    assert result == []
    assert (up, truncated) == ((False, False) if case == "unavailable" else (True, True))


@pytest.mark.asyncio
async def test_source_reference_list_remains_exact_and_scoped():
    await silver_repository.CommsFactsRepository().upsert(silver_row())
    observation = next(iter(repository._local_facts.values()))
    observation["payload"]["source_ids"] = [observation["payload"].pop("source_id")]
    _, sections = await project("source", "source-a")
    assert [entry["messageId"] for entry in sections["timeline"]["entries"]] == ["original"]
    _, other_sections = await project("source", "source")
    assert other_sections["timeline"]["entries"] == []


@pytest.mark.asyncio
async def test_source_inventory_survives_real_registry_frame_composition():
    await silver_repository.CommsFactsRepository().upsert(silver_row())

    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="communications360", tenantId=TENANT, evaluatedAt=NOW,
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={"message_inventory": Experience360PolicyDisposition(state="allowed")},
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            assert request.subject.kind == "source"
            context = await ProviderRegistry().build_context("communication360", request)
            return await Communication360Provider().project(request, context)

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="communications360", tenantId=TENANT,
            subject=ProjectionSubject(kind="source", id="source-a"),
            requestedSlotIds=["message_inventory"], includeEvidence=True,
        ),
        policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    inventory = next(slot for slot in frame.slots if slot.id == "message_inventory")
    assert inventory.state in {"available", "degraded"}
    assert inventory.evidenceRefs
    timeline = next(section["content"] for section in inventory.content["sections"] if section["sectionId"] == "timeline")
    assert [entry["messageId"] for entry in timeline["entries"]] == ["original"]


@pytest.mark.asyncio
async def test_local_observation_failure_does_not_commit_silver(monkeypatch):
    monkeypatch.setattr(
        repository.Communication360FactsRepository, "upsert_many",
        AsyncMock(side_effect=RuntimeError("canonical unavailable")),
    )
    with pytest.raises(RuntimeError, match="canonical unavailable"):
        await silver_repository.CommsFactsRepository().upsert(silver_row())
    assert silver_repository._local_facts == {}
    canonical = reader.CanonicalFactSource(AsyncMock())
    canonical._repo.query.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        await canonical.facts(TENANT)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_observation", [False, True])
async def test_postgres_observation_and_silver_share_transaction(monkeypatch, fail_observation):
    saved = silver_row()
    operations = []

    class Connection:
        @asynccontextmanager
        async def transaction(self):
            operations.append("begin")
            try:
                yield
            except Exception:
                operations.append("rollback")
                raise
            else:
                operations.append("commit")

        async def execute(self, sql, *params):
            if "INSERT INTO communication360_facts" in sql:
                operations.append("canonical")
                if fail_observation:
                    raise RuntimeError("canonical unavailable")
            elif "INSERT INTO silver_comms_facts" in sql:
                operations.append("silver")

        async def fetchrow(self, sql, *params):
            assert params == (TENANT, "original-event")
            return copy.deepcopy(saved)

    class Pool:
        @asynccontextmanager
        async def acquire(self):
            yield Connection()

    repo = silver_repository.CommsFactsRepository()
    monkeypatch.setattr(repo, "_pool", AsyncMock(return_value=Pool()))
    if fail_observation:
        with pytest.raises(RuntimeError, match="canonical unavailable"):
            await repo.upsert(silver_row(provider_account_id="forged"))
        assert operations == ["begin", "silver", "canonical", "rollback"]
    else:
        result = await repo.upsert(silver_row(provider_account_id="forged"))
        assert result["provider_account_id"] == "account-a"
        assert operations == ["begin", "silver", "canonical", "commit"]
