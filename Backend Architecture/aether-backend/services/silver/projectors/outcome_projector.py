"""Silver projector for the outcome event family."""

from __future__ import annotations

from typing import Any
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
        row = self._base_row(event)
        row.update({
            "outcome_type": event["type"],
            "goal_id": p.get("goalId"),
            "recommendation_id": p.get("recommendationId"),
            "value_amount": p.get("value") or p.get("amount"),
            "value_currency": p.get("currency", "USD"),
            "succeeded": event["type"] in {"goal_achieved", "recommendation_accepted", "retention_observed"},
        })
        return ProjectionResult(table="silver_outcome_facts", rows=[row])
