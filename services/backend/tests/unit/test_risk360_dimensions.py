"""Risk360 Phase-3 dimension-registry tests.

Asserts the registry is seeded with the canonical SoT (RISK_FRAUD_360.md §4)
24-dimension set and that every seeded ``default_state`` is non-value-bearing
— so an unobserved dimension is never coerced to a fabricated zero.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.risk360.dimensions import (  # noqa: E402
    RISK_DIMENSIONS,
    RISK_DIMENSION_KEYS,
    RiskDimension,
    dimension,
)
from shared.measurement.value_states import (  # noqa: E402
    requires_value,
)

# Canonical 24-dimension set, in SoT §4 order.
SOT_DIMENSION_KEYS: tuple[str, ...] = (
    "identity",
    "authentication",
    "behavioral",
    "relationship",
    "economic",
    "transaction",
    "payment",
    "geographic",
    "temporal",
    "communication",
    "campaign",
    "agentic",
    "execution",
    "infrastructure",
    "counterparty",
    "population",
    "operational",
    "security",
    "compliance",
    "reputation",
    "fraud",
    "exposure",
    "data_quality",
    "model_uncertainty",
)


def test_registry_contains_all_24_canonical_dimensions() -> None:
    assert len(RISK_DIMENSIONS) == 24
    assert RISK_DIMENSION_KEYS == frozenset(SOT_DIMENSION_KEYS)
    assert tuple(d.key for d in RISK_DIMENSIONS) == SOT_DIMENSION_KEYS


def test_rows_are_unique_frozen_typed_rows() -> None:
    keys = [d.key for d in RISK_DIMENSIONS]
    assert len(keys) == len(set(keys))
    for row in RISK_DIMENSIONS:
        assert isinstance(row, RiskDimension)
        assert row.key
        assert row.label
        assert row.description


def test_default_state_is_never_a_fabricated_zero() -> None:
    """Every seeded dimension defaults to an honest non-value-bearing state."""
    for row in RISK_DIMENSIONS:
        assert not requires_value(row.default_state), (
            f"{row.key} defaults to {row.default_state.value!r}, which would "
            "imply a fabricated number for an unobserved dimension"
        )


def test_dimension_lookup_returns_row() -> None:
    row = dimension("economic")
    assert isinstance(row, RiskDimension)
    assert row.key == "economic"
    assert dimension("model_uncertainty").key == "model_uncertainty"
    # Looked-up row is the same frozen registry row.
    assert row is next(d for d in RISK_DIMENSIONS if d.key == "economic")


def test_dimension_lookup_unknown_raises() -> None:
    with pytest.raises(KeyError):
        dimension("not_a_dimension")
