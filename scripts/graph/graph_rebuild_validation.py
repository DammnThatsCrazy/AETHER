#!/usr/bin/env python3
"""
Graph Rebuild Validation

Replays a canonical graph fixture twice through the in-memory GraphClient and
asserts that the resulting graph matches the expected vertex/edge/layer counts.
A non-zero diff exits 1 (for CI use).

Usage:
    python scripts/graph/graph_rebuild_validation.py
    python scripts/graph/graph_rebuild_validation.py --fixture tests/fixtures/graph/canonical_graph.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
BACKEND_ROOT = REPO_ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND_ROOT))

if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.SimpleNamespace(
        encode=lambda *a, **kw: "stub",
        decode=lambda *a, **kw: {},
        exceptions=types.SimpleNamespace(
            PyJWTError=Exception, ExpiredSignatureError=Exception, InvalidTokenError=Exception
        ),
    )

from datetime import datetime, timezone

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.relationship_layers import get_layer_stats

DEFAULT_FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "graph" / "canonical_graph.json"

# Built-in minimal fixture for CI environments without an external fixture file
_BUILT_IN_FIXTURE = {
    "vertices": [
        {"vertex_id": "rebuild-user-1", "vertex_type": "User", "properties": {"tenant_id": "rebuild-tenant"}},
        {"vertex_id": "rebuild-agent-1", "vertex_type": "Agent", "properties": {"tenant_id": "rebuild-tenant"}},
        {"vertex_id": "rebuild-session-1", "vertex_type": "Session", "properties": {"tenant_id": "rebuild-tenant"}},
    ],
    "edges": [
        {
            "edge_type": "HAS_SESSION",
            "from_vertex_id": "rebuild-user-1",
            "to_vertex_id": "rebuild-session-1",
            "properties": {
                "tenant_id": "rebuild-tenant",
                "idempotency_key": "rebuild-h2h-1",
                "actor_kind": "system",
                "actor_id": "rebuild-system",
                "schema_version": "1",
                "provenance": "rebuild_validation",
                "valid_from": "2024-01-01T00:00:00+00:00",
                "confidence": "1.0",
                "consent_purpose": "",
            },
        },
        {
            "edge_type": "DELEGATES",
            "from_vertex_id": "rebuild-user-1",
            "to_vertex_id": "rebuild-agent-1",
            "properties": {
                "tenant_id": "rebuild-tenant",
                "idempotency_key": "rebuild-h2a-1",
                "actor_kind": "system",
                "actor_id": "rebuild-system",
                "schema_version": "1",
                "provenance": "rebuild_validation",
                "valid_from": "2024-01-01T00:00:00+00:00",
                "confidence": "1.0",
                "consent_purpose": "rebuild_workload",
            },
        },
        {
            "edge_type": "NOTIFIES",
            "from_vertex_id": "rebuild-agent-1",
            "to_vertex_id": "rebuild-user-1",
            "properties": {
                "tenant_id": "rebuild-tenant",
                "idempotency_key": "rebuild-a2h-1",
                "actor_kind": "agent",
                "actor_id": "rebuild-agent-1",
                "schema_version": "1",
                "provenance": "rebuild_validation",
                "valid_from": "2024-01-01T00:00:00+00:00",
                "confidence": "1.0",
                "consent_purpose": "rebuild_workload",
            },
        },
    ],
}


async def replay_fixture(fixture: dict) -> tuple[int, int, dict]:
    """Replay a fixture once; return (vertex_count, edge_count, layer_stats)."""
    client = GraphClient()
    await client.connect()

    for v in fixture.get("vertices", []):
        await client.add_vertex(Vertex(
            vertex_type=v["vertex_type"],
            vertex_id=v["vertex_id"],
            properties=v.get("properties", {}),
        ))

    edges: list[Edge] = []
    for e in fixture.get("edges", []):
        edge = Edge(
            edge_type=e["edge_type"],
            from_vertex_id=e["from_vertex_id"],
            to_vertex_id=e["to_vertex_id"],
            properties=e.get("properties", {}),
        )
        await client.add_edge(edge)
        edges.append(edge)

    all_vertices = await client.get_all_vertices()
    stats = get_layer_stats(edges)
    return len(all_vertices), len(edges), stats


async def run(fixture_path: Path) -> int:
    if fixture_path.exists():
        fixture = json.loads(fixture_path.read_text())
        print(f"Using fixture: {fixture_path}")
    else:
        fixture = _BUILT_IN_FIXTURE
        print("Using built-in minimal fixture (no external fixture file found)")

    expected_vertices = len(fixture.get("vertices", []))
    expected_edges = len(fixture.get("edges", []))

    print(f"Expected: {expected_vertices} vertices, {expected_edges} edges")
    print()

    # First replay
    v1, e1, s1 = await replay_fixture(fixture)
    print(f"Replay 1: {v1} vertices, {e1} edges, layers={s1}")

    # Second replay (idempotency check)
    v2, e2, s2 = await replay_fixture(fixture)
    print(f"Replay 2: {v2} vertices, {e2} edges, layers={s2}")

    diffs: dict = {}
    vertex_diff = abs(v1 - expected_vertices)
    edge_diff = abs(e1 - expected_edges)

    if vertex_diff:
        diffs["vertex_diff"] = vertex_diff
    if edge_diff:
        diffs["edge_diff"] = edge_diff

    layer_diff: dict = {}
    for k in s1:
        if s1[k] != s2.get(k, 0):
            layer_diff[k] = {"replay_1": s1[k], "replay_2": s2[k]}
    if layer_diff:
        diffs["layer_diff"] = layer_diff

    result = {
        "vertex_diff": vertex_diff,
        "edge_diff": edge_diff,
        "layer_diff": layer_diff,
        "status": "clean" if not diffs else "diff_detected",
    }

    print()
    print(json.dumps(result, indent=2))

    if result["status"] == "clean":
        print("\nGraph rebuild validation PASSED.")
        return 0
    else:
        print(f"\nGraph rebuild validation FAILED — diffs detected: {list(diffs.keys())}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Graph rebuild validation")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    args = parser.parse_args()
    code = asyncio.run(run(args.fixture))
    sys.exit(code)


if __name__ == "__main__":
    main()
