"""WS5 — scheduled sync worker for the Universal Provider Runtime.

Supervised loop that, on each interval, runs the due-provider-connection sweep
through the existing :class:`~services.provider_runtime.scheduler.PullScheduler`
(``run_sync(connection, since=None)``), which opens a durable
:class:`~services.comms.sync_runs.SyncRun` ledger with ``triggered_by="system"``,
reuses :class:`~services.provider_runtime.scheduler.ProviderCursorRepository`,
and meters each completed/failed run.

The worker mirrors :mod:`services.storage_lifecycle.worker`:

  1. flags are re-read from ``config.settings`` every pass (no frozen config),
  2. one failing connection never takes the sweep down (per-connection errors
     are recorded and the loop continues),
  3. a ``ProviderPullFailed`` (the scheduler's typed failure) is NEVER converted
     into a silent empty success — zero records is a SUCCESS only when the
     provider actually returned none, which the scheduler itself guarantees by
     completing the run with ``records_received=0`` only on a healthy empty
     batch.

Flags (owned by Team D's ``ProviderRuntimeConfig``; read defensively so this
module works even before they land):

* ``AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED`` -> ``provider_sync_scheduler_enabled``
* interval -> ``provider_sync_interval_seconds`` (seconds)

Both default OFF/unset — a disabled scheduler is a no-op pass, never an error.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from shared.temporal import try_parse_instant

logger = get_logger("aether.provider_runtime.sync_worker")

#: Default interval when the config field is absent (Team D not landed yet).
_DEFAULT_INTERVAL_S = 300

#: Lifecycle states a connection may be in and still be worth a scheduled sync.
#: A connection that is disabled, deprecated, unsupported, or failed is never
#: auto-synced — a scheduled sync must not resurrect a terminal/blocked state.
_SYNCABLE_STATES: frozenset[str] = frozenset(
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


def _config_value(settings: Any, name: str, default: Any) -> Any:
    """Read one Team-D-owned field defensively (defaults before the field lands)."""
    cfg = getattr(settings, "provider_runtime", None)
    if cfg is None:
        return default
    return getattr(cfg, name, default)


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 exact instant; None when unparseable or naive.

    Delegates to the temporal kernel (``shared.temporal``) — aware values
    normalize to UTC; timezone-naive values are rejected rather than given an
    assumed offset (temporal-integrity policy). A naive stored timestamp
    therefore surfaces as never-synced in ``is_due``, which is the documented
    fail-open scheduling for an unparseable value.
    """
    instant, _reason = try_parse_instant(value)
    return instant


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProviderSyncRunner:
    """One sweep pass: list connections, select due ones, run each through the
    scheduler. Mirrors the storage-lifecycle worker's per-item isolation."""

    def __init__(
        self,
        *,
        interval_seconds: int = _DEFAULT_INTERVAL_S,
        connections: Any = None,
        scheduler: Any = None,
    ) -> None:
        self.interval_seconds = max(1, int(interval_seconds))
        self.connections = connections
        self.scheduler = scheduler

    # ── Lazy seam defaults (constructor-injected in tests) ──────────────────

    def _connections(self) -> Any:
        if self.connections is None:
            from services.provider_runtime.connection import (
                ProviderConnectionRepository,
            )

            self.connections = ProviderConnectionRepository()
        return self.connections

    def _scheduler(self) -> Any:
        if self.scheduler is None:
            from services.provider_runtime.scheduler import PullScheduler

            self.scheduler = PullScheduler()
        return self.scheduler

    # ── Due-connection selection ─────────────────────────────────────────────

    def is_due(self, connection: Any) -> bool:
        """True when a connection should be scheduled for a system-triggered sync.

        Due iff the connection is in a syncable state, holds a credential ref,
        and either never synced successfully or last synced more than
        ``interval_seconds`` ago. An unparseable ``last_successful_sync_at`` is
        treated as never-synced (scheduling is fail-open to give the connection
        a chance; the sync itself remains fail-closed on provider errors).
        """
        state = getattr(connection, "state", None)
        if hasattr(state, "value"):
            state = state.value
        if str(state) not in _SYNCABLE_STATES:
            return False
        if not getattr(connection, "credential_ref", ""):
            return False
        last_sync = getattr(connection, "last_successful_sync_at", None)
        if not last_sync:
            return True
        last_sync_dt = _parse_iso(last_sync)
        if last_sync_dt is None:
            return True
        return (_now() - last_sync_dt).total_seconds() >= self.interval_seconds

    # ── Sweep ───────────────────────────────────────────────────────────────

    async def run_pass(self) -> dict[str, Any]:
        """Run one due-connection sweep; returns an honest pass summary.

        Per-connection: the scheduler's ``run_sync`` is awaited directly. A
        typed ``ProviderPullFailed`` (or any scheduler exception) is caught and
        counted as a failure for that connection — it is NEVER a silent empty
        success. The sweep always completes so one bad provider cannot block the
        rest.
        """
        summary: dict[str, Any] = {
            "scanned": 0,
            "due": 0,
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        }
        try:
            rows = await self._connections().find_many(filters={}, limit=10000)
        except Exception as exc:  # pragma: no cover - best-effort sweep
            logger.warning(f"provider sync scheduler scan failed: {exc}")
            metrics.increment("provider_sync_scheduler_scan_error_total")
            return summary

        due: list[Any] = []
        for row in rows:
            summary["scanned"] += 1
            connection = _connection_from_row(row)
            if connection is None:
                summary["skipped"] += 1
                continue
            if self.is_due(connection):
                due.append(connection)
        summary["due"] = len(due)

        for connection in due:
            try:
                await self._scheduler().run_sync(connection, since=None)
                summary["completed"] += 1
                metrics.increment("provider_sync_scheduler_success_total")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # typed ProviderPullFailed and defensive
                summary["failed"] += 1
                metrics.increment("provider_sync_scheduler_failure_total")
                logger.warning(
                    "provider sync scheduler failed connection=%s tenant=%s provider=%s: %s",
                    getattr(connection, "connection_id", "?"),
                    getattr(connection, "tenant_id", "?"),
                    getattr(connection, "provider_identity", "?"),
                    exc,
                )

        metrics.increment("provider_sync_scheduler_pass_total")
        metrics.increment(
            "provider_sync_scheduler_due_total", value=len(due)
        )
        return summary


def _connection_from_row(row: Optional[dict]) -> Any:
    """Build a ``ProviderConnection`` from a repo row (shape-agnostic for fakes)."""
    if not isinstance(row, dict):
        return row
    from services.provider_runtime.connection import ProviderConnection

    try:
        return ProviderConnection.model_validate(
            {k: v for k, v in row.items() if k != "id"}
        )
    except Exception:  # pragma: no cover - unparseable row is skipped honestly
        return None


async def run_provider_sync_loop(interval_seconds: Optional[int] = None) -> None:
    """Periodic due-connection sweep (flags + interval re-read every pass).

    The interval is read INSIDE the loop (C-7) so a runtime cadence change in
    ``settings.provider_runtime.provider_sync_interval_seconds`` takes effect
    on the next pass without a restart — the worker never caches a frozen
    config. ``interval_seconds`` is a test/embedding override that pins the
    cadence for the lifetime of the loop.
    """
    from config.settings import settings

    logger.info("provider sync scheduler worker started (interval re-read every pass)")
    while True:
        interval = int(
            interval_seconds
            if interval_seconds is not None
            else _config_value(
                settings, "provider_sync_interval_seconds", _DEFAULT_INTERVAL_S
            )
        )
        try:
            await _sweep_once(settings)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            metrics.increment("provider_sync_scheduler_sweep_error_total")
            logger.error(f"provider sync scheduler sweep failed: {exc}", exc_info=True)
        await asyncio.sleep(interval)


async def _sweep_once(settings: Any) -> None:
    """One sweep pass — a no-op unless the Team-D scheduler flag is enabled."""
    if not bool(_config_value(settings, "provider_sync_scheduler_enabled", False)):
        return
    interval = int(
        _config_value(settings, "provider_sync_interval_seconds", _DEFAULT_INTERVAL_S)
    )
    summary = await ProviderSyncRunner(interval_seconds=interval).run_pass()
    if summary["due"]:
        logger.info(
            f"provider sync scheduler pass: scanned={summary['scanned']} "
            f"due={summary['due']} completed={summary['completed']} "
            f"failed={summary['failed']} skipped={summary['skipped']}"
        )


def build_provider_sync_coro() -> Any:
    """Zero-arg coroutine factory for the ``provider_sync_scheduler`` WorkerSpec.

    The WorkerSpec's ``enabled`` gate reads
    ``settings.provider_runtime.provider_sync_scheduler_enabled``; the loop
    itself re-reads the flag and the interval every pass so a runtime toggle
    takes effect without a restart.
    """
    return run_provider_sync_loop()


__all__ = [
    "ProviderSyncRunner",
    "build_provider_sync_coro",
    "run_provider_sync_loop",
]
