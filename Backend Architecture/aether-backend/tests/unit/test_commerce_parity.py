"""Envelope/payload parity pins for the S2 commerce-bridge follow-on.

Team B (commerce contracts) parity suite for the UPR follow-on. These tests
pin that the *canonical* commerce contracts — the :class:`AetherEvent` /
:class:`RawProviderRecord` envelope from ``shared.integration_contracts.events``
and the :class:`OrderSnapshot` / :class:`Money` payload from
``shared.commerce_contracts`` — are exactly consistent with the S2
commerce-bridge contract (``shared.integration_contracts.commerce_bridge``:
``SDKCommerceSignal``, ``BridgeResult``, ``envelope_bridge``, ``payload_bridge``,
``confirm_interaction``) that Team A is building in parallel.

Because the bridge module is an in-flight parallel delivery, the bridge-facing
assertions here are written two ways:

* unguarded parity pins against the canonical contracts (items 1–4 of the
  ownership brief), which run immediately; and
* introspection-only pins guarded by ``pytest.importorskip`` that activate once
  Team A's ``commerce_bridge.py`` lands, without assuming any signature that
  does not yet exist.

The default expectation is *no source changes* — these tests only observe and
pin the canonical contracts. If a parity test fails, it reports a genuine
cross-team gap rather than patching another team's file.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal

import pytest

from shared.commerce_contracts.events import (
    COMMERCE_EVENT_FAMILIES,
    commerce_event_family,
    is_canonical_commerce_event,
    is_commerce_event,
)
from shared.commerce_contracts.money import Currency, Money, money_from_cents, sum_money
from shared.commerce_contracts.order import (
    CommerceOrder,
    OrderCustomer,
    OrderLineItem,
    OrderSnapshot,
    OrderStatus,
    OrderTotals,
    order_to_snapshot,
)
from shared.integration_contracts.events import make_aether_event

# Backend root is three levels up (tests/unit -> tests -> aether-backend); the
# repo root (where packages/ lives) is one more.
BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, "..", ".."))
EVENT_REGISTRY = os.path.join(
    REPO_ROOT, "packages", "shared", "contracts", "event-registry.json"
)

# SDK EventType union: every registry event type is one member of it.
# ``_registryNotes`` carries the WS4 convergence tracker (runtime-domain
# commerce.* split is tracker-only — never an EventType-union edit).
_EVENT_REGISTRY_KEYS = (
    "_comment",
    "_registryNotes",
    "schemaVersion",
    "contractVersion",
    "events",
)

# ISO-4217 alphabetic code shape: three uppercase ASCII letters.
_ISO_4217_ALPHA = re.compile(r"^[A-Z]{3}$")

# Canonical dotted pattern the curated commerce families follow.
_CANONICAL_DOTTED = re.compile(r"^commerce\.[a-z]+(\.[a-z]+)*$")


# ── Fixtures / builders ─────────────────────────────────────────────────────


def _money(amount: str, currency: str = "USD") -> Money:
    return Money(amount=Decimal(amount), currency=currency)


def _order(**overrides) -> CommerceOrder:
    """A fully-valid single-currency commerce order (mirrors test_order)."""
    kwargs = dict(
        order_id="ord_parity_1",
        external_id="shopify-2001",
        account_id="acct_parity_1",
        status=OrderStatus.paid,
        currency="USD",
        totals=OrderTotals(
            subtotal=_money("20.00"),
            shipping=_money("2.00"),
            tax=_money("1.50"),
            discount=_money("0.50"),
            total=_money("23.00"),
        ),
        line_items=[
            OrderLineItem(
                line_item_id="li_parity_1",
                product_id="prod_parity_1",
                variant_id="var_parity_1",
                sku="SKU-PARITY-1",
                title="Widget",
                quantity=2,
                unit_price=_money("10.00"),
                line_total=_money("20.00"),
                attributes={"color": "blue"},
            )
        ],
        customer=OrderCustomer(
            customer_id="cus_parity_1",
            email="buyer@example.com",
            first_name="Ada",
            last_name="Lovelace",
        ),
        created_at="2026-08-08T12:00:00Z",
        updated_at="2026-08-08T12:30:00Z",
        note="parity fixture",
        properties={"channel": "web"},
    )
    kwargs.update(overrides)
    return CommerceOrder(**kwargs)


def _registry() -> dict:
    with open(EVENT_REGISTRY, encoding="utf-8") as fh:
        return json.load(fh)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Money exactness — Decimal everywhere, never float, ISO-4217 currency.
# ═══════════════════════════════════════════════════════════════════════════


class TestMoneyExactness:
    def test_money_amount_field_is_typed_decimal_never_float(self) -> None:
        # Schema-level pin: the canonical amount type is Decimal, so a bridge
        # payload serializing Money can never introduce float drift by typing.
        annotation = Money.model_fields["amount"].annotation
        assert annotation is Decimal

    def test_constructed_amounts_are_exact_decimal(self) -> None:
        m = Money(amount="12.34", currency="USD")
        assert isinstance(m.amount, Decimal)
        assert m.amount == Decimal("12.34")
        n = Money(amount=1200, currency="EUR")
        assert isinstance(n.amount, Decimal)
        assert n.amount == Decimal("1200")

    def test_currency_members_are_valid_iso_4217_codes(self) -> None:
        curated = {c.value for c in Currency}
        assert curated == {"USD", "EUR", "GBP", "CAD", "AUD"}
        for code in curated:
            assert _ISO_4217_ALPHA.fullmatch(code), code

    def test_money_round_trips_exactly_without_float_drift(self) -> None:
        # construct -> serialize (JSON mode) -> reconstruct must be byte-exact
        # in Decimal; the wire form is a str so no float ever appears.
        values = ("12.34", "0.01", "999.99", "123456789.12", "0.005", "1.005", "0.10")
        for raw in values:
            m = Money(amount=Decimal(raw), currency="USD")
            wire = m.model_dump(mode="json")
            assert isinstance(wire["amount"], str)
            assert wire["amount"] == format(Decimal(raw), "f")
            rebuilt = Money.model_validate(wire)
            assert rebuilt.amount == m.amount
            assert isinstance(rebuilt.amount, Decimal)

    def test_sum_money_preserves_exact_decimal(self) -> None:
        total = sum_money(
            [
                money_from_cents(12345, "USD"),
                money_from_cents(50, "USD"),
                money_from_cents(1, "USD"),
            ]
        )
        assert isinstance(total.amount, Decimal)
        assert total.amount == Decimal("123.96")
        assert total.currency == "USD"

    def test_money_from_cents_keeps_decimal_exactness(self) -> None:
        m = money_from_cents(12345, "USD")
        assert isinstance(m.amount, Decimal)
        assert m.amount == Decimal("123.45")
        # Construct -> serialize -> reconstruct keeps the exact Decimal.
        rebuilt = Money.model_validate(m.model_dump(mode="json"))
        assert rebuilt.amount == m.amount
        assert isinstance(rebuilt.amount, Decimal)


# ═══════════════════════════════════════════════════════════════════════════
# 2. OrderSnapshot envelope parity — snapshot rides AetherEvent.data intact.
# ═══════════════════════════════════════════════════════════════════════════


class TestOrderSnapshotEnvelopeParity:
    def test_snapshot_round_trips_through_aether_event_data(self) -> None:
        order = _order()
        snapshot = order_to_snapshot(order)
        event = make_aether_event(
            provider_identity="shopify.commerce.orders",
            event_type="commerce.order.created",
            event_family="commerce",
            tenant_id="tenant_parity_1",
            source_record_id="record_parity_1",
            data=snapshot.model_dump(mode="json"),
            account_id=order.account_id,
        )
        # The snapshot payload survives the envelope untouched.
        rebuilt = OrderSnapshot.model_validate(event.data)
        assert rebuilt == snapshot
        assert rebuilt.total == snapshot.total
        assert rebuilt.total.amount == snapshot.total.amount == order.totals.total.amount

    def test_event_metadata_aligns_with_payload(self) -> None:
        order = _order()
        snapshot = order_to_snapshot(order)
        event = make_aether_event(
            provider_identity="shopify.commerce.orders",
            event_type="commerce.order.created",
            event_family="commerce",
            tenant_id="tenant_parity_1",
            source_record_id="record_parity_1",
            data=snapshot.model_dump(mode="json"),
            account_id=order.account_id,
        )
        assert event.event_family == "commerce"
        assert event.account_id == order.account_id
        assert event.data["order_id"] == order.order_id
        assert event.data["currency"] == order.currency
        assert is_canonical_commerce_event(event.event_type)

    def test_snapshot_payload_is_json_serializable_from_the_event(self) -> None:
        # The bridge payload must be JSON-safe end-to-end: a Decimal-laden
        # snapshot in AetherEvent.data must serialize to JSON without coercion.
        order = _order()
        snapshot = order_to_snapshot(order)
        event = make_aether_event(
            provider_identity="shopify.commerce.orders",
            event_type="commerce.order.paid",
            event_family="commerce",
            tenant_id="tenant_parity_1",
            source_record_id="record_parity_1",
            data=snapshot.model_dump(mode="json"),
        )
        wire = event.model_dump(mode="json")
        json.dumps(wire)  # raises TypeError if any non-JSON value leaks through
        assert isinstance(wire["data"]["total"]["amount"], str)

    def test_order_to_snapshot_preserves_total_and_line_amounts_as_decimal(
        self,
    ) -> None:
        order = _order()
        snapshot = order_to_snapshot(order)
        assert isinstance(snapshot.total.amount, Decimal)
        assert snapshot.total.amount == order.totals.total.amount == Decimal("23.00")
        for line in order.line_items:
            assert isinstance(line.unit_price.amount, Decimal)
            assert isinstance(line.line_total.amount, Decimal)
        # The snapshot's total is the exact order total — never recomputed.
        assert snapshot.total.amount == Decimal("23.00")

    def test_snapshot_validates_from_arbitrary_provider_payload(self) -> None:
        # A bridge adapts a provider payload onto the canonical snapshot; the
        # snapshot must be constructible from JSON-shaped data (str amounts).
        data = {
            "order_id": "ord_parity_2",
            "status": "paid",
            "currency": "EUR",
            "total": {"amount": "42.99", "currency": "EUR"},
            "created_at": "2026-08-08T12:00:00Z",
            "updated_at": "2026-08-08T12:30:00Z",
            "account_id": "acct_parity_2",
        }
        snapshot = OrderSnapshot.model_validate(data)
        assert snapshot.total.amount == Decimal("42.99")
        assert isinstance(snapshot.total.amount, Decimal)
        assert snapshot.currency == "EUR"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Canonical event types — the 9 commerce.* families a BridgeResult carries.
# ═══════════════════════════════════════════════════════════════════════════


class TestCanonicalCommerceEventFamilies:
    def test_families_are_non_empty_and_curated_count(self) -> None:
        # B-7 relaxation: do NOT pin the exact curated count (==9). A
        # legitimate future 10th family (e.g. checkout.started) must not break
        # the suite, so assert a lower bound on the curated set instead; the
        # per-family canonicality of every member is pinned by the next test.
        assert COMMERCE_EVENT_FAMILIES
        assert len(COMMERCE_EVENT_FAMILIES) >= 9

    def test_every_family_is_a_canonical_dotted_commerce_string(self) -> None:
        for fam in sorted(COMMERCE_EVENT_FAMILIES):
            assert isinstance(fam, str)
            assert _CANONICAL_DOTTED.fullmatch(fam), fam
            assert commerce_event_family(fam) == "commerce"
            assert is_commerce_event(fam) is True
            assert is_canonical_commerce_event(fam) is True

    def test_families_cover_order_cart_product_customer_domains(self) -> None:
        # B-7 relaxation: the four curated domains must be PRESENT as a subset
        # of the family prefixes, not the exact prefix set — a future
        # checkout.started family adds a fifth domain ('checkout') without
        # removing any of the curated four.
        prefixes = {fam.split(".")[1] for fam in COMMERCE_EVENT_FAMILIES}
        curated_domains = {"order", "cart", "product", "customer"}
        assert curated_domains.issubset(prefixes)

    def test_every_family_is_usable_as_canonical_event_type_string(self) -> None:
        # A BridgeResult.canonical_event_type is a str field; every family is a
        # plain string, so any one of them can be carried verbatim.
        for fam in COMMERCE_EVENT_FAMILIES:
            assert isinstance(fam, str) and len(fam) > len("commerce.")
            assert fam.startswith("commerce.")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Dotted event-type rule — commerce.* stays runtime-domain (comms precedent).
# ═══════════════════════════════════════════════════════════════════════════


class TestDottedEventTypeSdkConvergence:
    def test_registry_shape(self) -> None:
        registry = _registry()
        assert tuple(registry) == _EVENT_REGISTRY_KEYS
        assert isinstance(registry["events"], list)

    def test_no_dotted_event_types_anywhere_in_sdk_registry(self) -> None:
        # Convergence-deferred (mirrors the comms precedent): the SDK EventType
        # union is underscore-named only; dotted runtime-domain types are
        # deferred to a later convergence and must NOT appear in the union.
        registry = _registry()
        assert all("." not in entry["type"] for entry in registry["events"])

    def test_canonical_commerce_families_are_not_in_sdk_eventtype_union(
        self,
    ) -> None:
        registry = _registry()
        sdk_types = {entry["type"] for entry in registry["events"]}
        overlap = COMMERCE_EVENT_FAMILIES & sdk_types
        assert overlap == set(), f"dotted commerce.* leaked into SDK union: {overlap}"

    def test_sdk_commerce_family_uses_underscore_names(self) -> None:
        # The SDK's commerce-family members are underscore-named
        # (payment_initiated, order_completed, ...) — the dotted canonical
        # runtime vocabulary is the deferred convergence gap, not the union.
        registry = _registry()
        sdk_commerce = [
            entry["type"]
            for entry in registry["events"]
            if entry.get("family") in ("commerce", "ecommerce")
        ]
        assert sdk_commerce
        assert all("." not in t for t in sdk_commerce)
        assert not COMMERCE_EVENT_FAMILIES.intersection(sdk_commerce)


# ═══════════════════════════════════════════════════════════════════════════
# S2 commerce-bridge parity (Team A in parallel) — introspection-only pins.
# ═══════════════════════════════════════════════════════════════════════════


class TestS2CommerceBridgeParity:
    """Pins the canonical side of the bridge parity once Team A's module lands.

    Guarded by ``pytest.importorskip`` so this suite passes in the current
    worktree (the bridge module does not exist yet) and activates, without any
    signature assumption, as soon as ``commerce_bridge.py`` is present.
    """

    def test_bridge_exports_the_s2_contract_surface(self) -> None:
        bridge = pytest.importorskip("shared.integration_contracts.commerce_bridge")
        for name in (
            "SDKCommerceSignal",
            "BridgeResult",
            "envelope_bridge",
            "payload_bridge",
            "confirm_interaction",
        ):
            assert hasattr(bridge, name), f"bridge missing {name}"

    def test_bridge_result_carries_every_canonical_family_as_str(self) -> None:
        bridge = pytest.importorskip("shared.integration_contracts.commerce_bridge")
        result = getattr(bridge, "BridgeResult", None)
        if result is None:
            pytest.fail("BridgeResult missing from bridge module")
        fields = getattr(result, "model_fields", {})
        if not fields:
            pytest.skip("BridgeResult is not a pydantic model with fields")
        assert "canonical_event_type" in fields, (
            "BridgeResult must carry canonical_event_type"
        )
        annotation = fields["canonical_event_type"].annotation
        assert annotation is str, annotation
        # Every curated family is the string form that field accepts.
        for fam in COMMERCE_EVENT_FAMILIES:
            assert isinstance(fam, str)
            assert is_canonical_commerce_event(fam)

    def test_payload_bridge_payload_validates_as_order_snapshot(self) -> None:
        # The bridge payload must BE the canonical OrderSnapshot shape: whatever
        # payload_bridge projects must validate back onto OrderSnapshot with
        # exact Decimal Money (no float drift on the wire).
        bridge = pytest.importorskip("shared.integration_contracts.commerce_bridge")
        snapshot = order_to_snapshot(_order())
        result = bridge.payload_bridge(snapshot)
        rebuilt = OrderSnapshot.model_validate(result.payload)
        assert rebuilt == snapshot
        assert rebuilt.total == snapshot.total
        assert isinstance(rebuilt.total.amount, Decimal)
        # B-9 relaxation: do NOT hard-pin the canonical label to the literal
        # 'commerce.order.confirmed'. Per DECISION 1, payload_bridge's
        # canonical_event_type stays a dotted commerce.* member while the sdk
        # side becomes the bare SDK name ('order_confirmed'); so here we assert
        # the canonical label is a valid commerce.* member — one of the curated
        # runtime families in this case it is NOT (the SDK-side confirmation
        # label is not a curated family), which is pinned by Team A's own
        # test_commerce_bridge.py.
        assert is_commerce_event(result.canonical_event_type)
        assert not is_canonical_commerce_event(result.canonical_event_type)

    def test_envelope_bridge_carries_every_canonical_family(self) -> None:
        # A canonical AetherEvent with any of the 9 commerce.* families must
        # bridge onto a BridgeResult that carries that exact family as
        # canonical_event_type and keeps the OrderSnapshot payload intact.
        bridge = pytest.importorskip("shared.integration_contracts.commerce_bridge")
        snapshot = order_to_snapshot(_order())
        for fam in sorted(COMMERCE_EVENT_FAMILIES):
            event = make_aether_event(
                provider_identity="shopify.commerce.orders",
                event_type=fam,
                event_family="commerce",
                tenant_id="tenant_parity_1",
                source_record_id="record_parity_1",
                data=snapshot.model_dump(mode="json"),
            )
            result = bridge.envelope_bridge(event)
            assert result.canonical_event_type == fam
            rebuilt = OrderSnapshot.model_validate(result.payload)
            assert rebuilt.total == snapshot.total
