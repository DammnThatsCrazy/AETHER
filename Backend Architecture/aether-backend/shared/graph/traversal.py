"""Aether Shared — @aether/graph/traversal
BFS graph traversal, shortest-path, and temporal graph reconstruction
over the pluggable GraphClient (in-memory or Neptune).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.graph.graph import Edge, GraphClient, Vertex

# A2A edge types that participate in agent-to-agent orchestration chains.
# Cycles through these edges are flagged in traversal metadata.
_A2A_EDGE_TYPES = frozenset({
    "HIRED", "SPAWNED_SUBAGENT", "DELEGATED_TO", "HANDED_OFF_TO",
    "DEPENDS_ON", "COMPOSED_WITH", "CALLED",
})


@dataclass
class TraversalResult:
    nodes: list[Vertex] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    a2a_cycles_detected: list[list[str]] = field(default_factory=list)


class GraphTraversalEngine:
    """BFS traversal, shortest-path, and temporal reconstruction over GraphClient."""

    def __init__(self, client: GraphClient) -> None:
        self._client = client

    async def bfs(
        self,
        start_id: str,
        depth: int,
        direction: str = "both",
        edge_types: Optional[list[str]] = None,
        limit: int = 100,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """BFS bounded neighbourhood traversal from start_id up to depth hops.

        Detects A2A cycles: if a vertex appears in the current active path
        while traversing A2A orchestration edges, the cycle is recorded in
        result.a2a_cycles_detected (as a list of vertex IDs) rather than
        raising an exception, preserving observability.

        When tenant_id is provided, traversal is scoped to vertices that carry
        a matching tenantId property. Cross-tenant vertices and their edges are
        silently dropped (fail-closed). This provides graph-level tenant
        isolation on top of the API-level _require_read check.
        """
        client = self._client
        visited: set[str] = {start_id}
        accepted: set[str] = {start_id}  # vertices that passed tenant check
        current_layer: list[str] = [start_id]
        result_nodes: list[Vertex] = []
        result_edges: list[Edge] = []
        seen_edge_keys: set[tuple[str, str, str]] = set()
        a2a_cycles: list[list[str]] = []

        for _ in range(depth):
            if not current_layer or len(result_nodes) >= limit:
                break
            next_layer: list[str] = []
            for vid in current_layer:
                if len(result_nodes) >= limit:
                    break
                edges = await client.get_edges(vid, direction=direction)
                for edge in edges:
                    if edge_types and edge.edge_type not in edge_types:
                        continue
                    neighbor_id = (
                        edge.to_vertex_id if edge.from_vertex_id == vid else edge.from_vertex_id
                    )
                    # A2A cycle detection: when an A2A orchestration edge leads back to
                    # an already-visited vertex, record the cycle pair for observability.
                    if edge.edge_type in _A2A_EDGE_TYPES and neighbor_id in visited:
                        a2a_cycles.append([vid, neighbor_id])
                        continue  # skip; do not re-traverse cyclic edge

                    neighbor_accepted = neighbor_id in accepted

                    if neighbor_id not in visited and len(result_nodes) < limit:
                        visited.add(neighbor_id)
                        neighbor = await client.get_vertex(neighbor_id)
                        if neighbor:
                            if tenant_id and neighbor.properties.get("tenantId") != tenant_id:
                                pass  # cross-tenant: fail closed, do not add
                            else:
                                accepted.add(neighbor_id)
                                neighbor_accepted = True
                                result_nodes.append(neighbor)
                                next_layer.append(neighbor_id)

                    # Only include edges where the neighbor vertex was accepted
                    if neighbor_accepted:
                        edge_key = (edge.from_vertex_id, edge.to_vertex_id, edge.edge_type)
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            result_edges.append(edge)
            current_layer = next_layer

        return TraversalResult(
            nodes=result_nodes,
            edges=result_edges,
            a2a_cycles_detected=a2a_cycles,
        )

    async def shortest_path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 6,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """BFS shortest path between two vertices. Returns empty result if no path exists.

        When tenant_id is provided, path search is restricted to vertices with a
        matching tenantId property (fail-closed cross-tenant isolation).
        """
        client = self._client
        if from_id == to_id:
            vertex = await client.get_vertex(from_id)
            return TraversalResult(nodes=[vertex] if vertex else [], edges=[])

        visited: set[str] = {from_id}
        # Queue entries: (current_id, path_vertex_ids, path_edges)
        queue: list[tuple[str, list[str], list[Edge]]] = [(from_id, [from_id], [])]

        while queue:
            current_id, path_ids, path_edges = queue.pop(0)
            if len(path_ids) > max_depth + 1:
                continue

            edges = await client.get_edges(current_id, direction="both")
            for edge in edges:
                neighbor_id = (
                    edge.to_vertex_id
                    if edge.from_vertex_id == current_id
                    else edge.from_vertex_id
                )
                new_path_ids = path_ids + [neighbor_id]
                new_path_edges = path_edges + [edge]

                if neighbor_id == to_id:
                    # Verify the destination vertex belongs to the tenant
                    if tenant_id:
                        dest = await client.get_vertex(neighbor_id)
                        if dest and dest.properties.get("tenantId") != tenant_id:
                            continue  # destination is cross-tenant; skip this path
                    vertices: list[Vertex] = []
                    for vid in new_path_ids:
                        v = await client.get_vertex(vid)
                        if v:
                            vertices.append(v)
                    return TraversalResult(nodes=vertices, edges=new_path_edges)

                if neighbor_id not in visited:
                    neighbor = await client.get_vertex(neighbor_id)
                    if neighbor:
                        if tenant_id and neighbor.properties.get("tenantId") != tenant_id:
                            visited.add(neighbor_id)  # mark visited to prevent retry
                            continue  # cross-tenant vertex: fail closed
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, new_path_ids, new_path_edges))

        return TraversalResult(nodes=[], edges=[])

    async def temporal_bfs(
        self,
        start_id: str,
        as_of: str,
        depth: int = 2,
        direction: str = "both",
        limit: int = 100,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """BFS traversal restricted to edges and vertices created at or before as_of (ISO8601).

        When tenant_id is provided, vertices with a mismatched tenantId property are
        silently dropped (fail-closed cross-tenant isolation).
        """
        client = self._client
        visited: set[str] = {start_id}
        accepted: set[str] = {start_id}
        current_layer: list[str] = [start_id]
        result_nodes: list[Vertex] = []
        result_edges: list[Edge] = []
        seen_edge_keys: set[tuple[str, str, str]] = set()

        for _ in range(depth):
            if not current_layer or len(result_nodes) >= limit:
                break
            next_layer: list[str] = []
            for vid in current_layer:
                if len(result_nodes) >= limit:
                    break
                edges = await client.get_edges(vid, direction=direction)
                for edge in edges:
                    if edge.created_at and edge.created_at > as_of:
                        continue
                    neighbor_id = (
                        edge.to_vertex_id if edge.from_vertex_id == vid else edge.from_vertex_id
                    )
                    neighbor_accepted = neighbor_id in accepted
                    if neighbor_id not in visited and len(result_nodes) < limit:
                        visited.add(neighbor_id)
                        neighbor = await client.get_vertex(neighbor_id)
                        if neighbor and (not neighbor.created_at or neighbor.created_at <= as_of):
                            if tenant_id and neighbor.properties.get("tenantId") != tenant_id:
                                pass  # cross-tenant: fail closed
                            else:
                                accepted.add(neighbor_id)
                                neighbor_accepted = True
                                result_nodes.append(neighbor)
                                next_layer.append(neighbor_id)
                    if neighbor_accepted:
                        edge_key = (edge.from_vertex_id, edge.to_vertex_id, edge.edge_type)
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            result_edges.append(edge)
            current_layer = next_layer

        return TraversalResult(nodes=result_nodes, edges=result_edges)
