from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_founding_tenant_surface",
    ROOT / "scripts/release/check_founding_tenant_surface.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_founding_tenant_manifest_matches_code_registries() -> None:
    assert MODULE.validate() == []


def test_rollout_stages_are_monotonic_and_bounded() -> None:
    assert MODULE.STAGES[0] == "disabled"
    assert MODULE.STAGES[-1] == "general_availability_candidate"
    assert len(MODULE.STAGES) == len(set(MODULE.STAGES))
