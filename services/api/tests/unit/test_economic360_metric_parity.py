"""Economic360 metric absorption parity (slice S3, hand-authored side).

The 11 economic metrics must be absorbed into the hand-authored
``shared/measurement/registry.py`` in lockstep with
``packages/shared/contracts/metric-registry.json``. The cross-source parity test
(``tests/unit/test_metric_registry_contract.py``) compares the hand-authored
registry against the GENERATED registry — that test needs the generator to be
re-run from the JSON and is the orchestrator's step, so this file asserts the
hand-authored side directly against the canonical JSON contract.
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

# The 11 metrics absorbed by slice S3 (the 4 pending campaign refs + the
# program's economic metric set).
ECONOMIC_METRICS: tuple[str, ...] = (
    "campaign_cac",
    "campaign_ltv",
    "campaign_roas",
    "campaign_spend",
    "costs",
    "exposure",
    "gross_value",
    "ltv",
    "margin",
    "net_value",
    "refunds",
)

_JSON_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "metric-registry.json"


def _json_metrics() -> dict[str, dict]:
    with open(_JSON_PATH, encoding="utf-8") as fh:
        data = json.load(fh)
    return {m["name"]: m for m in data["metrics"]}


def test_registry_contains_all_11_economic_metrics() -> None:
    for name in ECONOMIC_METRICS:
        assert name in METRIC_REGISTRY, f"metric {name!r} missing from METRIC_REGISTRY"


def test_hand_authored_metrics_match_json_field_for_field() -> None:
    json_metrics = _json_metrics()
    for name in ECONOMIC_METRICS:
        definition = METRIC_REGISTRY[name]
        jm = json_metrics[name]
        assert definition.version == jm["version"], name
        assert definition.unit == jm["unit"], name
        assert definition.description == jm["description"], name
        assert definition.lower == jm["lower"], name
        assert definition.upper == jm["upper"], name
        assert definition.allows_probability == jm["allowsProbability"], name
        assert definition.min_sample == jm["minSample"], name


def test_campaign_pending_refs_have_expected_bounds() -> None:
    # The 4 pending refs clear only when these bounds match the registry row's
    # intended metricRefs vocabulary.
    assert METRIC_REGISTRY["campaign_spend"].unit == "usd"
    assert METRIC_REGISTRY["campaign_spend"].lower == 0
    assert METRIC_REGISTRY["campaign_roas"].unit == "ratio"
    assert METRIC_REGISTRY["campaign_cac"].unit == "usd"
    assert METRIC_REGISTRY["campaign_ltv"].unit == "usd"
