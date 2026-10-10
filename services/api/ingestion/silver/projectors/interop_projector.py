"""Silver projector for Interoperability Intelligence canonical events.

Projects every registry event of family `interop` with
silverProjection `interop_facts` into silver_interop_facts.
Observation-only: Aether never relays, routes, or recovers messages.
"""

from __future__ import annotations

from typing import Any

from .base import BaseProjector, ProjectionResult
from .registry_handles import registry_handles


class InteropProjector(BaseProjector):
    handles = registry_handles("interop", "interop_facts")

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "event_type": event["type"],
            "entity_id": p.get("entity_id") or p.get("initiator_entity_id") or row.get("user_id"),
            "provider_id": p.get("provider_id"),
            "path_id": p.get("path_id"),
            "interop_message_id": p.get("interop_message_id"),
            "status": p.get("status"),
            "amount_decimal": p.get("amount_decimal") or p.get("fee_total_decimal"),
        })
        return ProjectionResult(table="silver_interop_facts", rows=[row])
