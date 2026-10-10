"""The schema-conformant multidimensional fidelity-vector surface (M7).

``FidelityVector`` mirrors
``packages/shared/contracts/relationship-fidelity-vector.schema.json`` exactly:
a MULTIDIMENSIONAL vector whose dimensions are nullable numbers with no default
and no synthetic 0 — unknown is a state, 0 is a measurement. There is NO scalar
field here (no ``fidelity_score`` / ``overall_fidelity`` / ``strength``), and the
assembler never reduces the vector to one number.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.computation.errors import TypeContractError
from shared.relationship_fidelity.definitions import (
    FIDELITY_DEFINITION_VERSION,
    FIDELITY_DIMENSIONS,
)

FIDELITY_SCHEMA_VERSION: str = "1.0.0"

FidelityStatus = Literal["current", "stale", "superseded", "disputed", "unknown"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FidelityVector(BaseModel):
    """A schema-conformant multidimensional relationship-fidelity vector."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = FIDELITY_SCHEMA_VERSION
    fidelity_vector_id: str
    relationship_ref: str
    definition_version: str = FIDELITY_DEFINITION_VERSION

    # The 20 multidimensional vector dimensions (nullable — no synthetic 0).
    evidence_confidence: Optional[float] = None
    source_reliability: Optional[float] = None
    identity_confidence: Optional[float] = None
    persistence: Optional[float] = None
    reciprocity: Optional[float] = None
    interaction_frequency: Optional[float] = None
    interaction_depth: Optional[float] = None
    context_diversity: Optional[float] = None
    temporal_continuity: Optional[float] = None
    semantic_specificity: Optional[float] = None
    semantic_originality: Optional[float] = None
    preexisting_affinity_support: Optional[float] = None
    incentive_exposure: Optional[float] = None
    incentive_independence_support: Optional[float] = None
    coordination_indicator_strength: Optional[float] = None
    economic_significance: Optional[float] = None
    social_significance: Optional[float] = None
    organizational_significance: Optional[float] = None
    agentic_significance: Optional[float] = None
    outcome_support: Optional[float] = None

    observation_count: int = 0
    independent_evidence_count: Optional[int] = None
    independent_source_count: Optional[int] = None

    first_observed_at: Optional[str] = None
    last_observed_at: Optional[str] = None
    coverage: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    uncertainty: Optional[dict[str, Any]] = None
    status: FidelityStatus = "unknown"
    computation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    computed_at: str = Field(default_factory=_utc_now_iso)

    @model_validator(mode="after")
    def _dimension_values_in_unit_range(self) -> "FidelityVector":
        for name in FIDELITY_DIMENSIONS:
            value = getattr(self, name)
            if value is None:
                continue
            if not (0.0 <= value <= 1.0):
                raise TypeContractError(
                    f"fidelity dimension {name} must be in [0, 1] (got {value})"
                )
        return self

    def dimension_values(self) -> dict[str, Optional[float]]:
        """The multidimensional vector as ``{dimension: value|None}`` — no scalar."""
        return {name: getattr(self, name) for name in FIDELITY_DIMENSIONS}

    @property
    def materialized_dimension_count(self) -> int:
        """Number of dimensions with a real (non-null) value."""
        return sum(1 for v in self.dimension_values().values() if v is not None)

    def to_contract_dict(self) -> dict[str, Any]:
        """JSON-safe wire dict conforming to the M1 fidelity-vector schema."""
        return self.model_dump(mode="json")


def assemble_fidelity_vector(
    *,
    fidelity_vector_id: str,
    relationship_ref: str,
    dimension_values: dict[str, Optional[float]],
    observation_count: int,
    independent_evidence_count: Optional[int],
    independent_source_count: Optional[int],
    first_observed_at: Optional[str],
    last_observed_at: Optional[str],
    coverage: Optional[dict[str, Any]] = None,
    quality: Optional[dict[str, Any]] = None,
    uncertainty: Optional[dict[str, Any]] = None,
    limitations: Optional[list[str]] = None,
    evidence_refs: Optional[list[str]] = None,
    computation_refs: Optional[list[str]] = None,
) -> FidelityVector:
    """Assemble a vector without ever fabricating a dimension or a scalar.

    ``status`` is chosen honestly: ``unknown`` when no dimension has a value
    (evidence insufficient), else ``current``. Dimension values outside the
    known set are rejected (``additionalProperties`` = false semantics).
    """
    extra = set(dimension_values) - set(FIDELITY_DIMENSIONS)
    if extra:
        raise TypeContractError(f"unknown fidelity dimension(s): {sorted(extra)}")
    fields: dict[str, object] = {
        "fidelity_vector_id": fidelity_vector_id,
        "relationship_ref": relationship_ref,
        "observation_count": observation_count,
        "independent_evidence_count": independent_evidence_count,
        "independent_source_count": independent_source_count,
        "first_observed_at": first_observed_at,
        "last_observed_at": last_observed_at,
        "coverage": coverage,
        "quality": quality,
        "uncertainty": uncertainty,
        "limitations": limitations or [],
        "evidence_refs": evidence_refs or [],
        "computation_refs": computation_refs or [],
    }
    for name in FIDELITY_DIMENSIONS:
        fields[name] = dimension_values.get(name)
    materialized = sum(1 for v in dimension_values.values() if v is not None)
    fields["status"] = "current" if materialized > 0 else "unknown"
    return FidelityVector(**fields)


__all__ = [
    "FIDELITY_SCHEMA_VERSION",
    "FidelityStatus",
    "FidelityVector",
    "assemble_fidelity_vector",
]
