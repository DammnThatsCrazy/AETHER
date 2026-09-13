"""cluster360 surface adapter — identity-cluster projection over the graph plane.

Nodes are grouped by their ``cluster_id`` property (the identity-cluster the
resolution plane assigned). Behavioural similarity is NEVER treated as identity
evidence here: grouping only reflects clusters already asserted upstream, it
does not infer new ones.
"""

from __future__ import annotations

from typing import Any

from services.exploration.adapters.graph import GraphSurfaceAdapter


class ClusterSurfaceAdapter(GraphSurfaceAdapter):
    surface_id = "cluster360"

    def _reshape(self, response: Any) -> dict:
        nodes = [n.model_dump(mode="json") for n in response.nodes]
        clusters: dict[str, list[str]] = {}
        for node in nodes:
            props = node.get("properties") or {}
            cluster_id = props.get("cluster_id") or props.get("entity_cluster_id")
            if not cluster_id:
                continue
            clusters.setdefault(str(cluster_id), []).append(node["id"])
        return {
            "clusters": [
                {"cluster_id": cid, "member_ids": members, "member_count": len(members)}
                for cid, members in sorted(clusters.items())
            ],
            "unclustered_count": sum(
                1
                for n in nodes
                if not ((n.get("properties") or {}).get("cluster_id")
                        or (n.get("properties") or {}).get("entity_cluster_id"))
            ),
            "nodes": nodes,
        }


__all__ = ["ClusterSurfaceAdapter"]
