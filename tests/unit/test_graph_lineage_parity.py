"""Parity: packages/shared/graph-contract.ts <-> shared/graph (agent lineage)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

TS = (REPO_ROOT / "packages/shared/graph-contract.ts").read_text(encoding="utf-8")


def _ts_array(name: str) -> list[str]:
    match = re.search(rf"export const {name}[^=]*=\s*\[(.*?)\]", TS, re.DOTALL)
    assert match, f"{name} not found in graph-contract.ts"
    return re.findall(r"'([A-Za-z_]+)'", match.group(1))


def _ts_record(name: str) -> dict[str, str]:
    match = re.search(rf"export const {name}[^=]*=\s*\{{(.*?)\n\}};", TS, re.DOTALL)
    assert match, f"{name} not found in graph-contract.ts"
    return dict(re.findall(r"(\w+):\s*'(\w+)'", match.group(1)))


def test_lineage_edge_properties_match():
    from shared.graph.edge_properties import LINEAGE_EDGE_PROPERTIES

    assert _ts_array("LINEAGE_EDGE_PROPERTIES") == list(LINEAGE_EDGE_PROPERTIES)


def test_lineage_resolution_methods_match():
    from shared.graph.edge_properties import LINEAGE_RESOLUTION_METHODS

    assert _ts_array("LINEAGE_RESOLUTION_METHODS") == list(LINEAGE_RESOLUTION_METHODS)


def test_lineage_relationship_edge_types_match():
    from shared.graph.graph_contract import LINEAGE_RELATIONSHIP_EDGE_TYPES

    assert _ts_record("LINEAGE_RELATIONSHIP_EDGE_TYPES") == dict(LINEAGE_RELATIONSHIP_EDGE_TYPES)


def test_execution_plane_only_match():
    from shared.graph.graph_contract import LINEAGE_EXECUTION_PLANE_ONLY

    match = re.search(r"export const LINEAGE_EXECUTION_PLANE_ONLY[^=]*=\s*\[(.*?)\]", TS, re.DOTALL)
    assert set(re.findall(r"'(\w+)'", match.group(1))) == set(LINEAGE_EXECUTION_PLANE_ONLY)


def test_new_lineage_edge_layers_match_backend_map():
    from shared.graph.graph import EdgeType
    from shared.graph.relationship_layers import _EDGE_LAYER_MAP

    ts_layers = _ts_record("EDGE_LAYER_MAP")
    for name in (
        "DEPLOYED_AS", "INSTANTIATED_AS", "PRINCIPAL_OF", "SUPERVISES", "DELEGATED_TO",
        "SPAWNED_SUBAGENT", "AUTHORIZED_AGENT", "AGENT_ACTED_ON_BEHALF_OF",
    ):
        assert ts_layers[name] == _EDGE_LAYER_MAP[getattr(EdgeType, name)].value, name
