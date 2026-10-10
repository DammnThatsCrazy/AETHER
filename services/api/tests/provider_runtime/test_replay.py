"""Bounded provider raw replay over durable jobs, Bronze and canonical outbox."""

from __future__ import annotations

from contextlib import asynccontextmanager

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from config.settings import Environment, settings
from repositories.lake import BronzeRepository
from repositories import repos
from repositories.jobs_repo import get_jobs_repository, reset_jobs_memory
from shared.integration_contracts.events import make_aether_event, make_raw_record
from shared.integration_contracts.normalization import NormalizationResult
from workers.jobs.bootstrap import register_durable_job_handlers
from workers.jobs.handlers import HANDLER_REGISTRY, TENANT_INVOCABLE, unregister_handler
from workers.jobs.service import get_jobs_service
from workers.jobs.worker import JobWorker
from connectors.provider_runtime import replay as replay_mod
from connectors.provider_runtime.bridge import EventBridge
from connectors.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
from connectors.provider_runtime.raw_store import (
    ProviderRawRecordQuarantined,
    RawProviderRecordStore,
)
from connectors.provider_runtime.rights_admission import (
    PROVIDER_RAW_RIGHTS_METADATA_KEY,
    ProviderRawRightsEvidence,
    provider_account_source_id,
)
from connectors.provider_runtime.replay import (
    PROVIDER_REPLAY_JOB_TYPE,
    ProviderRawReplayReader,
    ProviderRawReplayService,
    ReplayCursor,
    ReplayIntegrityError,
    ReplayScope,
)

pytestmark = pytest.mark.asyncio

TENANT = "tenant-replay"
PROVIDER = "shopify.orders.catalog"
CONNECTION = "conn-replay"
ACCOUNT = "shop-1"
STREAM = "orders"
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class _AdmittedBronzeRepository(BronzeRepository):
    """Test seam for rows admitted by trusted provenance setup."""

    async def ingest(self, **kwargs):
        kwargs.update(
            provenance_status="valid",
            license_status="public_api",
            terms_status="approved",
        )
        return await super().ingest(**kwargs)


class _TestRightsAdmission:
    """Explicit tenant-grant fixture for replay records and rechecks."""

    async def admit(self, record):
        return ProviderRawRightsEvidence(
            tenant_id=record.tenant_id,
            source_id=provider_account_source_id(record.connection_id, record.account_id),
            source_grant_ref="drg_replay_fixture",
            rights_decision_ref=f"rdec_{record.idempotency_key}",
            decision_identity=f"rdid_{record.idempotency_key}",
            policy_version="irrl-2",
            evaluated_at="2026-10-03T00:00:00+00:00",
        )

    @asynccontextmanager
    async def hold_grant(self, record, admission):
        yield

    async def verify_persisted(self, record, *, current_admission):
        stored = (record.metadata or {}).get(PROVIDER_RAW_RIGHTS_METADATA_KEY, {})
        if stored.get("source_grant_ref") != current_admission.source_grant_ref:
            raise ValueError("rights evidence does not match fixture grant")

    async def authorize_replay(self, record):
        stored = (record.metadata or {}).get(PROVIDER_RAW_RIGHTS_METADATA_KEY)
        evidence = ProviderRawRightsEvidence.model_validate(stored)
        if evidence.tenant_id != record.tenant_id:
            raise ValueError("rights evidence is outside fixture tenant")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repos.reset_in_memory_stores()
    reset_jobs_memory()
    original_runtime = settings.provider_runtime
    original_env = settings.env
    settings.provider_runtime = replace(original_runtime, enabled=True)
    settings.env = Environment.LOCAL
    unregister_handler(PROVIDER_REPLAY_JOB_TYPE)
    yield
    unregister_handler(PROVIDER_REPLAY_JOB_TYPE)
    settings.provider_runtime = original_runtime
    settings.env = original_env
    repos.reset_in_memory_stores()
    reset_jobs_memory()


class _Normalizer:
    normalizer_version = "fixture-v1"

    def normalize(self, raw):
        event = make_aether_event(
            provider_identity=raw.provider_identity,
            event_type="commerce.order.updated",
            event_family="commerce",
            tenant_id=raw.tenant_id,
            source_record_id=raw.record_id,
            account_id=raw.account_id,
            occurred_at=raw.observed_at,
            observed_at=raw.observed_at,
            data={"order_id": raw.provider_record_id},
        ).model_copy(update={"event_id": raw.idempotency_key})
        return NormalizationResult(events=[event], normalizer_version=self.normalizer_version)


class _CountingNormalizer(_Normalizer):
    def __init__(self):
        self.calls = 0

    def normalize(self, raw):
        self.calls += 1
        return super().normalize(raw)


class _Plugin:
    def __init__(self, normalizer=None):
        self._normalizer = normalizer or _Normalizer()

    def normalizer(self):
        return self._normalizer


class _Registry:
    def __init__(self, plugin=None):
        self.plugin = plugin or _Plugin()

    def get(self, identity):
        return self.plugin if identity == PROVIDER else None


async def _connection():
    await ProviderConnectionRepository().upsert(
        ProviderConnection(
            connection_id=CONNECTION,
            tenant_id=TENANT,
            provider_identity=PROVIDER,
            selected_accounts=[ACCOUNT],
        )
    )


def _scope(**changes):
    data = {
        "tenant_id": TENANT,
        "connection_id": CONNECTION,
        "provider_identity": PROVIDER,
        "account_id": ACCOUNT,
        "stream_id": STREAM,
        "source_account_realm": None,
        "ingested_from": T0 - timedelta(seconds=1),
        "ingested_before": T0 + timedelta(seconds=10),
        "max_records": 10,
        "dry_run": False,
        "normalizer_version": "fixture-v1",
        "event_schema_version": "1",
    }
    data.update(changes)
    return ReplayScope(**data)


async def _raw(number, **changes):
    fields = {
        "provider_identity": PROVIDER,
        "provider_record_id": f"order-{number}",
        "provider_record_type": "order",
        "tenant_id": TENANT,
        "connection_id": CONNECTION,
        "account_id": ACCOUNT,
        "stream_id": STREAM,
        "payload": {"id": f"order-{number}"},
    }
    fields.update(changes)
    record = make_raw_record(**fields)
    ((stored, was_new),) = await RawProviderRecordStore(
        repository=_AdmittedBronzeRepository("provider_records"),
        rights_admission=_TestRightsAdmission(),
    ).ingest([record])
    assert was_new
    row = next(
        row
        for row in repos._IN_MEMORY_STORES["bronze_provider_records"].values()
        if row["payload"]["record_id"] == stored.record_id
    )
    row["created_at"] = (T0 + timedelta(seconds=number)).isoformat()
    return stored, row


async def _quarantined_raw(number):
    record = make_raw_record(
        provider_identity=PROVIDER,
        provider_record_id=f"order-{number}",
        provider_record_type="order",
        tenant_id=TENANT,
        connection_id=CONNECTION,
        account_id=ACCOUNT,
        stream_id=STREAM,
        payload={"id": f"order-{number}"},
    )
    repository = BronzeRepository("provider_records")
    await repository.ingest(
        source=record.provider_identity,
        source_tag=f"provider:{record.provider_identity}:{TENANT}",
        provider_record_id=record.bronze_provider_record_id,
        payload=record.model_dump(),
        schema_version=record.schema_version,
        entity_id=record.provider_record_id,
        entity_type=record.provider_record_type or "",
        tenant_id=TENANT,
    )
    row = next(
        row
        for row in repos._IN_MEMORY_STORES["bronze_provider_records"].values()
        if row["payload"]["record_id"] == record.record_id
    )
    row["created_at"] = (T0 + timedelta(seconds=number)).isoformat()
    return record, row


def _service(**kwargs):
    kwargs.setdefault("rights_admission", _TestRightsAdmission())
    return ProviderRawReplayService(registry=_Registry(), **kwargs)


async def _checkpoint_list():
    checkpoints = []

    async def checkpoint(cursor, counts):
        checkpoints.append((cursor, dict(counts)))

    async def heartbeat():
        return True

    return checkpoints, checkpoint, heartbeat


async def test_reader_enforces_every_scope_dimension_and_ignores_unrelated_legacy_rows():
    wanted, _ = await _raw(1)
    await _raw(2, tenant_id="other-tenant")
    await _raw(3, connection_id="other-connection")
    await _raw(4, account_id="other-shop")
    await _raw(5, stream_id="refunds")
    repos._IN_MEMORY_STORES["bronze_provider_records"]["legacy-unrelated"] = {
        "id": "legacy-unrelated",
        "tenant_id": "another-tenant",
        "source": PROVIDER,
        "created_at": T0.isoformat(),
    }
    page = await ProviderRawReplayReader().page(_scope(), None, 10)
    assert [row.record.record_id for row in page] == [wanted.record_id]


async def test_reader_never_mixes_live_test_and_realm_unknown_raw_revisions():
    legacy, _ = await _raw(1)
    source = {
        "source_account_key": "gid://shopify/Shop/123",
        "source_object_type": "order",
        "source_revision_key": "snapshot:2026-01-01T12:00:00Z:digest",
        "schema_version": "2",
    }
    live, _ = await _raw(
        2, source_account_realm="live", source_object_id="gid://shopify/Order/2", **source
    )
    sandbox, _ = await _raw(
        3, source_account_realm="test", source_object_id="gid://shopify/Order/3", **source
    )

    reader = ProviderRawReplayReader()
    legacy_page = await reader.page(_scope(), None, 10)
    live_page = await reader.page(_scope(source_account_realm="live"), None, 10)
    test_page = await reader.page(_scope(source_account_realm="test"), None, 10)

    assert [row.record.record_id for row in legacy_page] == [legacy.record_id]
    assert [row.record.record_id for row in live_page] == [live.record_id]
    assert [row.record.record_id for row in test_page] == [sandbox.record_id]


async def test_reader_verifies_checksum_and_bronze_lineage_without_source_pii():
    await _raw(1)
    row = next(iter(repos._IN_MEMORY_STORES["bronze_provider_records"].values()))
    row["payload"]["payload"]["id"] = "tampered"
    with pytest.raises(ReplayIntegrityError, match="checksum mismatch"):
        await ProviderRawReplayReader().page(_scope(), None, 10)
    row["payload"]["payload"]["id"] = "order-1"
    row["idempotency_key"] = "incorrect"
    with pytest.raises(ReplayIntegrityError, match="lineage mismatch"):
        await ProviderRawReplayReader().page(_scope(), None, 10)


async def test_replay_rejects_quarantined_bronze_before_normalization():
    await _connection()
    await _quarantined_raw(1)
    normalizer = _CountingNormalizer()
    service = ProviderRawReplayService(
        registry=_Registry(plugin=_Plugin(normalizer)),
        rights_admission=_TestRightsAdmission(),
    )
    _, checkpoint, heartbeat = await _checkpoint_list()

    with pytest.raises(ReplayIntegrityError, match="quarantined"):
        await service.run_window(
            _scope(),
            cursor=None,
            counts={},
            checkpoint=checkpoint,
            heartbeat=heartbeat,
        )

    assert normalizer.calls == 0
    assert not repos._IN_MEMORY_STORES.get("bronze_sdk_events")
    assert not repos._IN_MEMORY_STORES.get("event_outbox")


async def test_dry_run_scans_and_checkpoints_without_canonical_or_outbox_writes():
    await _connection()
    await _raw(1)
    checkpoints, checkpoint, heartbeat = await _checkpoint_list()
    with patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        result = await _service().run_window(
            _scope(dry_run=True),
            cursor=None,
            counts={},
            checkpoint=checkpoint,
            heartbeat=heartbeat,
        )
    assert (result["status"], result["scanned"], result["candidates"]) == ("completed", 1, 1)
    assert (result["accepted"], result["dry_run_admitted"]) == (0, 1)
    assert len(checkpoints) == 1
    assert not repos._IN_MEMORY_STORES.get("bronze_sdk_events")
    assert not repos._IN_MEMORY_STORES.get("event_outbox")


async def test_live_replay_is_at_least_once_safe_after_checkpoint_failure():
    await _connection()
    await _raw(1)

    async def fail_checkpoint(_cursor, _counts):
        raise RuntimeError("checkpoint unavailable")

    _, checkpoint, heartbeat = await _checkpoint_list()
    service = _service(bridge=EventBridge())
    with patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        with pytest.raises(RuntimeError, match="checkpoint unavailable"):
            await service.run_window(
                _scope(),
                cursor=None,
                counts={},
                checkpoint=fail_checkpoint,
                heartbeat=heartbeat,
            )
        retried = await service.run_window(
            _scope(),
            cursor=None,
            counts={},
            checkpoint=checkpoint,
            heartbeat=heartbeat,
        )
    assert retried["scanned"] == retried["candidates"] == 1
    assert retried["accepted"] == 0  # bridge idempotency rejected redelivery
    assert len(repos._IN_MEMORY_STORES["bronze_sdk_events"]) == 1
    assert len(repos._IN_MEMORY_STORES["event_outbox"]) == 1


async def test_enqueue_dedupes_exact_scope_and_keeps_changed_scope_distinct():
    await _connection()
    service = _service()
    first = await service.enqueue(
        _scope(), run_key="run-1", actor_ref="operator-1", decision_ref="review-1"
    )
    again = await service.enqueue(
        _scope(), run_key="run-1", actor_ref="operator-1", decision_ref="review-1"
    )
    changed = await service.enqueue(
        _scope(dry_run=True), run_key="run-1", actor_ref="operator-1", decision_ref="review-1"
    )
    assert first["id"] == again["id"]
    assert again["replayed"] is True
    assert changed["id"] != first["id"]
    assert first["idempotency_key"] != changed["idempotency_key"]
    changed_actor = await service.enqueue(
        _scope(), run_key="run-1", actor_ref="operator-2", decision_ref="review-1"
    )
    changed_decision = await service.enqueue(
        _scope(), run_key="run-1", actor_ref="operator-1", decision_ref="review-2"
    )
    assert changed_actor["id"] != first["id"]
    assert changed_decision["id"] != first["id"]
    changed_realm = await service.enqueue(
        _scope(source_account_realm="live"),
        run_key="run-1",
        actor_ref="operator-1",
        decision_ref="review-1",
    )
    assert changed_realm["id"] != first["id"]


async def test_durable_handler_checkpoints_prefix_then_retry_resumes_suffix(monkeypatch):
    await _connection()
    first, _ = await _raw(1)
    second, _ = await _raw(2)
    service = _service(bridge=EventBridge())
    job = await service.enqueue(
        _scope(), run_key="retry-run", actor_ref="operator-1", decision_ref="review-1"
    )
    register_durable_job_handlers(settings)
    assert PROVIDER_REPLAY_JOB_TYPE in HANDLER_REGISTRY
    assert PROVIDER_REPLAY_JOB_TYPE not in TENANT_INVOCABLE
    original_ingest = service.bridge.ingest_events
    failed_once = False

    async def fail_second(tenant_id, events):
        nonlocal failed_once
        if events[0].source_record_id == second.record_id and not failed_once:
            failed_once = True
            raise RuntimeError("temporary canonical store failure")
        return await original_ingest(tenant_id, events)

    service.bridge.ingest_events = fail_second
    monkeypatch.setattr(replay_mod, "ProviderRawReplayService", lambda: service)
    with patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        worker = JobWorker(backoff_base_seconds=0, backoff_cap_seconds=0)
        assert await worker.run_once() is True
        pending = await get_jobs_service().get_job(TENANT, job["id"])
        assert pending["payload"]["counts"]["scanned"] == 1
        assert pending["payload"]["cursor"]["bronze_id"] != ""
        assert len(repos._IN_MEMORY_STORES["event_outbox"]) == 1
        assert await worker.run_once() is True
    finished = await get_jobs_service().get_job(TENANT, job["id"])
    assert finished["status"] == "succeeded"
    assert finished["result"]["scanned"] == 2
    assert finished["result"]["accepted"] == 2
    assert len(repos._IN_MEMORY_STORES["event_outbox"]) == 2
    assert {
        row["payload"]["source_record_id"]
        for row in repos._IN_MEMORY_STORES["event_outbox"].values()
    } == {
        first.record_id,
        second.record_id,
    }


async def test_scope_version_tenant_and_lease_fail_closed():
    await _connection()
    await _raw(1)
    _, checkpoint, heartbeat = await _checkpoint_list()
    with pytest.raises(ReplayIntegrityError, match="normalizer version"):
        await _service().run_window(
            _scope(normalizer_version="unavailable"),
            cursor=None,
            counts={},
            checkpoint=checkpoint,
            heartbeat=heartbeat,
        )
    with pytest.raises(ReplayIntegrityError, match="outside replay scope"):
        await _service().enqueue(
            _scope(tenant_id="other-tenant"),
            run_key="wrong-tenant",
            actor_ref="operator-1",
            decision_ref="review-1",
        )
    with pytest.raises(ReplayIntegrityError, match="worker lease"):
        await _service().run_window(
            _scope(),
            cursor=None,
            counts={},
            checkpoint=checkpoint,
            heartbeat=AsyncMock(return_value=False),
        )
    assert not repos._IN_MEMORY_STORES.get("event_outbox")


async def test_staging_enqueue_fails_closed_without_durable_jobs(monkeypatch):
    await _connection()
    settings.env = Environment.STAGING

    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    with pytest.raises(RuntimeError, match="durable jobs database"):
        await _service().enqueue(
            _scope(), run_key="staging", actor_ref="operator-1", decision_ref="review-1"
        )
