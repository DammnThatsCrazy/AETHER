"""Generator determinism tests for the intelligence-projection artifacts (P0.3).

The four artifacts emitted from
``packages/shared/contracts/intelligence-projection-registry.json`` — the TS
registry, the Python registry, the registry table and the dependency graph —
must be byte-identical across runs and immune to registry key/array order
shuffles (the order-stability contract). Also asserts ``--check`` exits 0 and
that the real registry produces zero validation errors through the generator's
validation path (warnings — the benign optional-edge cycle WARNINGS — are
allowed).
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import generate_platform_contracts as gpc  # noqa: E402

REGISTRY_PATH = gpc.INTELLIGENCE_PROJECTION_JSON
ARTIFACTS = (
    gpc.INTELLIGENCE_PROJECTION_TS,
    gpc.INTELLIGENCE_PROJECTION_PY,
    gpc.INTELLIGENCE_PROJECTION_TABLE_MD,
    gpc.INTELLIGENCE_PROJECTION_GRAPH_MD,
)

_EMITTERS = {
    gpc.INTELLIGENCE_PROJECTION_TS: gpc.gen_intelligence_projection_ts,
    gpc.INTELLIGENCE_PROJECTION_PY: gpc.gen_intelligence_projection_py,
    gpc.INTELLIGENCE_PROJECTION_TABLE_MD: gpc.gen_intelligence_projection_table_md,
    gpc.INTELLIGENCE_PROJECTION_GRAPH_MD: gpc.gen_intelligence_projection_graph_md,
}

REAL_REG = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _emitted(reg: dict) -> dict[Path, str]:
    """Run every projection emitter on one registry dict."""
    return {path: emit(reg) for path, emit in _EMITTERS.items()}


def _shuffle_registry(reg: dict, rng: random.Random) -> dict:
    """Deep-copy ``reg`` with every dict's key order and the ``projections``
    array order shuffled. Emitters must be immune to both."""
    def shuffle_value(value):
        if isinstance(value, dict):
            items = [(k, shuffle_value(v)) for k, v in value.items()]
            rng.shuffle(items)
            return {k: v for k, v in items}
        if isinstance(value, list):
            return [shuffle_value(v) for v in value]
        return value

    top_items = [(k, shuffle_value(v)) for k, v in reg.items()]
    rng.shuffle(top_items)
    shuffled = {k: v for k, v in top_items}
    rng.shuffle(shuffled["projections"])
    return shuffled


def test_generator_runs_and_is_idempotent():
    """Running the generator twice leaves every artifact byte-identical."""
    before = {path: path.read_text(encoding="utf-8") for path in ARTIFACTS}
    run = subprocess.run(
        [sys.executable, "scripts/generate_platform_contracts.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    after = {path: path.read_text(encoding="utf-8") for path in ARTIFACTS}
    assert after == before


def test_emitters_deterministic_across_runs():
    """Calling each emitter twice on the same registry is byte-identical."""
    first = _emitted(REAL_REG)
    second = _emitted(REAL_REG)
    assert second == first
    # Emitter output matches what is on disk (regen would be a no-op).
    for path, content in first.items():
        assert path.read_text(encoding="utf-8") == content, path


def test_key_and_order_shuffle_is_byte_identical(tmp_path):
    """Shuffling projections order + every key order must not change output."""
    rng = random.Random(7)
    for _ in range(5):
        shuffled = _shuffle_registry(REAL_REG, rng)
        # Write the shuffled registry to a temp copy and load it back (the
        # C3 spec's temp-registry path) so the emitters see a real JSON file
        # round-trip, not just the in-memory shuffle.
        tmp = tmp_path / "intelligence-projection-registry.json"
        tmp.write_text(json.dumps(shuffled, indent=2, sort_keys=False), encoding="utf-8")
        loaded = json.loads(tmp.read_text(encoding="utf-8"))
        assert gpc.gen_intelligence_projection_ts(loaded) == gpc.gen_intelligence_projection_ts(REAL_REG)
        assert gpc.gen_intelligence_projection_py(loaded) == gpc.gen_intelligence_projection_py(REAL_REG)
        # The markdown emitters must be stable too.
        assert gpc.gen_intelligence_projection_table_md(loaded) == gpc.gen_intelligence_projection_table_md(REAL_REG)
        assert gpc.gen_intelligence_projection_graph_md(loaded) == gpc.gen_intelligence_projection_graph_md(REAL_REG)


def test_generated_check_exits_zero():
    run = subprocess.run(
        [sys.executable, "scripts/generate_platform_contracts.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr


def test_validation_path_reports_zero_errors_for_real_registry():
    """The generator's validation wrapper reports zero errors (warnings ok)."""
    ctx = gpc._load_context()
    errors = gpc.validate_intelligence_projection_registry(REAL_REG, ctx)
    assert errors == []


def test_validation_rejects_a_bad_projection_dependency():
    """An undeclared projection dependency fails the wrapper (fail-closed).

    The wrapper exits non-zero on any error, mirroring the other registry
    validators in the generator, so the failure surfaces as SystemExit.
    """
    ctx = gpc._load_context()
    bad = json.loads(json.dumps(REAL_REG))
    bad["projections"][0]["projectionDependencies"].append("not_a_projection")
    try:
        gpc.validate_intelligence_projection_registry(bad, ctx)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("undeclared dependency must fail validation")
