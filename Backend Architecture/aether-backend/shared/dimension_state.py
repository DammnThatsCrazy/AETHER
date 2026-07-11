"""Canonical dimension-state contract (Python mirror of
``packages/shared/dimension-state.ts``).

A "dimension" is one slice of a profile / analytics surface (events, wallets,
consent, campaigns, …). Every dimension read reports one canonical
:class:`DimensionState` so a surface can say honestly WHY a slice is empty or
degraded instead of rendering a blank that reads as "no activity".

The TS twin and this module are kept in lockstep by
``tests/contracts/test_dimension_state_parity.py`` (const-array set equality).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

DimensionState = Literal[
    "ready",
    "empty",
    "partial",
    "stale",
    "insufficient_data",
    "degraded",
    "suppressed",
    "not_applicable",
    "pending",
    "error",
]

# Parallel const for iteration/validation (mirrors `dimensionStates`).
DIMENSION_STATES: tuple[str, ...] = (
    "ready",
    "empty",
    "partial",
    "stale",
    "insufficient_data",
    "degraded",
    "suppressed",
    "not_applicable",
    "pending",
    "error",
)

# Ordered BEST → WORST. The worst state wins in a rollup, so an overall
# readiness never looks better than the weakest dimension.
DIMENSION_STATE_PRECEDENCE: tuple[str, ...] = (
    "ready",
    "not_applicable",
    "empty",
    "pending",
    "partial",
    "insufficient_data",
    "stale",
    "suppressed",
    "degraded",
    "error",
)

DimensionReasonCode = Literal[
    "ok",
    "no_data",
    "below_min_events",
    "past_freshness_sla",
    "partial_inputs",
    "dependency_failed",
    "consent_withheld",
    "entity_type_mismatch",
    "awaiting_reconciliation",
    "computation_error",
]

DIMENSION_REASON_CODES: tuple[str, ...] = (
    "ok",
    "no_data",
    "below_min_events",
    "past_freshness_sla",
    "partial_inputs",
    "dependency_failed",
    "consent_withheld",
    "entity_type_mismatch",
    "awaiting_reconciliation",
    "computation_error",
)


class DimensionFreshness(BaseModel):
    """Freshness facts for a dimension (all optional — freshness may be unknown)."""

    watermark: Optional[str] = None
    age_seconds: Optional[float] = None
    sla_seconds: Optional[float] = None
    is_stale: Optional[bool] = None


class DimensionEnvelope(BaseModel):
    """The canonical envelope every dimension read returns."""

    dimension: str
    state: DimensionState = "empty"
    reason_code: DimensionReasonCode = "no_data"
    freshness: Optional[DimensionFreshness] = None
    count: Optional[int] = None
    message: Optional[str] = None

    def model_dump_safe(self) -> dict:
        return self.model_dump(mode="json")


def worst_state(states: list[str]) -> str:
    """Roll many states into the single worst one (empty list → ``ready``)."""
    worst = "ready"
    worst_rank = 0
    for state in states:
        try:
            rank = DIMENSION_STATE_PRECEDENCE.index(state)
        except ValueError:
            continue
        if rank > worst_rank:
            worst_rank = rank
            worst = state
    return worst


def envelope_for_error(
    dimension: str, *, reason_code: str = "computation_error", message: Optional[str] = None
) -> DimensionEnvelope:
    """Envelope for a dimension whose computation failed — surfaced, not erased."""
    return DimensionEnvelope(
        dimension=dimension,
        state="error",
        reason_code=reason_code,  # type: ignore[arg-type]
        message=message,
    )


def envelope_for_items(
    dimension: str,
    *,
    count: int,
    freshness: Optional[DimensionFreshness] = None,
    min_items: int = 1,
    applicable: bool = True,
) -> DimensionEnvelope:
    """Envelope for a successful dimension read, choosing the honest state.

    ``ready`` when data is present and fresh; ``stale`` when past SLA;
    ``insufficient_data`` when below ``min_items`` but non-empty; ``empty`` when
    there is genuinely nothing; ``not_applicable`` when the dimension does not
    apply to this entity.
    """
    if not applicable:
        return DimensionEnvelope(
            dimension=dimension, state="not_applicable", reason_code="entity_type_mismatch",
            count=count, freshness=freshness,
        )
    if count <= 0:
        return DimensionEnvelope(
            dimension=dimension, state="empty", reason_code="no_data",
            count=0, freshness=freshness,
        )
    if freshness is not None and freshness.is_stale:
        return DimensionEnvelope(
            dimension=dimension, state="stale", reason_code="past_freshness_sla",
            count=count, freshness=freshness,
        )
    if count < max(1, min_items):
        return DimensionEnvelope(
            dimension=dimension, state="insufficient_data", reason_code="below_min_events",
            count=count, freshness=freshness,
        )
    return DimensionEnvelope(
        dimension=dimension, state="ready", reason_code="ok",
        count=count, freshness=freshness,
    )


def rollup_state(envelopes: list[DimensionEnvelope]) -> str:
    """Worst state across a set of dimension envelopes."""
    return worst_state([e.state for e in envelopes])


__all__ = [
    "DimensionState",
    "DIMENSION_STATES",
    "DIMENSION_STATE_PRECEDENCE",
    "DimensionReasonCode",
    "DIMENSION_REASON_CODES",
    "DimensionFreshness",
    "DimensionEnvelope",
    "worst_state",
    "rollup_state",
    "envelope_for_error",
    "envelope_for_items",
]


# Silence unused-import complaints for re-exported typing helpers.
_ = (Any, Field)
