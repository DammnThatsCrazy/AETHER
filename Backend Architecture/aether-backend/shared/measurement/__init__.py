"""Aether Measurement Integrity Plane — pure contracts + logic.

Dependency-free (stdlib + pydantic + numpy only) building blocks that make one
rule enforceable across the platform:

    No metric is reported as a real number unless the data supports it.

Calculators return ``(value_or_None, ValueState)`` — never ``0`` on missing
data. A value is permitted only under a value-bearing state (OBSERVED /
ESTIMATED); every other state carries ``value is None`` and an honest reason.
"""

from __future__ import annotations

from shared.measurement.context import MeasurementContext
from shared.measurement.contracts import MeasurementResult, Uncertainty
from shared.measurement.registry import (
    METRIC_REGISTRY,
    REGISTRY_VERSION,
    MetricDefinition,
    get_definition,
    list_definitions,
)
from shared.measurement.restatement import build_restatement
from shared.measurement.sufficiency import evaluate_sufficiency, sufficiency_dict
from shared.measurement.uncertainty import as_uncertainty, bootstrap_ci, wilson_interval
from shared.measurement.validators import (
    MeasurementValidationError,
    validate_metric_version,
    validate_value,
)
from shared.measurement.value_states import (
    VALUE_STATES,
    ValueState,
    requires_value,
)

__all__ = [
    # value states
    "ValueState",
    "VALUE_STATES",
    "requires_value",
    # context
    "MeasurementContext",
    # contracts
    "MeasurementResult",
    "Uncertainty",
    # validators
    "MeasurementValidationError",
    "validate_value",
    "validate_metric_version",
    # uncertainty
    "wilson_interval",
    "bootstrap_ci",
    "as_uncertainty",
    # sufficiency
    "evaluate_sufficiency",
    "sufficiency_dict",
    # registry
    "MetricDefinition",
    "METRIC_REGISTRY",
    "get_definition",
    "list_definitions",
    "REGISTRY_VERSION",
    # restatement
    "build_restatement",
]
