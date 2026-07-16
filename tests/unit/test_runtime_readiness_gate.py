from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_runtime_readiness", ROOT / "scripts/release/check_runtime_readiness.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_durable_integration_topology_is_complete() -> None:
    assert MODULE.validate() == []
