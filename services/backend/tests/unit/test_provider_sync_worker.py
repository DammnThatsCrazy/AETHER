"""WS5 — scheduled provider sync worker tests.

Covers due-connection selection (syncable state + credential ref + staleness),
the per-connection sweep through the scheduler (``trigger="system"`` surface),
and the zero-records honesty contract: a run that raises
``ProviderPullFailed`` is a counted failure, never a silent empty success.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from services.provider_runtime.errors import ProviderPullFailed
from services.provider_runtime.sync_worker import ProviderSyncRunner

_SYNCABLE_STATES = frozenset(
    {
        "available",
        "credentials_received",
        "verifying",
        "verified",
        "account_selection_required",
        "configuration_required",
        "initial_sync_pending",
        "connected",
    }
)


def _row(
    connection_id: str,
    tenant_id: str,
    provider_identity: str,
    *,
    state: str = "verified",
    credential_ref: str = "",
    last_successful_sync_at: str | None = None,
) -> dict:
    # No repo-injected ``id`` key: ProviderConnection is extra="forbid", and the
    # worker's _connection_from_row accepts rows with or without it.
    return {
        "connection_id": connection_id,
        "tenant_id": tenant_id,
        "provider_identity": provider_identity,
        "display_name": provider_identity,
        "state": state,
        "credential_ref": credential_ref,
        "config": {},
        "created_at": "2026-08-01T00:00:00+00:00",
        "updated_at": "2026-08-01T00:00:00+00:00",
        "last_successful_sync_at": last_successful_sync_at,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


class FakeConnections:
    """Shape-agnostic repo seam returning dict rows (what the worker scans)."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def find_many(self, filters=None, limit=10000):
        return list(self.rows[:limit])


class FakeScheduler:
    """Records every run_sync invocation and its trigger surface."""

    def __init__(self, *, outcome: str = "ok") -> None:
        self.calls: list[tuple] = []
        self.outcome = outcome

    async def run_sync(self, connection, *, since=None):
        self.calls.append((connection.connection_id, since))
        if self.outcome == "fail":
            raise ProviderPullFailed(
                f"provider pull failed for {connection.provider_identity}"
            )
        if self.outcome == "raise":
            raise RuntimeError("unexpected scheduler crash")
        return {"connection_id": connection.connection_id, "records_received": 0}


# ── is_due selection ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "state,expect_due",
    [
        (state, True) for state in sorted(_SYNCABLE_STATES)
    ]
    + [(state, False) for state in ("disabled", "failed", "deprecated", "revoked")],
)
def test_is_due_state_gating(state: str, expect_due: bool) -> None:
    from services.provider_runtime.connection import ProviderConnection

    connection = ProviderConnection.model_validate(
        _row(
            "c1",
            "t1",
            "shopify.admin.orders_read",
            state=state,
            credential_ref="provider:t1:shopify.admin.orders_read",
        )
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is expect_due


def test_is_due_requires_credential_ref() -> None:
    from services.provider_runtime.connection import ProviderConnection

    connection = ProviderConnection.model_validate(
        _row("c1", "t1", "shopify.admin.orders_read", credential_ref="")
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is False


def test_is_due_never_synced_is_due() -> None:
    from services.provider_runtime.connection import ProviderConnection

    connection = ProviderConnection.model_validate(
        _row(
            "c1",
            "t1",
            "shopify.admin.orders_read",
            credential_ref="provider:t1:shopify.admin.orders_read",
        )
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is True


def test_is_due_fresh_sync_not_due() -> None:
    from services.provider_runtime.connection import ProviderConnection

    fresh = _iso(datetime.now(timezone.utc))
    connection = ProviderConnection.model_validate(
        _row(
            "c1",
            "t1",
            "shopify.admin.orders_read",
            credential_ref="provider:t1:shopify.admin.orders_read",
            last_successful_sync_at=fresh,
        )
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is False


def test_is_due_stale_sync_is_due() -> None:
    from services.provider_runtime.connection import ProviderConnection

    stale = _iso(datetime.now(timezone.utc) - timedelta(seconds=3600))
    connection = ProviderConnection.model_validate(
        _row(
            "c1",
            "t1",
            "shopify.admin.orders_read",
            credential_ref="provider:t1:shopify.admin.orders_read",
            last_successful_sync_at=stale,
        )
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is True


def test_is_due_unparseable_last_sync_treated_as_never_synced() -> None:
    from services.provider_runtime.connection import ProviderConnection

    connection = ProviderConnection.model_validate(
        _row(
            "c1",
            "t1",
            "shopify.admin.orders_read",
            credential_ref="provider:t1:shopify.admin.orders_read",
            last_successful_sync_at="not-a-timestamp",
        )
    )
    runner = ProviderSyncRunner(interval_seconds=300)
    assert runner.is_due(connection) is True


# ── run_pass sweep ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_pass_schedules_due_connections_with_system_trigger() -> None:
    due = _row(
        "due",
        "t1",
        "shopify.admin.orders_read",
        credential_ref="provider:t1:shopify.admin.orders_read",
    )
    not_due = _row(
        "fresh",
        "t1",
        "shopify.admin.orders_read",
        credential_ref="provider:t1:shopify.admin.orders_read",
        last_successful_sync_at=_iso(datetime.now(timezone.utc)),
    )
    runner = ProviderSyncRunner(
        interval_seconds=300,
        connections=FakeConnections([due, not_due]),
        scheduler=FakeScheduler(),
    )
    summary = await runner.run_pass()
    assert summary["scanned"] == 2
    assert summary["due"] == 1
    assert summary["completed"] == 1
    assert summary["failed"] == 0
    assert summary["skipped"] == 0
    # The scheduler was driven as the durable SyncRun ledger's system trigger.
    assert runner.scheduler.calls == [("due", None)]


@pytest.mark.asyncio
async def test_run_pass_counts_scheduler_failure_not_silent_success() -> None:
    due = _row(
        "failing",
        "t1",
        "shopify.admin.orders_read",
        credential_ref="provider:t1:shopify.admin.orders_read",
    )
    runner = ProviderSyncRunner(
        interval_seconds=300,
        connections=FakeConnections([due]),
        scheduler=FakeScheduler(outcome="fail"),
    )
    summary = await runner.run_pass()
    # ProviderPullFailed is a counted failure — never a zero-record "success".
    assert summary["due"] == 1
    assert summary["completed"] == 0
    assert summary["failed"] == 1


@pytest.mark.asyncio
async def test_run_pass_defensive_exception_counts_failure() -> None:
    due = _row(
        "crash",
        "t1",
        "shopify.admin.orders_read",
        credential_ref="provider:t1:shopify.admin.orders_read",
    )
    runner = ProviderSyncRunner(
        interval_seconds=300,
        connections=FakeConnections([due]),
        scheduler=FakeScheduler(outcome="raise"),
    )
    summary = await runner.run_pass()
    assert summary["completed"] == 0
    assert summary["failed"] == 1


@pytest.mark.asyncio
async def test_run_pass_skips_unparseable_rows_honestly() -> None:
    malformed = {"id": "broken", "connection_id": "broken", "tenant_id": "t1"}
    runner = ProviderSyncRunner(
        interval_seconds=300,
        connections=FakeConnections([malformed]),
        scheduler=FakeScheduler(),
    )
    summary = await runner.run_pass()
    assert summary["scanned"] == 1
    assert summary["skipped"] == 1
    assert summary["due"] == 0
    assert summary["completed"] == 0
    assert summary["failed"] == 0


@pytest.mark.asyncio
async def test_run_pass_zero_records_is_success_when_provider_returned_none() -> None:
    """The scheduler's contract: a healthy empty batch completes with
    records_received=0; the worker treats a completed run as success."""
    due = _row(
        "empty",
        "t1",
        "shopify.admin.orders_read",
        credential_ref="provider:t1:shopify.admin.orders_read",
    )

    class EmptyBatchScheduler(FakeScheduler):
        async def run_sync(self, connection, *, since=None):
            self.calls.append((connection.connection_id, since))
            return {
                "connection_id": connection.connection_id,
                "records_received": 0,
                "triggered_by": "system",
            }

    runner = ProviderSyncRunner(
        interval_seconds=300,
        connections=FakeConnections([due]),
        scheduler=EmptyBatchScheduler(),
    )
    summary = await runner.run_pass()
    assert summary["completed"] == 1
    assert summary["failed"] == 0


# ── sweep gating (flags re-read every pass) ─────────────────────────────────


class _Settings:
    """Fake config.settings mirroring the REAL ProviderRuntimeConfig field names
    (provider_sync_scheduler_enabled / provider_sync_interval_seconds) — the
    worker reads these exact names, so a fake using the old names would validate
    the broken contract (WS5-3)."""

    def __init__(self, enabled: bool, interval_seconds: int = 300) -> None:
        self.provider_runtime = type(
            "Cfg",
            (),
            {
                "provider_sync_scheduler_enabled": enabled,
                "provider_sync_interval_seconds": interval_seconds,
            },
        )()


@pytest.mark.asyncio
async def test_sweep_once_is_noop_when_scheduler_disabled(monkeypatch) -> None:
    from services.provider_runtime import sync_worker

    constructed: list = []

    class _Runner(ProviderSyncRunner):
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(sync_worker, "ProviderSyncRunner", _Runner)
    await sync_worker._sweep_once(_Settings(enabled=False))
    assert constructed == []


@pytest.mark.asyncio
async def test_sweep_once_enabled_constructs_runner_with_configured_interval(
    monkeypatch,
) -> None:
    """The enabled path must drive the sweep through a ProviderSyncRunner built
    with the REAL configured interval (WS5-3): the scheduler flag actually
    runs, and the cadence wiring reaches the runner."""
    from services.provider_runtime import sync_worker

    constructed: list = []
    calls: list = []

    class _Runner:
        def __init__(self, **kwargs) -> None:
            constructed.append(kwargs)

        async def run_pass(self):
            calls.append(1)
            return {"scanned": 0, "due": 0, "completed": 0, "failed": 0, "skipped": 0}

    monkeypatch.setattr(sync_worker, "ProviderSyncRunner", _Runner)
    await sync_worker._sweep_once(_Settings(enabled=True, interval_seconds=120))
    # Flag True → a sweep pass ran, and the runner was constructed with the
    # configured interval (not the default and not a stale field name).
    assert calls == [1]
    assert constructed == [{"interval_seconds": 120}]


# ── loop cadence (C-7: interval re-read every pass, no frozen config) ───────


@pytest.mark.asyncio
async def test_run_loop_rereads_interval_each_pass(monkeypatch) -> None:
    """The interval is read INSIDE the loop so a runtime change to
    provider_sync_interval_seconds takes effect on the next pass without a
    restart. Here the interval is changed mid-loop and the next sleep uses the
    new cadence."""
    import config.settings as settings_module

    from services.provider_runtime import sync_worker

    class _MutableCfg:
        provider_sync_scheduler_enabled = True
        provider_sync_interval_seconds = 60

    fake_settings = type("Settings", (), {"provider_runtime": _MutableCfg()})()
    monkeypatch.setattr(settings_module, "settings", fake_settings)

    sleeps: list[int] = []
    passes = 0

    async def fake_sweep(settings) -> None:
        nonlocal passes
        passes += 1
        if passes == 1:
            fake_settings.provider_runtime.provider_sync_interval_seconds = 90

    class _StopLoop(Exception):
        pass

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(int(seconds))
        if len(sleeps) >= 2:
            raise _StopLoop()

    monkeypatch.setattr(sync_worker, "_sweep_once", fake_sweep)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    with pytest.raises(_StopLoop):
        await sync_worker.run_provider_sync_loop()
    assert sleeps == [60, 90]
