"""Silver projector for the friction event family."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_FRICTION_TYPES = frozenset({
    "dead_click_observed",
    "rage_click_observed",
    "scroll_depth_observed",
    "form_started",
    "form_field_interaction",
    "form_validation_failed",
    "form_submitted",
    "form_abandoned",
    "search_reformulated",
    "retry_observed",
    "journey_stalled",
    "backtrack_observed",
})


class FrictionProjector(BaseProjector):
    handles = _FRICTION_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "friction_type": event["type"],
            "element_selector": p.get("selector") or p.get("elementSelector"),
            "page_url": p.get("url") or p.get("pageUrl"),
            "scroll_depth_pct": p.get("scrollDepthPct") or p.get("scrollDepth"),
            "form_id": p.get("formId"),
            "field_name": p.get("fieldName"),
        })
        return ProjectionResult(table="silver_friction_facts", rows=[row])
