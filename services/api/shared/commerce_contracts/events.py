"""Canonical commerce event-type vocabulary.

This module defines the provider-neutral *classification* of commerce event
types — which strings belong to the ``commerce.`` family and which of those
are canonical, curated event types the platform emits. It is deliberately
decoupled from any event envelope (e.g. ``shared.integration_contracts.events``
``AetherEvent``): these are pure string predicates over the ``event_type``
field, so they stay importable in every consumer regardless of envelope shape.
"""

from __future__ import annotations

from typing import Optional

# Curated set of canonical commerce event types the platform emits. Membership
# is what makes an event type "canonical"; other ``commerce.*`` event types
# remain valid family members but are not canonical.
COMMERCE_EVENT_FAMILIES: frozenset[str] = frozenset(
    {
        "commerce.order.created",
        "commerce.order.updated",
        "commerce.order.paid",
        "commerce.order.cancelled",
        "commerce.order.refunded",
        "commerce.cart.updated",
        "commerce.product.updated",
        "commerce.customer.created",
        "commerce.customer.updated",
    }
)


def commerce_event_family(event_type: str) -> Optional[str]:
    """Return ``"commerce"`` iff ``event_type`` starts with ``"commerce."``.

    Non-string inputs are not in the commerce family (defensive, never raised).
    """
    if not isinstance(event_type, str):
        return None
    return "commerce" if event_type.startswith("commerce.") else None


def is_commerce_event(event_type: str) -> bool:
    """True iff ``commerce_event_family(event_type) == "commerce"``."""
    return commerce_event_family(event_type) == "commerce"


def is_canonical_commerce_event(event_type: str) -> bool:
    """True iff ``event_type`` is in :data:`COMMERCE_EVENT_FAMILIES`."""
    return event_type in COMMERCE_EVENT_FAMILIES


__all__ = [
    "COMMERCE_EVENT_FAMILIES",
    "commerce_event_family",
    "is_canonical_commerce_event",
    "is_commerce_event",
]
