"""Communications usage metering (§20).

Emits billable ``metering_evidence`` records for the commercial dimensions the
comms product exposes. Metering is fail-closed on duplicates (the metering
service marks a repeated ``dedupe_key`` non-billable), so replays and retries
never double-bill. This is the "usage can be measured" half of commercial
readiness; pricing is deliberately NOT invented here — dimensions are measured,
plans decide what they cost.

Dedupe keys are dimension-scoped (``comms:<dimension>:<unit>``) so the same
underlying event can be metered under more than one dimension without one
shadowing the other.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.comms.metering")

# Canonical comms usage dimensions (metering_evidence.usage_dimension values).
COMMS_USAGE_DIMENSIONS: frozenset[str] = frozenset({
    "comms_events",
    "comms_reply_events",
    "comms_backfill_records",
    "comms_synced_profiles",
    "comms_synced_campaigns",
    "comms_reconciliation_runs",
    "comms_active_connections",
    "comms_provider_accounts",
})


async def record_comms_usage(
    tenant_id: str,
    *,
    dimension: str,
    unit_key: str,
    quantity: float = 1,
    provider: str = "",
    source_path: str = "/v1/comms",
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Record one billable comms usage unit (best-effort; never breaks flow)."""
    if dimension not in COMMS_USAGE_DIMENSIONS:
        logger.warning("comms_metering_unknown_dimension: %s", dimension)
        return
    dedupe_key = f"comms:{dimension}:{unit_key}"
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
        logger.warning("comms_metering_failed dim=%s: %s", dimension, exc)


async def record_event_usage(
    tenant_id: str, *, event_type: str, event_id: str, provider: str = "",
) -> None:
    """Meter a single canonical communication event (+ replies separately)."""
    await record_comms_usage(
        tenant_id, dimension="comms_events", unit_key=event_id, provider=provider,
    )
    if event_type == "email_replied":
        await record_comms_usage(
            tenant_id, dimension="comms_reply_events", unit_key=event_id,
            provider=provider,
        )


async def record_sync_usage(tenant_id: str, run: dict[str, Any]) -> None:
    """Meter sync-run-level dimensions from a completed sync run (§12.4 counts)."""
    run_id = run.get("sync_run_id") or ""
    provider = run.get("provider") or ""
    campaigns = int(run.get("campaigns_created") or 0)
    profiles = int(run.get("profiles_resolved") or 0) + int(run.get("profiles_unresolved") or 0)
    if campaigns:
        await record_comms_usage(
            tenant_id, dimension="comms_synced_campaigns", unit_key=f"{run_id}:campaigns",
            quantity=campaigns, provider=provider,
        )
    if profiles:
        await record_comms_usage(
            tenant_id, dimension="comms_synced_profiles", unit_key=f"{run_id}:profiles",
            quantity=profiles, provider=provider,
        )
    if run.get("mode") == "backfill":
        received = int(run.get("records_received") or 0)
        if received:
            await record_comms_usage(
                tenant_id, dimension="comms_backfill_records",
                unit_key=f"{run_id}:backfill", quantity=received, provider=provider,
            )


__all__ = [
    "COMMS_USAGE_DIMENSIONS",
    "record_comms_usage",
    "record_event_usage",
    "record_sync_usage",
]
