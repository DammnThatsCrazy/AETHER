"""Aether Shared — @aether/graph/traversal
BFS graph traversal, shortest-path, and temporal graph reconstruction
over the pluggable GraphClient (in-memory or Neptune).
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.path_scoring import classify_path, compute_evidence_coverage, make_path_id, score_path

def _edge_key(edge: Edge) -> str:
    """Stable synthetic edge identifier derived from the edge's three-part key."""
    return f"{edge.from_vertex_id}:{edge.to_vertex_id}:{edge.edge_type}"


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
    ordered_node_ids: list[str] = field(default_factory=list)
    ordered_edge_ids: list[str] = field(default_factory=list)


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
        """BFS traversal restricted to edges/vertices valid at as_of (ISO8601).

        Applies bitemporal valid-time filtering:
          - valid_from <= as_of  (edge/node must have started being true)
          - valid_to is absent OR valid_to > as_of  (not yet expired)

        Falls back to created_at when valid_from is absent, preserving
        compatibility with edges written before Phase 3.

        When tenant_id is provided, vertices with a mismatched tenantId property
        are silently dropped (fail-closed cross-tenant isolation).
        """
        client = self._client
        visited: set[str] = {start_id}
        accepted: set[str] = {start_id}
        current_layer: list[str] = [start_id]
        result_nodes: list[Vertex] = []
        result_edges: list[Edge] = []
        seen_edge_keys: set[tuple[str, str, str]] = set()

        def _edge_valid_at(edge: Edge) -> bool:
            """Return True if edge's valid-time window covers as_of."""
            ef = edge.properties.get("valid_from") or edge.created_at or ""
            et = edge.properties.get("valid_to") or ""
            if ef and ef > as_of:
                return False  # edge hasn't started yet
            if et and et <= as_of:
                return False  # edge has expired
            return True

        def _vertex_valid_at(v: Vertex) -> bool:
            """Return True if vertex's valid-time window covers as_of."""
            vf = v.properties.get("valid_from") or v.created_at or ""
            vt = v.properties.get("valid_to") or ""
            if vf and vf > as_of:
                return False
            if vt and vt <= as_of:
                return False
            return True

        for _ in range(depth):
            if not current_layer or len(result_nodes) >= limit:
                break
            next_layer: list[str] = []
            for vid in current_layer:
                if len(result_nodes) >= limit:
                    break
                edges = await client.get_edges(vid, direction=direction)
                for edge in edges:
                    if not _edge_valid_at(edge):
                        continue
                    neighbor_id = (
                        edge.to_vertex_id if edge.from_vertex_id == vid else edge.from_vertex_id
                    )
                    neighbor_accepted = neighbor_id in accepted
                    if neighbor_id not in visited and len(result_nodes) < limit:
                        visited.add(neighbor_id)
                        neighbor = await client.get_vertex(neighbor_id)
                        if neighbor and _vertex_valid_at(neighbor):
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

        return TraversalResult(nodes=result_nodes, edges=result_edges)  # temporal_bfs

    async def strongest_path(
        self,
        from_id: str,
        to_id: str,
        max_depth: int = 6,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """Confidence-weighted Dijkstra: find the path with the highest aggregate confidence.

        Edge cost = 1.0 - confidence, so low-cost paths are high-confidence paths.
        Applies the same two-set tenant isolation pattern as bfs() and shortest_path().
        Returns an empty TraversalResult when no path exists.
        """
        client = self._client
        if from_id == to_id:
            vertex = await client.get_vertex(from_id)
            result = TraversalResult(
                nodes=[vertex] if vertex else [],
                ordered_node_ids=[from_id] if vertex else [],
            )
            return result

        # cost_to[v] = best accumulated cost to reach v
        cost_to: dict[str, float] = {from_id: 0.0}
        # prev[v] = (predecessor_id, edge_that_led_here)
        prev: dict[str, tuple[str, Edge]] = {}
        visited: set[str] = set()
        accepted: set[str] = {from_id}

        # heap entries: (cost, vertex_id)
        heap: list[tuple[float, str]] = [(0.0, from_id)]

        while heap:
            cost, current_id = heapq.heappop(heap)
            if current_id in visited:
                continue
            visited.add(current_id)

            if current_id == to_id:
                break

            # Depth guard: count hops from from_id to current_id via prev chain
            hop_count = 0
            _tmp = current_id
            while _tmp in prev:
                hop_count += 1
                _tmp = prev[_tmp][0]
            if hop_count >= max_depth:
                continue

            edges = await client.get_edges(current_id, direction="both")
            for edge in edges:
                neighbor_id = (
                    edge.to_vertex_id if edge.from_vertex_id == current_id else edge.from_vertex_id
                )
                if neighbor_id in visited:
                    continue

                # Tenant isolation: check and cache acceptance
                if neighbor_id not in accepted:
                    neighbor = await client.get_vertex(neighbor_id)
                    if not neighbor:
                        continue
                    if tenant_id and neighbor.properties.get("tenantId") != tenant_id:
                        continue  # cross-tenant: fail closed
                    accepted.add(neighbor_id)

                confidence = float(
                    edge.properties.get("confidence", 1.0) if edge.properties else 1.0
                )
                edge_cost = 1.0 - confidence
                new_cost = cost + edge_cost

                if new_cost < cost_to.get(neighbor_id, float("inf")):
                    cost_to[neighbor_id] = new_cost
                    prev[neighbor_id] = (current_id, edge)
                    heapq.heappush(heap, (new_cost, neighbor_id))

        if to_id not in prev and from_id != to_id:
            return TraversalResult()

        # Reconstruct path by walking prev backwards
        ordered_node_ids: list[str] = []
        ordered_edge_ids: list[str] = []
        path_edges: list[Edge] = []
        current = to_id
        while current in prev:
            pred_id, edge = prev[current]
            ordered_node_ids.append(current)
            ordered_edge_ids.append(_edge_key(edge))
            path_edges.append(edge)
            current = pred_id
        ordered_node_ids.append(from_id)
        ordered_node_ids.reverse()
        ordered_edge_ids.reverse()
        path_edges.reverse()

        vertices: list[Vertex] = []
        for vid in ordered_node_ids:
            v = await client.get_vertex(vid)
            if v:
                vertices.append(v)

        return TraversalResult(
            nodes=vertices,
            edges=path_edges,
            ordered_node_ids=ordered_node_ids,
            ordered_edge_ids=ordered_edge_ids,
        )

    async def k_shortest_paths(
        self,
        from_id: str,
        to_id: str,
        k: int = 3,
        max_depth: int = 6,
        tenant_id: Optional[str] = None,
    ) -> list[TraversalResult]:
        """Yen's K-shortest simple paths algorithm.

        Returns up to k TraversalResults ordered by ascending accumulated cost.
        Deduplicates by make_path_id(ordered_node_ids).
        Applies the same tenant isolation pattern as shortest_path().
        """
        from shared.graph.path_scoring import make_path_id as _make_path_id

        # A set of candidate paths (spur-based candidates not yet confirmed)
        A: list[TraversalResult] = []  # confirmed k-shortest paths
        B: list[tuple[float, TraversalResult]] = []  # candidate heap
        seen_path_ids: set[str] = set()

        # Find the first shortest path using BFS (uniform cost = 1 per hop)
        first = await self.shortest_path(from_id, to_id, max_depth=max_depth, tenant_id=tenant_id)
        if not first.nodes:
            return []
        # Assign ordered_node_ids/ordered_edge_ids from shortest_path result if missing
        if not first.ordered_node_ids and first.nodes:
            first.ordered_node_ids = [v.vertex_id for v in first.nodes]
            first.ordered_edge_ids = [_edge_key(e) for e in first.edges]

        pid = _make_path_id(first.ordered_node_ids)
        if pid not in seen_path_ids:
            seen_path_ids.add(pid)
            A.append(first)

        for _ in range(k - 1):
            if not A:
                break
            last_path = A[-1]
            last_node_ids = last_path.ordered_node_ids

            for i in range(len(last_node_ids) - 1):
                spur_node = last_node_ids[i]
                root_path_ids = last_node_ids[: i + 1]
                root_path_edge_ids = last_path.ordered_edge_ids[:i]

                # Collect edges to temporarily hide (used by existing confirmed paths with same root)
                blocked_edges: set[tuple[str, str, str]] = set()
                for path in A:
                    if path.ordered_node_ids[: i + 1] == root_path_ids:
                        if i < len(path.ordered_edge_ids):
                            e_id = path.ordered_edge_ids[i]
                            # Store as (edge_id,) — we'll filter by ID in the sub-search
                            blocked_edges.add((e_id, "", ""))

                # Blocked root nodes (avoid revisiting root path nodes except spur)
                blocked_nodes: set[str] = set(root_path_ids[:-1])

                spur_result = await self._shortest_path_excluding(
                    spur_node, to_id,
                    blocked_edge_ids={t[0] for t in blocked_edges},
                    blocked_node_ids=blocked_nodes,
                    max_depth=max_depth,
                    tenant_id=tenant_id,
                )
                if not spur_result.nodes:
                    continue

                spur_node_ids = spur_result.ordered_node_ids or [v.vertex_id for v in spur_result.nodes]
                spur_edge_ids = spur_result.ordered_edge_ids or [_edge_key(e) for e in spur_result.edges]

                total_node_ids = root_path_ids + spur_node_ids[1:]
                total_edge_ids = root_path_edge_ids + spur_edge_ids

                pid = _make_path_id(total_node_ids)
                if pid in seen_path_ids:
                    continue
                seen_path_ids.add(pid)

                # Build merged vertex list
                vertices: list[Vertex] = []
                for vid in total_node_ids:
                    v = await self._client.get_vertex(vid)
                    if v:
                        vertices.append(v)

                # Build merged edge list
                merged_edges = last_path.edges[:i] + spur_result.edges

                candidate = TraversalResult(
                    nodes=vertices,
                    edges=merged_edges,
                    ordered_node_ids=total_node_ids,
                    ordered_edge_ids=total_edge_ids,
                )
                cost = sum(
                    1.0 - float(e.properties.get("confidence", 1.0) if e.properties else 1.0)
                    for e in merged_edges
                )
                heapq.heappush(B, (cost, candidate))  # type: ignore[misc]

            if not B:
                break
            _, next_path = heapq.heappop(B)
            A.append(next_path)

        return A[:k]

    async def _shortest_path_excluding(
        self,
        from_id: str,
        to_id: str,
        blocked_edge_ids: set[str],
        blocked_node_ids: set[str],
        max_depth: int = 6,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """BFS shortest path that skips specific edges and nodes (used by Yen's algorithm)."""
        client = self._client
        if from_id == to_id:
            vertex = await client.get_vertex(from_id)
            nodes = [vertex] if vertex else []
            return TraversalResult(
                nodes=nodes,
                ordered_node_ids=[from_id] if vertex else [],
            )

        visited: set[str] = {from_id} | blocked_node_ids
        queue: deque[tuple[str, list[str], list[Edge]]] = deque(
            [(from_id, [from_id], [])]
        )

        while queue:
            current_id, path_ids, path_edges = queue.popleft()
            if len(path_ids) > max_depth + 1:
                continue

            edges = await client.get_edges(current_id, direction="both")
            for edge in edges:
                if _edge_key(edge) in blocked_edge_ids:
                    continue
                neighbor_id = (
                    edge.to_vertex_id if edge.from_vertex_id == current_id else edge.from_vertex_id
                )
                if neighbor_id in blocked_node_ids:
                    continue

                new_path_ids = path_ids + [neighbor_id]
                new_path_edges = path_edges + [edge]

                if neighbor_id == to_id:
                    if tenant_id:
                        dest = await client.get_vertex(neighbor_id)
                        if dest and dest.properties.get("tenantId") != tenant_id:
                            continue
                    vertices: list[Vertex] = []
                    for vid in new_path_ids:
                        v = await client.get_vertex(vid)
                        if v:
                            vertices.append(v)
                    return TraversalResult(
                        nodes=vertices,
                        edges=new_path_edges,
                        ordered_node_ids=new_path_ids,
                        ordered_edge_ids=[_edge_key(e) for e in new_path_edges],
                    )

                if neighbor_id not in visited:
                    neighbor = await client.get_vertex(neighbor_id)
                    if neighbor:
                        if tenant_id and neighbor.properties.get("tenantId") != tenant_id:
                            visited.add(neighbor_id)
                            continue
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, new_path_ids, new_path_edges))

        return TraversalResult()

    async def multi_source_bfs(
        self,
        start_ids: list[str],
        depth: int,
        direction: str = "both",
        edge_types: Optional[list[str]] = None,
        limit: int = 100,
        tenant_id: Optional[str] = None,
    ) -> TraversalResult:
        """BFS seeded from multiple start nodes simultaneously.

        All start_ids share the same visited/accepted sets so duplicate neighbors
        from different seeds are fetched only once. Returns a merged TraversalResult
        (union of all reachable nodes/edges within depth hops).
        """
        client = self._client
        visited: set[str] = set(start_ids)
        accepted: set[str] = set(start_ids)
        current_layer: list[str] = list(start_ids)
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
                    if edge_types and edge.edge_type not in edge_types:
                        continue
                    neighbor_id = (
                        edge.to_vertex_id if edge.from_vertex_id == vid else edge.from_vertex_id
                    )
                    neighbor_accepted = neighbor_id in accepted
                    if neighbor_id not in visited and len(result_nodes) < limit:
                        visited.add(neighbor_id)
                        neighbor = await client.get_vertex(neighbor_id)
                        if neighbor:
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

        return TraversalResult(nodes=result_nodes, edges=result_edges)  # multi_source_bfs


def _build_path_explanation(path: "RelationshipPath") -> "PathExplanation":  # type: ignore[name-defined]
    """Generate a human-readable PathExplanation from a RelationshipPath.

    Produces why_connected prose and per-hop narrative from layer_sequence and node kinds/labels.
    causal_language_allowed is False when classification is 'correlated'.
    """
    from datetime import datetime, timezone

    hop_narrative: list[str] = []
    nodes = path.nodes
    edges = path.edges

    for i, edge in enumerate(edges):
        src = nodes[i] if i < len(nodes) else None
        dst = nodes[i + 1] if (i + 1) < len(nodes) else None
        src_label = (src.label or src.kind) if src else edge.from_
        dst_label = (dst.label or dst.kind) if dst else edge.to
        hop_narrative.append(
            f"Hop {i + 1}: {src_label} —[{edge.type}]→ {dst_label} (layer: {edge.layer})"
        )

    if nodes:
        start_label = nodes[0].label or nodes[0].kind
        end_label = nodes[-1].label or nodes[-1].kind
    else:
        start_label = path.source_id
        end_label = path.target_id

    layer_str = " → ".join(path.layer_sequence) if path.layer_sequence else "unknown"
    why_connected = (
        f"{start_label} is connected to {end_label} through {path.hop_count} hop(s) "
        f"via layers: {layer_str}. Path confidence: {path.path_confidence:.2%}."
    )

    summary = (
        f"{path.hop_count}-hop {path.classification} path from {start_label} to {end_label} "
        f"(confidence {path.path_confidence:.2%}, coverage {path.evidence_coverage:.0%})"
    )

    causal_language_allowed = path.classification not in ("correlated",)

    return {
        "path_id": path.path_id,
        "summary": summary,
        "why_connected": why_connected,
        "hop_narrative": hop_narrative,
        "supporting_evidence": [],
        "contradictory_evidence": [],
        "score_breakdown": path.score_breakdown.model_dump() if hasattr(path.score_breakdown, "model_dump") else path.score_breakdown,
        "classification": path.classification,
        "causal_language_allowed": causal_language_allowed,
        "policy_ids": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
