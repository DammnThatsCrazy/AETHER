"""Persist source-reported cart and checkout events with an explicit catalog key.

The event properties are source assertions. A Commerce360 read verifies the
tenant-owned product or offer before it joins these facts; the projector does
not assert a purchase, a current cart state, or a successful checkout.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult


_FLOW_TYPES = frozenset(
    {
        "cart_item_added",
        "cart_item_removed",
        "cart_updated",
        "checkout_started",
        "checkout_step_completed",
    }
)


def _identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 256 or any(ord(char) < 32 for char in value):
        return None
    return value


class CommerceFlowProjector(BaseProjector):
    """One Silver observation for one exact, source-asserted catalog subject."""

    handles = _FLOW_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        event_type = event.get("type")
        if event_type not in self.handles:
            return None
        properties = self._props(event)
        product_id = _identifier(properties.get("productId"))
        offer_id = _identifier(properties.get("offerId"))
        if bool(product_id) == bool(offer_id):
            return ProjectionResult(
                table="silver_commerce_flow_facts",
                rows=[],
                skipped=True,
                skip_reason="missing_or_ambiguous_catalog_subject",
            )
        row = self._base_row(event)
        row.update(
            {
                "subject_kind": "product" if product_id else "offer",
                "subject_id": product_id or offer_id,
                "cart_id": _identifier(properties.get("cartId")),
                "checkout_id": _identifier(properties.get("checkoutId")),
                "flow_event_type": event_type,
                # Store only the bounded fields used by this projection. No
                # cart contents, prices, customer data, or raw SDK properties.
                "payload": {},
            }
        )
        return ProjectionResult(table="silver_commerce_flow_facts", rows=[row])


__all__ = ["CommerceFlowProjector"]
