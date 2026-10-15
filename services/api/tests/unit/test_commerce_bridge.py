"""Unit tests for the SDK <-> canonical commerce bridge seam.

``SDKCommerceSignal`` / ``BridgeResult`` and the three bridge functions are the
typed seam between SDK commerce signals and the provider-neutral canonical
plane. These tests pin the mapping, the determinism contract (provider is never
a mapping key), exact Money handling, and the confirmation/replay semantics.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from shared.commerce_contracts.money import Money
from shared.commerce_contracts.order import OrderSnapshot, OrderStatus
from shared.integration_contracts.commerce_bridge import (
    SDK_SIGNAL_SCHEMA_VERSION,
    SDKCommerceSignal,
    BridgeResult,
    confirm_interaction,
    envelope_bridge,
    payload_bridge,
)
from shared.integration_contracts.events import AetherEvent, make_aether_event

ALL_SIGNAL_TYPES = [
    "product_view",
    "cart_updated",
    "checkout_started",
    "order_confirmed",
]


def _make_signal(
    signal_type: str,
    signal_id: str = "sig-1",
    lineage: dict[str, str | None] | None = None,
    payload: dict[str, Any] | None = None,
) -> SDKCommerceSignal:
    return SDKCommerceSignal(
        signal_id=signal_id,
        signal_type=signal_type,  # type: ignore[arg-type]
        occurred_at="2026-08-08T12:00:00+00:00",
        source_url="https://shop.example.com/checkout",
        lineage=lineage if lineage is not None else {"source_record_id": "rec-1"},
        payload=payload if payload is not None else {"order_id": "ord-1"},
    )


def _make_canonical(
    event_type: str = "commerce.order.confirmed",
    source_record_id: str = "rec-1",
    provider: str = "shopify",
    data: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> AetherEvent:
    return make_aether_event(
        provider_identity=f"{provider}.commerce.order",
        event_type=event_type,
        event_family="commerce",
        tenant_id="acme",
        source_record_id=source_record_id,
        data=data if data is not None else {"order_id": "ord-1"},
        provider=provider,
        context=context,
    )


def _make_snapshot(total: Money | None = None) -> OrderSnapshot:
    return OrderSnapshot(
        order_id="ord-1",
        status=OrderStatus.paid,
        currency="USD",
        total=total if total is not None else Money(amount=Decimal("19.99"), currency="USD"),
        created_at="2026-08-08T12:00:00+00:00",
        updated_at="2026-08-08T12:05:00+00:00",
        account_id="acc-1",
    )


# --- schema version ----------------------------------------------------------


def test_schema_version() -> None:
    assert SDK_SIGNAL_SCHEMA_VERSION == "1"


# --- signal_type -> sdk_event_type mapping -----------------------------------


@pytest.mark.parametrize(
    ("signal_type", "expected_sdk"),
    [
        # sdk_event_type is the BARE SDK signal name — never prefixed
        # with "commerce.".
        ("product_view", "product_view"),
        ("cart_updated", "cart_updated"),
        ("checkout_started", "checkout_started"),
        ("order_confirmed", "order_confirmed"),
    ],
)
def test_each_signal_type_maps_to_sdk_event_type(signal_type: str, expected_sdk: str) -> None:
    signal = _make_signal(signal_type)
    canonical = _make_canonical()
    result = confirm_interaction(signal, canonical)
    assert result.sdk_event_type == expected_sdk


# --- envelope_bridge ---------------------------------------------------------


def test_envelope_bridge_is_deterministic() -> None:
    event = _make_canonical()
    first = envelope_bridge(event)
    second = envelope_bridge(event)
    assert first == second
    assert first.model_dump() == second.model_dump()


def test_envelope_bridge_keyed_on_event_type_and_payload_only() -> None:
    # Identical event_type + data, different providers: the mapping and payload
    # are identical; only the metadata provider field differs.
    event_a = _make_canonical(provider="shopify", data={"order_id": "ord-1"})
    event_b = _make_canonical(provider="stripe", data={"order_id": "ord-1"})

    result_a = envelope_bridge(event_a)
    result_b = envelope_bridge(event_b)

    assert result_a.sdk_event_type == result_b.sdk_event_type
    assert result_a.payload == result_b.payload
    assert result_a.canonical_event_type == result_b.canonical_event_type
    assert result_a.confirmed == result_b.confirmed is False
    assert result_a.confirmation_state == result_b.confirmation_state == "not_found"
    # Provider is metadata only — never a mapping key in the payload.
    assert result_a.provider == "shopify"
    assert result_b.provider == "stripe"
    assert "shopify" not in result_a.payload
    assert "stripe" not in result_b.payload
    assert "shopify" not in result_a.payload.keys()


@pytest.mark.parametrize(
    ("event_type", "expected_sdk"),
    [
        # The four semantically-valid canonical pairs map to BARE SDK names.
        ("commerce.product.viewed", "product_view"),
        ("commerce.cart.updated", "cart_updated"),
        ("commerce.checkout.started", "checkout_started"),
        # commerce.order.created must NOT map to order_confirmed — a
        # created-but-not-confirmed order passes through unmapped (never
        # reported as confirmed).
        ("commerce.order.created", "commerce.order.created"),
        ("commerce.order.confirmed", "order_confirmed"),
    ],
)
def test_envelope_bridge_maps_known_canonical_event_types(
    event_type: str, expected_sdk: str
) -> None:
    result = envelope_bridge(_make_canonical(event_type=event_type))
    assert result.sdk_event_type == expected_sdk
    assert result.canonical_event_type == event_type
    assert result.provider == "shopify"


def test_envelope_bridge_passes_through_unmapped_event_type() -> None:
    result = envelope_bridge(_make_canonical(event_type="comms.email.sent"))
    assert result.sdk_event_type == "comms.email.sent"
    assert result.canonical_event_type == "comms.email.sent"


def test_envelope_bridge_defaults_are_not_confirmed() -> None:
    result = envelope_bridge(_make_canonical())
    assert result.confirmed is False
    assert result.confirmation_state == "not_found"
    assert result.payload == {"order_id": "ord-1"}


# --- payload_bridge ----------------------------------------------------------


def test_payload_bridge_emits_json_safe_string_amount() -> None:
    snapshot = _make_snapshot(total=Money(amount=Decimal("19.99"), currency="USD"))
    result = payload_bridge(snapshot)

    total = result.payload["total"]
    assert isinstance(total["amount"], str)
    assert total["amount"] == "19.99"
    assert total["currency"] == "USD"


def test_payload_bridge_no_float_drift() -> None:
    # 0.1 is not exactly representable as a binary float; the bridge must emit
    # the exact decimal value as a STRING (model_dump(mode="json") semantics) —
    # never a Decimal object, never a binary float — so the value survives the
    # JSON boundary.
    snapshot = _make_snapshot(total=Money(amount=Decimal("0.1"), currency="USD"))
    total = payload_bridge(snapshot).payload["total"]
    assert isinstance(total["amount"], str)
    assert total["amount"] == "0.1"
    assert total["amount"] != float(0.1)  # "0.1" != binary float 0.1


def test_payload_bridge_shapes_pinned() -> None:
    result = payload_bridge(_make_snapshot())
    # sdk_event_type is the BARE SDK name; canonical_event_type stays the
    # dotted runtime type.
    assert result.sdk_event_type == "order_confirmed"
    assert result.canonical_event_type == "commerce.order.confirmed"
    assert result.provider == ""  # snapshot carries no provider lineage
    assert result.confirmed is False
    assert result.confirmation_state == "not_found"
    assert result.payload["order_id"] == "ord-1"
    assert result.payload["status"] == "paid"
    assert result.payload["currency"] == "USD"
    assert result.payload["total"] == {
        "amount": "19.99",  # exact decimal STRING, not Decimal, not float
        "currency": "USD",
    }
    assert result.payload["created_at"] == "2026-08-08T12:00:00+00:00"
    assert result.payload["updated_at"] == "2026-08-08T12:05:00+00:00"
    assert result.payload["account_id"] == "acc-1"


# --- confirm_interaction -----------------------------------------------------


def test_confirm_matched() -> None:
    signal = _make_signal("order_confirmed", lineage={"source_record_id": "rec-1"})
    canonical = _make_canonical(source_record_id="rec-1")
    result = confirm_interaction(signal, canonical)

    assert result.confirmed is True
    assert result.confirmation_state == "matched"
    assert result.sdk_event_type == "order_confirmed"  # BARE SDK name
    assert result.canonical_event_type == "commerce.order.confirmed"
    assert result.provider == "shopify"
    assert result.payload == {"order_id": "ord-1"}


def test_confirm_unconfirmed_on_lineage_mismatch() -> None:
    signal = _make_signal("order_confirmed", lineage={"source_record_id": "rec-2"})
    canonical = _make_canonical(source_record_id="rec-1")
    result = confirm_interaction(signal, canonical)

    # Never auto-confirm on a mismatch — confirmed stays False.
    assert result.confirmed is False
    assert result.confirmation_state == "unconfirmed"


def test_confirm_unconfirmed_when_lineage_missing() -> None:
    signal = _make_signal("order_confirmed", lineage={})
    canonical = _make_canonical(source_record_id="rec-1")
    result = confirm_interaction(signal, canonical)

    assert result.confirmed is False
    assert result.confirmation_state == "unconfirmed"


def test_confirm_replay_on_second_confirm_of_same_signal() -> None:
    # The runtime stamps confirmed signal ids into canonical.context; a signal
    # that already appears there is a replay, not a new confirmation.
    signal = _make_signal("order_confirmed", signal_id="sig-1")
    canonical = _make_canonical(
        source_record_id="rec-1", context={"confirmed_signal_ids": ["sig-1"]}
    )
    result = confirm_interaction(signal, canonical)

    assert result.confirmed is False
    assert result.confirmation_state == "replay"


def test_confirm_replay_guard_fails_closed_on_non_list_confirmed_signal_ids() -> None:
    # A malformed (non-list) confirmed_signal_ids — e.g. a stringified list —
    # means the replay state cannot be verified. Fail-closed: the signal must
    # NOT fall through to matched; it is treated as cannot-verify → unconfirmed.
    signal = _make_signal(
        "order_confirmed", signal_id="sig-1", lineage={"source_record_id": "rec-1"}
    )
    canonical = _make_canonical(
        source_record_id="rec-1", context={"confirmed_signal_ids": "['sig-1']"}
    )
    result = confirm_interaction(signal, canonical)

    assert result.confirmed is False
    assert result.confirmation_state == "unconfirmed"


def test_confirm_replay_requires_matching_lineage() -> None:
    # A signal stamped in context but with a non-matching lineage is still
    # unconfirmed — the replay branch must not fire past the lineage gate.
    signal = _make_signal(
        "order_confirmed", signal_id="sig-1", lineage={"source_record_id": "rec-9"}
    )
    canonical = _make_canonical(
        source_record_id="rec-1", context={"confirmed_signal_ids": ["sig-1"]}
    )
    result = confirm_interaction(signal, canonical)

    assert result.confirmed is False
    assert result.confirmation_state == "unconfirmed"


def test_confirm_not_found_when_canonical_missing() -> None:
    signal = _make_signal("order_confirmed", lineage={"source_record_id": "rec-1"})
    result = confirm_interaction(signal, None)

    assert result.confirmed is False
    assert result.confirmation_state == "not_found"
    assert result.canonical_event_type == ""
    assert result.provider == ""
    assert result.payload == {"order_id": "ord-1"}


def test_confirm_interaction_never_auto_confirms_on_mismatch() -> None:
    # Across every non-matched outcome, confirmed must be False.
    signal = _make_signal("order_confirmed", lineage={"source_record_id": "rec-2"})
    canonical = _make_canonical(source_record_id="rec-1")
    for outcome in (confirm_interaction(signal, canonical), confirm_interaction(signal, None)):
        assert outcome.confirmed is False


# --- extra="forbid" enforcement ----------------------------------------------


def test_sdk_signal_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        SDKCommerceSignal(
            signal_id="sig-1",
            signal_type="order_confirmed",
            occurred_at="2026-08-08T12:00:00+00:00",
            source_url="https://example.com",
            lineage={},
            payload={},
            unexpected=True,
        )


def test_bridge_result_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BridgeResult(
            sdk_event_type="order_confirmed",
            payload={},
            canonical_event_type="commerce.order.confirmed",
            provider="shopify",
            confirmed=True,
            confirmation_state="matched",
            unexpected=True,
        )


def test_sdk_signal_rejects_bad_signal_type() -> None:
    with pytest.raises(ValidationError):
        SDKCommerceSignal(
            signal_id="sig-1",
            signal_type="add_to_cart",  # type: ignore[arg-type]
            occurred_at="2026-08-08T12:00:00+00:00",
            source_url="https://example.com",
            lineage={},
            payload={},
        )


def test_bridge_result_rejects_bad_confirmation_state() -> None:
    with pytest.raises(ValidationError):
        BridgeResult(
            sdk_event_type="order_confirmed",
            payload={},
            canonical_event_type="commerce.order.confirmed",
            provider="shopify",
            confirmed=True,
            confirmation_state="pending",  # type: ignore[arg-type]
        )


# --- round-trip --------------------------------------------------------------


def test_models_round_trip() -> None:
    signal = _make_signal("cart_updated", lineage={"source_record_id": "rec-1"})
    assert SDKCommerceSignal.model_validate(signal.model_dump()) == signal

    result = confirm_interaction(signal, _make_canonical())
    assert BridgeResult.model_validate(result.model_dump()) == result
