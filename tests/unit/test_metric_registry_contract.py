"""Generated metric registry must stay in lockstep with the hand-authored one.

The canonical source is packages/shared/contracts/metric-registry.json. The
generator (scripts/generate_contracts.py) emits
Backend Architecture/aether-backend/shared/measurement/generated_registry.py from
it. shared/measurement/registry.py is hand-authored and intentionally NOT merged
with the generated twin.

This test is the seam that keeps the JSON contract and the hand-authored registry
honest: if either drifts, the field-for-field comparison below fails.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"

sys.path.insert(0, str(BACKEND))

from shared.measurement.generated_registry import (  # noqa: E402
    GENERATED_METRIC_REGISTRY_VERSION,
    GENERATED_METRICS,
)
from shared.measurement.registry import (  # noqa: E402
    METRIC_REGISTRY,
    REGISTRY_VERSION,
)

# Fields compared field-for-field between the generated contract and the
# hand-authored MetricDefinition. `version` and `description` are compared too so
# the two never quietly disagree.
_COMPARED_FIELDS = (
    "name",
    "version",
    "unit",
    "description",
    "lower",
    "upper",
    "allows_probability",
    "min_sample",
)


def test_contract_version_matches_registry_version() -> None:
    assert GENERATED_METRIC_REGISTRY_VERSION == REGISTRY_VERSION


def test_generated_metric_names_match_registry() -> None:
    assert set(GENERATED_METRICS) == set(METRIC_REGISTRY)


def test_generated_metrics_match_registry_field_for_field() -> None:
    for name, definition in METRIC_REGISTRY.items():
        assert name in GENERATED_METRICS, f"generated registry missing metric {name!r}"
        generated = GENERATED_METRICS[name]
        for field in _COMPARED_FIELDS:
            expected = getattr(definition, field)
            actual = generated[field]
            assert actual == expected, (
                f"metric {name!r} field {field!r}: "
                f"generated {actual!r} != registry {expected!r}"
            )


def test_no_extra_generated_metrics() -> None:
    for name in GENERATED_METRICS:
        assert name in METRIC_REGISTRY, f"generated registry has unknown metric {name!r}"
