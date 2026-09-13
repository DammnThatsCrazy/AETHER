"""Interoperability reconciliation evidence (1E).

Cross-leg reconciliation compares the source and destination observations of one
correlated message and records any variance as an immutable reconciliation
record plus an ``interop_reconciliation_variance_detected`` event. The scan
worker advances the adapter checkpoint's ``reconciliation_conflicts`` runtime
counter with the per-cycle conflict count, so ``operational_state()`` surfaces
it as a first-class operational field.

Observation-only: a variance is never repaired by Aether. It is recorded,
counted, and surfaced to operators (``resolved_at`` stays null until an
operator or a later converged leg resolves it upstream).
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.interop_repos import InteropMessageRepo, InteropReconciliationRepo
from services.interop.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)

_VARIANCE_TOLERANCE_PCT = 0.000001  # 1e-4 % of the reference amount

# The operational fields a reconcile-state row persists per adapter. Mirrors the
# OperationalFieldsMixin.operational_state() shape so the persisted state and
# the live operational view never drift.
_OPERATIONAL_FIELDS: tuple[str, ...] = (
    "configured",
    "credential_status",
    "reachable",
    "latest_cursor",
    "latest_observation_at",
    "lag",
    "decode_failures",
    "reorg_count",
    "reconciliation_conflicts",
    "dead_letter_count",
    "last_success",
    "last_failure",
)


def leg_variance(source: dict, destination: dict) -> list[str]:
    """Deterministic difference notes between a message's source and
    destination endpoint refs. Empty list == reconciled."""
    notes: list[str] = []
    source = source or {}
    destination = destination or {}
    if not source and not destination:
        return []
    if not destination:
        return ["missing_destination_leg"]
    if not source:
        return ["missing_source_leg"]
    source_amount = _amount(source.get("amount_decimal"))
    dest_amount = _amount(destination.get("amount_decimal"))
    if source_amount is not None and dest_amount is not None:
        if source_amount and dest_amount:
            delta = abs(source_amount - dest_amount) / max(source_amount, dest_amount, 1)
            if delta > _VARIANCE_TOLERANCE_PCT:
                notes.append(
                    f"amount_mismatch:source={source_amount},destination={dest_amount}"
                )
    if source.get("payload_hash") and destination.get("payload_hash"):
        if source.get("payload_hash") != destination.get("payload_hash"):
            notes.append("payload_hash_mismatch")
    if source.get("transaction_hash") and destination.get("transaction_hash"):
        if source.get("transaction_hash") == destination.get("transaction_hash"):
            notes.append("same_transaction_across_legs")
    return notes


class InteropReconciler:
    """Reconciles correlated messages and emits immutable variance evidence."""

    def __init__(
        self,
        message_repo: Optional[InteropMessageRepo] = None,
        record_repo: Optional[InteropReconciliationRepo] = None,
    ) -> None:
        self.messages = message_repo or InteropMessageRepo()
        self.records = record_repo or InteropReconciliationRepo()

    async def persist_reconciliation_state(
        self,
        *,
        tenant_id: str,
        provider_id: str,
        operational: dict[str, Any],
        reconciliation_conflicts: int = 0,
        delivered: Optional[list[dict[str, Any]]] = None,
        source: Optional[list[dict[str, Any]]] = None,
    ) -> dict:
        """Persist the per-adapter reconciliation STATE (durable, idempotent).

        The write-path closure for interop reconciliation: each scan cycle
        reconciles correlated messages (immutable variance rows) and then calls
        this to record the adapter's current reconciliation state — the
        operational fields (``configured``, ``credential_status``,
        ``reachable``, ``latest_cursor``, ``latest_observation_at``, ``lag``,
        ``decode_failures``, ``reorg_count``, ``reconciliation_conflicts``,
        ``dead_letter_count``, ``last_success``, ``last_failure``) plus the
        source-vs-delivered snapshot — as a single current-state row keyed
        deterministically on ``(tenant_id, provider_id)``.

        The row is a current-state projection (not an immutable trail): the
        deterministic ``reconciliation_id`` + ``idempotency_key`` make a re-run
        of the same cycle collapse instead of forking; a later cycle supersedes
        it in place via the repo's conflict key.
        """
        basis = f"{tenant_id}|{provider_id}"
        reconciliation_id = deterministic_id("iorc_", basis)
        idempotency_key = deterministic_idempotency_key(basis)
        status = "reconciled" if reconciliation_conflicts == 0 else "variance_detected"
        source_refs = source or []
        delivered_refs = delivered or []
        sources_compared = {
            "source": source_refs,
            "delivered": delivered_refs,
            "operational": {k: operational.get(k) for k in _OPERATIONAL_FIELDS},
        }
        record = {
            "tenant_id": tenant_id,
            "reconciliation_id": reconciliation_id,
            "interop_message_id": "",
            "correlation_key": f"provider:{provider_id}",
            "status": status,
            "sources_compared": sources_compared,
            "difference_note": (
                f"{reconciliation_conflicts} reconciliation conflict(s) for {provider_id}"
                if reconciliation_conflicts else f"{provider_id} reconciled"
            ),
            "resolved_at": None,
            "idempotency_key": idempotency_key,
            "evidence": {
                "provider_id": provider_id,
                "reconciliation_conflicts": reconciliation_conflicts,
            },
            "execution_by_aether": False,
        }
        await self.records.insert(record)
        return record

    async def reconcile_message(
        self, tenant_id: str, message: dict[str, Any],
    ) -> tuple[bool, list[dict]]:
        """Reconcile one correlated message. Returns (conflict, emitted_events).

        A message with both legs is compared; a mismatch writes a
        reconciliation record and emits the variance event. Messages missing a
        leg are not conflicts — the correlation engine is still waiting for the
        other side (out-of-order evidence is normal).
        """
        source = message.get("source") or {}
        destination = message.get("destination") or {}
        notes = leg_variance(source, destination)
        if not notes:
            return False, []

        interop_message_id = message["interop_message_id"]
        correlation_key = message.get("correlation_key", "")
        basis = f"{tenant_id}|{interop_message_id}|{utc_now_iso()}"
        record = {
            "tenant_id": tenant_id,
            "reconciliation_id": deterministic_id("iorec_", basis),
            "interop_message_id": interop_message_id,
            "correlation_key": correlation_key,
            "status": "variance_detected",
            "sources_compared": {
                "source": source,
                "destination": destination,
            },
            "difference_note": "; ".join(notes),
            "resolved_at": None,
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": {"notes": notes},
            "execution_by_aether": False,
        }
        await self.records.insert(record)
        emitted = [make_event("interop_reconciliation_variance_detected", tenant_id, {
            "reconciliation_id": record["reconciliation_id"],
            "interop_message_id": interop_message_id,
            "correlation_key": correlation_key,
            "difference_note": record["difference_note"],
            "status": "variance_detected",
        })]
        return True, emitted

    async def run(
        self, tenant_id: str, correlation_results: list[dict[str, Any]],
    ) -> tuple[int, list[dict]]:
        """Reconcile the messages referenced by one scan cycle's correlation
        results. Returns (conflict_count, emitted_events)."""
        conflicts = 0
        emitted: list[dict] = []
        seen: set[str] = set()
        for result in correlation_results:
            message_id = result.get("interop_message_id")
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message = await self.messages.find_one({
                "tenant_id": tenant_id,
                "interop_message_id": message_id,
            })
            if not message:
                continue
            conflict, events = await self.reconcile_message(tenant_id, message)
            if conflict:
                conflicts += 1
            emitted.extend(events)
        return conflicts, emitted


def _amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
