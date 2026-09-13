"""The CanonicalResult envelope — the self-describing shape every canonical
computation produces.

This generalizes ``shared/measurement/contracts.py::MeasurementResult`` to all
domains and enforces the platform's core invariant at construction: a value may
be present only under a status that justifies it, and the honest-absence
statuses forbid a value entirely (so "unknown" can never masquerade as 0).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

from shared.computation.errors import TypeContractError
from shared.computation.quality import Quality
from shared.computation.types import MathType
from shared.computation.uncertainty import Uncertainty


class ResultStatus(str, Enum):
    """Every honest state a computed result can be in."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    ESTIMATED = "estimated"
    INSUFFICIENT_DATA = "insufficient_data"
    MISSING_INPUTS = "missing_inputs"
    NOT_APPLICABLE = "not_applicable"
    NOT_PROVISIONED = "not_provisioned"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    CONFLICTED = "conflicted"
    UNRECONCILED = "unreconciled"
    TRUNCATED = "truncated"
    PRIVACY_RESTRICTED = "privacy_restricted"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


RESULT_STATUSES: tuple[str, ...] = tuple(s.value for s in ResultStatus)

# ``available`` REQUIRES a value. The honest-absence statuses FORBID one (so a
# missing/unavailable/failed number can never be a real 0). The middle band
# (partial/estimated/stale/conflicted/unreconciled/truncated) MAY carry a
# best-effort value, but always flagged as such.
_REQUIRE_VALUE: frozenset[ResultStatus] = frozenset({ResultStatus.AVAILABLE})
_FORBID_VALUE: frozenset[ResultStatus] = frozenset(
    {
        ResultStatus.MISSING_INPUTS,
        ResultStatus.UNAVAILABLE,
        ResultStatus.INSUFFICIENT_DATA,
        ResultStatus.NOT_APPLICABLE,
        ResultStatus.NOT_PROVISIONED,
        ResultStatus.SUPPRESSED,
        ResultStatus.PRIVACY_RESTRICTED,
        ResultStatus.FAILED,
    }
)


def requires_value(status: ResultStatus) -> bool:
    return status in _REQUIRE_VALUE


def forbids_value(status: ResultStatus) -> bool:
    return status in _FORBID_VALUE


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CanonicalResult(BaseModel):
    """A single canonical computed result, self-describing about its own truth."""

    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    definition_id: str
    definition_version: str
    run_id: Optional[str] = None

    # Scope
    tenant_id: str
    subject: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    grain: Optional[str] = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
    window: dict[str, Any] = Field(default_factory=dict)
    as_of: Optional[str] = None
    context_hash: Optional[str] = None

    # Value
    value: Optional[float] = None
    value_type: MathType
    unit: str = "count"
    currency: Optional[str] = None
    status: ResultStatus

    # Rate/estimate detail
    numerator: Optional[str] = None
    denominator: Optional[str] = None
    sample_size: Optional[int] = None
    interval_low: Optional[float] = None
    interval_high: Optional[float] = None
    standard_error: Optional[float] = None

    # Trust
    quality: Quality = Field(default_factory=Quality)
    uncertainty: Optional[Uncertainty] = None
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    allocation: dict[str, Any] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)

    # Bitemporal
    effective_at: Optional[str] = None
    computed_at: str = Field(default_factory=_utc_now_iso)
    recorded_at: Optional[str] = None

    # Correction chain
    supersedes_result_id: Optional[str] = None
    superseded_by: Optional[str] = None
    restatement_reason: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_value_invariant(self) -> "CanonicalResult":
        if requires_value(self.status):
            if self.value is None:
                raise TypeContractError(
                    f"status {self.status.value!r} requires a value but value is None"
                )
            if not math.isfinite(self.value):
                raise TypeContractError(
                    f"value must be finite for status {self.status.value!r}"
                )
        if forbids_value(self.status) and self.value is not None:
            raise TypeContractError(
                f"status {self.status.value!r} forbids a value but value is {self.value!r}"
            )
        # Money must carry a currency whenever it bears a value.
        if (
            self.value_type == MathType.MONEY
            and self.value is not None
            and not self.currency
        ):
            raise TypeContractError("money result carries a value but no currency")
        return self


__all__ = [
    "ResultStatus",
    "RESULT_STATUSES",
    "requires_value",
    "forbids_value",
    "CanonicalResult",
]
