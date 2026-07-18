"""Duplicate-webhook storm + supervised-worker restart idempotency.

Two real recovery invariants, credentialless:

  * duplicate webhook storm -> the REAL x402 payment-identifier idempotency store
    (``services.x402.idempotency``) collapses N duplicate deliveries of the same
    (tenant, payment_identifier) to a single applied effect.
  * worker restart          -> the REAL payment-rails supervised sync worker
    (``services.integrations.providers.payment_rails.sync_worker``) is
    re-runnable: a second cycle (a "restart") does not re-transition sessions it
    already aged, i.e. the sweep is idempotent across restarts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.x402.idempotency import get_idempotency_store

from services.integrations.providers.payment_rails import sync_worker
from services.integrations.providers.payment_rails.models import (
    FundingSession,
    ReconciliationRecord,
)
from services.integrations.providers.payment_rails.service import PaymentRailsService

OLD_TS = "2020-01-01T00:00:00+00:00"
NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


# ── duplicate webhook storm ───────────────────────────────────────────────────
async def test_duplicate_webhook_storm_applies_effect_once(tenant):
    """50 duplicate deliveries of one webhook id apply the effect exactly once."""
    store = get_idempotency_store()
    applied: list[str] = []

    async def process_webhook(payment_id: str, payload: dict) -> str:
        # Idempotent handler: replay returns the recorded result, no re-apply.
        prior = await store.lookup(tenant, payment_id)
        if prior is not None:
            return "duplicate"
        applied.append(payment_id)
        await store.record(tenant, payment_id, {"status": "processed", "payload": payload})
        return "applied"

    outcomes = [await process_webhook("evt-abc", {"amount": "10.00"}) for _ in range(50)]

    assert outcomes[0] == "applied"
    assert set(outcomes[1:]) == {"duplicate"}
    assert applied == ["evt-abc"]  # effect applied exactly once


async def test_idempotency_is_tenant_scoped(tenant):
    """The same webhook id under two tenants is two distinct effects (no bleed)."""
    store = get_idempotency_store()
    other = f"{tenant}-other"
    await store.record(tenant, "evt-shared", {"status": "processed"})
    assert await store.lookup(tenant, "evt-shared") is not None
    assert await store.lookup(other, "evt-shared") is None


# ── supervised-worker restart ─────────────────────────────────────────────────
def _service() -> PaymentRailsService:
    from shared.store import InMemoryStore
    from services.integrations.providers.payment_rails.repository import (
        PaymentRailsRepositories,
    )

    repos = PaymentRailsRepositories()
    for repo in (
        repos.sessions, repos.events, repos.accounts, repos.deposit_addresses,
        repos.virtual_accounts, repos.reconciliation, repos.audit,
    ):
        repo._store = InMemoryStore(getattr(repo._store, "name", "payment_chaos"))
    return PaymentRailsService(repositories=repos)


async def _seed_stale_session(service: PaymentRailsService, tenant_id: str, session_id: str) -> None:
    session = FundingSession(
        id=session_id,
        tenant_id=tenant_id,
        provider="coinbase",  # type: ignore[arg-type]
        flow_type="fiat_onramp",
        rail="coinbase",
        status="pending",  # type: ignore[arg-type]
        reconciliation_state="sdk_only",  # type: ignore[arg-type]
        idempotency_key=f"coinbase:{session_id}",
        created_at=OLD_TS,
        occurred_at=OLD_TS,
        metadata={"sdk_signal": {"event_id": f"sdk-{session_id}", "status": "pending", "observed_at": OLD_TS}},
    )
    await service.repos.sessions.save(tenant_id, session.model_dump(mode="json"))
    record = ReconciliationRecord(
        tenant_id=tenant_id,
        funding_session_id=session_id,
        provider="coinbase",  # type: ignore[arg-type]
        state="sdk_only",  # type: ignore[arg-type]
        last_source="sdk",
        sdk_event_id=f"sdk-{session_id}",
        first_observed_at=OLD_TS,
    )
    await service.repos.reconciliation.upsert(tenant_id, record.model_dump(mode="json"))


async def test_worker_restart_is_idempotent_across_cycles(tenant):
    """First cycle ages the SDK-only session into 'stale'; a second cycle
    (a worker restart) does not re-transition it — the sweep is idempotent."""
    service = _service()
    await _seed_stale_session(service, tenant, "s1")

    first = await sync_worker.run_sync_cycle(service=service, now=NOW)
    assert first["transitioned"] == 1
    rec = await service.repos.reconciliation.get_for_session(tenant, "s1")
    assert rec["state"] == "stale"

    # "Restart": run the cycle again. Already-stale sessions are not re-aged.
    second = await sync_worker.run_sync_cycle(service=service, now=NOW)
    assert second["transitioned"] == 0
    rec2 = await service.repos.reconciliation.get_for_session(tenant, "s1")
    assert rec2["state"] == "stale"


async def test_worker_restart_survives_provider_pull_failure(tenant, monkeypatch):
    """A provider raising mid-cycle must not abort staleness handling — the
    supervised worker keeps the tenant converging on restart."""
    service = _service()
    await _seed_stale_session(service, tenant, "s1")

    async def _boom(tenant_id, provider, *, records=None):
        raise RuntimeError("provider API down")

    monkeypatch.setattr(sync_worker, "provider_enabled", lambda p: True)
    monkeypatch.setattr(service, "status_sync", _boom)

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)
    assert stats["transitioned"] == 1  # staleness still applied despite the failure
    rec = await service.repos.reconciliation.get_for_session(tenant, "s1")
    assert rec["state"] == "stale"
