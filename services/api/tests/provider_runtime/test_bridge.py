"""Provider canonical Bronze/outbox durability and relay behavior."""

from __future__ import annotations

from unittest import mock

import pytest
from pydantic import ValidationError

from repositories import repos
from shared.events.events import Topic
from shared.integration_contracts.events import (
    AetherEvent,
    compute_checksum,
    deterministic_v1_event_id_for_source_record,
    make_aether_event,
    make_raw_record,
)
from shared.integration_contracts.source_objects import (
    event_revision_id_for_parts,
    logical_event_id_for_source_parts,
)
from ingestion.ingestion import bronze_bulk
from ingestion.ingestion.outbox_relay import EventOutboxRelay, RELAY_SOURCE_SERVICE
from ingestion.ingestion.spine import is_provider_delivery
import connectors.provider_runtime.bridge as bridge_module
from connectors.provider_runtime.bridge import EventBridge


def _event(event_id: str = "evt_1", *, tenant_id: str = "tenant-1", **changes):
    data = {"order_id": event_id}
    context = {"acquisition_mode": "poll"}
    data.update(changes.pop("data", {}))
    context.update(changes.pop("context", {}))
    base = make_aether_event(
        provider_identity="shopify.orders.catalog",
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id=tenant_id,
        source_record_id=f"raw_{event_id}",
        data=data,
        context=context,
        **changes,
    )
    return base.model_copy(update={"event_id": event_id})


def _event_revision(*, mapping_version: str, data: dict) -> AetherEvent:
    logical_event_id = logical_event_id_for_source_parts(
        tenant_id="tenant-1",
        provider_family="shopify",
        source_account_realm="live",
        source_account_key="gid://shopify/Shop/123",
        source_object_type="order",
        source_object_id="gid://shopify/Order/456",
        source_revision_key="snapshot:2026-10-03T00:00:00Z:economic-digest",
        semantic_slot="order.snapshot",
    )
    event_type = "commerce.order.updated"
    event_family = "commerce"
    canonical_payload_digest = compute_checksum(
        {
            "event_type": event_type,
            "event_family": event_family,
            "data": data,
        }
    )
    event_revision_id = event_revision_id_for_parts(
        logical_event_id=logical_event_id,
        event_schema_version="2",
        mapping_version=mapping_version,
        normalizer_version="shopify-orders-v1",
        canonical_payload_digest=canonical_payload_digest,
    )
    return AetherEvent(
        event_id=event_revision_id,
        logical_event_id=logical_event_id,
        event_revision_id=event_revision_id,
        mapping_version=mapping_version,
        normalizer_version="shopify-orders-v1",
        source_revision_key="snapshot:2026-10-03T00:00:00Z:economic-digest",
        canonical_payload_digest=canonical_payload_digest,
        event_type=event_type,
        event_family=event_family,
        tenant_id="tenant-1",
        provider="shopify",
        provider_identity="shopify.admin.orders_read",
        source_record_id="raw-order-revision",
        occurred_at="2026-10-03T00:00:00+00:00",
        observed_at="2026-10-03T00:01:00+00:00",
        account_id="gid://shopify/Shop/123",
        data=data,
        context={"source_account_realm": "live"},
        schema_version="2",
    )


@pytest.fixture(autouse=True)
def _local_store(monkeypatch: pytest.MonkeyPatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    repos.reset_in_memory_stores()
    yield
    repos.reset_in_memory_stores()


def _rows(table: str) -> list[dict]:
    return list(repos._IN_MEMORY_STORES.get(table, {}).values())


@pytest.mark.asyncio
async def test_bridge_atomically_stores_provider_bronze_and_pending_outbox():
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        accepted = await EventBridge().ingest_events("tenant-1", [_event(), _event("evt_2")])

    assert accepted == 2
    bronze = _rows("bronze_sdk_events")
    outbox = _rows("event_outbox")
    assert len(bronze) == len(outbox) == 2
    assert {row["source"] for row in bronze} == {"shopify"}
    assert {row["source_tag"] for row in bronze} == {"provider:shopify.orders.catalog:"}
    assert {row["topic"] for row in outbox} == {Topic.SDK_EVENTS_VALIDATED.value}
    assert all(row["status"] == "pending" for row in outbox)
    assert {row["payload"]["event_id"] for row in outbox} == {"evt_1", "evt_2"}
    assert all(row["payload"]["source_type"] == "provider" for row in outbox)


@pytest.mark.asyncio
async def test_duplicate_is_not_requeued_and_tenant_scope_is_distinct():
    bridge = EventBridge()
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        assert await bridge.ingest_events("tenant-1", [_event()]) == 1
        assert await bridge.ingest_events("tenant-1", [_event()]) == 0
        assert await bridge.ingest_events("tenant-2", [_event(tenant_id="tenant-2")]) == 1
    assert len(_rows("bronze_sdk_events")) == len(_rows("event_outbox")) == 2
    assert {row["tenant_id"] for row in _rows("event_outbox")} == {"tenant-1", "tenant-2"}


@pytest.mark.asyncio
async def test_repeat_normalization_without_event_id_uses_raw_record_fallback():
    raw = make_raw_record(
        provider_identity="shopify.orders.catalog",
        provider_record_id="order-1",
        provider_record_type="order",
        tenant_id="tenant-1",
        payload={"id": "order-1"},
        observed_at="2026-10-03T00:00:00+00:00",
    )

    def normalize_again() -> AetherEvent:
        return make_aether_event(
            provider_identity=raw.provider_identity,
            event_type="commerce.order.updated",
            event_family="commerce",
            tenant_id=raw.tenant_id,
            source_record_id=raw.record_id,
            data={"order_id": raw.provider_record_id},
            occurred_at="2026-10-03T00:00:00+00:00",
            observed_at="2026-10-03T00:00:00+00:00",
        )

    first = normalize_again()
    second = normalize_again()
    # Simulate the same event crossing a JSON serialization boundary before
    # bridge ingestion; the generated UUID4 must still be recognized as
    # unstable even though the reconstructed model marks event_id as supplied.
    rehydrated_second = AetherEvent.model_validate(second.model_dump())
    assert first.event_id != second.event_id
    assert first.event_id_needs_stable_fallback
    assert rehydrated_second.event_id_needs_stable_fallback

    expected_id = deterministic_v1_event_id_for_source_record(
        tenant_id=raw.tenant_id,
        provider_identity=raw.provider_identity,
        event_type="commerce.order.updated",
        source_record_id=raw.record_id,
    )
    bridge = EventBridge()
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision",
        return_value=(True, None, []),
    ):
        assert await bridge.ingest_events("tenant-1", [first]) == 1
        assert await bridge.ingest_events("tenant-1", [rehydrated_second]) == 0
        assert await bridge.ingest_events("tenant-1", [second]) == 0

    bronze = _rows("bronze_sdk_events")
    outbox = _rows("event_outbox")
    assert len(bronze) == len(outbox) == 1
    assert bronze[0]["event_id"] == expected_id
    assert outbox[0]["event_id"] == expected_id
    assert outbox[0]["payload"]["event_id"] == expected_id


@pytest.mark.asyncio
async def test_provider_metrics_use_bounded_labels_without_tenant_ids():
    metric_calls = []

    def capture_metric(name, value=1, labels=None):
        metric_calls.append((name, value, labels))

    monkeypatch_calls = [
        (True, None, []),
        (True, None, []),
        (False, "consent_denied", []),
    ]
    bridge = EventBridge()
    with mock.patch.object(bridge_module.metrics, "increment", side_effect=capture_metric):
        with mock.patch(
            "ingestion.ingestion.validation.evaluate_ingress_decision",
            side_effect=monkeypatch_calls,
        ):
            assert await bridge.ingest_events("tenant-1", [_event("metric_evt")]) == 1
            assert await bridge.ingest_events("tenant-1", [_event("metric_evt")]) == 0
            assert await bridge.ingest_events("tenant-1", [_event("denied_evt")]) == 0

    accepted_calls = [
        call for call in metric_calls if call[0] == "provider_runtime_bridge_accepted_total"
    ]
    duplicate_calls = [
        call for call in metric_calls if call[0] == "provider_runtime_bridge_duplicate_total"
    ]
    denied_calls = [
        call for call in metric_calls if call[0] == "provider_runtime_consent_blocked_total"
    ]
    assert len(accepted_calls) == 2
    assert len(duplicate_calls) == len(denied_calls) == 1
    assert all(labels is None for _name, _value, labels in accepted_calls + duplicate_calls)
    assert denied_calls[0][2] == {"reason": "consent_denied"}
    assert all("tenant_id" not in (labels or {}) for _name, _value, labels in metric_calls)


@pytest.mark.asyncio
async def test_interpretation_revisions_with_one_logical_id_persist_separately_and_replay_dedupes():
    first = _event_revision(
        mapping_version="commerce-order-map-v1",
        data={"order_id": "456", "total": "120.00"},
    )
    second = _event_revision(
        mapping_version="commerce-order-map-v2",
        data={"order_id": "456", "total": "120.00", "currency": "USD"},
    )
    assert first.logical_event_id == second.logical_event_id
    assert first.event_revision_id != second.event_revision_id
    assert first.event_id == first.event_revision_id
    assert second.event_id == second.event_revision_id

    bridge = EventBridge()
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        assert await bridge.ingest_events("tenant-1", [first, second]) == 2
        assert await bridge.ingest_events("tenant-1", [first]) == 0

    bronze = _rows("bronze_sdk_events")
    outbox = _rows("event_outbox")
    assert len(bronze) == len(outbox) == 2
    assert {row["event_id"] for row in bronze} == {
        first.event_revision_id,
        second.event_revision_id,
    }
    assert {row["schema_version"] for row in bronze} == {"2"}
    assert {row["event_id"] for row in outbox} == {
        first.event_revision_id,
        second.event_revision_id,
    }
    assert {row["payload"]["logical_event_id"] for row in outbox} == {
        first.logical_event_id,
    }
    assert {row["payload"]["event_revision_id"] for row in outbox} == {
        first.event_revision_id,
        second.event_revision_id,
    }

    producer = _Producer()
    relay = EventOutboxRelay(producer, claim_owner="provider-revision-test")
    stats = await relay.drain_once()
    assert stats.published == 2
    assert {event.payload["event_id"] for event in producer.events} == {
        first.event_revision_id,
        second.event_revision_id,
    }
    assert all(
        event.payload["logical_event_id"] == first.logical_event_id
        and is_provider_delivery(event.payload, event.source_service)
        for event in producer.events
    )


@pytest.mark.asyncio
async def test_bridge_revalidates_v2_event_revision_identity_before_writing():
    valid = _event_revision(
        mapping_version="commerce-order-map-v1",
        data={"order_id": "456", "total": "120.00"},
    )
    invalid = valid.model_copy(update={"event_revision_id": "erev_v1_" + "0" * 64})

    with pytest.raises(ValidationError, match="event_id must equal event_revision_id"):
        await EventBridge().ingest_events("tenant-1", [invalid])

    assert _rows("bronze_sdk_events") == _rows("event_outbox") == []


@pytest.mark.asyncio
async def test_tenant_mismatch_rejected_before_consent_or_durable_write():
    with pytest.raises(ValueError, match="tenant"):
        await EventBridge().ingest_events("tenant-1", [_event(tenant_id="tenant-2")])
    assert _rows("bronze_sdk_events") == _rows("event_outbox") == []


@pytest.mark.asyncio
async def test_canonical_bronze_and_outbox_rollback_together(monkeypatch: pytest.MonkeyPatch):
    def fail_between_writes():
        raise RuntimeError("transaction interrupted")

    monkeypatch.setattr(bronze_bulk, "_commit_hook", fail_between_writes)
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        with pytest.raises(RuntimeError, match="transaction interrupted"):
            await EventBridge().ingest_events("tenant-1", [_event()])
    assert _rows("bronze_sdk_events") == _rows("event_outbox") == []


@pytest.mark.asyncio
async def test_scrub_precedes_both_durable_copies_and_denial_writes_neither():
    allowed = _event(
        data={"password": "private", "nested": {"api_key": "secret"}},
        context={"raw_provider_payload": {"card_number": "4111111111111111"}},
    )
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        assert await EventBridge().ingest_events("tenant-1", [allowed]) == 1
    for row in (_rows("bronze_sdk_events")[0], _rows("event_outbox")[0]):
        payload = row["payload"]
        assert payload["data"]["password"] == "[REDACTED]"
        assert payload["data"]["nested"]["api_key"] == "[REDACTED]"
        assert payload["context"]["raw_provider_payload"]["card_number"] == "[REDACTED]"

    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision",
        return_value=(False, "consent_denied", []),
    ):
        assert await EventBridge().ingest_events("tenant-1", [_event("evt_denied")]) == 0
    assert len(_rows("bronze_sdk_events")) == len(_rows("event_outbox")) == 1


class _Producer:
    def __init__(self) -> None:
        self.events = []
        self.fail_next = False

    async def publish(self, event) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("broker unavailable")
        self.events.append(event)


@pytest.mark.asyncio
async def test_relay_retries_provider_event_without_new_bronze_row():
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        assert await EventBridge().ingest_events("tenant-1", [_event()]) == 1
    producer = _Producer()
    producer.fail_next = True
    relay = EventOutboxRelay(
        producer,
        backoff_base_s=0,
        backoff_cap_s=0,
        claim_owner="provider-test",
    )
    failed = await relay.drain_once()
    assert (failed.claimed, failed.published, failed.retried) == (1, 0, 1)
    assert _rows("event_outbox")[0]["status"] == "retry"
    recovered = await relay.drain_once()
    assert (recovered.claimed, recovered.published) == (1, 1)
    assert _rows("event_outbox")[0]["status"] == "published"
    assert len(_rows("bronze_sdk_events")) == 1
    assert len(producer.events) == 1
    assert producer.events[0].source_service == RELAY_SOURCE_SERVICE
    assert producer.events[0].payload["provider"] == "shopify"


@pytest.mark.asyncio
async def test_expired_lease_can_redeliver_at_least_once():
    with mock.patch(
        "ingestion.ingestion.validation.evaluate_ingress_decision", return_value=(True, None, [])
    ):
        await EventBridge().ingest_events("tenant-1", [_event()])
    producer = _Producer()
    crashed = EventOutboxRelay(producer, claim_owner="crashed-worker")
    claimed = crashed._memory_claim()
    assert len(claimed) == 1
    await crashed._publish_row(claimed[0])  # simulated crash before published mark
    row = _rows("event_outbox")[0]
    row["available_at"] = "2000-01-01T00:00:00+00:00"
    recovered = EventOutboxRelay(producer, claim_owner="recovery-worker")
    stats = await recovered.drain_once()
    assert stats.published == 1
    assert len(producer.events) == 2
    assert len(_rows("bronze_sdk_events")) == len(_rows("event_outbox")) == 1
