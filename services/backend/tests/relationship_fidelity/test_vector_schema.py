"""Schema-conformance + honesty tests for the fidelity-vector surface (M7).

Checks that produced fidelity vectors are MULTIDIMENSIONAL (never a universal
scalar), that every dimension is nullable with no synthetic 0, and that
insufficient evidence yields an honest unknown surface rather than fabricated
zeros. Payloads are validated against the M1 canonical JSON Schema
``packages/shared/contracts/relationship-fidelity-vector.schema.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validate

from services.relationship_fidelity.engine import RelationshipFidelityEngine
from shared.computation.errors import TypeContractError
from shared.relationship_fidelity.definitions import FIDELITY_DIMENSIONS
from shared.relationship_fidelity.evidence import Observation
from shared.relationship_fidelity.vector import (
    FidelityVector,
    assemble_fidelity_vector,
)

ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = (
    ROOT / "packages" / "shared" / "contracts" / "relationship-fidelity-vector.schema.json"
)
FIDELITY_SCHEMA = json.loads(SCHEMA_PATH.read_text())

engine = RelationshipFidelityEngine()


def _obs(
    oid: str,
    direction: str = "outgoing",
    source: str = "src-a",
    ts: str = "2026-08-01T00:00:00Z",
    **kwargs,
) -> Observation:
    return Observation(
        observation_id=oid,
        predicate="FOLLOWS",
        direction=direction,
        source_key=source,
        observed_at=ts,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Multidimensional, never scalar
# --------------------------------------------------------------------------- #
def test_vector_is_multidimensional_never_scalar():
    vec = engine.compute_fidelity(
        relationship_ref="rel:u1",
        observations=[_obs("o1")],
        measured={"identity_confidence": 0.5},
    )
    payload = vec.to_contract_dict()
    # no universal composite / scalar representation may appear
    assert not (set(payload) & {"fidelity_score", "overall_fidelity", "strength", "score"})
    # every schema dimension present as a number-or-null
    for dim in FIDELITY_DIMENSIONS:
        assert dim in payload, f"missing dimension {dim}"
        assert payload[dim] is None or isinstance(payload[dim], (int, float))
    # payload validates against the M1 contract
    validate(payload, FIDELITY_SCHEMA)


def test_schema_has_no_universal_scalar_key():
    schema_props = set(FIDELITY_SCHEMA["properties"])
    assert not (schema_props & {"fidelity_score", "overall_fidelity", "strength", "score"})


def test_existence_confidence_is_separate_from_strength():
    # evidence_confidence (existence) and strength dims are distinct axes.
    assert "evidence_confidence" in FIDELITY_DIMENSIONS
    for strength in ("persistence", "reciprocity", "interaction_depth"):
        assert strength in FIDELITY_DIMENSIONS
        assert strength != "evidence_confidence"


# --------------------------------------------------------------------------- #
# unknown is never zero
# --------------------------------------------------------------------------- #
def test_insufficient_evidence_unknown_not_zero_schema_valid():
    # One observation from an UNKNOWN source, no window, no independence account:
    # nothing is corroborated => every dimension is null (never fabricated to 0),
    # yet the surface is schema-valid because first/last are real timestamps.
    obs = [
        Observation(
            observation_id="o1",
            predicate="FOLLOWS",
            direction="outgoing",
            source_key="",
            observed_at="2026-08-01T00:00:00Z",
        )
    ]
    vec = engine.compute_fidelity(relationship_ref="rel:u2", observations=obs)
    assert vec.observation_count == 1
    assert vec.independent_evidence_count is None
    assert vec.status == "unknown"
    values = vec.dimension_values()
    assert all(v is None for v in values.values())
    assert all(v != 0 for v in values.values())  # unknown is never 0
    validate(vec.to_contract_dict(), FIDELITY_SCHEMA)


def test_zero_observations_unknown_never_zero():
    vec = engine.compute_fidelity(relationship_ref="rel:u3", observations=[])
    assert vec.observation_count == 0
    assert vec.status == "unknown"
    assert vec.materialized_dimension_count == 0
    values = vec.dimension_values()
    assert all(v is None for v in values.values())
    assert vec.to_contract_dict()["observation_count"] == 0
    # zero/absent independence must surface as null, never a fabricated number
    assert vec.independent_evidence_count is None
    assert vec.independent_source_count is None


def test_assembler_rejects_unknown_dimension():
    with pytest.raises(TypeContractError):
        assemble_fidelity_vector(
            fidelity_vector_id="fid-x",
            relationship_ref="rel:x",
            dimension_values={"not_a_dimension": 0.5},
            observation_count=1,
            independent_evidence_count=None,
            independent_source_count=None,
            first_observed_at="2026-08-01T00:00:00Z",
            last_observed_at="2026-08-01T00:00:00Z",
        )


def test_vector_model_forbids_extra_properties():
    # additionalProperties:false is honored at the model boundary.
    with pytest.raises(Exception):
        FidelityVector(
            fidelity_vector_id="fid-x",
            relationship_ref="rel:x",
            gibberish=1,  # type: ignore[call-arg]
        )


def test_dimensions_are_bounded_when_present():
    with pytest.raises(Exception):
        assemble_fidelity_vector(
            fidelity_vector_id="fid-x",
            relationship_ref="rel:x",
            dimension_values={"evidence_confidence": 1.7},
            observation_count=1,
            independent_evidence_count=None,
            independent_source_count=None,
            first_observed_at="2026-08-01T00:00:00Z",
            last_observed_at="2026-08-01T00:00:00Z",
        )
