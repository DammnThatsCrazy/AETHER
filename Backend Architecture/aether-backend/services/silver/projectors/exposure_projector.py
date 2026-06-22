"""Silver projector for the exposure event family."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_EXPOSURE_TYPES = frozenset({
    "content_impression",
    "recommendation_exposed",
    "offer_exposed",
    "feature_exposed",
    "search_result_exposed",
    "ad_exposed",
    "notification_presented",
    "decision_observed",
})


class ExposureProjector(BaseProjector):
    handles = _EXPOSURE_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "content_type": p.get("contentType") or p.get("type"),
            "content_id": p.get("contentId") or p.get("itemId"),
            "recommendation_id": p.get("recommendationId"),
            "position": p.get("position"),
            "score": p.get("score"),
            "model_version": p.get("modelVersion"),
            "campaign_id": p.get("campaignId"),
        })
        return ProjectionResult(table="silver_exposure_facts", rows=[row])
