"""Value / state / unit / bounds validation for measurement results.

These validators are the enforcement teeth of the integrity plane. They are
pure and dependency-free (stdlib only) so they can run anywhere: inside a
pydantic model, in a calculator before it emits, or in a persistence guard.
"""

from __future__ import annotations

import math
from typing import Optional

from shared.measurement.value_states import ValueState, requires_value


class MeasurementValidationError(Exception):
    """Raised when a measurement violates its value / state / unit / bounds contract."""


def _is_real_number(value: object) -> bool:
    """True for int/float that is not a bool. Booleans are never a measurement."""

    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_value(
    value: Optional[float],
    value_state: ValueState | str,
    *,
    unit: Optional[str] = None,
    lower: Optional[float] = None,
    upper: Optional[float] = None,
) -> None:
    """Validate a ``(value, value_state)`` pair against the integrity contract.

    Raises :class:`MeasurementValidationError` when:

    * ``value`` is present but not a real, finite number (NaN / inf / non-numeric),
    * ``value`` is present while ``value_state`` forbids a value,
    * ``value`` is absent while ``value_state`` requires one,
    * ``unit == "count"`` and ``value < 0`` (counts cannot be negative),
    * ``value`` falls outside ``[lower, upper]`` when those bounds are given.
    """

    state = ValueState(value_state)
    needs_value = requires_value(state)

    if value is not None:
        if not _is_real_number(value):
            raise MeasurementValidationError(
                f"value must be a real number, got {type(value).__name__}"
            )
        if math.isnan(value) or math.isinf(value):
            raise MeasurementValidationError("value must be finite (got NaN or inf)")

    if needs_value:
        if value is None:
            raise MeasurementValidationError(
                f"value_state {state.value!r} requires a numeric value but got None"
            )
    else:
        if value is not None:
            raise MeasurementValidationError(
                f"value_state {state.value!r} forbids a value but got {value!r}"
            )
        # No value present and none allowed — nothing further to check.
        return

    # From here ``value`` is a finite, real number.
    if unit == "count" and value < 0:
        raise MeasurementValidationError(f"count metric cannot be negative, got {value!r}")
    if lower is not None and value < lower:
        raise MeasurementValidationError(f"value {value!r} is below lower bound {lower!r}")
    if upper is not None and value > upper:
        raise MeasurementValidationError(f"value {value!r} is above upper bound {upper!r}")


def validate_metric_version(version: object) -> None:
    """Require ``version`` to be a non-empty string."""

    if not isinstance(version, str) or not version.strip():
        raise MeasurementValidationError("metric_version must be a non-empty string")
