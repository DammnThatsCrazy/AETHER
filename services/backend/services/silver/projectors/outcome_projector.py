"""Silver projector for the outcome event family.

WS-D item 7 (Silver exact money / Invariant #13): when
``AETHER_SILVER_EXACT_MONEY_ENABLED`` is ON the projector emits the additive
``value_amount_exact`` / ``value_currency_exact`` columns via the canonical
financial exact-decimal machinery and stops defaulting a missing currency to
``'USD'``. OFF (default) is byte-for-byte the historical behavior.
"""

from __future__ import annotations

from typing import Any
from shared.backend_interpretation.money import outcome_exact_money
from .base import BaseProjector, ProjectionResult

_OUTCOME_TYPES = frozenset({
    "outcome_observed",
    "goal_achieved",
    "goal_failed",
    "recommendation_accepted",
    "recommendation_rejected",
    "feedback_submitted",
    "retention_observed",
    "churn_observed",
    "human_override_observed",
})


class OutcomeProjector(BaseProjector):
    handles = _OUTCOME_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        exact = outcome_exact_money(p)
        row = self._base_row(event)
        value_amount = p.get("value") or p.get("amount")
        if exact:
            # Money-exact path: value_amount is the numeric present value (None
            # when absent) and value_currency is never defaulted 'USD'.
            value_amount = _as_float(value_amount)
            value_currency = p.get("currency")
        else:
            value_currency = p.get("currency", "USD")
        row.update({
            "outcome_type": event["type"],
            "goal_id": p.get("goalId"),
            "recommendation_id": p.get("recommendationId"),
            "value_amount": value_amount,
            "value_currency": value_currency,
            "succeeded": event["type"] in {"goal_achieved", "recommendation_accepted", "retention_observed"},
        })
        if exact:
            row.update(exact)  # value_amount_exact / value_currency_exact
        return ProjectionResult(table="silver_outcome_facts", rows=[row])


def _as_float(value: Any) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
