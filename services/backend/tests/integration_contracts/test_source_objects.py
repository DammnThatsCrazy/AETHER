"""Non-identity provider object references and deterministic logical fact IDs."""

from __future__ import annotations

import re

import pytest

from shared.integration_contracts.source_objects import (
    LogicalEventKey,
    SourceObjectRef,
    event_revision_id_for_parts,
    logical_event_id_for_source_parts,
)


def _source(**overrides: object) -> SourceObjectRef:
    values: dict[str, object] = dict(
        tenant_id="tenant-a",
        provider_identity="shopify.admin.orders_read",
        source_account_key="gid://shopify/Shop/123",
        source_account_realm="live",
        account_verification_ref="conn-1:shop:example.myshopify.com",
        source_object_type="order",
        source_object_id="gid://shopify/Order/456",
    )
    values.update(overrides)
    return SourceObjectRef(**values)  # type: ignore[arg-type]


def test_source_object_is_scoped_but_excludes_connection_from_identity() -> None:
    source = _source()
    assert source.provider_family == "shopify"
    assert source.logical_account_key == "live:gid://shopify/Shop/123"
    assert source.account.account_verification_ref == source.account_verification_ref
    with pytest.raises(Exception):
        _source(integration_id="mutable-integration")


@pytest.mark.parametrize(
    "identity_kind",
    ["customer", "person", "account", "agent", "device", "shopify_customer"],
)
def test_identity_kinds_cannot_get_canonical_object_ids(identity_kind: str) -> None:
    with pytest.raises(Exception):
        _source(source_object_type=identity_kind)


def test_logical_event_id_is_stable_across_reconnect_and_unicode_normalization() -> None:
    first = LogicalEventKey(
        source=_source(source_object_id="order-cafe\u0301"),
        source_revision_key="snapshot:2026-10-02:abcdef",
        semantic_slot="order.lifecycle",
    )
    reconnect = LogicalEventKey(
        source=_source(
            source_object_id="order-caf\u00e9",
            account_verification_ref="conn-2:shop:example.myshopify.com",
        ),
        source_revision_key="snapshot:2026-10-02:abcdef",
        semantic_slot="order.lifecycle",
    )
    assert first.event_id == reconnect.event_id
    assert first.full_digest == reconnect.full_digest
    assert re.fullmatch(r"cevt_v1_[a-z2-7]{32}", first.event_id)
    assert len(first.full_digest) == 64


def test_logical_event_id_has_a_stable_versioned_golden_value() -> None:
    key = LogicalEventKey(
        source=_source(), source_revision_key="snapshot:1", semantic_slot="order.lifecycle"
    )
    assert key.event_id == "cevt_v1_kdu375m4sgnmvz3f7uapm7sqs6emcwva"
    assert key.full_digest == ("50e9bff59c919acae765fd00f67e509788c15aa044986c1d7c9c3e7d3a079b32")


def test_event_revision_id_is_stable_and_versioned() -> None:
    values = dict(
        logical_event_id="cevt_v1_kdu375m4sgnmvz3f7uapm7sqs6emcwva",
        event_schema_version="2",
        mapping_version="shopify.order.snapshot.v1",
        normalizer_version="2",
        canonical_payload_digest="0" * 64,
    )
    revision_id = event_revision_id_for_parts(**values)
    assert revision_id == (
        "erev_v1_2696acdf255f92274efd476451848eaeaa55e2cc6fd3630f0916169afede5235"
    )
    assert revision_id == event_revision_id_for_parts(**values)
    assert re.fullmatch(r"erev_v1_[0-9a-f]{64}", revision_id)


@pytest.mark.parametrize(
    "change",
    [
        {"event_schema_version": "3"},
        {"mapping_version": "shopify.order.snapshot.v2"},
        {"normalizer_version": "3"},
        {"canonical_payload_digest": "1" * 64},
    ],
)
def test_event_revision_id_changes_for_each_interpretation_dimension(change: dict) -> None:
    values = dict(
        logical_event_id="cevt_v1_kdu375m4sgnmvz3f7uapm7sqs6emcwva",
        event_schema_version="2",
        mapping_version="shopify.order.snapshot.v1",
        normalizer_version="2",
        canonical_payload_digest="0" * 64,
    )
    assert event_revision_id_for_parts(**(values | change)) != event_revision_id_for_parts(**values)


@pytest.mark.parametrize(
    "change",
    [
        {"logical_event_id": "not-an-event-id"},
        {"event_schema_version": " "},
        {"mapping_version": " "},
        {"normalizer_version": " "},
        {"canonical_payload_digest": "not-a-digest"},
    ],
)
def test_event_revision_id_rejects_incomplete_inputs(change: dict) -> None:
    values = dict(
        logical_event_id="cevt_v1_kdu375m4sgnmvz3f7uapm7sqs6emcwva",
        event_schema_version="2",
        mapping_version="shopify.order.snapshot.v1",
        normalizer_version="2",
        canonical_payload_digest="0" * 64,
    )
    with pytest.raises(ValueError):
        event_revision_id_for_parts(**(values | change))


def test_pure_source_parts_encoder_matches_verified_model_without_verification_ref() -> None:
    key = LogicalEventKey(
        source=_source(), source_revision_key="snapshot:1", semantic_slot="order.snapshot"
    )
    assert (
        logical_event_id_for_source_parts(
            tenant_id="tenant-a",
            provider_family="shopify",
            source_account_realm="live",
            source_account_key="gid://shopify/Shop/123",
            source_object_type="order",
            source_object_id="gid://shopify/Order/456",
            source_revision_key="snapshot:1",
            semantic_slot="order.snapshot",
        )
        == key.event_id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_family": "shopify.admin"},
        {"source_account_realm": "unknown"},
        {"source_object_type": "customer"},
        {"source_account_key": " "},
        {"source_revision_key": ""},
        {"semantic_slot": "order"},
    ],
)
def test_pure_source_parts_encoder_rejects_invalid_dimensions(changes: dict) -> None:
    values = dict(
        tenant_id="tenant-a",
        provider_family="shopify",
        source_account_realm="live",
        source_account_key="gid://shopify/Shop/123",
        source_object_type="order",
        source_object_id="gid://shopify/Order/456",
        source_revision_key="snapshot:1",
        semantic_slot="order.snapshot",
    )
    values.update(changes)
    with pytest.raises(ValueError):
        logical_event_id_for_source_parts(**values)


@pytest.mark.parametrize(
    ("source_change", "revision", "slot"),
    [
        ({"tenant_id": "tenant-b"}, "snapshot:1", "order.lifecycle"),
        ({"source_account_key": "gid://shopify/Shop/999"}, "snapshot:1", "order.lifecycle"),
        ({"source_account_realm": "test"}, "snapshot:1", "order.lifecycle"),
        ({"source_object_id": "order-other"}, "snapshot:1", "order.lifecycle"),
        ({"source_object_type": "payment"}, "snapshot:1", "order.lifecycle"),
        ({"provider_identity": "stripe.payments.payments_read"}, "snapshot:1", "order.lifecycle"),
        ({}, "snapshot:2", "order.lifecycle"),
        ({}, "snapshot:1", "order.snapshot"),
    ],
)
def test_logical_event_id_changes_with_every_fact_identity_dimension(
    source_change: dict[str, object], revision: str, slot: str
) -> None:
    baseline = LogicalEventKey(
        source=_source(), source_revision_key="snapshot:1", semantic_slot="order.lifecycle"
    )
    changed = LogicalEventKey(
        source=_source(**source_change), source_revision_key=revision, semantic_slot=slot
    )
    assert changed.event_id != baseline.event_id


def test_provider_capability_is_not_part_of_source_object_identity() -> None:
    orders = LogicalEventKey(
        source=_source(), source_revision_key="snapshot:1", semantic_slot="order.lifecycle"
    )
    another_capability = LogicalEventKey(
        source=_source(provider_identity="shopify.admin.orders_webhook"),
        source_revision_key="snapshot:1",
        semantic_slot="order.lifecycle",
    )
    assert orders.event_id == another_capability.event_id


def test_length_prefix_prevents_delimiter_ambiguity() -> None:
    first = LogicalEventKey(
        source=_source(source_account_key="a:b", source_object_id="c"),
        source_revision_key="snapshot:1",
        semantic_slot="order.lifecycle",
    )
    second = LogicalEventKey(
        source=_source(source_account_key="a", source_object_id="b:c"),
        source_revision_key="snapshot:1",
        semantic_slot="order.lifecycle",
    )
    assert first.event_id != second.event_id


def test_logical_event_key_rejects_unversioned_or_unstable_inputs() -> None:
    with pytest.raises(Exception):
        LogicalEventKey(source=_source(), source_revision_key="", semantic_slot="order.lifecycle")
    with pytest.raises(Exception):
        LogicalEventKey(source=_source(), source_revision_key="snapshot:1", semantic_slot="order")
    with pytest.raises(Exception):
        LogicalEventKey(
            source=_source(),
            source_revision_key="snapshot:1",
            semantic_slot="order.lifecycle",
            schema_version="2",
        )
