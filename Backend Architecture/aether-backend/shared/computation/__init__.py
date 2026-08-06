"""Aether Computation Substrate — one governed contract for every platform number.

Generalizes the Measurement Integrity Plane (``shared/measurement``) and composes
the financial value semantics (``services/value``), dimension-state envelopes
(``shared/dimension_state``), and temporal kernel (``shared/temporal``) into a
single substrate under which every material number is:

    typed · scoped · versioned · explainable · quality-aware · uncertainty-aware
    · restatable · and consistent wherever it appears.

Non-negotiables enforced here: unknown is never 0, money is Decimal + currency,
different mathematical kinds are not interchangeable, and every rate exposes its
numerator and denominator.
"""

from __future__ import annotations

from shared.computation.aggregation import (
    AGGREGATION_TYPES,
    AggregationType,
    ratio_of_sums,
    sum_money,
    weighted_average,
)
from shared.computation.allocation import (
    ALLOCATION_POLICIES,
    AllocationPolicy,
    AllocationResult,
    AllocationTarget,
    allocate,
)
from shared.computation.calibration import (
    CalibrationArtifact,
    CalibrationMethod,
    brier_score,
    expected_calibration_error,
)
from shared.computation.context import ComputationContext
from shared.computation.definition import (
    ComputationDefinition,
    ComputationKind,
    DecisionImpactClass,
    LifecycleState,
)
from shared.computation.errors import (
    AggregationError,
    AllocationError,
    ComputationError,
    ContextError,
    DefinitionError,
    ReconciliationError,
    RestatementError,
    TypeContractError,
)
from shared.computation.lineage import (
    BoundedReadDisclosure,
    ComputationLineage,
    InputLineage,
)
from shared.computation.policies import DecisionPolicy, DecisionThreshold, PolicyOutcome
from shared.computation.quality import (
    Quality,
    QualityDimension,
    QualityDimensionName,
)
from shared.computation.reconciliation import (
    RECONCILIATION_STATES,
    ReconciliationCase,
    ReconciliationState,
    reconcile,
)
from shared.computation.registry import (
    COMPUTATION_REGISTRY,
    REGISTRY_VERSION,
    get_definition,
    list_active,
    list_definitions,
    register,
)
from shared.computation.result import (
    RESULT_STATUSES,
    CanonicalResult,
    ResultStatus,
    forbids_value,
    requires_value,
)
from shared.computation.runtime import (
    count_result,
    money_result,
    new_run_id,
    rate_result,
)
from shared.computation.serialization import presentation_metadata, result_to_wire
from shared.computation.types import (
    MATH_TYPES,
    Balance,
    CanonicalValue,
    Distribution,
    Duration,
    FractionalCount,
    GraphMetric,
    HeuristicScore,
    IntegerCount,
    Interval,
    MathType,
    Money,
    OrdinalScore,
    Percentage,
    Percentile,
    Probability,
    Quantity,
    Rank,
    Rate,
    Ratio,
    TimestampedValue,
    TriState,
    UncalibratedScore,
    Vector,
    to_decimal,
    to_decimal_string,
)
from shared.computation.uncertainty import Uncertainty, UncertaintyKind

__all__ = [
    # errors
    "ComputationError",
    "DefinitionError",
    "ContextError",
    "TypeContractError",
    "AggregationError",
    "AllocationError",
    "ReconciliationError",
    "RestatementError",
    # types
    "MathType",
    "MATH_TYPES",
    "CanonicalValue",
    "IntegerCount",
    "FractionalCount",
    "Money",
    "Rate",
    "Ratio",
    "Percentage",
    "Probability",
    "OrdinalScore",
    "HeuristicScore",
    "UncalibratedScore",
    "Rank",
    "Percentile",
    "Interval",
    "Distribution",
    "Vector",
    "GraphMetric",
    "Duration",
    "Quantity",
    "Balance",
    "TriState",
    "TimestampedValue",
    "to_decimal",
    "to_decimal_string",
    # context / result
    "ComputationContext",
    "CanonicalResult",
    "ResultStatus",
    "RESULT_STATUSES",
    "requires_value",
    "forbids_value",
    # quality / uncertainty
    "Quality",
    "QualityDimension",
    "QualityDimensionName",
    "Uncertainty",
    "UncertaintyKind",
    # aggregation / allocation / reconciliation
    "AggregationType",
    "AGGREGATION_TYPES",
    "ratio_of_sums",
    "weighted_average",
    "sum_money",
    "AllocationPolicy",
    "ALLOCATION_POLICIES",
    "AllocationResult",
    "AllocationTarget",
    "allocate",
    "ReconciliationState",
    "RECONCILIATION_STATES",
    "ReconciliationCase",
    "reconcile",
    # definition / registry
    "ComputationDefinition",
    "ComputationKind",
    "LifecycleState",
    "DecisionImpactClass",
    "COMPUTATION_REGISTRY",
    "REGISTRY_VERSION",
    "get_definition",
    "list_definitions",
    "list_active",
    "register",
    # calibration / policies / lineage
    "CalibrationArtifact",
    "CalibrationMethod",
    "brier_score",
    "expected_calibration_error",
    "DecisionPolicy",
    "DecisionThreshold",
    "PolicyOutcome",
    "InputLineage",
    "ComputationLineage",
    "BoundedReadDisclosure",
    # runtime / serialization
    "new_run_id",
    "rate_result",
    "money_result",
    "count_result",
    "presentation_metadata",
    "result_to_wire",
]
