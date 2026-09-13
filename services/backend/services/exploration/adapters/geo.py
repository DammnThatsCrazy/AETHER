"""Geo surface adapter — geography-bucketed projection over the graph plane.

Nodes are bucketed by their country property. Buckets are returned raw here;
cohort-minimum suppression for small geographies is applied by
``services.exploration.facets`` when the geo view is requested as facets.
"""

from __future__ import annotations

from typing import Any

from services.exploration.adapters.graph import GraphSurfaceAdapter


class GeoSurfaceAdapter(GraphSurfaceAdapter):
    surface_id = "geo"

    def _reshape(self, response: Any) -> dict:
        nodes = [n.model_dump(mode="json") for n in response.nodes]
        countries: dict[str, int] = {}
        without_geo = 0
        for node in nodes:
            props = node.get("properties") or {}
            country = props.get("country") or props.get("geo_country")
            if country:
                countries[str(country)] = countries.get(str(country), 0) + 1
            else:
                without_geo += 1
        return {
            "countries": [
                {"country": c, "count": n}
                for c, n in sorted(countries.items(), key=lambda x: (-x[1], x[0]))
            ],
            "without_geo_count": without_geo,
            "nodes": nodes,
        }


__all__ = ["GeoSurfaceAdapter"]
