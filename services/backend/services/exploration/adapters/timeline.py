"""Timeline surface adapter — time-ordered projection over the graph plane.

Nodes are ordered by their most authoritative timestamp property (occurred_at,
then created/first-seen fallbacks). Nodes without a placeable timestamp are
reported separately rather than silently reordered to the front.
"""

from __future__ import annotations

from typing import Any, Optional

from services.exploration.adapters.graph import GraphSurfaceAdapter

_TIME_KEYS = ("occurred_at", "createdAt", "created_at", "first_seen", "valid_from")


def _timestamp(node: dict) -> Optional[str]:
    props = node.get("properties") or {}
    for key in _TIME_KEYS:
        val = props.get(key) or node.get(key)
        if val:
            return str(val)
    return None


class TimelineSurfaceAdapter(GraphSurfaceAdapter):
    surface_id = "timeline"

    def _reshape(self, response: Any) -> dict:
        nodes = [n.model_dump(mode="json") for n in response.nodes]
        placed = [(ts, n) for n in nodes if (ts := _timestamp(n)) is not None]
        placed.sort(key=lambda pair: pair[0])
        undated = [n for n in nodes if _timestamp(n) is None]
        return {
            "events": [
                {"at": ts, "node": n} for ts, n in placed
            ],
            "undated_count": len(undated),
            "undated": undated,
        }


__all__ = ["TimelineSurfaceAdapter"]
