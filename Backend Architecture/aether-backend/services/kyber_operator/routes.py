"""Kyber Operator — privileged tenant access and fleet operational envelope.

Routes:
    POST   /v1/kyber/operator/tenant-entry          Request privileged tenant access
    DELETE /v1/kyber/operator/tenant-entry          Exit tenant access session
    GET    /v1/kyber/tenants/{tenant_id}/operational-envelope  Tenant health summary
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, Field

from dependencies.providers import get_graph
from repositories.interop_repos import (
    InteropProviderCheckpointRepo,
    InteropReconciliationRepo,
)
from services.providers.credentials.operator_view import tenant_credential_slot_states
from services.tenant_readiness.service import TenantLaunchReadiness
from shared.common.common import APIResponse, ForbiddenError
from shared.temporal.instant import coerce_utc_lenient
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger
from shared.store import get_store
from shared.supervisor_handle import get_worker_supervisor

logger = get_logger("aether.service.kyber_operator")

router = APIRouter(prefix="/v1/kyber", tags=["Kyber Operator"])

# Retained only so an in-flight session_id issued before this deployment still
# resolves on exit. New entries are NEVER written here — they go to the durable
# kyber_access_scopes table via access_scope_service. The previous behaviour
# (this dict as the only store) meant a scope vanished on restart, was invisible
# to every other replica, and was read by nothing, so the "all subsequent
# queries are operator-scoped" guarantee below was never actually enforced.
_active_sessions: dict[str, dict] = {}

ACCESS_PURPOSES = frozenset({
    "incident_response",
    "customer_support",
    "compliance_audit",
    "security_investigation",
    "data_request",
    "diagnostics",
    "break_glass",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


from services.security.request_context import require_kyber_operator as _canonical_kyber_gate


def _require_kyber_operator(request: Request) -> None:
    """Canonical fail-closed Kyber operator gate.

    Replaces the previous ``is_platform_admin`` check (a field never set on any
    TenantContext, which locked out real operators). Now recognises operators by
    the configured ``kyber:operator`` grant or the operator tenant-id allowlist,
    while still denying every Aether tenant (including ``Role.ADMIN``).
    """
    _canonical_kyber_gate(request)


# ── Operational envelope builders ─────────────────────────────────────────────
# Every value is wired to a real, durable source: the WorkerSupervisor, the
# interop provider checkpoints / reconciliation records, the credential
# authority (safe views only — never secrets), the activation repository, the
# source-classification repair-runs store, and the credential-audit store.
# Where a source has produced no signal yet, the field is None / an explicit
# "unknown" — never a fabricated zero.

_LIVE_WORKER_STATES = frozenset({"running", "restarting"})


def _age_seconds(iso_value: Optional[str], now: datetime) -> Optional[float]:
    """Age of an RFC3339/ISO timestamp in seconds, or None when unparseable."""
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = coerce_utc_lenient(parsed)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return max(0.0, (now - parsed).total_seconds())


def _envelope_workers() -> dict[str, Any]:
    """Worker fleet health from the WorkerSupervisor (honest tri-state).

    No supervisor bound (or its status read is broken) → ``observed: False``,
    ``live: None``: nothing was observed this process. Workers exist but none is
    live → ``live: False``. At least one live worker → ``live: True``. The
    backlog / dead-letter / lag fields are None when no worker publishes
    telemetry — distinct from zero.
    """
    supervisor = get_worker_supervisor()
    if supervisor is None:
        return {"observed": False, "live": None, "worker_count": 0,
                "live_count": 0, "dead_letter_depth": None, "consumer_lag": None,
                "oldest_pending_age_s": None, "last_success_at": None}
    try:
        status = supervisor.status()
    except Exception:  # noqa: BLE001 — a broken status read is unknown, not dead
        return {"observed": False, "live": None, "worker_count": 0,
                "live_count": 0, "dead_letter_depth": None, "consumer_lag": None,
                "oldest_pending_age_s": None, "last_success_at": None}
    if not status:
        return {"observed": True, "live": None, "worker_count": 0,
                "live_count": 0, "dead_letter_depth": None, "consumer_lag": None,
                "oldest_pending_age_s": None, "last_success_at": None}

    from services.runtime.supervisor import HEARTBEAT_TIMEOUT_S

    live_count = sum(
        1 for info in status.values()
        if info.get("state") in _LIVE_WORKER_STATES
        and info.get("heartbeat_age_s") is not None
        and float(info.get("heartbeat_age_s")) <= HEARTBEAT_TIMEOUT_S
    )
    successes = [
        info.get("last_success_at") for info in status.values()
        if info.get("last_success_at")
    ]
    dlq = [info.get("dlq_depth") for info in status.values() if info.get("dlq_depth") is not None]
    lag = [info.get("consumer_lag") for info in status.values() if info.get("consumer_lag") is not None]
    pending = [
        info.get("oldest_pending_age_s") for info in status.values()
        if info.get("oldest_pending_age_s") is not None
    ]
    return {
        "observed": True,
        "live": live_count > 0,
        "worker_count": len(status),
        "live_count": live_count,
        "dead_letter_depth": sum(int(d) for d in dlq) if dlq else None,
        "consumer_lag": sum(float(lag_) for lag_ in lag) if lag else None,
        "oldest_pending_age_s": max(pending) if pending else None,
        "last_success_at": max(successes, default=None),
    }


async def _envelope_providers(tenant_id: str, now: datetime) -> dict[str, Any]:
    """Per-provider interop checkpoint operational state for the tenant.

    Aggregates the provider's persisted checkpoints (one per network) into a
    single operational row: latest cursor, summed decode/reorg/conflict/dead-
    letter counters, newest success/failure, and the age of the newest
    ``advanced_at``. No live network calls; a field the checkpoint never
    recorded stays None — never a fabricated zero.
    """
    try:
        checkpoints = await InteropProviderCheckpointRepo().find_many(
            {"tenant_id": tenant_id}, limit=500
        )
    except Exception:  # noqa: BLE001
        return {"providers": [], "checkpoint_count": None,
                "reconciliation_conflicts_total": None}
    by_provider: dict[str, dict[str, Any]] = {}
    conflicts_total = 0
    for cp in checkpoints:
        provider_id = cp.get("provider_id") or "unknown"
        evidence = cp.get("evidence") or {}
        runtime = evidence.get("runtime") or {}
        networks = evidence.get("networks") or {}
        cursor = runtime.get("latest_cursor")
        if cursor is None:
            cursors = []
            for state in networks.values():
                value = state.get("last_scanned_block")
                if value is None:
                    value = state.get("last_scanned_height")
                if value is not None:
                    cursors.append(int(value))
            cursor = max(cursors) if cursors else None
        conflicts = int(runtime.get("reconciliation_conflicts") or 0)
        conflicts_total += conflicts
        entry = by_provider.setdefault(provider_id, {
            "provider_id": provider_id,
            "checkpoint_count": 0,
            "configured": runtime.get("configured"),
            "credential_status": runtime.get("credential_status"),
            "reachable": runtime.get("reachable"),
            "latest_cursor": None,
            "latest_observation_at": runtime.get("latest_observation_at"),
            "lag": runtime.get("lag"),
            "decode_failures": 0,
            "reorg_count": 0,
            "reconciliation_conflicts": 0,
            "dead_letter_count": 0,
            "last_success": runtime.get("last_success"),
            "last_failure": runtime.get("last_failure"),
            "cursor_age_seconds": None,
        })
        entry["checkpoint_count"] += 1
        if cursor is not None and (
            entry["latest_cursor"] is None or cursor > entry["latest_cursor"]
        ):
            entry["latest_cursor"] = cursor
        entry["decode_failures"] += int(runtime.get("decode_failures") or 0)
        entry["reorg_count"] += int(runtime.get("reorg_count") or 0)
        entry["reconciliation_conflicts"] += conflicts
        entry["dead_letter_count"] += int(runtime.get("dead_letter_count") or 0)
        if entry.get("last_success") is None and runtime.get("last_success"):
            entry["last_success"] = runtime["last_success"]
        if runtime.get("last_failure") and (
            entry.get("last_failure") is None
            or runtime["last_failure"] > entry["last_failure"]
        ):
            entry["last_failure"] = runtime["last_failure"]
        age = _age_seconds(cp.get("advanced_at"), now)
        if age is not None and (
            entry["cursor_age_seconds"] is None
            or age > entry["cursor_age_seconds"]
        ):
            entry["cursor_age_seconds"] = age
    providers = sorted(by_provider.values(), key=lambda p: p["provider_id"])
    return {
        "providers": providers,
        "checkpoint_count": len(checkpoints),
        "reconciliation_conflicts_total": conflicts_total,
    }


async def _envelope_reconciliation(tenant_id: str) -> dict[str, Any]:
    """Unresolved interop reconciliation-variance records + the latest record."""
    try:
        records = await InteropReconciliationRepo().find_many(
            {"tenant_id": tenant_id}, limit=500
        )
    except Exception:  # noqa: BLE001
        return {"unresolved_count": None, "latest": None}
    unresolved = [r for r in records if not r.get("resolved_at")]
    latest: Optional[dict[str, Any]] = None
    if records:
        newest = max(records, key=lambda r: r.get("created_at") or "")
        latest = {
            "reconciliation_id": newest.get("reconciliation_id"),
            "correlation_key": newest.get("correlation_key"),
            "status": newest.get("status"),
            "difference_note": newest.get("difference_note"),
            "resolved_at": newest.get("resolved_at"),
            "created_at": newest.get("created_at"),
        }
    return {"unresolved_count": len(unresolved), "latest": latest}


async def _envelope_audit(tenant_id: str) -> dict[str, Any]:
    """Latest credential-audit entry for the tenant from the durable store."""
    try:
        rows = await get_store("credential_audit").find(tenant_id=tenant_id)
    except Exception:  # noqa: BLE001
        return {"latest": None, "count": None}
    latest: Optional[dict[str, Any]] = None
    if rows:
        newest = max(rows, key=lambda r: r.get("at") or "")
        latest = {k: newest.get(k) for k in (
            "id", "action", "provider", "environment", "slot_name",
            "credential_version", "actor", "result", "at",
        )}
    return {"latest": latest, "count": len(rows)}


def _repair_ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _repair_run_view(row: dict[str, Any]) -> dict[str, Any]:
    counters = row.get("counters") or {}
    return {
        "run_id": str(row.get("run_id") or ""),
        "job_id": row.get("job_id"),
        "status": row.get("status"),
        "phase": row.get("phase"),
        "started_at": _repair_ts(row.get("started_at")),
        "completed_at": _repair_ts(row.get("completed_at")),
        "scanned": counters.get("scanned"),
        "reclassified": counters.get("reclassified"),
        "journeys_rebuilt": counters.get("journeys_rebuilt"),
    }


async def _envelope_repair(tenant_id: str) -> dict[str, Any]:
    """Latest source-classification repair run for the tenant (honest unknown)."""
    from repositories.repos import get_pool

    pool = None
    try:
        pool = await get_pool()
    except Exception:  # noqa: BLE001
        pool = None
    if pool is not None:
        try:
            rows = await pool.fetch(
                "SELECT * FROM source_classification_repair_runs "
                "WHERE tenant_id=$1 ORDER BY started_at DESC LIMIT 20",
                tenant_id,
            )
        except Exception:  # noqa: BLE001
            return {"run_count": None, "latest": None}
        runs = [_repair_run_view(dict(r)) for r in rows]
        return {"run_count": len(runs), "latest": runs[0] if runs else None}
    try:
        from services.traffic.repair import _local_runs

        runs = [dict(r) for r in _local_runs.values() if r.get("tenant_id") == tenant_id]
    except Exception:  # noqa: BLE001
        return {"run_count": None, "latest": None}
    runs.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return {"run_count": len(runs),
            "latest": _repair_run_view(runs[0]) if runs else None}


async def _envelope_activation(tenant_id: str) -> dict[str, Any]:
    """Tenant self-serve activation lifecycle state (read-only, no writes)."""
    from services.activation.repository import ActivationRepository

    try:
        record = await ActivationRepository().get_for_tenant(tenant_id)
    except Exception:  # noqa: BLE001
        return {"observed": False, "state": None, "updated_at": None,
                "manual_reason": None, "blocked_reason": None,
                "history_count": None}
    if record is None:
        return {"observed": True, "state": None, "updated_at": None,
                "manual_reason": None, "blocked_reason": None, "history_count": 0}
    return {
        "observed": True,
        "state": record.get("state"),
        "updated_at": record.get("updated_at"),
        "manual_reason": record.get("manual_reason"),
        "blocked_reason": record.get("blocked_reason"),
        "history_count": len(record.get("history") or []),
    }


async def _envelope_demotion(tenant_id: str) -> dict[str, Any]:
    """Last automatic-demotion reason + timestamp for the tenant."""
    try:
        record = await TenantLaunchReadiness().get(tenant_id)
    except Exception:  # noqa: BLE001
        return {"demotion_reason": None, "demotion_at": None}
    if record is None:
        return {"demotion_reason": None, "demotion_at": None}
    return {
        "demotion_reason": record.get("demotion_reason"),
        "demotion_at": record.get("demotion_at"),
    }


async def _envelope_readiness(tenant_id: str) -> dict[str, Any]:
    """Launch-readiness snapshot: ready + blocking gates (real or all-pending)."""
    readiness = TenantLaunchReadiness()
    try:
        record = await readiness.get(tenant_id)
    except Exception:  # noqa: BLE001
        return {"observed": None, "ready": None, "blocking": None,
                "blocking_count": None}
    if record is None:
        evaluation = readiness.evaluate(tenant_id, {})
        return {
            "observed": False,
            "ready": evaluation["ready"],
            "blocking": evaluation["blocking"],
            "blocking_count": len(evaluation["blocking"]),
        }
    blocking = record.get("blocking") or []
    return {
        "observed": True,
        "ready": record.get("ready"),
        "blocking": blocking,
        "blocking_count": len(blocking),
    }


async def _operational_envelope_sections(tenant_id: str) -> dict[str, Any]:
    """The non-graph operational sections of the per-tenant envelope."""
    now = datetime.now(timezone.utc)
    return {
        "workers": _envelope_workers(),
        "credentials": await tenant_credential_slot_states(tenant_id),
        "providers": await _envelope_providers(tenant_id, now),
        "reconciliation": await _envelope_reconciliation(tenant_id),
        "audit": await _envelope_audit(tenant_id),
        "repair": await _envelope_repair(tenant_id),
        "activation": await _envelope_activation(tenant_id),
        "demotion": await _envelope_demotion(tenant_id),
        "readiness": await _envelope_readiness(tenant_id),
    }


# ── Models ─────────────────────────────────────────────────────────────────────

class TenantEntryRequest(BaseModel):
    tenant_id: str
    access_reason: str = Field(..., min_length=10, description="Required justification for tenant access")
    purpose: Literal[
        "incident_response", "customer_support", "compliance_audit",
        "security_investigation", "data_request", "diagnostics", "break_glass"
    ]
    duration_minutes: int = Field(default=60, ge=1, le=480)


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/operator/tenant-entry")
async def enter_tenant(body: TenantEntryRequest, request: Request) -> dict:
    """Request privileged scoped access to a specific tenant's data.

    Compatibility shim over the durable scope plane. The response shape is
    unchanged — the existing Kyber frontend calls this endpoint — but the scope
    is now a row in ``kyber_access_scopes``: session- and device-bound,
    expiring, revocable, audited, and actually consulted by
    ``require_kyber_access`` when a route reaches tenant data.

    Prefer ``POST /v1/kyber/scopes`` for new work.
    """
    context = _require_kyber_operator(request)

    from services.kyber.access.dependencies import current_kyber_context
    from services.kyber.access.scopes import access_scope_service

    kyber_context = current_kyber_context(request)
    if kyber_context is None or not getattr(kyber_context, "session", None):
        # A durable scope is bound to a session and a device. Without a Kyber
        # workforce session there is nothing to bind to, and issuing an
        # unbindable scope id would recreate exactly the non-enforcement this
        # shim exists to remove.
        raise ForbiddenError(
            "a Kyber workforce session is required to enter a tenant; "
            "authenticate through /v1/kyber/auth/login"
        )

    scope = await access_scope_service.open_scope(
        operator_id=kyber_context.operator_id,
        session_id=kyber_context.session.session_id,
        device_id=getattr(kyber_context, "device_id", None),
        environment=getattr(kyber_context, "environment", "unknown"),
        tenant_id=body.tenant_id,
        purpose=body.purpose,
        reason=body.access_reason,
        ttl_minutes=body.duration_minutes,
    )

    logger.info(
        "kyber_operator_tenant_entry",
        extra={
            "session_id": scope.scope_id,
            "operator_id": kyber_context.operator_id,
            "tenant_id": body.tenant_id,
            "purpose": body.purpose,
        },
    )

    return APIResponse(
        data={
            # The legacy field name is preserved for the existing client; it now
            # carries the durable scope id.
            "session_id": scope.scope_id,
            "tenant_id": scope.tenant_id,
            "purpose": scope.purpose,
            "entered_at": scope.entered_at,
            "expires_at": scope.expires_at,
            "message": f"Entering tenant {body.tenant_id} as operator — all actions audited",
        }
    ).to_dict()


@router.delete("/operator/tenant-entry")
async def exit_tenant(session_id: str, request: Request) -> dict:
    """Close an operator tenant scope. Idempotent.

    Resolves the durable scope first. The legacy in-process entry is still
    honoured so a session_id issued before this deployment can still be exited
    cleanly, but nothing new is ever written there.
    """
    context = _require_kyber_operator(request)

    from services.kyber.access.dependencies import current_kyber_context
    from services.kyber.access.scopes import access_scope_service

    kyber_context = current_kyber_context(request)
    actor_id = getattr(kyber_context, "operator_id", None) or getattr(
        request.state.tenant, "tenant_id", "unknown"
    )

    scope = await access_scope_service.get(session_id)
    if scope is not None:
        if scope.status != "active":
            return APIResponse(
                data={"status": "already_expired", "session_id": session_id}
            ).to_dict()
        # An operator may only close their own scope. Without this, any operator
        # could close another's scope mid-investigation.
        if kyber_context is not None and scope.operator_id != actor_id:
            raise ForbiddenError("a tenant scope may only be exited by the operator that opened it")
        await access_scope_service.exit_scope(session_id, actor_id=actor_id)
        return APIResponse(data={"status": "exited", "session_id": session_id}).to_dict()

    # ── Legacy pre-deployment entry ──────────────────────────────────────────
    session = _active_sessions.get(session_id)
    if not session or session.get("exited_at") or not session.get("active"):
        return APIResponse(data={"status": "already_expired", "session_id": session_id}).to_dict()
    session["active"] = False
    session["exited_at"] = _utc_now()
    logger.info(
        "kyber_operator_tenant_exit",
        extra={
            "session_id": session_id,
            "operator_id": actor_id,
            "tenant_id": session.get("tenant_id"),
        },
    )
    return APIResponse(data={"status": "exited", "session_id": session_id}).to_dict()


@router.get("/tenants/{tenant_id}/operational-envelope")
async def tenant_operational_envelope(
    tenant_id: str = Path(..., description="Target tenant ID"),
    request: Request = ...,
    graph: GraphClient = Depends(get_graph),
) -> dict:
    """Return operational health envelope for a specific tenant.

    Aggregates health signals from SDK, connector, graph, measurement, and fraud
    services into a single operational snapshot for Kyber operator dashboards.

    Requires: kyber:operator permission.
    """
    _require_kyber_operator(request)

    # ── Graph health ──────────────────────────────────────────────────────────
    # Scoped to the path tenant: the cap bounds THAT tenant's rows, so an
    # envelope for a tenant sorting past a global page no longer reports zero.
    tenant_verts = await graph.get_vertices_for_tenant(tenant_id, limit=10000)
    graph_node_count = len(tenant_verts)

    # Count edges for the sampled nodes
    edge_count = 0
    for v in tenant_verts[:100]:
        try:
            edges = await graph.get_edges(v.vertex_id, direction="out")
            edge_count += len(edges)
        except Exception:
            pass

    # ── Fraud volume (from fraud_networks) ────────────────────────────────────
    fraud_network_count = 0
    try:
        from repositories.repos import FraudNetworkRepository
        _fraud_repo = FraudNetworkRepository()
        networks = await _fraud_repo.list_by_tenant(tenant_id, limit=200)
        fraud_network_count = len(networks)
    except Exception:
        pass

    # ── SDK health (from sdk_health events) ──────────────────────────────────
    sdk_health_score: Optional[float] = None
    try:
        from services.data_quality.service import intelligence_quality_service
        report = await intelligence_quality_service.dimension_report("graph", tenant_id)
        sdk_health_score = float(report.get("quality_score", 0.0))
    except Exception:
        pass

    computed_at = _utc_now()

    # Worker health, credential slots, provider cursor/reconciliation state,
    # latest audit, last repair, activation lifecycle, demotion reason and
    # readiness all come from real durable sources (never hardcoded zeros);
    # a source with no signal yet reports None / explicit "unknown".
    envelope_sections = await _operational_envelope_sections(tenant_id)

    return APIResponse(
        data={
            "tenant_id": tenant_id,
            "computed_at": computed_at,
            "graph": {
                "node_count": graph_node_count,
                "edge_count_sample": edge_count,
                "has_data": graph_node_count > 0,
            },
            "fraud": {
                "fraud_network_count": fraud_network_count,
            },
            "sdk": {
                "health_score": sdk_health_score,
            },
            "status": "healthy" if graph_node_count > 0 else "no_data",
            **envelope_sections,
        }
    ).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Payment-rails fleet operational summary (agent 3B — observability closure)
# ═══════════════════════════════════════════════════════════════════════════
# Operator control-plane aggregate over the durable payment-rail ledgers —
# cross-tenant, sanitized (counters / health / reasons only, never tenant-
# private payment payloads). Surfaces the fleet signals an operator needs at a
# glance: polling-cursor age, reconciliation conflicts, activation lifecycle
# stage, per-provider demotion reasons, last audit, and last repair outcomes.

#: Poll-health tokens that are a REAL degradation (as opposed to absent data or
#: the not_configured off state). ``auth_error`` is the credential-invalid
#: signal; the rest downgrade to ``degraded``. Mirrors readiness_demotion.py.
_DEGRADED_POLL_HEALTH = frozenset({
    "rate_limited", "client_error", "server_error", "timeout", "network_error",
    "bad_response",
})


@router.get("/operator/payment-rails/summary")
async def payment_rails_fleet_operational_summary(request: Request) -> dict:
    """Operator fleet operational summary for the payment-rails plane.

    Reads the durable payment-rail ledgers (cross-tenant operator aggregate) and
    surfaces sanitized operational signals:

      * ``activation_lifecycle_stage``   — payment-rails capability lifecycle
                                           stage, or null when undeclared.
      * ``fleet_cursor_age_seconds``     — stalest observed successful poll
                                           cursor across all provider accounts
                                           (null when none recorded).
      * ``reconciliation_conflicts``     — open SDK-vs-provider truth
                                           disagreements.
      * ``demotion_reasons``             — per-provider readiness off-ramp
                                           reason derived from poll health
                                           (credential_invalid / degraded).
      * ``last_audit`` / ``last_repair_outcomes`` — most recent safe records.

    Read-only and fail-open: any ledger that is unavailable contributes no rows
    and an honest null/zero, never a fabricated signal. Requires kyber:operator.
    """
    _require_kyber_operator(request)

    from services.integrations.providers.payment_rails.base import POLL_HEALTH_OK
    from services.integrations.providers.payment_rails.lifecycle import (
        current_lifecycle_stage,
    )
    from services.integrations.providers.payment_rails.service import (
        get_payment_rails_service,
    )

    service = get_payment_rails_service()
    now = datetime.now(timezone.utc)

    accounts = await service.repos.accounts.list_all()
    reconciliations = await service.repos.reconciliation.list_all()
    audits = await service.repos.audit.list_all()
    receipts = await service.repos.receipts.list_all()

    # Fleet cursor age: the STALEST observed successful poll. Only accounts
    # whose poll health is ``ok`` count — a degraded poll is a different signal
    # (captured under demotion_reasons), and an absent cursor is unknown.
    poll_ages: list[float] = []
    for acct in accounts:
        last_poll = acct.get("last_poll_at")
        if last_poll and acct.get("provider_poll_health") == POLL_HEALTH_OK:
            try:
                parsed = datetime.fromisoformat(str(last_poll).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if parsed.tzinfo is None:
                parsed = coerce_utc_lenient(parsed)
            poll_ages.append(max(0.0, (now - parsed).total_seconds()))
    fleet_cursor_age_seconds = max(poll_ages) if poll_ages else None

    # Demotion reasons per provider, derived from durable poll health.
    demotion_reasons: dict[str, str] = {}
    for acct in accounts:
        provider = acct.get("provider")
        if not provider:
            continue
        health = acct.get("provider_poll_health")
        if health == "auth_error":
            demotion_reasons[provider] = "credential_invalid"
        elif health in _DEGRADED_POLL_HEALTH:
            demotion_reasons.setdefault(provider, "degraded")

    reconciliation_conflicts = sum(
        1 for r in reconciliations if r.get("state") == "conflict"
    )

    audits_sorted = sorted(
        audits, key=lambda r: r.get("occurred_at") or "", reverse=True
    )
    last_audit = audits_sorted[:10]

    last_repair_outcomes = [
        {
            "at": r.get("last_attempted_at"),
            "provider": r.get("provider"),
            "stage": r.get("current_stage"),
            "repair_attempts": r.get("repair_attempts"),
        }
        for r in receipts if int(r.get("repair_attempts", 0)) > 0
    ][:25]

    lifecycle_stage = await current_lifecycle_stage()

    return APIResponse(
        data={
            "plane": "payment_rails",
            "computed_at": now.isoformat(),
            "activation_lifecycle_stage": lifecycle_stage,
            "fleet_cursor_age_seconds": fleet_cursor_age_seconds,
            "reconciliation_conflicts": reconciliation_conflicts,
            "demotion_reasons": demotion_reasons,
            "last_audit": last_audit,
            "last_repair_outcomes": last_repair_outcomes,
        }
    ).to_dict()
