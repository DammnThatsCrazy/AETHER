"""TS <-> Python parity for the comparison contract.

`packages/shared/comparison-contract.ts` and
`services/intelligence/comparison/generated_vocabulary.py` are generated twins
of `packages/shared/contracts/comparison-registry.json`;
`services/intelligence/comparison/contracts.py` is the hand-authored twin of
the generated interfaces. This test fails on vocabulary or field drift, if the
TS module leaves the barrel, and if the comparison package starts being
imported eagerly by `services.intelligence`.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.intelligence.comparison.contracts import (  # noqa: E402
    BaselineSpec,
    ComparisonDefinition,
    ComparisonFinding,
    ComparisonRun,
    ComparisonSubject,
)
from services.intelligence.comparison.generated_vocabulary import (  # noqa: E402
    ALIGNMENT_OUTCOMES,
    BASELINE_TYPES,
    CAUSAL_CLAIM_LEVELS,
    COMPARISON_CONTRACT_VERSION,
    COMPARISON_DIMENSIONS,
    COMPARISON_DISPOSITIONS,
    COMPARISON_MODES,
    COMPARISON_RUN_STATES,
    COMPARISON_SEVERITIES,
    FACT_LINKAGE_STATES,
    MATERIALITY_COMPONENTS,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "comparison-contract.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "comparison-registry.json"

_VOCAB_PAIRS = (
    ("comparisonModes", COMPARISON_MODES),
    ("baselineTypes", BASELINE_TYPES),
    ("alignmentOutcomes", ALIGNMENT_OUTCOMES),
    ("comparisonRunStates", COMPARISON_RUN_STATES),
    ("comparisonSeverities", COMPARISON_SEVERITIES),
    ("comparisonDispositions", COMPARISON_DISPOSITIONS),
    ("factLinkageStates", FACT_LINKAGE_STATES),
    ("causalClaimLevels", CAUSAL_CLAIM_LEVELS),
    ("comparisonDimensions", COMPARISON_DIMENSIONS),
    ("materialityComponents", MATERIALITY_COMPONENTS),
)

_MODEL_PAIRS = (
    ("ComparisonSubject", ComparisonSubject),
    ("BaselineSpec", BaselineSpec),
    ("ComparisonDefinition", ComparisonDefinition),
    ("ComparisonRun", ComparisonRun),
    ("ComparisonFinding", ComparisonFinding),
)


def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in comparison-contract.ts"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _interface_fields(interface: str) -> set[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"export interface {interface}\s*\{{(.*?)\n\}}", text, re.S)
    assert m, f"interface {interface} not found in comparison-contract.ts"
    return set(re.findall(r"^\s*([a-z_][a-z0-9_]*)\??:", m.group(1), re.M))


def test_vocabulary_parity():
    for ts_name, py_tuple in _VOCAB_PAIRS:
        ts_values = set(_const_array(ts_name))
        assert ts_values == set(py_tuple), (
            f"{ts_name} drift: TS-only={ts_values - set(py_tuple)}, "
            f"PY-only={set(py_tuple) - ts_values}"
        )


def test_model_field_parity():
    for ts_name, model in _MODEL_PAIRS:
        ts_fields = _interface_fields(ts_name)
        py_fields = set(model.model_fields.keys())
        assert ts_fields == py_fields, (
            f"{ts_name} drift: TS-only={ts_fields - py_fields}, "
            f"PY-only={py_fields - ts_fields}"
        )


def test_finding_required_fields():
    required = {
        name for name, field in ComparisonFinding.model_fields.items() if field.is_required()
    }
    assert required == {"id", "comparison_run_id", "tenant_id", "finding_type"}


def test_generated_vocabulary_matches_registry():
    """Generated Python vocabulary mirrors the JSON registry (regen if this fails)."""
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert COMPARISON_CONTRACT_VERSION == registry["contractVersion"]
    json_keys = {
        "comparisonModes": COMPARISON_MODES,
        "baselineTypes": BASELINE_TYPES,
        "alignmentOutcomes": ALIGNMENT_OUTCOMES,
        "runStates": COMPARISON_RUN_STATES,
        "severities": COMPARISON_SEVERITIES,
        "dispositions": COMPARISON_DISPOSITIONS,
        "factLinkageStates": FACT_LINKAGE_STATES,
        "causalClaimLevels": CAUSAL_CLAIM_LEVELS,
        "comparisonDimensions": COMPARISON_DIMENSIONS,
        "materialityComponents": MATERIALITY_COMPONENTS,
    }
    for key, py_tuple in json_keys.items():
        assert list(py_tuple) == registry[key], f"{key} drifted from registry"


def test_comparison_not_imported_eagerly_by_intelligence():
    """services.intelligence must not pull the comparison package at import time."""
    for mod in [m for m in list(sys.modules) if m.startswith("services")]:
        del sys.modules[mod]
    import services.intelligence  # noqa: F401

    assert "services.intelligence.comparison" not in sys.modules


def test_barrel_exports_comparison_contract():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './comparison-contract';" in index
