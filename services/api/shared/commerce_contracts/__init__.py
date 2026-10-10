"""Canonical commerce domain vocabulary for the Universal Provider Runtime.

This package is the provider-neutral vocabulary of commerce concepts that the
UPR exposes to adapters and downstream consumers. It is fully self-contained
(standard library + pydantic only) and must never import from
``shared.integration_contracts`` or any service/HTTP/DB layer.

* :mod:`money` — :class:`Money`, :class:`Currency`, and money helpers
  (:func:`~.money.sum_money`, :func:`~.money.money_from_cents`,
  :func:`~.money.to_cents`).
* :mod:`order` — the canonical order vocabulary
  (:class:`~.order.CommerceOrder`), its closed sub-models, and the
  :class:`~.order.OrderSnapshot` projection used as an event payload.
* :mod:`events` — commerce event-type family classification.

Consumers (e.g. the Shopify plugin) import repo-absolutely, e.g.
``from shared.commerce_contracts.order import CommerceOrder``.
"""

from __future__ import annotations

from shared.commerce_contracts.events import (
    COMMERCE_EVENT_FAMILIES,
    commerce_event_family,
    is_canonical_commerce_event,
    is_commerce_event,
)
from shared.commerce_contracts.money import (
    Currency,
    Money,
    money_from_cents,
    sum_money,
    to_cents,
)
from shared.commerce_contracts.order import (
    CommerceOrder,
    OrderCustomer,
    OrderLineItem,
    OrderSnapshot,
    OrderStatus,
    OrderTotals,
    order_to_snapshot,
)

__all__ = [
    # money
    "Currency",
    "Money",
    "money_from_cents",
    "sum_money",
    "to_cents",
    # order
    "CommerceOrder",
    "OrderCustomer",
    "OrderLineItem",
    "OrderSnapshot",
    "OrderStatus",
    "OrderTotals",
    "order_to_snapshot",
    # events
    "COMMERCE_EVENT_FAMILIES",
    "commerce_event_family",
    "is_canonical_commerce_event",
    "is_commerce_event",
]
