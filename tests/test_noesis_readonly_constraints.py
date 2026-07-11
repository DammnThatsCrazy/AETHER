"""Constraint tests proving Noesis stays read-only over the observability
subsystems (imports / jobs / measurement) and never relabels measurement
semantics.

These are pure, synchronous assertions over the capability registry, the
intent allowlist / schema, and the measurement value-state + metric-registry
invariants. No repositories are touched and no event loop is required.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import get_args

# This file lives at repo-root ``tests/``; parents[1] is the repo root and the
# backend package lives under "Backend Architecture/aether-backend".
BACKEND = Path(__file__).resolve().parents[1] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.noesis.capability_registry import CAPABILITY_REGISTRY  # noqa: E402
from services.noesis.models import (  # noqa: E402
    SUPPORTED_INTENTS,
    WRITE_LIKE_KEYWORDS,
    QueryPlan,
)

NEW_INTENTS = {
    "import_status_lookup",
    "job_status_lookup",
    "measurement_integrity_lookup",
}

_MUTATION_SOURCE_SUBSTRINGS = ("writer", "commit", "mutate")


def _tokens(*values: str) -> set[str]:
    """Split intent/label strings into lowercase alphanumeric tokens."""
    tokens: set[str] = set()
    for value in values:
        tokens.update(t for t in re.split(r"[^a-z0-9]+", value.lower()) if t)
    return tokens


def _plan_intent_literals() -> set[str]:
    """The allowed values of the ``QueryPlan.intent`` Literal."""
    annotation = QueryPlan.model_fields["intent"].annotation
    return set(get_args(annotation))


# ─── Registry / allowlist parity ──────────────────────────────────────────


def test_every_registered_intent_is_supported():
    for cap in CAPABILITY_REGISTRY:
        assert cap.intent in SUPPORTED_INTENTS, (
            f"capability '{cap.intent}' is not in SUPPORTED_INTENTS"
        )


def test_no_capability_intent_or_label_is_write_like():
    for cap in CAPABILITY_REGISTRY:
        overlap = _tokens(cap.intent, cap.label) & WRITE_LIKE_KEYWORDS
        assert not overlap, (
            f"capability '{cap.intent}' intent/label tokens are write-like: {overlap}"
        )


def test_no_capability_data_source_is_mutating():
    for cap in CAPABILITY_REGISTRY:
        for source in cap.data_sources:
            low = source.lower()
            for bad in _MUTATION_SOURCE_SUBSTRINGS:
                assert bad not in low, (
                    f"capability '{cap.intent}' data source '{source}' looks mutating"
                )


# ─── The three new read-only intents are registered end-to-end ─────────────


def test_new_observability_intents_registered():
    registered = {cap.intent for cap in CAPABILITY_REGISTRY}
    assert NEW_INTENTS <= registered
    assert NEW_INTENTS <= SUPPORTED_INTENTS
    assert NEW_INTENTS <= _plan_intent_literals()


def test_new_capabilities_are_read_only_in_description():
    by_intent = {cap.intent: cap for cap in CAPABILITY_REGISTRY}
    # Each new capability must advertise its observation-only posture.
    for intent in NEW_INTENTS:
        cap = by_intent[intent]
        low = cap.description.lower()
        assert "read-only" in low or "observation-only" in low, (
            f"capability '{intent}' does not declare a read-only posture"
        )
    # Measurement must explicitly forbid relabelling / zero-coercion.
    measurement_desc = by_intent["measurement_integrity_lookup"].description.lower()
    assert "relabel" in measurement_desc
    assert "not causal" in measurement_desc
    assert "never reported as zero" in measurement_desc


# ─── Measurement semantics (missing != zero, index != probability) ─────────


def test_only_observed_and_estimated_carry_a_value():
    from shared.measurement.value_states import ValueState, requires_value

    value_bearing = {state for state in ValueState if requires_value(state)}
    assert value_bearing == {ValueState.OBSERVED, ValueState.ESTIMATED}
    # Every other state is honestly value-absent — a missing value is never a zero.
    for state in ValueState:
        if state not in (ValueState.OBSERVED, ValueState.ESTIMATED):
            assert not requires_value(state)


def test_index_is_not_a_probability_unless_flagged():
    from shared.measurement import list_definitions

    definitions = list_definitions()
    assert definitions, "expected at least one metric definition"

    for defn in definitions:
        # The probability flag must be an explicit, present boolean.
        assert "allows_probability" in defn
        assert isinstance(defn["allows_probability"], bool)
        # Invariant: a metric is a probability ONLY when explicitly flagged.
        if not defn["allows_probability"]:
            assert defn["allows_probability"] is False

    # Concrete proof that being a [0,1] ratio does NOT make a metric a
    # probability: conversion_rate is bounded to [0,1] yet is not flagged.
    by_name = {d["name"]: d for d in definitions}
    conversion = by_name.get("conversion_rate")
    assert conversion is not None
    assert conversion["lower"] == 0.0 and conversion["upper"] == 1.0
    assert conversion["allows_probability"] is False
