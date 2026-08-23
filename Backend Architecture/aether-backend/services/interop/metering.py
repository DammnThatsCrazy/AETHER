"""Interoperability Intelligence usage metering hook.

Records billable ``metering_evidence`` records for the commercial dimensions the
interop intelligence plane exposes: observations ingested, messages correlated,
reconciliation runs, security-policy snapshots, and provider scan cycles.
Follows the comms metering pattern (``services/comms/metering.py``): dimensions
are measured here, pricing is deliberately NOT invented — plans decide what
dimensions cost.

Fail-closed on duplicates: a restart replay of the same checkpoint cycle
reproduces the same ``dedupe_key``, which the metering service records but marks
non-billable with ``excluded_reason="duplicate"`` — so checkpoint re-runs and
retries can never double-bill. Metering is best-effort: a metering failure is
logged and never breaks the scan flow.

Dedupe keys are dimension-scoped (``interop:<dimension>:<unit_key>``) so one
cycle can be metered under more than one dimension without one shadowing the
other.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.interop.metering")

# Canonical interop usage dimensions (metering_evidence.usage_dimension values).
INTEROP_USAGE_DIMENSIONS: frozenset[str] = frozenset({
    "interop_observations_ingested",
    "interop_messages_correlated",
    "interop_reconciliation_runs",
    "interop_security_policy_snapshots",
    "interop_provider_cycles",
})


def checkpoint_unit_key(provider_id: str, checkpoint: Optional[dict[str, Any]]) -> str:
    """Deterministic per-cycle anchor for dedupe: provider + highest cursor.

    Replaying the same persisted checkpoint reproduces the same anchor, so the
    metering service marks the re-run non-billable (fail-closed double-billing
    protection). A later cycle that advances a cursor produces a fresh anchor
    and a fresh billable record.
    """
    cursors = [
        int(state.get("last_scanned_block") or state.get("last_scanned_height") or 0)
        for state in ((checkpoint or {}).get("networks") or {}).values()
        if isinstance(state, dict)
    ]
    return f"{provider_id}:{max(cursors) if cursors else 0}"


async def record_interop_usage(
    tenant_id: str,
    *,
    dimension: str,
    unit_key: str,
    quantity: float = 1,
    provider: str = "",
    source_path: str = "/v1/interoperability",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Record one billable interop usage unit (best-effort; never breaks flow)."""
    if dimension not in INTEROP_USAGE_DIMENSIONS:
        logger.warning("interop_metering_unknown_dimension: %s", dimension)
        return
    dedupe_key = f"interop:{dimension}:{unit_key}"
    try:
        from services.metering_evidence.service import MeteringEvidenceService

        await MeteringEvidenceService().record(
            tenant_id=tenant_id,
            source_path=source_path,
            event_id=dedupe_key,
            dedupe_key=dedupe_key,
            source_provider=provider,
            usage_dimension=dimension,
            quantity=quantity,
            metadata=metadata or {},
        )
    except Exception as exc:  # pragma: no cover - metering must never break flow
        logger.warning("interop_metering_failed dim=%s: %s", dimension, exc)


async def record_cycle_usage(
    tenant_id: str,
    provider_id: str,
    *,
    checkpoint: Optional[dict[str, Any]],
    observations: int = 0,
    correlated: int = 0,
    reconciliation_runs: int = 1,
    security_snapshots: int = 0,
) -> None:
    """Meter one governed scan cycle across the canonical dimensions.

    Called at the end of a successful :meth:`ScanWorker.run_cycle`. All writes
    are best-effort and dimension-scoped-dedupe, so a checkpoint restart replay
    can never double-bill.
    """
    unit_key = checkpoint_unit_key(provider_id, checkpoint)
    if observations:
        await record_interop_usage(
            tenant_id, dimension="interop_observations_ingested",
            unit_key=unit_key, quantity=observations, provider=provider_id,
        )
    if correlated:
        await record_interop_usage(
            tenant_id, dimension="interop_messages_correlated",
            unit_key=unit_key, quantity=correlated, provider=provider_id,
        )
    if reconciliation_runs:
        await record_interop_usage(
            tenant_id, dimension="interop_reconciliation_runs",
            unit_key=unit_key, quantity=reconciliation_runs, provider=provider_id,
        )
    if security_snapshots:
        await record_interop_usage(
            tenant_id, dimension="interop_security_policy_snapshots",
            unit_key=unit_key, quantity=security_snapshots, provider=provider_id,
        )
    await record_interop_usage(
        tenant_id, dimension="interop_provider_cycles",
        unit_key=unit_key, quantity=1, provider=provider_id,
    )


__all__ = [
    "INTEROP_USAGE_DIMENSIONS",
    "checkpoint_unit_key",
    "record_interop_usage",
    "record_cycle_usage",
]
