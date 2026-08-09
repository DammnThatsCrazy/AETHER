"""Kyber operator surfaces for Interoperability Intelligence —
/v1/admin/kyber/interop. Operator-gated, audited, observation-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from config.settings import settings
from repositories.interop_repos import (
    InteropMessageRepo,
    InteropProviderCheckpointRepo,
    SecurityPolicySnapshotRepo,
)
from shared.auth.auth import Permissions
from shared.common.common import ForbiddenError
from services.interop.correlation import CorrelationEngine
from services.interop.foundation import require_flag
from services.interop.providers import INTEROP_PROVIDERS, get_provider

admin_router = APIRouter(prefix="/v1/admin/kyber/interop", tags=["kyber-interop"])


from services.security.request_context import is_kyber_operator as _is_kyber_operator


def _gate(request: Request) -> None:
    require_flag(settings.interop.kyber_enabled, "Kyber Interop Ops")
    tenant = request.state.tenant
    # Canonical fail-closed operator check (replaces the never-set
    # is_platform_admin flag): only kyber:operator grant or the operator
    # tenant-id allowlist passes; Aether tenants (incl. Role.ADMIN) are denied.
    if not _is_kyber_operator(tenant):
        raise ForbiddenError("Kyber operator access required; Aether tenants may not access Kyber")
    tenant.require_permission(Permissions.INTEROP_OPERATOR)


@admin_router.get("/providers/health")
async def providers_health(request: Request):
    """Adapter descriptors + checkpoint lag per provider."""
    _gate(request)
    checkpoints = await InteropProviderCheckpointRepo().find_many(limit=500)
    by_provider: dict[str, list[dict]] = {}
    for checkpoint in checkpoints:
        by_provider.setdefault(checkpoint["provider_id"], []).append(checkpoint)
    return {
        "items": [
            {
                **adapter.descriptor(),
                "checkpoints": by_provider.get(adapter.provider_id, []),
            }
            for adapter in INTEROP_PROVIDERS.values()
        ],
        "count": len(INTEROP_PROVIDERS),
    }


@admin_router.get("/providers/{provider_id}/operational")
async def provider_operational(provider_id: str, request: Request):
    """One adapter's canonical operational fields: configured, credential_status,
    reachable, latest_cursor, latest_observation_at, lag, decode_failures,
    reorg_count, reconciliation_conflicts, dead_letter_count, last_success,
    last_failure. Read from the persisted checkpoint (runtime telemetry survives
    worker restarts); never a live network call."""
    _gate(request)
    if provider_id == "layerzero_v2":
        require_flag(settings.interop.layerzero_enabled, "LayerZero adapter")
    adapter = get_provider(provider_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider_id}")

    tenant = request.state.tenant
    stored = await InteropProviderCheckpointRepo().find_one({
        "tenant_id": tenant.tenant_id, "provider_id": provider_id, "network_id": "*",
    })
    evidence = (stored or {}).get("evidence") or None
    operational = adapter.operational_state(evidence)
    operational["last_scan_advanced_at"] = (stored or {}).get("advanced_at")
    return {
        "provider_id": provider_id,
        "descriptor": adapter.descriptor(),
        "operational": operational,
        "checkpoint_present": stored is not None,
    }


@admin_router.get("/checkpoints")
async def list_checkpoints(request: Request, limit: int = Query(default=100, ge=1, le=500)):
    _gate(request)
    rows = await InteropProviderCheckpointRepo().find_many(limit=limit)
    return {"items": rows, "count": len(rows)}


@admin_router.get("/policy-drift")
async def policy_drift(request: Request, limit: int = Query(default=500, ge=1, le=2000)):
    """Paths whose security policy hash has changed across snapshots."""
    _gate(request)
    rows = await SecurityPolicySnapshotRepo().find_many(limit=limit)
    by_path: dict[str, set[str]] = {}
    latest: dict[str, str] = {}
    for row in sorted(rows, key=lambda r: r.get("captured_at") or ""):
        by_path.setdefault(row["path_id"], set()).add(row["content_hash"])
        latest[row["path_id"]] = row["content_hash"]
    drifted = [
        {
            "path_id": path_id,
            "distinct_policies": len(hashes),
            "latest_hash": latest[path_id],
        }
        for path_id, hashes in by_path.items() if len(hashes) > 1
    ]
    return {"items": drifted, "count": len(drifted)}


@admin_router.get("/correlation/health")
async def correlation_health(request: Request, limit: int = Query(default=2000, ge=1, le=10000)):
    """Out-of-order discoveries and uncorrelated (missing-leg) messages."""
    _gate(request)
    rows = await InteropMessageRepo().find_many(limit=limit)
    out_of_order = 0
    uncorrelated = 0
    by_status: dict[str, int] = {}
    for message in rows:
        extension = message.get("provider_extension") or {}
        if extension.get("discovered_out_of_order"):
            out_of_order += 1
        if not message.get("source") or not message.get("destination"):
            uncorrelated += 1
        by_status[message["status"]] = by_status.get(message["status"], 0) + 1
    return {
        "message_count": len(rows),
        "out_of_order_discoveries": out_of_order,
        "uncorrelated_messages": uncorrelated,
        "by_status": by_status,
    }


@admin_router.post("/scan/{provider_id}", status_code=201)
async def run_scan(provider_id: str, request: Request):
    """Run one governed scan cycle for a provider adapter (audited).
    LayerZero requires its dedicated flag; scaffolds honestly refuse."""
    _gate(request)
    if provider_id == "layerzero_v2":
        require_flag(settings.interop.layerzero_enabled, "LayerZero adapter")
    adapter = get_provider(provider_id)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"unknown provider: {provider_id}")

    checkpoint_repo = InteropProviderCheckpointRepo()
    tenant = request.state.tenant
    stored = await checkpoint_repo.find_one({
        "tenant_id": tenant.tenant_id, "provider_id": provider_id, "network_id": "*",
    })
    try:
        observations, new_checkpoint = await adapter.scan(
            (stored or {}).get("evidence") or None,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    engine = CorrelationEngine()
    results = []
    for observation in observations:
        results.append(await engine.ingest_observation(tenant.tenant_id, observation))

    from services.interop.foundation import (
        deterministic_id,
        deterministic_idempotency_key,
        utc_now_iso,
    )

    basis = f"{tenant.tenant_id}|{provider_id}|*"
    if stored is None:
        await checkpoint_repo.insert({
            "tenant_id": tenant.tenant_id,
            "checkpoint_id": deterministic_id("iocp_", basis),
            "provider_id": provider_id,
            "network_id": "*",
            "last_scanned_block": 0,
            "confirmed_block": 0,
            "advanced_at": utc_now_iso(),
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": new_checkpoint,
            "execution_by_aether": False,
        })
    else:
        await checkpoint_repo.update_by_key(
            {"tenant_id": tenant.tenant_id, "provider_id": provider_id, "network_id": "*"},
            {"evidence": new_checkpoint, "advanced_at": utc_now_iso()},
        )
    try:
        from shared.logger.logger import metrics
        metrics.increment("interop_reconciliation_run")
    except Exception:
        pass
    return {
        "observations": len(observations),
        "ingested": sum(1 for r in results if r.get("accepted")),
        "checkpoint_advanced": True,
    }
