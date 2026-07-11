"""Pydantic contracts for the Measurement Integrity Plane.

:class:`MeasurementResult` is the single wire/persistence shape every metric
produces. Its model validator hard-enforces the plane's core invariant, so an
invalid ``(value, value_state)`` pair can never be constructed — not from a
calculator, not from a repository row, not from an API payload.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from shared.measurement.validators import MeasurementValidationError
from shared.measurement.value_states import ValueState, requires_value


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string."""

    return datetime.now(timezone.utc).isoformat()


class Uncertainty(BaseModel):
    """A quantified uncertainty band attached to a measurement value."""

    method: str
    point: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    confidence_level: float = 0.95


class MeasurementResult(BaseModel):
    """A single measured metric, self-describing about its own trustworthiness."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    metric_name: str
    metric_version: str
    context_hash: str
    value: Optional[float] = None
    value_state: ValueState
    unit: str = "count"
    lineage: dict = Field(default_factory=dict)
    sufficiency: dict = Field(default_factory=dict)
    uncertainty: Optional[Uncertainty] = None
    computed_at: str = Field(default_factory=_utc_now_iso)
    superseded_by: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_value_invariant(self) -> "MeasurementResult":
        """Value-bearing states require a finite number; all others require None."""

        if requires_value(self.value_state):
            if self.value is None:
                raise MeasurementValidationError(
                    f"value_state {self.value_state.value!r} requires a numeric "
                    "value but value is None"
                )
            if not math.isfinite(self.value):
                raise MeasurementValidationError(
                    f"value must be finite for value_state "
                    f"{self.value_state.value!r} (got {self.value!r})"
                )
        else:
            if self.value is not None:
                raise MeasurementValidationError(
                    f"value_state {self.value_state.value!r} forbids a value "
                    f"but value is {self.value!r}"
                )
        return self
