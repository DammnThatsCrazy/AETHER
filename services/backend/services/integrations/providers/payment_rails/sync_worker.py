"""Payment Rail Observability — supervised sync / staleness worker.

Webhook ingestion advances a funding session whenever a provider pushes an
event, but two open sessions would otherwise never resolve on their own:

- a session whose provider never sends a terminal webhook (stuck ``pending`` /
  ``submitted``) — only a provider-truth *pull* can advance it; and
- an SDK-only session no provider ever confirms — it must age into ``stale``
  once the reconciliation window passes.

Webhook handling never runs on a timer, so neither transition fires without a
periodic sweep. This supervised worker closes that gap. Each cycle it:

1. Pulls provider truth for the open sessions of every configured,
   polling-capable provider via :meth:`PaymentRailsService.status_sync`.
   This is offline-safe by construction: an unconfigured tenant, a local
   process, or a provider without a live polling endpoint performs no network
   IO (the base adapter returns no records) — the pull is a no-op, never a
   fabricated success.
2. Re-runs reconciliation for every still-open session. This is the *only*
   place the ``sdk_only → stale`` transition is produced; provider-driven
   reconciliation (which always has a provider view) can never yield it.
3. Materializes card-linked Gold rollups per tenant when the card-linked flag
   is enabled — the periodic hook the card-linked plane was missing.

Everything is best-effort and tenant-scoped: a failure for one tenant or
provider is logged and metered, never aborting the cycle or leaking across
tenants. Aether observes; this worker never executes, settles, or custodies.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import AetherError
from shared.logger.logger import get_logger, metrics

from services.integrations.providers.payment_rails import get_adapter
from services.integrations.providers.payment_rails.models import FINAL_STATUSES
from services.integrations.providers.payment_rails.reconciliation import reconcile_session
from services.integrations.providers.payment_rails.service import (
    PaymentRailsService,
    get_payment_rails_service,
    provider_enabled,
)

logger = get_logger("aether.payment_rails.sync_worker")

# Default cadence for the supervised loop. Sessions age into ``stale`` over a
# 24h window (reconciliation.STALE_AFTER_SECONDS), so a few sweeps per hour is
# ample; a shorter interval only adds provider-poll pressure with no benefit.
# Environment-tunable so ops can tighten/loosen the cadence per deployment.
PAYMENT_RAIL_SYNC_INTERVAL_SECONDS = int(
    os.getenv("AETHER_PAYMENT_SYNC_INTERVAL_SECONDS", str(15 * 60))
)


def _open_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sessions still eligible for provider truth / staleness (non-final)."""
    return [s for s in sessions if s.get("status") not in FINAL_STATUSES]


async def _pull_provider_truth(
    service: PaymentRailsService, tenant_id: str, provider: str
) -> Optional[int]:
    """Best-effort provider-truth pull for one (tenant, provider).

    Returns the number of provider events processed, or ``None`` when the pull
    was skipped/failed. Never raises — a provider-side problem must not stop
    the sweep for other providers or tenants.
    """
    try:
        adapter = get_adapter(provider)
    except AetherError:
        return None
    if not adapter.polling_supported:
        # Privy / Stripe onramp are webhook-only — nothing to poll.
        return None
    try:
        result = await service.status_sync(tenant_id, provider)
    except AetherError as exc:
        # Disabled provider / bad request — expected, quiet skip.
        logger.debug(
            "payment_rail_sync provider pull skipped tenant=%s provider=%s: %s",
            tenant_id, provider, exc,
        )
        return None
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "payment_rail_sync provider pull failed tenant=%s provider=%s: %s",
            tenant_id, provider, exc,
        )
        metrics.increment("payment_rail_sync_error_total",
                          labels={"stage": "provider_pull", "provider": provider})
        return None
    events = result.get("events", []) if isinstance(result, dict) else []
    metrics.increment("payment_rail_sync_provider_pulled_total",
                      labels={"provider": provider})
    return len(events)


async def _reevaluate_staleness(
    service: PaymentRailsService,
    tenant_id: str,
    session_id: str,
    *,
    now: datetime,
) -> Optional[str]:
    """Re-run reconciliation for one open session; persist + return the new
    state only when it changed.

    Reuses the stored reconciliation record's ``last_source`` so the view
    selection is identical to the record's origin: an SDK-only record
    (``last_source == 'sdk'``, no provider view) is what ages into ``stale``,
    while a provider-confirmed record (``webhook`` / ``polling``) re-evaluates
    idempotently. Sessions never reconciled are left alone — there is no
    prior state to transition.
    """
    session = await service.repos.sessions.get_record(tenant_id, session_id)
    if session is None or session.get("status") in FINAL_STATUSES:
        return None
    existing = await service.repos.reconciliation.get_for_session(tenant_id, session_id)
    if existing is None:
        return None

    record = reconcile_session(
        session,
        last_source=existing.get("last_source", "polling"),
        sdk_event_id=existing.get("sdk_event_id"),
        provider_event_id=existing.get("provider_event_id"),
        now=now,
    )
    if record.state == existing.get("state"):
        return None

    await service.repos.reconciliation.upsert(tenant_id, record.model_dump(mode="json"))
    if session.get("reconciliation_state") != record.state:
        session["reconciliation_state"] = record.state
        await service.repos.sessions.save(tenant_id, session)
    metrics.increment("payment_rail_sync_transitioned_total",
                      labels={"state": record.state})
    return record.state


async def _materialize_card_linked_gold(tenant_id: str) -> bool:
    """Best-effort card-linked Gold rollup for one tenant. Never raises."""
    try:
        from services.card_linked_payments.gold import materialize_gold

        await materialize_gold(tenant_id)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "payment_rail_sync card-linked gold materialization failed tenant=%s: %s",
            tenant_id, exc,
        )
        metrics.increment("payment_rail_sync_error_total", labels={"stage": "card_linked_gold"})
        return False
    metrics.increment("card_linked_gold_materialized_total")
    return True


async def run_sync_cycle(
    *,
    service: Optional[PaymentRailsService] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Run one sweep over all open funding sessions across tenants.

    Cross-tenant enumeration is a control-plane sweep (never surfaced to a
    tenant); every read/write below is re-scoped to the owning tenant.
    Returns per-cycle counters for logging/tests.
    """
    from config.settings import settings

    service = service or get_payment_rails_service()
    now = now or datetime.now(timezone.utc)
    card_linked_enabled = bool(settings.card_linked_payment_rails.enabled)

    all_sessions = await service.repos.sessions.list_all()
    open_sessions = _open_sessions(all_sessions)

    by_tenant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for session in open_sessions:
        tenant_id = session.get("tenant_id")
        if tenant_id:
            by_tenant[tenant_id].append(session)

    stats = {
        "tenants": 0,
        "open_sessions": len(open_sessions),
        "provider_pulls": 0,
        "transitioned": 0,
        "gold_tenants": 0,
    }

    for tenant_id, sessions in by_tenant.items():
        stats["tenants"] += 1

        # 1. Pull provider truth once per distinct enabled, polling-capable
        #    provider present among this tenant's open sessions.
        providers = sorted({s.get("provider") for s in sessions if s.get("provider")})
        for provider in providers:
            if not provider_enabled(provider):
                continue
            pulled = await _pull_provider_truth(service, tenant_id, provider)
            if pulled is not None:
                stats["provider_pulls"] += 1

        # 2. Re-evaluate staleness per open session (re-reading each, since a
        #    provider pull above may have already advanced it to terminal).
        for session in sessions:
            new_state = await _reevaluate_staleness(
                service, tenant_id, session["id"], now=now,
            )
            if new_state:
                stats["transitioned"] += 1

        # 3. Card-linked Gold rollups (flag-gated) — the periodic hook the
        #    card-linked plane otherwise lacked.
        if card_linked_enabled:
            if await _materialize_card_linked_gold(tenant_id):
                stats["gold_tenants"] += 1

    metrics.increment("payment_rail_sync_cycle_total")
    metrics.increment("payment_rail_sync_session_scanned_total",
                      value=len(open_sessions))
    logger.info(
        "payment_rail_sync cycle complete tenants=%d open_sessions=%d "
        "provider_pulls=%d transitioned=%d gold_tenants=%d",
        stats["tenants"], stats["open_sessions"], stats["provider_pulls"],
        stats["transitioned"], stats["gold_tenants"],
    )
    return stats


async def run_payment_rail_sync_loop(
    interval_seconds: int = PAYMENT_RAIL_SYNC_INTERVAL_SECONDS,
) -> None:
    """Supervised periodic sweep — provider-truth pull + staleness + gold."""
    while True:
        try:
            await run_sync_cycle()
        except Exception as exc:  # pragma: no cover — defensive; supervisor also guards
            logger.warning("payment_rail_sync cycle failed: %s", exc)
            metrics.increment("payment_rail_sync_error_total", labels={"stage": "cycle"})
        await asyncio.sleep(interval_seconds)


def build_payment_rail_sync_coro():
    """Fresh coroutine for the WorkerSupervisor (one per (re)start)."""
    return run_payment_rail_sync_loop()
