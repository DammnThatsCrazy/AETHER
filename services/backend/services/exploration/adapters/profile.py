"""Profile360 surface adapter — entity-centric projection over the graph plane.

profile360 is an anchored neighbourhood: the projection foregrounds the anchor
entity and its directly related nodes/edges. Data is read from the same real,
tenant-scoped Universal Graph Query plane; an anchorless or empty tenant yields
an honest empty profile, never a synthesised one.
"""

from __future__ import annotations

from typing import Any

from services.exploration.adapters.graph import GraphSurfaceAdapter


class ProfileSurfaceAdapter(GraphSurfaceAdapter):
    surface_id = "profile360"

    def _reshape(self, response: Any) -> dict:
        nodes = [n.model_dump(mode="json") for n in response.nodes]
        edges = [e.model_dump(mode="json") for e in response.edges]
        anchor_id = nodes[0]["id"] if nodes else None
        return {
            "anchor_id": anchor_id,
            "entity": nodes[0] if nodes else None,
            "related": nodes[1:],
            "edges": edges,
        }


__all__ = ["ProfileSurfaceAdapter"]
