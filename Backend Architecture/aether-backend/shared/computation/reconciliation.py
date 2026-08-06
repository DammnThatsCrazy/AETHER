"""A generic reconciliation model.

Reuses the state/tolerance vocabulary already proven in
``services/reconciliation`` and ``packages/shared/value.ts`` and packages it into
a portable :class:`ReconciliationCase` so any two authorities (SDK vs provider,
provider vs invoice, on-chain vs indexer, campaign total vs entity allocations,
prediction vs outcome) can be compared with a recorded tolerance and rationale.

A value is not "reconciled" merely because a formula executed — reconciliation is
an explicit comparison against an authority with a resolution state.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.computation.types import to_decimal


class ReconciliationState(str, Enum):
    MATCHED = "matched"
    WITHIN_TOLERANCE = "within_tolerance"
    PARTIAL = "partial"
    STALE = "stale"
    CONFLICT = "conflict"
    SOURCE_ONLY = "source_only"
    DERIVED_ONLY = "derived_only"
    DUPLICATE = "duplicate"
    UNRECONCILED = "unreconciled"
    NOT_APPLICABLE = "not_applicable"


RECONCILIATION_STATES: tuple[str, ...] = tuple(s.value for s in ReconciliationState)


class ReconciliationCase(BaseModel):
    """The record of comparing a derived value against an authority."""

    dimension: str
    authorities: list[str] = Field(default_factory=list)
    source_value: Optional[str] = None
    derived_value: Optional[str] = None
    difference: Optional[str] = None
    relative_difference: Optional[float] = None
    tolerance: Optional[float] = None
    tolerance_rationale: Optional[str] = None
    state: ReconciliationState = ReconciliationState.UNRECONCILED
    resolution: Optional[str] = None
    human_review_state: Optional[str] = None
    evidence: dict[str, Any] = Field(default_factory=dict)


def reconcile(
    *,
    dimension: str,
    source_value: object,
    derived_value: object,
    tolerance: float = 0.0,
    tolerance_rationale: Optional[str] = None,
    authorities: Optional[list[str]] = None,
) -> ReconciliationCase:
    """Compare two values and classify the reconciliation state honestly.

    Missing sides yield ``source_only``/``derived_only``/``unreconciled`` — never
    a false ``matched``.
    """
    src = to_decimal(source_value)
    der = to_decimal(derived_value)
    case = ReconciliationCase(
        dimension=dimension,
        authorities=authorities or [],
        source_value=None if src is None else format(src, "f"),
        derived_value=None if der is None else format(der, "f"),
        tolerance=tolerance,
        tolerance_rationale=tolerance_rationale,
    )
    if src is None and der is None:
        case.state = ReconciliationState.UNRECONCILED
        return case
    if src is None:
        case.state = ReconciliationState.DERIVED_ONLY
        return case
    if der is None:
        case.state = ReconciliationState.SOURCE_ONLY
        return case

    diff = der - src
    case.difference = format(diff, "f")
    rel = float(abs(diff) / abs(src)) if src != 0 else (0.0 if diff == 0 else 1.0)
    case.relative_difference = rel
    if diff == 0:
        case.state = ReconciliationState.MATCHED
    elif rel <= tolerance:
        case.state = ReconciliationState.WITHIN_TOLERANCE
    else:
        case.state = ReconciliationState.CONFLICT
    return case


__all__ = [
    "ReconciliationState",
    "RECONCILIATION_STATES",
    "ReconciliationCase",
    "reconcile",
]
