"""Silver projector for ecommerce / revenue events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_REVENUE_TYPES = frozenset({
    "order_completed",
    "order_cancelled",
    "order_refunded",
    "subscription_started",
    "trial_started",
    "trial_converted",
    "subscription_renewed",
    "subscription_upgrade_observed",
    "subscription_downgrade_observed",
    "subscription_cancelled",
    "invoice_issued",
    "invoice_paid",
    "invoice_failed",
    "payment_intent_created",
    "payment_succeeded",
    "payment_failed",
    "chargeback_observed",
})

_MRR_INCREASING = frozenset({
    "subscription_started", "trial_converted", "subscription_renewed",
    "subscription_upgrade_observed", "invoice_paid",
})
_MRR_DECREASING = frozenset({
    "subscription_cancelled", "subscription_downgrade_observed",
    "order_refunded", "chargeback_observed",
})


class RevenueProjector(BaseProjector):
    handles = _REVENUE_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        evt_type = event["type"]
        amount = _to_decimal(p.get("amount") or p.get("total") or p.get("value") or 0)
        currency = p.get("currency", "USD")
        mrr_delta = amount if evt_type in _MRR_INCREASING else (-amount if evt_type in _MRR_DECREASING else None)
        row = self._base_row(event)
        row.update({
            "revenue_type": evt_type,
            "amount": amount,
            "currency": currency,
            "product_id": p.get("productId"),
            "plan_id": p.get("planId"),
            "subscription_id": p.get("subscriptionId"),
            "invoice_id": p.get("invoiceId"),
            "mrr_delta": mrr_delta,
            "arr_delta": mrr_delta * 12 if mrr_delta is not None else None,
            "payment_method": p.get("paymentMethod"),
        })
        return ProjectionResult(table="silver_revenue_facts", rows=[row])


def _to_decimal(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
