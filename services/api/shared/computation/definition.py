"""Versioned computation definitions.

A definition declares *what a number is* — its kind, output type, unit, formula
inputs, scope, time semantics, null/zero policy, aggregation, allocation, and
governance metadata. Definitions are immutable once ``active``: any change to
formula, denominator, scope, allocation, source, precision, threshold
interpretation, or window semantics requires a NEW version. (Policies — what to
DO with a number — are versioned separately in ``policies.py``.)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from shared.computation.aggregation import AggregationType
from shared.computation.types import MathType


class ComputationKind(str, Enum):
    """What sort of mathematical object the definition produces (task §0.3)."""

    OBSERVED_FACT = "observed_fact"
    DETERMINISTIC_METRIC = "deterministic_metric"
    ALLOCATED_VALUE = "allocated_value"
    HEURISTIC_SCORE = "heuristic_score"
    STATISTICAL_ESTIMATE = "statistical_estimate"
    CALIBRATED_PROBABILITY = "calibrated_probability"
    FORECAST = "forecast"
    RECONCILED_VALUE = "reconciled_value"
    POLICY_DECISION = "policy_decision"
    COUNTERFACTUAL_ESTIMATE = "counterfactual_estimate"
    SIMULATION = "simulation"
    RANK = "rank"
    PERCENTILE = "percentile"
    GRAPH_METRIC = "graph_metric"


class LifecycleState(str, Enum):
    DRAFT = "draft"
    EXPERIMENTAL = "experimental"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class DecisionImpactClass(str, Enum):
    """How consequential decisions built on this number are (drives fail-closed)."""

    INFORMATIONAL = "informational"
    OPERATIONAL = "operational"
    CUSTOMER_FACING = "customer_facing"
    FINANCIAL = "financial"
    ACCESS_CONTROL = "access_control"
    LEGAL = "legal"


class ComputationDefinition(BaseModel):
    """One versioned, immutable-once-active canonical computation definition."""

    definition_id: str
    definition_version: str = "1"
    display_name: str
    description: str = ""
    owner: str
    domain: str
    lifecycle_state: LifecycleState = LifecycleState.DRAFT

    computation_kind: ComputationKind
    output_type: MathType
    unit: str
    scale: Optional[str] = None
    valid_range_low: Optional[float] = None
    valid_range_high: Optional[float] = None
    precision: Optional[int] = None
    rounding_policy: str = "half_up"

    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    dependency_definitions: list[str] = Field(default_factory=list)

    scope_dimensions: list[str] = Field(default_factory=list)
    supported_grains: list[str] = Field(default_factory=list)
    default_grain: Optional[str] = None

    event_time_field: Optional[str] = None
    window_semantics: Optional[str] = None
    timezone_policy: str = "context"
    late_data_policy: str = "restate_window"
    correction_policy: str = "supersede"

    null_policy: str = "null_not_zero"
    zero_policy: str = "evidence_backed"
    minimum_sample_size: int = 1
    minimum_coverage: Optional[float] = None

    aggregation_type: AggregationType = AggregationType.NON_AGGREGATABLE
    allocation_policy: Optional[str] = None
    reconciliation_policy: Optional[str] = None

    executor_type: str = "python"
    executor_reference: Optional[str] = None
    code_commit: Optional[str] = None
    sql_digest: Optional[str] = None
    model_reference: Optional[str] = None
    feature_contract_reference: Optional[str] = None

    consent_purposes: list[str] = Field(default_factory=list)
    data_classification: Optional[str] = None
    permitted_consumers: list[str] = Field(default_factory=list)
    decision_impact_class: DecisionImpactClass = DecisionImpactClass.INFORMATIONAL

    # Governance: an active definition must have an owner and declare its tests.
    tests: list[str] = Field(default_factory=list)

    @field_validator("owner")
    @classmethod
    def _owner_present(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("computation definition requires an owner")
        return v

    def key(self) -> str:
        return f"{self.definition_id}@{self.definition_version}"


__all__ = [
    "ComputationKind",
    "LifecycleState",
    "DecisionImpactClass",
    "ComputationDefinition",
]
