"""Event envelopes: defaults, checksums, idempotency keys, extra-field rejection."""

from __future__ import annotations

import hashlib
import json

import pytest

from shared.integration_contracts.events import (
    AetherEvent,
    ReadBatch,
    RawProviderRecord,
    compute_checksum,
    make_aether_event,
    make_raw_record,
    verify_checksum,
)


# ── RawProviderRecord ───────────────────────────────────────────────────────


def test_raw_record_defaults() -> None:
    r = RawProviderRecord(provider_identity="shopify.admin.orders_read", provider_record_id="p-1", payload={"id": "p-1"})
    assert len(r.record_id) == 32  # uuid4().hex
    assert r.tenant_id == ""
    assert r.acquisition_mode == "poll"
    assert r.observed_at == ""
    assert r.checksum == ""
    assert r.schema_version == "1"
    assert r.metadata == {}


def test_raw_record_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        RawProviderRecord(  # type: ignore[call-arg]
            provider_identity="shopify.admin.orders_read",
            provider_record_id="p-1",
            payload={},
            unexpected_field="boom",
        )


def test_raw_record_requires_payload_and_provider_record_id() -> None:
    with pytest.raises(Exception):
        RawProviderRecord(provider_identity="shopify.admin.orders_read", payload={})


# ── checksum ────────────────────────────────────────────────────────────────


def test_compute_checksum_is_canonical_and_key_order_independent() -> None:
    a = compute_checksum({"a": 1, "b": {"c": 2, "d": [1, 2]}})
    b = compute_checksum({"b": {"d": [1, 2], "c": 2}, "a": 1})
    assert a == b
    expected = hashlib.sha256(
        json.dumps({"a": 1, "b": {"c": 2, "d": [1, 2]}}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert a == expected


def test_checksum_changes_with_payload() -> None:
    assert compute_checksum({"a": 1}) != compute_checksum({"a": 2})


def test_verify_checksum_accepts_only_matching_checksums() -> None:
    base = dict(provider_identity="shopify.admin.orders_read", provider_record_id="p-1", payload={"a": 1})
    uncomputed = RawProviderRecord(**base)
    assert uncomputed.checksum == ""  # never computed
    assert verify_checksum(uncomputed) is False  # unverified is never verified

    correct = RawProviderRecord(checksum=compute_checksum(base["payload"]), **base)
    assert verify_checksum(correct) is True

    wrong = RawProviderRecord(checksum=compute_checksum({"a": 2}), **base)
    assert verify_checksum(wrong) is False

    # A payload mutated after construction leaves the stored checksum stale.
    stale = make_raw_record(
        provider_identity="shopify.admin.orders_read",
        provider_record_id="p-1",
        payload={"a": 1},
    )
    stale.payload["a"] = 2
    assert verify_checksum(stale) is False


# ── idempotency keys ────────────────────────────────────────────────────────


def test_raw_record_idempotency_key_shape_and_determinism() -> None:
    r = RawProviderRecord(
        tenant_id="t1",
        provider_identity="shopify.admin.orders_read",
        provider_record_id="p-1",
        payload={},
    )
    assert len(r.idempotency_key) == 32
    assert r.idempotency_key == r.idempotency_key
    expected = hashlib.sha256(
        "t1:shopify.admin.orders_read:p-1:1".encode("utf-8")
    ).hexdigest()[:32]
    assert r.idempotency_key == expected


def test_raw_record_idempotency_key_inputs_distinguish() -> None:
    base = dict(provider_identity="shopify.admin.orders_read", payload={})
    a = RawProviderRecord(tenant_id="t1", provider_record_id="p-1", **base)
    assert a.idempotency_key != RawProviderRecord(tenant_id="t2", provider_record_id="p-1", **base).idempotency_key
    assert a.idempotency_key != RawProviderRecord(tenant_id="t1", provider_record_id="p-2", **base).idempotency_key
    assert a.idempotency_key != RawProviderRecord(tenant_id="t1", provider_record_id="p-1", payload={}, provider_identity="shopify.admin.orders_write").idempotency_key


# ── AetherEvent ─────────────────────────────────────────────────────────────


def test_aether_event_defaults() -> None:
    e = AetherEvent(
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id="t1",
        provider="shopify",
        provider_identity="shopify.admin.orders_read",
        source_record_id="r1",
        occurred_at="2026-01-01T00:00:00+00:00",
        observed_at="2026-01-01T00:00:01+00:00",
        data={"order_id": "x"},
    )
    assert len(e.event_id) == 32
    assert e.account_id == ""
    assert e.subject_id is None
    assert e.context == {}
    assert e.schema_version == "1"


def test_aether_event_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        AetherEvent(  # type: ignore[call-arg]
            event_type="commerce.order.created",
            event_family="commerce",
            tenant_id="t1",
            provider="shopify",
            provider_identity="shopify.admin.orders_read",
            source_record_id="r1",
            occurred_at="2026-01-01T00:00:00+00:00",
            observed_at="2026-01-01T00:00:01+00:00",
            data={},
            unexpected_field="boom",
        )


def test_aether_event_idempotency_key() -> None:
    e = AetherEvent(
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id="t1",
        provider="shopify",
        provider_identity="shopify.admin.orders_read",
        source_record_id="r1",
        occurred_at="2026-01-01T00:00:00+00:00",
        observed_at="2026-01-01T00:00:01+00:00",
        data={},
    )
    assert len(e.idempotency_key) == 32
    expected = hashlib.sha256(
        "t1:commerce.order.created:r1:1".encode("utf-8")
    ).hexdigest()[:32]
    assert e.idempotency_key == expected
    # event_type is part of the key: same source can emit two distinct events.
    other = e.model_copy(update={"event_type": "commerce.order.updated"})
    assert other.idempotency_key != e.idempotency_key


# ── ReadBatch ───────────────────────────────────────────────────────────────


def test_read_batch_defaults() -> None:
    b = ReadBatch()
    assert b.records == []
    assert b.next_cursor is None
    assert b.has_more is False


def test_read_batch_forbids_unknown_fields() -> None:
    with pytest.raises(Exception):
        ReadBatch(unexpected_field=True)  # type: ignore[call-arg]


def test_read_batch_holds_records() -> None:
    r = RawProviderRecord(provider_identity="shopify.admin.orders_read", provider_record_id="p-1", payload={})
    b = ReadBatch(records=[r], next_cursor="abc", has_more=True)
    assert b.records[0] is r
    assert b.next_cursor == "abc"
    assert b.has_more is True


# ── convenience constructors ────────────────────────────────────────────────


def test_make_raw_record_fills_checksum_and_observed_at() -> None:
    r = make_raw_record(
        provider_identity="shopify.admin.orders_read",
        provider_record_id="p-1",
        payload={"id": "p-1", "note": "x"},
        tenant_id="t1",
    )
    assert r.checksum == compute_checksum(r.payload)
    assert r.observed_at != ""  # server now
    assert r.tenant_id == "t1"


def test_make_raw_record_respects_explicit_checksum() -> None:
    r = make_raw_record(
        provider_identity="shopify.admin.orders_read",
        provider_record_id="p-1",
        payload={"id": "p-1"},
        checksum="deadbeef",
    )
    assert r.checksum == "deadbeef"


def test_make_aether_event_defaults_provider_and_timestamps() -> None:
    e = make_aether_event(
        provider_identity="shopify.admin.orders_read",
        event_type="commerce.order.created",
        event_family="commerce",
        tenant_id="t1",
        source_record_id="r1",
        data={"order_id": "x"},
    )
    assert e.provider == "shopify"
    assert e.occurred_at != ""
    assert e.observed_at != ""
    assert e.context == {}
