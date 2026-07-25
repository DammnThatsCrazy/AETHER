"""Aether Runtime — Worker Supervisor.

Owns the lifecycle of long-running background loop workers:

- Each worker is described by a frozen :class:`WorkerSpec` whose ``factory``
  returns a FRESH coroutine per (re)start.
- Every worker runs inside a guard task: a crash is logged, counted via the
  shared metrics helper, and the worker is restarted with exponential backoff
  up to ``max_restarts``; after that the worker enters the ``failed`` state.
- In staging/production a REQUIRED worker whose FIRST start fails raises
  ``RuntimeError`` from :meth:`WorkerSupervisor.start_all` to abort startup
  (fail-closed). Local/dev keep warn-and-restart semantics.
- No module-level singleton: the instance lives on ``app.state.worker_supervisor``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

from config.settings import Environment
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.runtime.supervisor")

# Environments where a required worker's first-start failure aborts startup.
_STRICT_ENVIRONMENTS = (Environment.STAGING, Environment.PRODUCTION)

# Worker states surfaced by WorkerSupervisor.status()
STATE_RUNNING = "running"
STATE_FAILED = "failed"
STATE_DISABLED = "disabled"
STATE_STOPPED = "stopped"
STATE_RESTARTING = "restarting"


@dataclass(frozen=True)
class WorkerSpec:
    """Declarative description of one supervised background worker.

    ``factory`` must return a *fresh* coroutine object on every call — the
    supervisor invokes it once per (re)start attempt.

    ``role`` names the *logical* worker role that owns this worker, which is
    not always the role the process was booted as: a consolidated execution
    group hosts several roles in one process, and per-role health, metrics and
    logs must stay derivable there. Empty means unattributed.
    """

    name: str
    factory: Callable[[], Coroutine[Any, Any, Any]]
    required: bool = False
    enabled: Callable[[], bool] = lambda: True
    max_restarts: int = 5
    backoff_base_s: float = 2.0
    role: str = ""


class _WorkerRecord:
    """Mutable per-worker runtime state (internal)."""

    __slots__ = ("spec", "state", "restarts", "last_error", "first_start")

    def __init__(self, spec: WorkerSpec) -> None:
        self.spec = spec
        self.state: str = STATE_STOPPED
        self.restarts: int = 0
        self.last_error: Optional[str] = None
        # Resolved with the exception on a first-attempt crash, with None on
        # clean completion/cancellation. Never resolved while the first run
        # is still healthy (loop workers run forever).
        self.first_start: Optional[asyncio.Future] = None


class WorkerSupervisor:
    """Supervises background loop workers registered via :meth:`register`.

    Lifecycle: ``register(...)`` × N → ``await start_all()`` → app runs →
    ``await stop_all()``. The instance is one-shot; a stopped supervisor is
    not restarted.
    """

    def __init__(
        self,
        *,
        environment: Optional[Environment] = None,
        first_start_grace_s: float = 1.0,
    ) -> None:
        # ``environment=None`` resolves config.settings.settings.env lazily at
        # start_all() time (keeps tests able to monkeypatch settings.env).
        self._environment = environment
        self._first_start_grace_s = first_start_grace_s
        self._records: dict[str, _WorkerRecord] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._started = False
        self._stopping = False

    # ── registration ──────────────────────────────────────────────────────

    def register(self, spec: WorkerSpec) -> None:
        """Register a worker spec. Duplicate names raise ValueError."""
        if spec.name in self._records:
            raise ValueError(f"duplicate worker name: {spec.name!r}")
        self._records[spec.name] = _WorkerRecord(spec)

    # ── environment ───────────────────────────────────────────────────────

    def _resolve_environment(self) -> Environment:
        if self._environment is not None:
            return self._environment
        from config.settings import settings  # late import: honor monkeypatching

        return settings.env

    # ── start / stop ──────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start every enabled worker inside its guard task.

        In staging/production, waits a short grace window for REQUIRED
        workers and raises RuntimeError if any of them failed their first
        start — aborting application startup (fail-closed).
        """
        if self._started:
            raise RuntimeError("WorkerSupervisor.start_all() called twice")
        self._started = True
        self._stopping = False

        env = self._resolve_environment()
        strict = env in _STRICT_ENVIRONMENTS
        loop = asyncio.get_running_loop()
        required_records: list[_WorkerRecord] = []

        for record in self._records.values():
            spec = record.spec
            try:
                is_enabled = bool(spec.enabled())
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "worker_enabled_check_failed name=%s error=%s: %s",
                    spec.name, type(exc).__name__, exc,
                )
                is_enabled = False
            if not is_enabled:
                record.state = STATE_DISABLED
                logger.info("worker_disabled name=%s", spec.name)
                continue

            record.first_start = loop.create_future()
            self._tasks[spec.name] = asyncio.create_task(
                self._guard(spec, record), name=f"aether-worker:{spec.name}",
            )
            if spec.required:
                required_records.append(record)

        if strict and required_records:
            futures = [r.first_start for r in required_records if r.first_start is not None]
            # A healthy loop worker never resolves its first-start future, so
            # bound the wait: only immediate first-start failures abort boot.
            await asyncio.wait(futures, timeout=self._first_start_grace_s)
            failed = [
                r for r in required_records
                if r.first_start is not None
                and r.first_start.done()
                and r.first_start.result() is not None
            ]
            if failed:
                names = ", ".join(sorted(r.spec.name for r in failed))
                details = "; ".join(
                    f"{r.spec.name}: {r.last_error}" for r in failed
                )
                logger.error(
                    "required_worker_first_start_failed env=%s workers=%s (%s)",
                    env.value, names, details,
                )
                await self.stop_all()
                raise RuntimeError(
                    f"required worker(s) failed first start in {env.value}: {names}"
                )

        logger.info(
            "worker_supervisor_started env=%s workers=%d disabled=%d",
            env.value,
            len(self._tasks),
            sum(1 for r in self._records.values() if r.state == STATE_DISABLED),
        )

    async def stop_all(self) -> None:
        """Cancel and await every guard task (running or backoff-restarting).

        Idempotent: safe to call multiple times.
        """
        self._stopping = True
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for record in self._records.values():
            if record.state in (STATE_RUNNING, STATE_RESTARTING):
                record.state = STATE_STOPPED

    # ── guard task ────────────────────────────────────────────────────────

    async def _guard(self, spec: WorkerSpec, record: _WorkerRecord) -> None:
        """Run the worker coroutine; on crash, backoff-restart up to max_restarts."""
        attempt = 0  # crashes observed so far (== restarts already consumed)
        while True:
            try:
                record.state = STATE_RUNNING
                await spec.factory()
                # Worker coroutine returned on its own — clean completion.
                record.state = STATE_STOPPED
                self._resolve_first_start(record, None)
                logger.info("worker_completed name=%s", spec.name)
                return
            except asyncio.CancelledError:
                record.state = STATE_STOPPED
                self._resolve_first_start(record, None)
                raise
            except Exception as exc:
                # Every crash/restart/failure signal carries the owning role so
                # a consolidated process (one task, many logical roles) stays
                # per-role attributable in metrics and logs.
                labels = {"worker": spec.name, "role": spec.role or "unattributed"}
                record.last_error = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "worker_crashed name=%s role=%s attempt=%d error=%s",
                    spec.name, spec.role or "unattributed", attempt + 1, record.last_error,
                )
                metrics.increment("worker_supervisor_crash", labels=labels)
                if attempt == 0:
                    self._resolve_first_start(record, exc)
                if attempt >= spec.max_restarts:
                    record.state = STATE_FAILED
                    metrics.increment("worker_supervisor_failed", labels=labels)
                    logger.error(
                        "worker_failed name=%s role=%s restarts_exhausted=%d",
                        spec.name, spec.role or "unattributed", spec.max_restarts,
                    )
                    return
                attempt += 1
                record.restarts = attempt
                record.state = STATE_RESTARTING
                metrics.increment("worker_supervisor_restart", labels=labels)
                delay = spec.backoff_base_s * (2 ** (attempt - 1))
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    record.state = STATE_STOPPED
                    raise

    @staticmethod
    def _resolve_first_start(record: _WorkerRecord, exc: Optional[BaseException]) -> None:
        fut = record.first_start
        if fut is not None and not fut.done():
            # set_result (not set_exception) so an unawaited future never
            # emits "exception was never retrieved" warnings.
            fut.set_result(exc)

    # ── introspection ─────────────────────────────────────────────────────

    def status(self) -> dict[str, dict[str, Any]]:
        """Per-worker state map used by /v1/ready and diagnostics.

        ``role`` is the logical worker role owning each entry, so callers can
        fold this map into per-role health even when one process hosts several
        roles (see :func:`status_by_role`).
        """
        return {
            name: {
                "state": record.state,
                "restarts": record.restarts,
                "last_error": record.last_error,
                "required": record.spec.required,
                "role": record.spec.role,
            }
            for name, record in self._records.items()
        }

    def status_by_role(self) -> dict[str, dict[str, Any]]:
        """Fold :meth:`status` into one health entry per logical role.

        A role is healthy only when none of its workers is ``failed``. This is
        what makes a consolidated deployment observable at the same granularity
        as the dedicated deployment it replaces: one crashed logical role shows
        up as that role being unhealthy, not as the whole process degrading.
        """
        by_role: dict[str, dict[str, Any]] = {}
        for name, info in self.status().items():
            role = info.get("role") or "unattributed"
            entry = by_role.setdefault(
                role, {"healthy": True, "workers": {}, "failed": []},
            )
            entry["workers"][name] = info
            if info.get("state") == STATE_FAILED:
                entry["healthy"] = False
                entry["failed"].append(name)
        for entry in by_role.values():
            entry["failed"].sort()
        return by_role
