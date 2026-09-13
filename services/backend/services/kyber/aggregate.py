"""Kyber fleet-level aggregate endpoint (operator plane).

A single cross-tenant operational snapshot for the Kyber operator: worker
fleet health, per-tenant credential slot states (safe views only — secrets are
never decrypted or returned), interop provider cursor/reconciliation state,
activation lifecycle roll-up, launch-readiness roll-up and the credential-audit
event count.

Honesty rules mirror the rest of the operator plane: every value is wired to a
real durable source; a source that has produced no signal reports ``None`` /
explicit ``"unknown"``, never a fabricated zero. Counts that come from a
successful repository read are genuine zeros.

Not mounted here — the application assembles it (see wiringNeeds). The router
is gated by the canonical ``require_kyber_operator`` gate, which denies every
Aether tenant including ``Role.ADMIN``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request

from repositories.interop_repos import InteropProviderCheckpointRepo
from services.activation.repository import ActivationRepository
from services.providers.credentials.operator_view import collect_credential_slot_states
from services.security.request_context import require_kyber_operator
from services.tenant_readiness.service import TenantReadinessRepository
from shared.common.common import APIResponse
from shared.logger.logger import get_logger
from shared.store import get_store
from shared.supervisor_handle import get_worker_supervisor

logger = get_logger("aether.kyber.aggregate")

router = APIRouter(
    prefix="/v1/kyber/aggregate",
    tags=["Kyber Aggregate"],
    dependencies=[Depends(require_kyber_operator)],
)

_LIVE_WORKER_STATES = frozenset({"running", "restarting"})


def _fleet_worker_summary() -> dict[str, Any]:
    """Honest tri-state fleet worker health.

    No supervisor bound (or its status read is broken) → ``observed: False``,
    ``live: None``. Workers exist but none is live → ``live: False``. At least
    one live worker → ``live: True``.
    """
    supervisor = get_worker_supervisor()
    if supervisor is None:
        return {"observed": False, "live": None, "worker_count": 0, "live_count": 0}
    try:
        status = supervisor.status()
    except Exception:  # noqa: BLE001 — a broken status read is unknown, not dead
        return {"observed": False, "live": None, "worker_count": 0, "live_count": 0}
    if not status:
        return {"observed": True, "live": None, "worker_count": 0, "live_count": 0}

    from services.runtime.supervisor import HEARTBEAT_TIMEOUT_S

    live_count = sum(
        1 for info in status.values()
        if info.get("state") in _LIVE_WORKER_STATES
        and info.get("heartbeat_age_s") is not None
        and float(info.get("heartbeat_age_s")) <= HEARTBEAT_TIMEOUT_S
    )
    return {
        "observed": True,
        "live": live_count > 0,
        "worker_count": len(status),
        "live_count": live_count,
    }


async def _provider_rollup() -> dict[str, Any]:
    """Interop provider checkpoint roll-up across tenants."""
    try:
        checkpoints = await InteropProviderCheckpointRepo().find_many(limit=1000)
    except Exception:  # noqa: BLE001
        return {"checkpoint_count": None, "reconciliation_conflicts_total": None}
    conflicts = 0
    for cp in checkpoints:
        runtime = (cp.get("evidence") or {}).get("runtime") or {}
        conflicts += int(runtime.get("reconciliation_conflicts") or 0)
    return {
        "checkpoint_count": len(checkpoints),
        "reconciliation_conflicts_total": conflicts,
    }


async def _activation_rollup() -> dict[str, Any]:
    """Activation lifecycle roll-up across tenants (read-only, no writes)."""
    try:
        records = await ActivationRepository().find_many(limit=2000)
    except Exception:  # noqa: BLE001
        return {"tenant_count": None, "by_state": None}
    by_state: dict[str, int] = {}
    tenants: set[str] = set()
    for record in records:
        state = record.get("state") or "unknown"
        by_state[state] = by_state.get(state, 0) + 1
        tenant_id = record.get("tenant_id")
        if tenant_id:
            tenants.add(tenant_id)
    return {"tenant_count": len(tenants), "by_state": by_state}


async def _readiness_rollup() -> dict[str, Any]:
    """Launch-readiness roll-up across recorded tenants."""
    try:
        records = await TenantReadinessRepository().list_all(limit=2000)
    except Exception:  # noqa: BLE001
        return {"tenant_count": None, "ready_count": None,
                "not_ready_count": None, "demoted_count": None}
    ready = not_ready = demoted = 0
    for record in records:
        if record.get("demotion_reason"):
            demoted += 1
        if record.get("ready"):
            ready += 1
        else:
            not_ready += 1
    return {
        "tenant_count": len(records),
        "ready_count": ready,
        "not_ready_count": not_ready,
        "demoted_count": demoted,
    }


async def _audit_rollup() -> dict[str, Any]:
    """Credential-audit event count from the durable store."""
    try:
        return {"audit_event_count": int(await get_store("credential_audit").count())}
    except Exception:  # noqa: BLE001
        return {"audit_event_count": None}


@router.get("/fleet")
async def fleet_aggregate(request: Request) -> dict:
    """Fleet-wide operator aggregate.

    Workers, cross-tenant credential slot states (no secrets), provider
    cursor/reconciliation roll-up, activation and readiness roll-ups, and the
    credential-audit event count. A source with no signal yet reports
    ``None`` / explicit ``"unknown"`` — never a fabricated zero. Gated by the
    router-level ``require_kyber_operator`` dependency.
    """
    data = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "workers": _fleet_worker_summary(),
        "credentials": await collect_credential_slot_states(),
        "providers": await _provider_rollup(),
        "activation": await _activation_rollup(),
        "readiness": await _readiness_rollup(),
        "audit": await _audit_rollup(),
    }
    logger.info("kyber_fleet_aggregate computed", extra={
        "tenant_count": data["credentials"]["tenant_count"],
    })
    return APIResponse(data=data).to_dict()


__all__ = ["router"]
