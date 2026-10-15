"""Silver projector for Stablecoin Intelligence canonical events.

Projects every registry event of family `stablecoin` with
silverProjection `stablecoin_facts` into silver_stablecoin_facts.
Observation-only: rows record externally executed activity.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult
from .registry_handles import registry_handles


class StablecoinProjector(BaseProjector):
    handles = registry_handles("stablecoin", "stablecoin_facts")

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "event_type": event["type"],
            "entity_id": p.get("entity_id") or p.get("from_entity_id") or row.get("user_id"),
            "deployment_id": p.get("deployment_id"),
            "canonical_asset_id": p.get("canonical_asset_id"),
            "chain_id": p.get("chain_id"),
            # Canonical amounts travel as decimal strings; the NUMERIC column
            # parses them server-side without float transit.
            "amount_decimal": p.get("amount_decimal"),
            "finality_status": p.get("finality_status", "provisional"),
        })
        return ProjectionResult(table="silver_stablecoin_facts", rows=[row])
