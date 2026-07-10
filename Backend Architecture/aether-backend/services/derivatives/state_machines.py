"""Order and position state machines.

Observation semantics, not execution semantics: these machines classify
externally executed lifecycle evidence. Out-of-order and duplicate venue
updates are normal — a lower-rank status arriving after a higher-rank one is
recorded as stale evidence (applied=False), never an error, and corrections
append `*_corrected` facts rather than mutating history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ── Order lifecycle ──────────────────────────────────────────────────────────

ORDER_LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending": ("open", "partially_filled", "filled", "cancelled", "rejected", "expired", "unknown"),
    "open": ("partially_filled", "filled", "cancelled", "expired", "unknown"),
    "partially_filled": ("partially_filled", "filled", "cancelled", "expired", "unknown"),
    "filled": ("unknown",),
    "cancelled": ("unknown",),
    "rejected": ("unknown",),
    "expired": ("unknown",),
    # 'unknown' is the recovery state: any status may follow once evidence returns.
    "unknown": ("pending", "open", "partially_filled", "filled", "cancelled", "rejected", "expired"),
}

ORDER_TERMINAL_STATES: tuple[str, ...] = ("filled", "cancelled", "rejected", "expired")

# Monotonic progression rank for out-of-order tolerance. Terminal states share
# the top rank; 'unknown' ranks lowest so recovery evidence always applies.
_ORDER_RANK: dict[str, int] = {
    "unknown": 0,
    "pending": 1,
    "open": 2,
    "partially_filled": 3,
    "filled": 4,
    "cancelled": 4,
    "rejected": 4,
    "expired": 4,
}

# ── Position lifecycle (PositionStatus in packages/shared/derivatives.ts) ────

POSITION_LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "absent": ("opening", "open", "unknown"),
    "opening": ("open", "closed", "unknown"),
    "open": ("increasing", "reducing", "closing", "liquidating", "settlement_pending",
             "reconciliation_required", "source_stale", "unknown"),
    "increasing": ("open", "reducing", "closing", "liquidating", "reconciliation_required",
                   "source_stale", "unknown"),
    "reducing": ("open", "closing", "closed", "liquidating", "reconciliation_required",
                 "source_stale", "unknown"),
    "closing": ("closed", "reconciliation_required", "unknown"),
    "closed": ("unknown",),
    "liquidating": ("liquidated", "auto_deleveraged", "reconciliation_required", "unknown"),
    "liquidated": ("unknown",),
    "auto_deleveraged": ("open", "closed", "unknown"),
    "settlement_pending": ("settled", "reconciliation_required", "unknown"),
    "settled": ("unknown",),
    "reconciliation_required": ("open", "closed", "liquidated", "settled", "source_stale", "unknown"),
    "source_stale": ("open", "closed", "reconciliation_required", "unknown"),
    "unknown": ("absent", "opening", "open", "increasing", "reducing", "closing", "closed",
                "liquidating", "liquidated", "auto_deleveraged", "settlement_pending", "settled",
                "reconciliation_required", "source_stale"),
}

POSITION_TERMINAL_STATES: tuple[str, ...] = ("closed", "liquidated", "settled")

_POSITION_RANK: dict[str, int] = {
    "unknown": 0,
    "absent": 1,
    "opening": 2,
    "open": 3,
    "increasing": 3,
    "reducing": 3,
    "auto_deleveraged": 3,
    "source_stale": 3,
    "reconciliation_required": 3,
    "closing": 4,
    "liquidating": 4,
    "settlement_pending": 4,
    "closed": 5,
    "liquidated": 5,
    "settled": 5,
}


@dataclass
class TransitionResult:
    applied: bool
    new_status: str
    reason: str


class _BaseStateMachine:
    LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {}
    TERMINAL_STATES: tuple[str, ...] = ()
    _RANK: dict[str, int] = {}

    @classmethod
    def is_legal(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.LEGAL_TRANSITIONS.get(from_status, ())

    @classmethod
    def apply(
        cls,
        current_status: str,
        incoming_status: str,
        observed_at: str = "",
        venue_sequence: Optional[int] = None,
    ) -> TransitionResult:
        if current_status not in cls.LEGAL_TRANSITIONS:
            return TransitionResult(False, current_status, f"unknown_current_status:{current_status}")
        if incoming_status not in cls.LEGAL_TRANSITIONS:
            return TransitionResult(False, current_status, f"unknown_incoming_status:{incoming_status}")
        if incoming_status == current_status:
            # Re-observation of the same state is duplicate evidence.
            if current_status in cls.LEGAL_TRANSITIONS.get(current_status, ()):
                return TransitionResult(True, incoming_status, "reapplied_same_status")
            return TransitionResult(False, current_status, "duplicate_evidence")
        # Out-of-order tolerance: a lower-rank status after a higher-rank one
        # is stale venue evidence — attach, never regress.
        if cls._RANK.get(incoming_status, 0) < cls._RANK.get(current_status, 0):
            return TransitionResult(False, current_status, "stale_out_of_order")
        if not cls.is_legal(current_status, incoming_status):
            return TransitionResult(False, current_status, "illegal_transition")
        return TransitionResult(True, incoming_status, "applied")


class OrderStateMachine(_BaseStateMachine):
    LEGAL_TRANSITIONS = ORDER_LEGAL_TRANSITIONS
    TERMINAL_STATES = ORDER_TERMINAL_STATES
    _RANK = _ORDER_RANK


class PositionStateMachine(_BaseStateMachine):
    LEGAL_TRANSITIONS = POSITION_LEGAL_TRANSITIONS
    TERMINAL_STATES = POSITION_TERMINAL_STATES
    _RANK = _POSITION_RANK
