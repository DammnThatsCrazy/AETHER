"""Canonical interoperability message lifecycle.

LEGAL_TRANSITIONS mirrors INTEROP_LEGAL_TRANSITIONS in
packages/shared/interoperability.ts EXACTLY — the TypeScript const is the
single source of truth and tests/unit/interop/test_lifecycle_parity.py
regex-parses it to assert equality. Change the TS map first, then this one.

Observation semantics: out-of-order provider evidence is normal. Applying a
lower-rank status over a higher-rank one attaches evidence without
regressing; illegal transitions are recorded anomalies, never exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from services.interop.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    utc_now_iso,
)

LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "discovered": ("source_pending", "source_confirmed", "failed", "unknown"),
    "source_pending": ("source_confirmed", "reorged", "failed", "expired", "unknown"),
    "source_confirmed": ("verification_in_progress", "partially_verified", "verified", "delivered", "reorged", "timed_out", "failed", "unknown"),
    "verification_in_progress": ("partially_verified", "verified", "verification_failed", "timed_out", "reorged", "unknown"),
    "partially_verified": ("verified", "verification_failed", "timed_out", "reorged", "unknown"),
    "verified": ("delivery_pending", "delivery_attempted", "delivered", "delivery_failed", "timed_out", "reorged", "unknown"),
    "delivery_pending": ("delivery_attempted", "delivered", "delivery_failed", "timed_out", "cancelled", "unknown"),
    "delivery_attempted": ("delivered", "delivery_failed", "timed_out", "unknown"),
    "delivered": ("executed", "application_failed", "settled", "unknown"),
    "executed": ("settled", "unknown"),
    "settled": (),
    "failed": ("recovered", "refunded"),
    "verification_failed": ("verification_in_progress", "failed", "recovered", "refunded"),
    "delivery_failed": ("delivery_pending", "delivery_attempted", "failed", "recovered", "refunded"),
    "application_failed": ("recovered", "refunded", "failed"),
    "timed_out": ("recovered", "refunded", "failed", "delivered"),
    "expired": ("refunded",),
    "cancelled": (),
    "refunded": (),
    "reorged": ("discovered", "source_pending", "source_confirmed", "failed"),
    "recovered": ("delivered", "executed", "settled"),
    "unknown": ("discovered", "source_pending", "source_confirmed", "verification_in_progress", "verified", "delivered", "executed", "settled", "failed", "timed_out"),
}

TERMINAL_STATES: tuple[str, ...] = ("settled", "cancelled", "refunded")

# Progression rank for out-of-order tolerance. Failure/recovery states rank
# alongside the phase that produces them so legal failure transitions always
# apply; terminal states rank highest.
STATE_RANK: dict[str, int] = {
    "unknown": 0,
    "discovered": 1,
    "source_pending": 2,
    "reorged": 2,
    "source_confirmed": 3,
    "verification_in_progress": 4,
    "partially_verified": 5,
    "verification_failed": 5,
    "verified": 6,
    "delivery_pending": 7,
    "delivery_attempted": 8,
    "delivery_failed": 8,
    "timed_out": 8,
    "expired": 8,
    "failed": 8,
    "recovered": 8,
    "delivered": 9,
    "application_failed": 9,
    "executed": 10,
    "settled": 11,
    "cancelled": 11,
    "refunded": 11,
}


@dataclass
class LifecycleResult:
    applied: bool
    new_status: str
    reason: str
    transition_record: Optional[dict] = None


class LifecycleEngine:
    @staticmethod
    def is_legal(from_status: str, to_status: str) -> bool:
        return to_status in LEGAL_TRANSITIONS.get(from_status, ())

    @staticmethod
    def apply(
        tenant_id: str,
        interop_message_id: str,
        current_status: str,
        incoming_status: str,
        observed_at: str = "",
        provider_native_stage: Optional[str] = None,
        evidence_ref: Optional[str] = None,
    ) -> LifecycleResult:
        observed_at = observed_at or utc_now_iso()
        if current_status not in LEGAL_TRANSITIONS:
            return LifecycleResult(False, current_status, f"unknown_current_status:{current_status}")
        if incoming_status not in LEGAL_TRANSITIONS:
            return LifecycleResult(False, current_status, f"unknown_incoming_status:{incoming_status}")
        if incoming_status == current_status:
            return LifecycleResult(False, current_status, "duplicate_evidence")
        if current_status in TERMINAL_STATES:
            return LifecycleResult(False, current_status, "terminal_state")

        # Legal transitions always apply — the map itself encodes the allowed
        # regressions (retry cycles, recovery, reorg). Rank only classifies
        # ILLEGAL arrivals: lower-rank evidence is a late duplicate leg
        # (attach, don't alarm); same-or-higher-rank is a genuine anomaly.
        if not LifecycleEngine.is_legal(current_status, incoming_status):
            if STATE_RANK.get(incoming_status, 0) < STATE_RANK.get(current_status, 0):
                return LifecycleResult(False, current_status, "late_evidence_attached")
            return LifecycleResult(False, current_status, "illegal_transition")

        basis = f"{interop_message_id}|{current_status}|{incoming_status}|{observed_at}"
        record = {
            "tenant_id": tenant_id,
            "transition_id": deterministic_id("iotr_", basis),
            "interop_message_id": interop_message_id,
            "from_status": current_status,
            "to_status": incoming_status,
            "provider_native_stage": provider_native_stage,
            "observed_at": observed_at,
            "evidence_ref": evidence_ref,
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": None,
            "execution_by_aether": False,
        }
        return LifecycleResult(True, incoming_status, "applied", record)


def build_interop_scan_coro(*args, **kwargs):
    """Durable interop scan-loop coroutine (runtime worker registry entry).

    Consumed by ``services/runtime/specs.py`` under the ``interop_scan`` spec,
    gated on ``settings.interop.adapters_enabled``. Defined in
    :mod:`services.interop.scan_worker`; re-exported here (lazily) so the
    runtime spec's import path stays stable without a module-level import cycle
    (scan_worker -> correlation -> lifecycle).
    """
    from services.interop.scan_worker import build_interop_scan_coro as _builder
    return _builder(*args, **kwargs)
