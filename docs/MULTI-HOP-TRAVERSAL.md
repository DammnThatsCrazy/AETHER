---
title: Multi-Hop Traversal Algorithms
slug: concepts/multi-hop-traversal
section: concepts
visibility: P
audience: [architect, dev-senior, ai]
source_files:
  - Backend Architecture/aether-backend/shared/graph/traversal.py
  - Backend Architecture/aether-backend/shared/graph/path_scoring.py
---

# Multi-Hop Traversal Algorithms

This document is the algorithm reference for the three new traversal methods added in Phase 20. All algorithms live in `shared/graph/traversal.py` and are exposed via `POST /v1/graph/paths`.

---

## Shared Invariants

All algorithms copy the **two-set isolation pattern** from `bfs()`:
- `visited`: nodes whose neighbours have been expanded
- `accepted`: nodes that passed the tenant-id filter and were added to the result

A vertex is only added to `accepted` when `vertex.tenant_id == tenant_id`. This prevents cross-tenant data leakage even if vertex IDs collide across tenants.

Edge keys are synthetic: `f"{from_vertex_id}:{to_vertex_id}:{edge_type}"`. The underlying `Edge` dataclass has no `edge_id` field.

---

## `strongest_path(from_id, to_id, max_depth, tenant_id)`

**Goal**: Find the path that maximises cumulative edge confidence (not shortest hop count).

**Algorithm**: Modified Dijkstra with a min-heap keyed on `cost`, where `cost = 1 - confidence`.

```
cost_to[from_id] = 0.0
heap = [(0.0, from_id)]
prev = {}  # node_id → (parent_id, Edge)

while heap:
    cost, node = heappop(heap)
    if node in visited: continue
    visited.add(node)

    if node == to_id:
        break                       # found target — reconstruct path

    for edge in graph.get_edges(node):
        neighbour = edge.to_vertex_id
        if neighbour.tenant_id != tenant_id: continue   # two-set filter
        edge_cost = 1.0 - float(edge.properties.get("confidence", 1.0))
        new_cost = cost + edge_cost
        if new_cost < cost_to.get(neighbour, inf):
            cost_to[neighbour] = new_cost
            prev[neighbour] = (node, edge)
            heappush(heap, (new_cost, neighbour))
```

Path is reconstructed by walking `prev` backwards from `to_id` to `from_id`, then reversing.

**Complexity**: O((V + E) log V) per call.

---

## `k_shortest_paths(from_id, to_id, k, max_depth, tenant_id)`

**Goal**: Return up to `k` distinct shortest paths in order of total edge cost.

**Algorithm**: Yen's algorithm.

```
A = [shortest_path(from_id, to_id)]   # first best path
B = []                                  # candidate heap

for i in 1..k-1:
    for each spur_node in A[i-1].nodes[:-1]:
        root_path = A[i-1].prefix_up_to(spur_node)

        # Block edges used by previous k-th paths at this spur node
        blocked_edges = {edge_key(e) for p in A if p.prefix == root_path
                         for e in p.edges_at_spur(spur_node)}
        # Block all nodes in root_path except spur_node
        blocked_nodes = set(root_path.nodes[:-1])

        spur = _shortest_path_excluding(spur_node, to_id,
                                        blocked_edges, blocked_nodes, ...)
        if spur is not empty:
            candidate = root_path + spur
            if candidate not in B:
                heappush(B, (candidate.cost, candidate))

    if B is empty: break
    A.append(heappop(B))

return A   # up to k results, deduplicated by make_path_id
```

`_shortest_path_excluding()` is a BFS variant that skips specified edge keys and node IDs. Deduplication uses `make_path_id()` (SHA-256 of ordered node IDs) so structurally identical paths are never returned twice.

**Complexity**: O(kn(m + n log n)) where k ≤ 10, n = vertices in tenant subgraph, m = edges.

---

## `multi_source_bfs(start_ids, depth, direction, edge_types, limit, tenant_id)`

**Goal**: Run BFS from multiple seed nodes simultaneously and merge the results.

**Algorithm**: Seeds the standard BFS `frontier` deque with all `start_ids`. A single pair of `visited`/`accepted` sets merges results across all seeds.

```
frontier = deque([(sid, 0) for sid in start_ids if sid in graph])
visited  = set(start_ids)
accepted = set()
result_nodes, result_edges = [], []

while frontier and len(accepted) < limit:
    node_id, depth_so_far = frontier.popleft()
    if depth_so_far >= depth: continue

    for edge in graph.get_edges(node_id, direction):
        if edge_types and edge.type not in edge_types: continue
        neighbour = edge.to_vertex_id
        if neighbour in visited: continue
        if neighbour.tenant_id != tenant_id: continue   # isolation
        visited.add(neighbour)
        accepted.add(neighbour)
        result_nodes.append(neighbour)
        result_edges.append(edge)
        frontier.append((neighbour, depth_so_far + 1))
```

---

## Budget Enforcement

Server-side query budgets (from `QUERY_BUDGET_DEFAULTS`):

| Budget | Value |
|--------|-------|
| `max_depth` default | 6 |
| `max_depth` hard ceiling | 20 |
| `max_nodes` soft limit | 500 |
| `max_edges` soft limit | 2000 |

Clients may specify lower budgets in `PathQuery` but never higher. Any `PathQuery` with `max_depth > 6` or estimated node count > 500 is routed to `POST /v1/graph/paths/jobs` (async deep traversal). This routing happens server-side; clients cannot bypass it by calling `/paths` directly with large budgets.

---

## Scoring Version Protocol

All paths include `score_breakdown.scoring_version`. Currently `"1"`. When the scoring formula changes:
1. Bump `DEFAULT_SCORING_VERSION` in `path_scoring.py`.
2. Old paths in snapshots retain their original `scoring_version`.
3. Comparison endpoints must not mix scores from different versions.

---

## `_build_path_explanation(path) → dict`

Module-level helper in `traversal.py`. Generates a human-readable explanation from the path structure:

- `why_connected`: synthesised from layer_sequence and node kinds (e.g. "human→agent path via H2A layer")
- `hop_narrative`: one sentence per hop: `"{label_a} → {label_b} via {edge_type} ({layer}, {confidence}%)"`
- `causal_language_allowed`: `True` unless `classification == "correlated"`

This function returns a plain `dict` (not a Pydantic model) to avoid circular imports with `PathExplanation` in `models.py`.
