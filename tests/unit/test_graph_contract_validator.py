"""The contract validator runs the graph contract and economic-schema checks."""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services" / "api"


def _validator():
    spec = importlib.util.spec_from_file_location("validate_contracts_under_test", ROOT / "scripts" / "validate_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_graph_contracts_are_consistent():
    assert _validator().check_graph_contracts() == []


def test_an_economic_edge_with_an_unknown_endpoint_is_reported(monkeypatch):
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    from shared.graph import economic_schema

    some_edge = next(iter(economic_schema.EDGE_SCHEMA_MAP.values()))
    broken = replace(some_edge, to_type="NoSuchVertexType")
    monkeypatch.setitem(economic_schema.EDGE_SCHEMA_MAP, "BROKEN_EDGE", replace(broken, edge_type="BROKEN_EDGE"))
    errors = _validator().check_graph_contracts()
    assert any("BROKEN_EDGE" in e and "NoSuchVertexType" in e for e in errors)
    assert any("'BROKEN_EDGE' is not an EdgeType" in e for e in errors)
