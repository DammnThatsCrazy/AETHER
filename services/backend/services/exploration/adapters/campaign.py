"""campaign360 surface adapter — campaign-bucketed projection over the graph plane.

Nodes are bucketed by the campaign they are attributed to. Attribution here is
read from node properties already asserted upstream — the adapter does not
re-run attribution modelling.
"""

from __future__ import annotations

from typing import Any

from services.exploration.adapters.graph import GraphSurfaceAdapter


class CampaignSurfaceAdapter(GraphSurfaceAdapter):
    surface_id = "campaign360"

    def _reshape(self, response: Any) -> dict:
        nodes = [n.model_dump(mode="json") for n in response.nodes]
        campaigns: dict[str, int] = {}
        unattributed = 0
        for node in nodes:
            props = node.get("properties") or {}
            cid = props.get("attributed_campaign_id") or props.get("campaign_id")
            if cid:
                campaigns[str(cid)] = campaigns.get(str(cid), 0) + 1
            else:
                unattributed += 1
        return {
            "campaigns": [
                {"campaign_id": c, "count": n}
                for c, n in sorted(campaigns.items(), key=lambda x: (-x[1], x[0]))
            ],
            "unattributed_count": unattributed,
            "nodes": nodes,
        }


__all__ = ["CampaignSurfaceAdapter"]
