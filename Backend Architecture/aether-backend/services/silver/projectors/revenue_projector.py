"""Silver projector for ecommerce / revenue events.

WS-D item 7 (Silver exact money / Invariant #13): when
``AETHER_SILVER_EXACT_MONEY_ENABLED`` is ON the projector emits the additive
``amount_exact`` / ``currency_exact`` columns via the canonical financial
exact-decimal machinery (``services.value.models.to_decimal_string``) and stops
collapsing a missing amount to ``0.0`` / a missing currency to ``'USD'``. OFF
(default) is byte-for-byte the historical behavior.
"""

from __future__ import annotations

from typing import Any
from shared.backend_interpretation.money import revenue_exact_money
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
        # WS-D item 7: exact-money column surface ({} when flag OFF).
        exact = revenue_exact_money(p)
        amount_raw = _first_present(p, ("amount", "total", "value"))
        if exact:
            # Money-exact path: a missing/unparseable amount is a typed absence
            # (None), never a fabricated 0.0; currency is never defaulted 'USD'.
            amount = _as_float(amount_raw)
            currency = p.get("currency")
        else:
            # Historical path preserved byte-for-byte when the flag is OFF.
            amount = _to_decimal(amount_raw)
            currency = p.get("currency", "USD")
        if evt_type in _MRR_INCREASING:
            mrr_delta = amount
        elif evt_type in _MRR_DECREASING:
            mrr_delta = -amount if amount is not None else None
        else:
            mrr_delta = None
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
        if exact:
            row.update(exact)  # amount_exact / currency_exact
        return ProjectionResult(table="silver_revenue_facts", rows=[row])


def _first_present(props: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = props.get(key)
        if value not in (None, ""):
            return value
    return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_decimal(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
