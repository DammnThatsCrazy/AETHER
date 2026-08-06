"""Kyber operator financial-health aggregation.

Builds the typed fleet + tenant contract (:mod:`kyber_contract`) from the durable
payment-rail stores. Cross-tenant reads are a control-plane aggregate (operator
only) — never surfaced to a tenant — and carry only sanitized counters / health,
never tenant-private payment payloads. Distinguishes real zeros from unknowns:
an uncomputable value is ``None`` (unknown), never a misleading ``0``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.integrations.providers.payment_rails import ADAPTERS
from services.integrations.providers.payment_rails.kyber_contract import (
    CredentialSlotState,
    FleetHealthResponse,
    FleetTotals,
    ProviderFleetRow,
    TenantBacklogs,
    TenantDiagnosticsResponse,
    TenantFleetRow,
    TenantProviderAdapter,
    TenantProviderDiagnostics,
    TenantProviderHealth,
)
from services.integrations.providers.payment_rails.receipts import (
    COMPLETE_STAGES,
    TERMINAL_STATES,
    ReceiptState,
)
from services.integrations.providers.payment_rails.service import provider_enabled

_PENDING = ("pending", "submitted", "initiated")


def _age_seconds(iso_value: Optional[str], now: datetime) -> Optional[float]:
    if not iso_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return max(0.0, (now - parsed).total_seconds())


def _rate(matched: int, total: int) -> Optional[float]:
    return (matched / total) if total else None


def _incomplete(receipts: list[dict]) -> list[dict]:
    return [
        r for r in receipts
        if r.get("current_stage") not in COMPLETE_STAGES
        and r.get("current_stage") not in TERMINAL_STATES
    ]


async def build_fleet_health(service: Any) -> FleetHealthResponse:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()

    sessions = await service.repos.sessions.list_all()
    all_events = await service.repos.events.list_all()  # cross-tenant (operator aggregate)
    reconciliations = await service.repos.reconciliation.list_all()
    audits = await service.repos.audit.list_all()
    receipts = await service.repos.receipts.list_all()

    tenants_observed = sorted({s.get("tenant_id") for s in sessions if s.get("tenant_id")})

    providers: list[ProviderFleetRow] = []
    degraded_providers = 0
    for name in ADAPTERS:
        adapter = ADAPTERS[name]
        enabled = provider_enabled(name)
        p_sessions = [s for s in sessions if s.get("provider") == name]
        recent = [s for s in p_sessions if (s.get("created_at") or "") >= cutoff]
        p_recons = [r for r in reconciliations if r.get("provider") == name]
        verified_24h = sum(
            1 for e in all_events
            if e.get("provider") == name and (e.get("received_at") or "") >= cutoff
        )
        rejected_24h = sum(
            1 for a in audits
            if a.get("provider") == name and a.get("action") == "webhook_rejected"
            and (a.get("occurred_at") or "") >= cutoff
        )
        matched = sum(1 for r in p_recons if r.get("state") == "matched")
        conflicts = sum(1 for r in p_recons if r.get("state") == "conflict")
        configured_tenants = len({s.get("tenant_id") for s in p_sessions if s.get("tenant_id")})

        if not enabled:
            status = "disabled"
        elif configured_tenants == 0:
            status = "not_configured"
        elif rejected_24h > 0 and verified_24h == 0:
            status = "error"
        elif conflicts > 0 or rejected_24h > 0:
            status = "degraded"
        else:
            status = "healthy"
        if status in ("degraded", "error"):
            degraded_providers += 1

        providers.append(ProviderFleetRow(
            provider=name, status=status, enabled=enabled,
            configured_tenants=configured_tenants,
            webhook_verified_24h=verified_24h, webhook_rejected_24h=rejected_24h,
            signature_failures_24h=rejected_24h,
            sessions_observed_24h=len(recent),
            sessions_completed_24h=sum(1 for s in recent if s.get("status") == "completed"),
            sessions_failed_24h=sum(1 for s in recent if s.get("status") == "failed"),
            sessions_pending=sum(1 for s in p_sessions if s.get("status") in _PENDING),
            sessions_stale=sum(
                1 for s in p_sessions if s.get("reconciliation_state") == "stale"
            ),
            sessions_unresolved=sum(
                1 for s in p_sessions if s.get("status") in ("unresolved", "pending")
            ),
            reconciliation_matched_rate=_rate(matched, len(p_recons)),
            reconciliation_conflicts=conflicts,
            polling_cursor_age_seconds=None,
            provider_probe_status=None,
        ))

    # Per-tenant fleet rows.
    tenant_rows: list[TenantFleetRow] = []
    by_tenant: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        if s.get("tenant_id"):
            by_tenant[s["tenant_id"]].append(s)
    for tenant_id, t_sessions in sorted(by_tenant.items()):
        t_recent = [s for s in t_sessions if (s.get("created_at") or "") >= cutoff]
        t_recons = [r for r in reconciliations if r.get("tenant_id") == tenant_id]
        conflicts = sum(1 for r in t_recons if r.get("state") == "conflict")
        t_providers = {s.get("provider") for s in t_sessions if s.get("provider")}
        t_rejected = sum(
            1 for a in audits
            if a.get("tenant_id") == tenant_id and a.get("action") == "webhook_rejected"
            and (a.get("occurred_at") or "") >= cutoff
        )
        degraded = conflicts > 0 or t_rejected > 0
        tenant_rows.append(TenantFleetRow(
            tenant_id=tenant_id,
            status="degraded" if degraded else "healthy",
            providers_configured=len(t_providers),
            providers_degraded=(1 if degraded else 0),
            sessions_observed_24h=len(t_recent),
            sessions_unresolved=sum(
                1 for s in t_sessions if s.get("status") in ("unresolved", "pending")
            ),
            reconciliation_conflicts=conflicts,
        ))

    incomplete = _incomplete(receipts)
    dead_lettered = sum(1 for r in receipts if r.get("current_stage") == ReceiptState.DEAD_LETTERED)
    oldest = min((r.get("received_at") for r in incomplete if r.get("received_at")), default=None)

    all_recons = reconciliations
    matched_all = sum(1 for r in all_recons if r.get("state") == "matched")
    any_enabled = any(provider_enabled(n) for n in ADAPTERS)

    totals = FleetTotals(
        configured_tenants=len(tenants_observed),
        enabled_tenants=len(tenants_observed) if any_enabled else 0,
        providers_degraded=degraded_providers,
        sessions_observed_24h=sum(p.sessions_observed_24h for p in providers),
        sessions_completed_24h=sum(p.sessions_completed_24h for p in providers),
        sessions_failed_24h=sum(p.sessions_failed_24h for p in providers),
        sessions_pending=sum(p.sessions_pending for p in providers),
        sessions_stale=sum(p.sessions_stale for p in providers),
        sessions_unresolved=sum(p.sessions_unresolved for p in providers),
        webhook_verified_24h=sum(p.webhook_verified_24h for p in providers),
        webhook_rejected_24h=sum(p.webhook_rejected_24h for p in providers),
        signature_failures_24h=sum(p.signature_failures_24h for p in providers),
        reconciliation_matched_rate=_rate(matched_all, len(all_recons)),
        reconciliation_conflicts=sum(p.reconciliation_conflicts for p in providers),
        oldest_incomplete_receipt_age_seconds=_age_seconds(oldest, now),
        canonical_backlog=len(incomplete),
        outbox_lag=None,
        repair_backlog=sum(1 for r in incomplete if int(r.get("repair_attempts", 0)) > 0),
        dead_lettered=dead_lettered,
        worker_heartbeat=None,
        last_successful_worker_cycle=None,
    )

    return FleetHealthResponse(
        tenants_observed=len(tenants_observed),
        totals=totals, providers=providers, tenants=tenant_rows,
    )


async def build_tenant_diagnostics(
    service: Any, tenant_id: str, provider: Optional[str] = None
) -> TenantDiagnosticsResponse:
    now = datetime.now(timezone.utc)
    health_rows = await service.health(tenant_id)
    if provider:
        health_rows = [h for h in health_rows if h.provider == provider]

    # Credential-slot states from the durable authority (no secret values).
    slots_by_provider: dict[str, list[CredentialSlotState]] = defaultdict(list)
    try:
        from services.providers.credentials.authority import credential_authority

        for env in ("sandbox", "live"):
            connections = await credential_authority.get_connections(tenant_id, environment=env)
            for conn in connections:
                for slot in conn.get("slots", []):
                    status = slot.get("status") or {}
                    slots_by_provider[conn["provider"]].append(CredentialSlotState(
                        slot_name=slot.get("slot_name", ""),
                        required=bool(slot.get("required")),
                        configured=bool(slot.get("configured")),
                        state=(status or {}).get("state"),
                    ))
    except Exception:  # noqa: BLE001 — authority unavailable → no slot detail (not a fake zero)
        slots_by_provider = defaultdict(list)

    diagnostics: list[TenantProviderDiagnostics] = []
    for h in health_rows:
        name = h.provider
        account = await service.repos.accounts.get(tenant_id, name) or {}
        endpoint_registered = False
        try:
            from services.integrations.providers.payment_rails.webhook_endpoints import (
                webhook_endpoint_registry,
            )

            endpoints = await webhook_endpoint_registry.list_for(tenant_id, name)
            endpoint_registered = any(e.get("state") == "active" for e in endpoints)
        except Exception:  # noqa: BLE001
            endpoint_registered = False

        adapter = TenantProviderAdapter(
            status=("configured" if h.configured else "not_configured"),
            environment=account.get("environment"),
            webhook_configured=bool(h.configured),
            polling_configured=bool(account.get("provider_poll_health") not in (None, "not_configured")
                                    and ADAPTERS[name].polling_supported),
            webhook_endpoint_registered=endpoint_registered,
            credential_slots=slots_by_provider.get(name, []),
        )
        poll_health = account.get("provider_poll_health")
        health = TenantProviderHealth(
            status=h.status,
            sessions_observed_24h=h.sessions_observed_24h,
            sessions_completed_24h=h.sessions_completed_24h,
            sessions_failed_24h=h.sessions_failed_24h,
            sessions_unresolved=h.sessions_unresolved,
            webhook_verified_24h=h.webhook_verified_24h,
            webhook_rejected_24h=h.webhook_rejected_24h,
            reconciliation_matched_rate=h.reconciliation_matched_rate,
            reconciliation_conflicts=h.reconciliation_conflicts,
            last_event_at=h.last_event_at,
            last_poll_at=h.last_poll_at,
            last_successful_poll_at=(h.last_poll_at if poll_health == "ok" else None),
            last_failed_poll_at=(h.last_poll_at if poll_health not in (None, "ok", "webhook_only") else None),
            polling_cursor_age_seconds=_age_seconds(h.last_poll_at, now),
            provider_poll_health=poll_health,
            connection_probe_result=None,
        )
        diagnostics.append(TenantProviderDiagnostics(
            provider=name, adapter=adapter, health=health,
        ))

    receipts = await service.repos.receipts.list_for_tenant(tenant_id, limit=1000)
    if provider:
        receipts = [r for r in receipts if r.get("provider") == provider]
    incomplete = _incomplete(receipts)
    dead_lettered = sum(1 for r in receipts if r.get("current_stage") == ReceiptState.DEAD_LETTERED)
    oldest = min((r.get("received_at") for r in incomplete if r.get("received_at")), default=None)
    backlogs = TenantBacklogs(
        receipt_backlog=len(incomplete),
        canonical_backlog=len(incomplete),
        outbox_backlog=None,
        repair_backlog=sum(1 for r in incomplete if int(r.get("repair_attempts", 0)) > 0),
        dead_lettered=dead_lettered,
        oldest_incomplete_receipt_age_seconds=_age_seconds(oldest, now),
    )

    audits = await service.repos.audit.list_for_tenant(tenant_id, provider=provider, limit=50)
    repair_outcomes = [
        {"at": r.get("last_attempted_at"), "provider": r.get("provider"),
         "receipt_id": r.get("receipt_id"), "stage": r.get("current_stage"),
         "repair_attempts": r.get("repair_attempts"),
         "history": (r.get("repair_history") or [])[-3:]}
        for r in receipts if int(r.get("repair_attempts", 0)) > 0
    ][:25]

    return TenantDiagnosticsResponse(
        tenant_id=tenant_id, providers=diagnostics, backlogs=backlogs,
        recent_audit=audits, recent_repair_outcomes=repair_outcomes,
    )
