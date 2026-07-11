"""Payment Rail sync/staleness worker.

Proves the supervised sweep does the three things webhook ingestion cannot do
on a timer: age SDK-only sessions into ``stale``, pull provider truth for open
sessions of configured polling-capable providers, and materialize card-linked
Gold — all tenant-scoped and best-effort.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.integrations.providers.payment_rails import sync_worker  # noqa: E402
from services.integrations.providers.payment_rails.models import (  # noqa: E402
    FundingSession,
    ReconciliationRecord,
)
from services.integrations.providers.payment_rails.reconciliation import (  # noqa: E402
    STALE_AFTER_SECONDS,
)
from services.integrations.providers.payment_rails.service import PaymentRailsService  # noqa: E402

OLD_TS = "2020-01-01T00:00:00+00:00"
NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def _service() -> PaymentRailsService:
    """A payment-rails service backed by fresh, isolated in-memory stores.

    The sync worker sweeps sessions cross-tenant via ``list_all()``, so its
    correctness assertions must not see funding sessions written by other
    suites into the process-global stores. Overriding each repository's
    ``_store`` on the instance the test actually uses is identity-robust:
    unlike patching a module-level ``get_store``, it survives the full suite's
    sys.modules churn (which can otherwise leave the patched module a different
    identity than the one the repositories were built from). The store is
    duck-typed, so a freshly-constructed InMemoryStore drops straight in.
    """
    from shared.store import InMemoryStore
    from services.integrations.providers.payment_rails.repository import (
        PaymentRailsRepositories,
    )

    repos = PaymentRailsRepositories()
    for repo in (
        repos.sessions, repos.events, repos.accounts, repos.deposit_addresses,
        repos.virtual_accounts, repos.reconciliation, repos.audit,
    ):
        repo._store = InMemoryStore(getattr(repo._store, "name", "payment_test"))
    return PaymentRailsService(repositories=repos)


async def _seed_session(
    service: PaymentRailsService,
    tenant_id: str,
    session_id: str,
    *,
    provider: str = "coinbase",
    status: str = "pending",
    reconciliation_state: str = "sdk_only",
    sdk_observed_at: str | None = OLD_TS,
) -> dict:
    metadata: dict = {}
    if sdk_observed_at is not None:
        metadata["sdk_signal"] = {
            "event_id": f"sdk-{session_id}",
            "status": status,
            "observed_at": sdk_observed_at,
        }
    session = FundingSession(
        id=session_id,
        tenant_id=tenant_id,
        provider=provider,  # type: ignore[arg-type]
        flow_type="fiat_onramp",
        rail="coinbase",
        status=status,  # type: ignore[arg-type]
        reconciliation_state=reconciliation_state,  # type: ignore[arg-type]
        idempotency_key=f"{provider}:{session_id}",
        created_at=OLD_TS,
        occurred_at=OLD_TS,
        metadata=metadata,
    )
    return await service.repos.sessions.save(tenant_id, session.model_dump(mode="json"))


async def _seed_reconciliation(
    service: PaymentRailsService,
    tenant_id: str,
    session_id: str,
    *,
    provider: str = "coinbase",
    state: str = "sdk_only",
    last_source: str = "sdk",
) -> None:
    record = ReconciliationRecord(
        tenant_id=tenant_id,
        funding_session_id=session_id,
        provider=provider,  # type: ignore[arg-type]
        state=state,  # type: ignore[arg-type]
        last_source=last_source,
        sdk_event_id=f"sdk-{session_id}",
        first_observed_at=OLD_TS,
    )
    await service.repos.reconciliation.upsert(tenant_id, record.model_dump(mode="json"))


# ── staleness ──────────────────────────────────────────────────────────────


async def test_sdk_only_session_ages_into_stale():
    service = _service()
    await _seed_session(service, "t-stale", "s1")
    await _seed_reconciliation(service, "t-stale", "s1")

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["transitioned"] == 1
    rec = await service.repos.reconciliation.get_for_session("t-stale", "s1")
    assert rec["state"] == "stale"
    session = await service.repos.sessions.get_record("t-stale", "s1")
    assert session["reconciliation_state"] == "stale"


async def test_sdk_only_within_window_stays_sdk_only():
    service = _service()
    recent = (NOW - timedelta(seconds=STALE_AFTER_SECONDS // 2)).isoformat()
    await _seed_session(service, "t-fresh", "s1", sdk_observed_at=recent)
    await _seed_reconciliation(service, "t-fresh", "s1")

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["transitioned"] == 0
    rec = await service.repos.reconciliation.get_for_session("t-fresh", "s1")
    assert rec["state"] == "sdk_only"


async def test_final_sessions_are_not_scanned():
    service = _service()
    await _seed_session(service, "t-final", "open1", status="pending")
    await _seed_session(service, "t-final", "done1", status="completed",
                        reconciliation_state="matched")

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["open_sessions"] == 1


async def test_provider_confirmed_session_is_idempotent():
    """A session with provider truth must not be spuriously aged into stale."""
    service = _service()
    await _seed_session(service, "t-prov", "s1", reconciliation_state="provider_only",
                        sdk_observed_at=None)
    await _seed_reconciliation(service, "t-prov", "s1", state="provider_only",
                               last_source="webhook")

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["transitioned"] == 0
    rec = await service.repos.reconciliation.get_for_session("t-prov", "s1")
    assert rec["state"] == "provider_only"


async def test_session_without_reconciliation_record_is_left_alone():
    service = _service()
    await _seed_session(service, "t-none", "s1")  # no reconciliation record seeded

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["transitioned"] == 0
    assert await service.repos.reconciliation.get_for_session("t-none", "s1") is None


# ── provider-truth pull ──────────────────────────────────────────────────────


async def test_provider_truth_pulled_for_enabled_polling_provider(monkeypatch):
    service = _service()
    await _seed_session(service, "t-pull", "s1", provider="coinbase")

    calls: list[tuple[str, str]] = []

    async def _fake_status_sync(tenant_id, provider, *, records=None):
        calls.append((tenant_id, provider))
        return {"synced": True, "events": []}

    monkeypatch.setattr(sync_worker, "provider_enabled", lambda p: True)
    monkeypatch.setattr(service, "status_sync", _fake_status_sync)

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert ("t-pull", "coinbase") in calls
    assert stats["provider_pulls"] == 1


async def test_webhook_only_provider_is_not_polled(monkeypatch):
    service = _service()
    await _seed_session(service, "t-privy", "s1", provider="privy")

    calls: list[tuple[str, str]] = []

    async def _fake_status_sync(tenant_id, provider, *, records=None):
        calls.append((tenant_id, provider))
        return {"synced": True, "events": []}

    monkeypatch.setattr(sync_worker, "provider_enabled", lambda p: True)
    monkeypatch.setattr(service, "status_sync", _fake_status_sync)

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert calls == []  # privy is polling_supported=False
    assert stats["provider_pulls"] == 0


async def test_disabled_provider_is_not_polled(monkeypatch):
    service = _service()
    await _seed_session(service, "t-off", "s1", provider="coinbase")

    async def _fake_status_sync(tenant_id, provider, *, records=None):
        raise AssertionError("status_sync must not be called for a disabled provider")

    monkeypatch.setattr(sync_worker, "provider_enabled", lambda p: False)
    monkeypatch.setattr(service, "status_sync", _fake_status_sync)

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["provider_pulls"] == 0


async def test_provider_pull_failure_does_not_abort_cycle(monkeypatch):
    """One provider raising must not stop staleness handling for the tenant."""
    service = _service()
    await _seed_session(service, "t-resil", "s1", provider="coinbase")
    await _seed_reconciliation(service, "t-resil", "s1")

    async def _boom(tenant_id, provider, *, records=None):
        raise RuntimeError("provider API down")

    monkeypatch.setattr(sync_worker, "provider_enabled", lambda p: True)
    monkeypatch.setattr(service, "status_sync", _boom)

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    # Cycle completed; staleness still applied despite the provider failure.
    assert stats["transitioned"] == 1
    rec = await service.repos.reconciliation.get_for_session("t-resil", "s1")
    assert rec["state"] == "stale"


# ── card-linked gold ─────────────────────────────────────────────────────────


async def test_card_linked_gold_materialized_when_enabled(monkeypatch, request):
    service = _service()
    await _seed_session(service, "t-gold", "s1")

    from config.settings import settings

    cfg = settings.card_linked_payment_rails
    original = cfg.enabled
    object.__setattr__(cfg, "enabled", True)
    request.addfinalizer(lambda: object.__setattr__(cfg, "enabled", original))

    materialized: list[str] = []

    async def _fake_materialize(tenant_id):
        materialized.append(tenant_id)
        return {"cluster_feature_rows": 0}

    monkeypatch.setattr(
        "services.card_linked_payments.gold.materialize_gold", _fake_materialize
    )

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert materialized == ["t-gold"]
    assert stats["gold_tenants"] == 1


async def test_card_linked_gold_skipped_when_disabled(monkeypatch):
    service = _service()
    await _seed_session(service, "t-nogold", "s1")

    async def _fake_materialize(tenant_id):
        raise AssertionError("gold must not materialize when the flag is off")

    monkeypatch.setattr(
        "services.card_linked_payments.gold.materialize_gold", _fake_materialize
    )

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["gold_tenants"] == 0


# ── tenant scoping ───────────────────────────────────────────────────────────


async def test_cycle_is_tenant_scoped():
    service = _service()
    await _seed_session(service, "tenant-a", "sa")
    await _seed_reconciliation(service, "tenant-a", "sa")
    await _seed_session(service, "tenant-b", "sb")
    await _seed_reconciliation(service, "tenant-b", "sb")

    stats = await sync_worker.run_sync_cycle(service=service, now=NOW)

    assert stats["tenants"] == 2
    assert stats["transitioned"] == 2
    a = await service.repos.reconciliation.get_for_session("tenant-a", "sa")
    b = await service.repos.reconciliation.get_for_session("tenant-b", "sb")
    assert a["state"] == "stale" and b["state"] == "stale"
    # No cross-tenant bleed: tenant-a cannot see tenant-b's session.
    assert await service.repos.sessions.get_record("tenant-a", "sb") is None
