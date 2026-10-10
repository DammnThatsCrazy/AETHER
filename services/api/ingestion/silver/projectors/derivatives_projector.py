"""Silver projector for Derivatives Intelligence canonical events.

Projects every registry event of family `derivatives` with
silverProjection `derivatives_facts` into silver_derivatives_facts.
Observation-only: Aether never executes, places, or amends trades.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult
from .registry_handles import registry_handles


class DerivativesProjector(BaseProjector):
    handles = registry_handles("derivatives", "derivatives_facts")

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "event_type": event["type"],
            "entity_id": p.get("entity_id") or p.get("owner_id") or row.get("user_id"),
            "trading_account_id": p.get("trading_account_id"),
            "canonical_market_id": p.get("canonical_market_id"),
            "amount": p.get("amount") or p.get("quantity") or p.get("size"),
            "asset_id": p.get("asset_id") or p.get("settlement_asset_id"),
        })
        return ProjectionResult(table="silver_derivatives_facts", rows=[row])
