"""Projection-engine generator tests (A8): lens-registry artifacts + validator.

The three artifacts emitted from ``packages/shared/contracts/lens-registry.json``
— the TS twin, the Python twin and the generated table — must be byte-identical
across runs and immune to key/array order shuffles (order-stability contract).
Also asserts the ``lens_registry`` rule group fails closed on illegal lens
definitions: duplicate ids, unresolvable ``baseLens``, self-base, a base-kind
lens as an overlay, and a second default base.
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

LENS_REGISTRY_PATH = gpc.LENS_REGISTRY_JSON
LENS_ARTIFACTS = (
    gpc.LENS_REGISTRY_TS,
    gpc.LENS_REGISTRY_PY,
    gpc.LENS_REGISTRY_MD,
)
_LENS_EMITTERS = {
    gpc.LENS_REGISTRY_TS: gpc.gen_lens_registry_ts,
    gpc.LENS_REGISTRY_PY: gpc.gen_lens_registry_py,
    gpc.LENS_REGISTRY_MD: gpc.gen_lens_registry_md,
}

REAL_REG = json.loads(LENS_REGISTRY_PATH.read_text(encoding="utf-8"))


def _emitted(reg: dict) -> dict[Path, str]:
    return {path: emit(reg) for path, emit in _LENS_EMITTERS.items()}


def _shuffle_registry(reg: dict, rng: random.Random) -> dict:
    """Deep-copy ``reg`` with every key order and the ``lenses`` array order
    shuffled. Emitters must be immune to all of these."""

    def shuffle_value(value):
        if isinstance(value, dict):
            items = [(k, shuffle_value(v)) for k, v in value.items()]
            rng.shuffle(items)
            return {k: v for k, v in items}
        if isinstance(value, list):
            items = [shuffle_value(v) for v in value]
            rng.shuffle(items)
            return items
        return value

    top_items = [(k, shuffle_value(v)) for k, v in reg.items()]
    rng.shuffle(top_items)
    shuffled = {k: v for k, v in top_items}
    rng.shuffle(shuffled["lenses"])
    return shuffled


def test_lens_generator_runs_and_is_idempotent():
    """Running the generator leaves every lens artifact byte-identical."""
    before = {path: path.read_text(encoding="utf-8") for path in LENS_ARTIFACTS}
    run = subprocess.run(
        [sys.executable, "scripts/generate_platform_contracts.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    after = {path: path.read_text(encoding="utf-8") for path in LENS_ARTIFACTS}
    assert after == before


def test_lens_emitters_deterministic_across_runs():
    """Calling each emitter twice on the same registry is byte-identical."""
    first = _emitted(REAL_REG)
    second = _emitted(REAL_REG)
    assert second == first
    for path, content in first.items():
        assert path.read_text(encoding="utf-8") == content, path


def test_lens_key_and_order_shuffle_is_byte_identical():
    """Shuffling the lenses array + every key order must not change output."""
    rng = random.Random(11)
    for trial in range(10):
        shuffled = _shuffle_registry(REAL_REG, rng)
        for emit in _LENS_EMITTERS.values():
            assert emit(shuffled) == emit(REAL_REG), emit.__name__


def test_lens_registry_validation_accepts_real_registry():
    """The generator's lens-registry wrapper reports zero errors (warnings ok)."""
    ctx = gpc._load_context()
    assert gpc.validate_lens_registry(REAL_REG, ctx) == []


def test_lens_registry_validation_rejects_duplicate_ids():
    ctx = gpc._load_context()
    bad = json.loads(json.dumps(REAL_REG))
    dup = json.loads(json.dumps(bad["lenses"][1]))  # duplicate an overlay verbatim
    bad["lenses"].append(dup)
    try:
        gpc.validate_lens_registry(bad, ctx)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("duplicate lens id must fail validation")


def test_lens_registry_validation_rejects_unresolvable_base_lens():
    ctx = gpc._load_context()
    bad = json.loads(json.dumps(REAL_REG))
    bad["lenses"][0]["baseLens"] = "no_such_lens"  # standard is a base; make it point nowhere
    try:
        gpc.validate_lens_registry(bad, ctx)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("unresolvable baseLens must fail validation")


def test_lens_registry_validation_rejects_second_default_base():
    ctx = gpc._load_context()
    bad = json.loads(json.dumps(REAL_REG))
    for lens in bad["lenses"]:
        if lens["kind"] == "overlay":
            lens["default"] = True
            break
    try:
        gpc.validate_lens_registry(bad, ctx)
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("a second default lens must fail validation")
