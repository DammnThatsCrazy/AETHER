"""Computation-substrate registration parity tests for fidelity definitions (M7).

The fidelity Computation Definitions self-register additively on the Canonical
Computation Substrate via ``register_fidelity_definitions()``. These tests
assert registration parity: every fidelity definition is present and immutable
under its governed key, dimension definitions cover exactly the M1 vector
dimensions, math types never claim PROBABILITY for uncalibrated heuristics, and
count definitions carry the honest count facts.
"""

from __future__ import annotations

from shared.computation.definition import ComputationKind, LifecycleState
from shared.computation.registry import COMPUTATION_REGISTRY, register
from shared.computation.types import MathType
from shared.relationship_fidelity.definitions import (
    FIDELITY_COUNT_FIELDS,
    FIDELITY_DEFINITIONS,
    FIDELITY_DEFINITION_VERSION,
    FIDELITY_DIMENSIONS,
    FIDELITY_OWNER,
    INDEPENDENCE_GATED_DIMENSIONS,
    MEASURED_PASSTHROUGH_DIMENSIONS,
    register_fidelity_definitions,
)


def _keys() -> set[str]:
    return {d.key() for d in FIDELITY_DEFINITIONS}


def test_all_definitions_register_additively_and_idempotently():
    before = set(COMPUTATION_REGISTRY)
    new_keys = set(_keys()) - before
    count = register_fidelity_definitions()
    assert count == len(FIDELITY_DEFINITIONS)
    # every fidelity definition is now present on the substrate under its key
    for definition in FIDELITY_DEFINITIONS:
        assert definition.key() in COMPUTATION_REGISTRY
    assert set(COMPUTATION_REGISTRY) - before == new_keys
    # idempotent second registration must not raise or add duplicates
    register_fidelity_definitions()
    assert len(COMPUTATION_REGISTRY) == len(before) + len(new_keys)


def test_definitions_never_probability():
    for definition in FIDELITY_DEFINITIONS:
        assert definition.output_type != MathType.PROBABILITY, (
            f"{definition.definition_id} must not claim Probability (uncalibrated)"
        )


def test_dimension_definitions_cover_exactly_the_vector_dimensions():
    registered_dimensions = {
        d.definition_id.removeprefix("relationship_fidelity.")
        for d in FIDELITY_DEFINITIONS
        if d.definition_id.startswith("relationship_fidelity.")
    }
    assert registered_dimensions == set(FIDELITY_DIMENSIONS) | set(FIDELITY_COUNT_FIELDS)
    # 20 dimensions + 3 count fields
    assert len(FIDELITY_DIMENSIONS) == 20
    assert len(FIDELITY_COUNT_FIELDS) == 3


def test_dimension_definitions_are_governed_and_bounded():
    for definition in FIDELITY_DEFINITIONS:
        assert definition.owner == FIDELITY_OWNER
        assert definition.definition_version == FIDELITY_DEFINITION_VERSION
        assert definition.lifecycle_state == LifecycleState.ACTIVE
        assert definition.null_policy == "null_not_zero"
        assert definition.zero_policy == "evidence_backed"
    for dim in FIDELITY_DIMENSIONS:
        definition = next(
            d for d in FIDELITY_DEFINITIONS if d.definition_id == f"relationship_fidelity.{dim}"
        )
        assert definition.output_type == MathType.HEURISTIC_SCORE
        assert definition.computation_kind == ComputationKind.HEURISTIC_SCORE
        assert definition.valid_range_low == 0.0
        assert definition.valid_range_high == 1.0
    for field in FIDELITY_COUNT_FIELDS:
        definition = next(
            d for d in FIDELITY_DEFINITIONS if d.definition_id == f"relationship_fidelity.{field}"
        )
        assert definition.output_type == MathType.INTEGER_COUNT


def test_independence_gated_definitions_declare_the_independence_dependency():
    for dim in INDEPENDENCE_GATED_DIMENSIONS:
        definition = next(
            d for d in FIDELITY_DEFINITIONS if d.definition_id == f"relationship_fidelity.{dim}"
        )
        assert "evidence.independent_groups" in definition.required_inputs
        assert (
            "relationship_fidelity.independent_evidence_count" in definition.dependency_definitions
        )


def test_measured_passthrough_definitions_declare_upstream_input():
    for dim in MEASURED_PASSTHROUGH_DIMENSIONS:
        definition = next(
            d for d in FIDELITY_DEFINITIONS if d.definition_id == f"relationship_fidelity.{dim}"
        )
        assert definition.required_inputs == [f"upstream.{dim}"]


def test_no_universal_composite_definition_exists():
    ids = {d.definition_id for d in FIDELITY_DEFINITIONS}
    assert not (
        ids
        & {
            "relationship_fidelity.composite",
            "relationship_fidelity.overall",
            "relationship_fidelity.strength",
        }
    )
