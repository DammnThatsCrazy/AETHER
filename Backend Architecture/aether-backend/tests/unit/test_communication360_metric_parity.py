"""Communication360 information-fidelity metric absorption parity (Phase 5).

The seven §71 information-quality metrics produced by
``services/communication360/fidelity.py`` (``FidelityReport`` fields) are
registered in the hand-authored ``shared/measurement/registry.py`` in lockstep
with ``packages/shared/contracts/metric-registry.json``. The cross-source parity
test (``tests/unit/test_metric_registry_contract.py``) compares the hand-authored
registry against the GENERATED registry — that test needs the generator to be
re-run from the JSON (``python scripts/generate_contracts.py``) and is the
orchestrator's step, so this file asserts the hand-authored side directly against
the canonical JSON contract.

Per decision D6, a metric is registered only alongside its producer. The seven
names below are exactly the rates ``FidelityReport`` computes. §71's
``constraint_retention_rate`` is deliberately NOT registered here: no producer
computes it in this slice (the fidelity engine measures ``omission_rate`` as its
complementary truth), so registering it would violate D6.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend
REPO_ROOT = BACKEND_ROOT.parents[1]  # repo root

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.measurement.registry import METRIC_REGISTRY  # noqa: E402

# The 7 §71 information-quality metrics absorbed by Phase 5 — exactly the rates
# `services/communication360/fidelity.py::FidelityReport` computes.
COMMUNICATION360_FIDELITY_METRICS: tuple[str, ...] = (
    "claim_retention_rate",
    "citation_retention_rate",
    "contradiction_rate",
    "evidence_retention_rate",
    "omission_rate",
    "semantic_drift",
    "unsupported_addition_rate",
)

_JSON_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "metric-registry.json"


def _json_metrics() -> dict[str, dict]:
    with open(_JSON_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {m["name"]: m for m in data["metrics"]}


def test_registry_contains_all_7_fidelity_metrics() -> None:
    for name in COMMUNICATION360_FIDELITY_METRICS:
        assert name in METRIC_REGISTRY, f"metric {name!r} missing from METRIC_REGISTRY"


def test_hand_authored_metrics_match_json_field_for_field() -> None:
    json_metrics = _json_metrics()
    for name in COMMUNICATION360_FIDELITY_METRICS:
        definition = METRIC_REGISTRY[name]
        jm = json_metrics[name]
        assert definition.version == jm["version"], name
        assert definition.unit == jm["unit"], name
        assert definition.description == jm["description"], name
        assert definition.lower == jm["lower"], name
        assert definition.upper == jm["upper"], name
        assert definition.allows_probability == jm["allowsProbability"], name
        assert definition.min_sample == jm["minSample"], name


def test_fidelity_metrics_have_expected_bounds() -> None:
    # All seven are ratios bounded to [0, 1]; none are probabilities.
    for name in COMMUNICATION360_FIDELITY_METRICS:
        definition = METRIC_REGISTRY[name]
        assert definition.unit == "ratio", name
        assert definition.lower == 0.0, name
        assert definition.upper == 1.0, name
        assert definition.allows_probability is False, name
        assert definition.min_sample == 1, name
