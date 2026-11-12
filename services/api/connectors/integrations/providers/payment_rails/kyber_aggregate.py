"""Kyber operator financial-health aggregation.

Builds the typed fleet + tenant contract (:mod:`kyber_contract`) from the durable
payment-rail stores. Cross-tenant reads are a control-plane aggregate (operator
only) — never surfaced to a tenant — and carry only sanitized counters / health,
never tenant-private payment payloads. Distinguishes real zeros from unknowns:
an uncomputable value is ``None`` (unknown), never a misleading ``0``.

Worker-liveness fields (``worker_heartbeat``, ``last_successful_worker_cycle``)
are folded from the live ``WorkerSupervisor`` state via
:func:`shared.supervisor_handle.get_worker_supervisor` (bound by the lifespan).
``outbox_lag`` and ``polling_cursor_age_seconds`` are computed from the durable
receipt + provider-account ledgers. When no supervisor is bound (or a ledger
value cannot be computed) the field stays ``None`` — "no signal observed", never
a fabricated zero. Fleet-health gauges are emitted alongside so a Grafana/Kyber
dashboard has a metric source, not just a JSON endpoint.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from shared.logger.logger import metrics
from shared.supervisor_handle import get_worker_supervisor
from shared.temporal.instant import ensure_aware_utc

from connectors.integrations.providers.payment_rails import ADAPTERS
from connectors.integrations.providers.payment_rails.kyber_contract import (
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
from connectors.integrations.providers.payment_rails.receipts import (
    COMPLETE_STAGES,
    TERMINAL_STATES,
    ReceiptStage,
    ReceiptState,
)
from connectors.integrations.providers.payment_rails.service import provider_enabled

_PENDING = ("pending", "submitted", "initiated")

# Live worker states per WorkerSupervisor.status(); a worker in one of these
# whose heartbeat is fresh is evidence the worker plane is advancing.
_LIVE_WORKER_STATES = ("running", "restarting")


def _age_seconds(iso_value: Optional[str], now: datetime) -> Optional[float]:
    if not iso_value:
        return None
    try:
        parsed = ensure_aware_utc(datetime.fromisoformat(str(iso_value).replace("Z", "+00:00")))
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


def _fleet_cursor_age_by_provider(
    accounts: list[dict], now: datetime
) -> dict[str, Optional[float]]:
    """Per-provider fleet polling-cursor age — the stalest observed cursor.

    For each provider, the age of the OLDEST ``last_poll_at`` across its durable
    provider-account records: that cursor is the one lagging most behind
    provider truth, so it bounds the operator's "is our pull plane advancing?"
    answer. A provider with no account that ever recorded a poll stays ``None``
    (unknown) — never a fabricated 0. Webhook-only providers naturally have no
    ``last_poll_at`` and therefore no entry; the caller additionally gates on
    ``polling_supported`` so an unknown is never rendered where polling is
    architecturally absent.
    """
    ages_by_provider: dict[str, list[float]] = defaultdict(list)
    for account in accounts:
        provider = account.get("provider")
        last_poll_at = account.get("last_poll_at")
        if not provider or not last_poll_at:
            continue
        age = _age_seconds(last_poll_at, now)
        if age is not None:
            ages_by_provider[provider].append(age)
    return {provider: max(ages) for provider, ages in ages_by_provider.items()}


def _observed_tenants_by_provider(
    sessions: list[dict],
    events: list[dict],
    reconciliations: list[dict],
    accounts: list[dict],
) -> dict[str, set[str]]:
    """Tenants with at least one real provider observation, per provider.

    Evidence is a session, a verified provider event, a reconciliation record, or
    a successful poll recorded on the durable provider account. Credentials alone
    and rejected webhooks are not observation evidence.
    """
    observed: dict[str, set[str]] = defaultdict(set)
    for row in sessions:
        tenant_id = row.get("tenant_id")
        provider = row.get("provider")
        if tenant_id and provider in ADAPTERS:
            observed[provider].add(tenant_id)
    for row in events:
        tenant_id = row.get("tenant_id")
        provider = row.get("provider")
        if tenant_id and provider in ADAPTERS and row.get("received_at"):
            observed[provider].add(tenant_id)
    for row in reconciliations:
        tenant_id = row.get("tenant_id")
        provider = row.get("provider")
        if tenant_id and provider in ADAPTERS:
            observed[provider].add(tenant_id)
    for account in accounts:
        tenant_id = account.get("tenant_id")
        provider = account.get("provider")
        if (
            tenant_id
            and provider in ADAPTERS
            and ADAPTERS[provider].polling_supported
            and account.get("last_poll_at")
            and account.get("provider_poll_health") == "ok"
        ):
            observed[provider].add(tenant_id)
    return observed


def _fleet_observation_status(
    configured: Optional[set[str]],
    observed: set[str],
    *,
    inventory_available: bool,
) -> str:
    """Coverage status for configured tenants, independent of health.

    ``unknown`` means the credential inventory could not be read, so a confident
    ``not_configured``/``never_observed`` answer would be a fabricated claim.
    """
    if not inventory_available:
        return "unknown"
    configured = configured or set()
    if not configured:
        return "not_configured"
    observed_configured = configured & observed
    if not observed_configured:
        return "never_observed"
    if configured <= observed:
        return "observed"
    return "partially_observed"


def _fleet_health_status(
    *,
    enabled: bool,
    configured_count: Optional[int],
    observed_count: int,
    observation_status: str,
    webhook_verified_24h: int,
    webhook_rejected_24h: int,
    conflicts: int,
) -> str:
    """Health status that never upgrades missing observation to healthy."""
    if not enabled:
        return "disabled"
    if configured_count == 0:
        return "not_configured"
    if webhook_rejected_24h > 0 and webhook_verified_24h == 0:
        return "error"
    if observation_status == "never_observed":
        return "unknown"
    if conflicts > 0 or webhook_rejected_24h > 0:
        return "degraded"
    if observation_status == "partially_observed":
        return "degraded"
    if observed_count == 0:
        return "unknown"
    return "healthy"


def _emit_fleet_gauges(
    totals: "FleetTotals",
    providers: list["ProviderFleetRow"],
    *,
    worker_heartbeat: Optional[bool],
    last_successful_worker_cycle: Optional[str],
    now: datetime,
) -> None:
    """Emit ``kyber_fleet_*`` gauges so a Grafana/Kyber dashboard has a metric
    source, not just a JSON endpoint.

    Honesty mirrors the contract: an unknown liveness is *absent*, never a
    fabricated 0. ``kyber_fleet_worker_heartbeat`` / ``..._cycle_seconds`` are
    simply not emitted when no supervisor was observed; the backlog/cursor
    gauges are real zeros (the ledgers are always readable) and always emitted.
    Configured-tenant coverage follows the same rule: it is absent when the
    credential inventory is unreadable, while observed coverage is a real count.
    """
    if worker_heartbeat is not None:
        metrics.gauge("kyber_fleet_worker_heartbeat", 1.0 if worker_heartbeat else 0.0)
    if last_successful_worker_cycle is not None:
        cycle_age = _age_seconds(last_successful_worker_cycle, now)
        if cycle_age is not None:
            metrics.gauge("kyber_fleet_last_successful_worker_cycle_seconds", cycle_age)
    metrics.gauge("kyber_fleet_outbox_lag", float(totals.outbox_lag or 0.0))
    metrics.gauge("kyber_fleet_canonical_backlog", float(totals.canonical_backlog))
    metrics.gauge("kyber_fleet_dead_lettered", float(totals.dead_lettered))
    metrics.gauge("kyber_fleet_providers_degraded", float(totals.providers_degraded))
    metrics.gauge("kyber_fleet_observed_tenants", float(totals.observed_tenants))
    metrics.gauge(
        "kyber_fleet_configuration_inventory_available",
        1.0 if totals.configuration_inventory_available else 0.0,
    )
    # Configured coverage is absent (not zero) when the inventory is unreadable.
    if totals.configured_tenants is not None:
        metrics.gauge("kyber_fleet_configured_tenants", float(totals.configured_tenants))
    if totals.oldest_incomplete_receipt_age_seconds is not None:
        metrics.gauge(
            "kyber_fleet_oldest_incomplete_receipt_seconds",
            totals.oldest_incomplete_receipt_age_seconds,
        )
    for row in providers:
        labels = {"provider": row.provider}
        if row.configured_tenants is not None:
            metrics.gauge(
                "kyber_fleet_provider_configured_tenants",
                float(row.configured_tenants),
                labels=labels,
            )
        metrics.gauge(
            "kyber_fleet_provider_observed_tenants",
            float(row.observed_tenants),
            labels=labels,
        )
        if row.never_observed_tenants is not None:
            metrics.gauge(
                "kyber_fleet_provider_never_observed_tenants",
                float(row.never_observed_tenants),
                labels=labels,
            )
        if row.polling_cursor_age_seconds is not None:
            metrics.gauge(
                "kyber_fleet_provider_cursor_age_seconds",
                row.polling_cursor_age_seconds,
                labels=labels,
            )


def _fleet_worker_liveness(
    supervisor: Any, now: datetime
) -> tuple[Optional[bool], Optional[str]]:
    """Fold WorkerSupervisor state into (worker_heartbeat, last_successful_worker_cycle).

    Honest tri-state semantics (never a fabricated signal):
    - no supervisor bound, or the supervisor exposes no workers → ``None``
      (nothing observed this process — unknown).
    - at least one worker live (running/restarting with a heartbeat within the
      supervisor's own liveness window) → ``True``.
    - workers exist but none is live → ``False`` (deliberately not healthy).
    ``last_successful_worker_cycle`` is the newest ``last_success_at`` across
    workers (already RFC 3339 UTC from ``status()``), or ``None`` when no worker
    has completed a unit of work yet.
    """
    if supervisor is None:
        return None, None
    try:
        status = supervisor.status()
    except Exception:  # noqa: BLE001 — a broken status read is unknown, not dead
        return None, None
    if not status:
        return None, None

    from workers.runtime.supervisor import HEARTBEAT_TIMEOUT_S

    live = any(
        info.get("state") in _LIVE_WORKER_STATES
        and info.get("heartbeat_age_s") is not None
        and float(info.get("heartbeat_age_s")) <= HEARTBEAT_TIMEOUT_S
        for info in status.values()
    )
    successes = [
        info.get("last_success_at")
        for info in status.values()
        if info.get("last_success_at")
    ]
    last_success = max(successes, default=None)
    return live, last_success


async def build_fleet_health(
    service: Any, *, supervisor: Any = None
) -> FleetHealthResponse:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=24)).isoformat()

    sessions = await service.repos.sessions.list_all()
    all_events = await service.repos.events.list_all()  # cross-tenant (operator aggregate)
    reconciliations = await service.repos.reconciliation.list_all()
    audits = await service.repos.audit.list_all()
    receipts = await service.repos.receipts.list_all()
    accounts = await service.repos.accounts.list_all()  # provider accounts (poll cursors)

    supervisor = supervisor if supervisor is not None else get_worker_supervisor()
    worker_heartbeat, last_successful_worker_cycle = _fleet_worker_liveness(supervisor, now)

    # Durable-outbox lag: receipts parked at OUTBOX_ENQUEUED with the
    # publication state still "enqueued" are canonical events written to the
    # Bronze + event_outbox spine but not yet published by the supervised relay.
    # A direct-publish deployment never passes through OUTBOX_ENQUEUED, so the
    # count is 0 there — a real zero, not an unknown. None is never returned
    # here because the receipt ledger is always readable; the honest-unknown
    # path is reserved for worker liveness, which depends on an external handle.
    outbox_lag = sum(
        1 for r in receipts
        if r.get("current_stage") == ReceiptStage.OUTBOX_ENQUEUED
        and r.get("outbox_publication_state") == "enqueued"
    )

    # Fleet polling-cursor age per provider, derived from the durable
    # provider-account ledgers (the stalest observed ``last_poll_at``).
    cursor_age_by_provider = _fleet_cursor_age_by_provider(accounts, now)

    observed_by_provider = _observed_tenants_by_provider(
        sessions, all_events, reconciliations, accounts
    )
    observed_tenant_ids = {
        tenant_id
        for tenants in observed_by_provider.values()
        for tenant_id in tenants
    }

    # Authoritative configured-tenant inventory. Credentials alone are not
    # observation evidence, but configured-never-observed tenants must still be
    # represented. When the authority is disabled (local legacy vault) or
    # unreadable, coverage is unknown (None), never a fabricated zero.
    inventory_available = False
    configured_by_provider: dict[str, set[str]] = {}
    try:
        from connectors.integrations.providers.payment_rails.base import (
            _credential_authority_enabled,
        )
        from connectors.providers.credentials.operator_view import (
            collect_payment_rail_configured_tenants,
        )

        if _credential_authority_enabled():
            configured_by_provider = await collect_payment_rail_configured_tenants(ADAPTERS)
            inventory_available = True
    except Exception:  # noqa: BLE001 — coverage becomes unknown, never a fake zero
        configured_by_provider = {}
        inventory_available = False
        metrics.increment("kyber_fleet_credential_inventory_failures")

    configured_by_tenant: dict[str, set[str]] = defaultdict(set)
    for provider, tenant_ids in configured_by_provider.items():
        for tenant_id in tenant_ids:
            configured_by_tenant[tenant_id].add(provider)
    observed_by_tenant: dict[str, set[str]] = defaultdict(set)
    for provider, tenant_ids in observed_by_provider.items():
        for tenant_id in tenant_ids:
            observed_by_tenant[tenant_id].add(provider)

    rejected_by_tenant_provider: dict[tuple[str, str], int] = defaultdict(int)
    verified_by_tenant_provider: dict[tuple[str, str], int] = defaultdict(int)
    conflicts_by_tenant_provider: dict[tuple[str, str], int] = defaultdict(int)
    for audit in audits:
        if (
            audit.get("action") == "webhook_rejected"
            and (audit.get("occurred_at") or "") >= cutoff
            and audit.get("tenant_id")
            and audit.get("provider") in ADAPTERS
        ):
            key = (audit["tenant_id"], audit["provider"])
            rejected_by_tenant_provider[key] += 1
    for event in all_events:
        if (
            (event.get("received_at") or "") >= cutoff
            and event.get("tenant_id")
            and event.get("provider") in ADAPTERS
        ):
            key = (event["tenant_id"], event["provider"])
            verified_by_tenant_provider[key] += 1
    for record in reconciliations:
        if (
            record.get("state") == "conflict"
            and record.get("tenant_id")
            and record.get("provider") in ADAPTERS
        ):
            key = (record["tenant_id"], record["provider"])
            conflicts_by_tenant_provider[key] += 1

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

        p_observed = observed_by_provider.get(name, set())
        p_configured = configured_by_provider.get(name) if inventory_available else None
        configured_count = len(p_configured) if p_configured is not None else None
        observed_count = len(p_observed)
        never_observed = (
            len(p_configured - p_observed) if p_configured is not None else None
        )
        observation_status = _fleet_observation_status(
            p_configured, p_observed, inventory_available=inventory_available
        )
        status = _fleet_health_status(
            enabled=enabled,
            configured_count=configured_count,
            observed_count=observed_count,
            observation_status=observation_status,
            webhook_verified_24h=verified_24h,
            webhook_rejected_24h=rejected_24h,
            conflicts=conflicts,
        )
        if status in ("degraded", "error"):
            degraded_providers += 1

        providers.append(ProviderFleetRow(
            provider=name, status=status, observation_status=observation_status,
            enabled=enabled,
            configured_tenants=configured_count,
            observed_tenants=observed_count,
            never_observed_tenants=never_observed,
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
            polling_cursor_age_seconds=(
                cursor_age_by_provider.get(name)
                if adapter.polling_supported else None
            ),
            provider_probe_status=None,
        ))

    # Per-tenant fleet rows. Configured-never-observed tenants are included even
    # when they have no sessions/events; only observed evidence drives counters.
    tenant_rows: list[TenantFleetRow] = []
    by_tenant: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        if s.get("tenant_id"):
            by_tenant[s["tenant_id"]].append(s)
    all_tenant_ids = set(by_tenant) | set(observed_by_tenant) | set(configured_by_tenant)
    for tenant_id in sorted(all_tenant_ids):
        t_sessions = by_tenant.get(tenant_id, [])
        t_recent = [s for s in t_sessions if (s.get("created_at") or "") >= cutoff]
        t_recons = [r for r in reconciliations if r.get("tenant_id") == tenant_id]
        conflicts = sum(1 for r in t_recons if r.get("state") == "conflict")
        t_observed = observed_by_tenant.get(tenant_id, set())
        t_configured = (
            configured_by_tenant.get(tenant_id, set()) if inventory_available else None
        )
        t_configured_count = len(t_configured) if t_configured is not None else None
        t_never_observed = (
            len(t_configured - t_observed) if t_configured is not None else None
        )
        t_observation_status = _fleet_observation_status(
            t_configured, t_observed, inventory_available=inventory_available
        )
        t_rejected = sum(
            count for (tenant, provider), count in rejected_by_tenant_provider.items()
            if tenant == tenant_id
        )
        t_verified = sum(
            count for (tenant, provider), count in verified_by_tenant_provider.items()
            if tenant == tenant_id
        )
        t_degraded_providers = 0
        for provider in ADAPTERS:
            p_configured = (
                (1 if provider in t_configured else 0)
                if t_configured is not None else None
            )
            p_observed = provider in t_observed
            if not p_observed and p_configured == 0:
                continue
            p_status = _fleet_health_status(
                enabled=provider_enabled(provider),
                configured_count=p_configured,
                observed_count=1 if p_observed else 0,
                observation_status=_fleet_observation_status(
                    {provider} if p_configured else set(),
                    t_observed,
                    inventory_available=inventory_available,
                ),
                webhook_verified_24h=verified_by_tenant_provider.get(
                    (tenant_id, provider), 0
                ),
                webhook_rejected_24h=rejected_by_tenant_provider.get(
                    (tenant_id, provider), 0
                ),
                conflicts=conflicts_by_tenant_provider.get((tenant_id, provider), 0),
            )
            if p_status in ("degraded", "error"):
                t_degraded_providers += 1

        if t_configured_count == 0:
            status = "not_configured"
        elif t_rejected > 0 and t_verified == 0:
            status = "error"
        elif t_observation_status == "never_observed":
            status = "unknown"
        elif (
            conflicts > 0
            or t_rejected > 0
            or t_observation_status == "partially_observed"
        ):
            status = "degraded"
        elif t_observed:
            status = "healthy"
        else:
            status = "unknown"

        tenant_rows.append(TenantFleetRow(
            tenant_id=tenant_id,
            status=status,
            observation_status=t_observation_status,
            providers_configured=t_configured_count,
            providers_observed=len(t_observed),
            providers_never_observed=t_never_observed,
            providers_degraded=t_degraded_providers,
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
    configured_tenant_ids = set(configured_by_tenant)
    enabled_tenant_ids = {
        tenant_id
        for provider, tenant_ids in configured_by_provider.items()
        if provider_enabled(provider)
        for tenant_id in tenant_ids
    } | {
        tenant_id
        for provider, tenant_ids in observed_by_provider.items()
        if provider_enabled(provider)
        for tenant_id in tenant_ids
    }

    totals = FleetTotals(
        configured_tenants=(
            len(configured_tenant_ids) if inventory_available else None
        ),
        observed_tenants=len(observed_tenant_ids),
        configuration_inventory_available=inventory_available,
        enabled_tenants=len(enabled_tenant_ids),
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
        outbox_lag=outbox_lag,
        repair_backlog=sum(1 for r in incomplete if int(r.get("repair_attempts", 0)) > 0),
        dead_lettered=dead_lettered,
        worker_heartbeat=worker_heartbeat,
        last_successful_worker_cycle=last_successful_worker_cycle,
    )

    # Emit operator-surface gauges so a Grafana/Kyber fleet-health dashboard has
    # a metric source, not just a JSON endpoint (unknown liveness stays absent).
    _emit_fleet_gauges(
        totals, providers,
        worker_heartbeat=worker_heartbeat,
        last_successful_worker_cycle=last_successful_worker_cycle,
        now=now,
    )

    return FleetHealthResponse(
        tenants_observed=len(observed_tenant_ids),
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
        from connectors.providers.credentials.authority import credential_authority

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
            from connectors.integrations.providers.payment_rails.webhook_endpoints import (
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
            observation_status=h.observation_status,
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
            # The last connection-probe outcome, derived from the stored poll
            # health: a real classification (`ok` = last poll authenticated and
            # reached the provider; `auth_error`/`rate_limited`/`timeout`/…= the
            # last failure class) is surfaced verbatim. `not_configured`,
            # `webhook_only` and a missing value stay null — an honest "unknown /
            # not applicable", never a fabricated "ok". No probe classification
            # ever carries a secret or provider payload.
            connection_probe_result=(
                poll_health
                if poll_health not in (None, "not_configured", "webhook_only")
                else None
            ),
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
