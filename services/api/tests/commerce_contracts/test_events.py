"""Commerce event-type classification helpers."""

from __future__ import annotations

import pytest

from shared.commerce_contracts.events import (
    COMMERCE_EVENT_FAMILIES,
    commerce_event_family,
    is_canonical_commerce_event,
    is_commerce_event,
)


# ── commerce_event_family ──────────────────────────────────────────────────


def test_family_returns_commerce_for_commerce_prefix() -> None:
    assert commerce_event_family("commerce.order.created") == "commerce"
    assert commerce_event_family("commerce.cart.updated") == "commerce"
    assert commerce_event_family("commerce.order.paid") == "commerce"


def test_family_returns_none_for_non_commerce() -> None:
    assert commerce_event_family("shopify.order.created") is None
    assert commerce_event_family("order.created") is None
    assert commerce_event_family("") is None
    assert commerce_event_family("commerce") is None  # prefix requires "commerce."


def test_family_returns_none_for_non_strings() -> None:
    assert commerce_event_family(None) is None  # type: ignore[arg-type]
    assert commerce_event_family(42) is None  # type: ignore[arg-type]


# ── is_commerce_event ──────────────────────────────────────────────────────


def test_is_commerce_event() -> None:
    assert is_commerce_event("commerce.order.created") is True
    assert is_commerce_event("commerce.product.updated") is True
    assert is_commerce_event("shopify.order.created") is False
    assert is_commerce_event("order.created") is False
    assert is_commerce_event("commerce") is False


# ── is_canonical_commerce_event ────────────────────────────────────────────


def test_is_canonical_commerce_event() -> None:
    assert is_canonical_commerce_event("commerce.order.created") is True
    assert is_canonical_commerce_event("commerce.customer.updated") is True
    # A valid family member that is not in the curated canonical set.
    assert is_canonical_commerce_event("commerce.order.archived") is False
    assert is_canonical_commerce_event("shopify.order.created") is False
    assert is_canonical_commerce_event("order.created") is False


def test_is_canonical_commerce_event_non_strings_do_not_raise() -> None:
    # Membership in a frozenset[str] is safe for any input.
    assert is_canonical_commerce_event(None) is False  # type: ignore[arg-type]
    assert is_canonical_commerce_event(42) is False  # type: ignore[arg-type]


def test_every_canonical_event_is_also_a_commerce_event() -> None:
    # Canonical is a strict subset of the family.
    for event_type in COMMERCE_EVENT_FAMILIES:
        assert is_commerce_event(event_type) is True
        assert commerce_event_family(event_type) == "commerce"
        assert is_canonical_commerce_event(event_type) is True


def test_family_is_an_immutable_frozenset() -> None:
    assert isinstance(COMMERCE_EVENT_FAMILIES, frozenset)
    with pytest.raises(AttributeError):
        COMMERCE_EVENT_FAMILIES.add("commerce.order.archived")  # type: ignore[attr-defined]
