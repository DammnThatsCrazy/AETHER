"""Provider identity: round-trip parse/format and per-capability distinctness."""

from __future__ import annotations

import pytest

from shared.integration_contracts.identity import (
    CANONICAL_CAPABILITY_KEYS,
    CapabilityKey,
    IdentityError,
    ProviderIdentity,
    format_identity,
    is_canonical_capability,
    parse_capability_key,
    parse_identity,
)


def test_identity_parse_format_round_trip() -> None:
    raw = "shopify.admin.orders_read"
    ident = parse_identity(raw)
    assert ident.family == "shopify"
    assert ident.product == "admin"
    assert ident.capability == "orders_read"
    assert ident.key == raw
    assert str(ident) == raw
    # format helper is the inverse of parse
    assert format_identity("shopify", "admin", "orders_read") == raw


def test_identity_rejects_wrong_arity_and_bad_segments() -> None:
    # Parse/format helpers raise the module error type for any malformation.
    with pytest.raises(IdentityError):
        parse_identity("shopify.admin")  # only two segments
    with pytest.raises(IdentityError):
        parse_identity("shopify.admin.orders.read")  # four segments
    with pytest.raises(IdentityError):
        parse_identity("Shopify.admin.orders_read")  # bad segment via helper
    # Direct model construction surfaces pydantic's ValidationError (a ValueError).
    with pytest.raises(ValueError):
        ProviderIdentity(family="Shopify", product="admin", capability="orders_read")
    with pytest.raises(ValueError):
        ProviderIdentity(family="shopify", product="admin", capability="orders-read")


def test_per_capability_distinctness() -> None:
    """A capability is never implicitly widened to a sibling capability."""
    orders = ProviderIdentity(family="shopify", product="admin", capability="orders_read")
    customers = ProviderIdentity(
        family="shopify", product="admin", capability="customers_read"
    )
    # Same family+product, different capability -> distinct identity + key.
    assert orders != customers
    assert orders.key != customers.key
    assert hash(orders) != hash(customers)
    # Distinct as dict keys / set members (identity is per-capability).
    registry = {orders: "flag_a", customers: "flag_b"}
    assert len(registry) == 2
    assert registry[orders] != registry[customers]


def test_identity_is_frozen() -> None:
    ident = parse_identity("stripe.core.payments_read")
    with pytest.raises(Exception):
        ident.capability = "refunds_read"  # type: ignore[misc]


def test_capability_key_round_trip_and_canonical() -> None:
    key = parse_capability_key("commerce.orders.read")
    assert key.domain == "commerce"
    assert key.resource == "orders"
    assert key.action == "read"
    assert key.value == "commerce.orders.read"
    assert str(key) == "commerce.orders.read"
    assert key.is_canonical is True
    assert is_canonical_capability("commerce.orders.read") is True
    # Every documented canonical key parses and is flagged canonical.
    for raw in CANONICAL_CAPABILITY_KEYS:
        assert CapabilityKey.parse(raw).is_canonical is True


def test_capability_key_non_canonical_and_malformed() -> None:
    # Well-formed but not in the canonical set.
    assert is_canonical_capability("commerce.refunds.read") is False
    # Malformed -> not canonical, no exception from the helper.
    assert is_canonical_capability("commerce.orders") is False
    with pytest.raises(IdentityError):
        parse_capability_key("commerce.orders")
