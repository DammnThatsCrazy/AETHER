"""Shared fakes + builders for exploration-fabric unit tests."""
from __future__ import annotations

from typing import Any, Optional

from shared.exploration.models import ExplorationContextV1


def context(
    surface: str,
    expressions: Optional[list[dict]] = None,
    *,
    tenant_id: str = "t1",
    logic: str = "AND",
    anchors: Optional[list[dict]] = None,
    temporal_mode: str = "window",
) -> ExplorationContextV1:
    """Build a valid ExplorationContextV1 for a surface with a flat filter group."""
    payload: dict[str, Any] = {
        "scope": {"tenant_id": tenant_id, "surface": surface},
        "temporal": {"mode": temporal_mode, "field": "occurred_at", "timezone": "UTC"},
    }
    if expressions is not None:
        payload["population"] = {"logic": logic, "expressions": expressions}
    if anchors is not None:
        payload["anchors"] = anchors
    return ExplorationContextV1(**payload)


class FakeGraphMeta:
    def __init__(self, *, node_count: int, truncated: bool = False, reason=None, cursor=None):
        self.node_count = node_count
        self.truncated = truncated
        self.truncation_reason = reason
        self.cursor = cursor
        self.warnings: list[str] = []


class FakeGraphNode:
    def __init__(self, node_id: str, properties: Optional[dict] = None):
        self._id = node_id
        self._props = properties or {}

    def model_dump(self, mode: str = "json") -> dict:
        return {"id": self._id, "kind": "entity", "properties": self._props}


class FakeGraphResponse:
    def __init__(self, nodes: list[FakeGraphNode], *, truncated: bool = False, reason=None, cursor=None):
        self.nodes = nodes
        self.edges: list[Any] = []
        self.meta = FakeGraphMeta(
            node_count=len(nodes), truncated=truncated, reason=reason, cursor=cursor
        )


def fake_graph_runner(response: FakeGraphResponse):
    """Return an async delegation seam that ignores its args and yields `response`."""

    async def _run(body, request, graph, cache):  # noqa: ANN001
        return response

    return _run
