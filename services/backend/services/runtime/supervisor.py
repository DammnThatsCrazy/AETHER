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
- A supervisor-owned watchdog task samples liveness and per-worker workload
  telemetry on a fixed interval, so :meth:`WorkerSupervisor.status` answers
  "is this worker alive and making progress?" rather than only "what state did
  it last transition to?".
- No module-level singleton: the instance lives on ``app.state.worker_supervisor``.

:func:`evaluate_worker_readiness` folds that state into per-role and
per-capability readiness. It is deliberately the *only* implementation of that
fold: the gateway probe (``services/gateway/readiness.py``) and the worker
process's own health surface (``services/runtime/run_role.py``) both call it, so
the ALB gate and the container health check can never disagree about whether a
role is up.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Iterable, Mapping, Optional

from config.settings import Environment
from services.runtime.roles import capability_for, is_release_critical, owning_role
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

# States in which a guard task is expected to be executing (running) or about to
# resume (sleeping off a restart backoff). Only these carry a lease and only
# these are expected to keep a heartbeat advancing.
_LIVE_STATES = (STATE_RUNNING, STATE_RESTARTING)

# How often the watchdog re-stamps liveness and re-reads worker telemetry.
_WATCHDOG_INTERVAL_S = 5.0

# A live worker whose heartbeat has not advanced within this window is treated
# as unhealthy. Generous against the watchdog interval so a loaded event loop
# does not read as a dead one, but far below any deploy gate's patience.
HEARTBEAT_TIMEOUT_S = 60.0

# Per-role readiness states produced by evaluate_worker_readiness().
ROLE_OK = "ok"
ROLE_FAILED = "failed"
ROLE_STALE = "stale"
ROLE_STOPPED = "stopped"
ROLE_DISABLED = "disabled"
ROLE_UNKNOWN = "unknown"

# A role is available to serve its capability in exactly these states. Every
# other state — including "no signal at all" — counts as unavailable, because a
# probe that cannot see a role has not established that the role is working.
_AVAILABLE_ROLE_STATES = (ROLE_OK, ROLE_DISABLED)

# Role bucket for a supervised worker no role claims. Never release-critical:
# see roles.is_release_critical.
UNATTRIBUTED_ROLE = "unattributed"


def _iso(timestamp: Optional[float]) -> Optional[str]:
    """Render an epoch timestamp as RFC 3339 UTC, or None when never observed."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


@dataclass(frozen=True)
class WorkerSpec:
    """Declarative description of one supervised background worker.

    ``factory`` must return a *fresh* coroutine object on every call — the
    supervisor invokes it once per (re)start attempt.

    ``role`` names the *logical* worker role that owns this worker, which is
    not always the role the process was booted as: a consolidated execution
    group hosts several roles in one process, and per-role health, metrics and
    logs must stay derivable there. Empty means unattributed.

    ``healthy_run_s`` is how long one run must last before the restart budget is
    considered earned back — see :meth:`WorkerSupervisor._guard`.

    ``telemetry`` optionally returns this worker's own workload counters. The
    supervisor samples it to derive backlog, dead-letter depth and last
    successful processing time, which liveness alone cannot express: a consumer
    pipeline that is alive but has not acknowledged a message in an hour is a
    different operational state from one that is idle because there is no work.
    Recognised keys are ``in_flight``, ``unacked`` and ``dlq_depth`` — the
    counters :class:`ConsumerRunner` already publishes. ``None`` means the worker
    exposes no workload signal, which is reported as such rather than as zero.
    """

    name: str
    factory: Callable[[], Coroutine[Any, Any, Any]]
    required: bool = False
    enabled: Callable[[], bool] = lambda: True
    max_restarts: int = 5
    backoff_base_s: float = 2.0
    role: str = ""
    healthy_run_s: float = 300.0
    telemetry: Optional[Callable[[], Mapping[str, Any]]] = None


class _WorkerRecord:
    """Mutable per-worker runtime state (internal)."""

    __slots__ = (
        "spec", "state", "restarts", "total_restarts", "last_error", "first_start",
        "heartbeat_at", "last_success_at", "pending_since", "consumer_lag",
        "dlq_depth", "telemetry_error",
    )

    def __init__(self, spec: WorkerSpec) -> None:
        self.spec = spec
        self.state: str = STATE_STOPPED
        # Last moment this worker was observed alive: stamped when a run starts
        # and re-stamped by the watchdog while the guard task is executing. It
        # stops advancing the instant the task dies or the event loop stalls,
        # which is what makes it a liveness signal rather than a status echo.
        self.heartbeat_at: Optional[float] = None
        # Last moment this worker was observed to have finished and acknowledged
        # everything it had taken (pending returned to zero), or to have
        # completed its run cleanly. None means no completed work observed yet.
        self.last_success_at: Optional[float] = None
        # When the current uninterrupted stretch of pending work began. Because
        # pending was zero immediately before it, every item pending now arrived
        # at or after this instant — so "now - pending_since" bounds the age of
        # the oldest pending item.
        self.pending_since: Optional[float] = None
        # Latest telemetry sample. None (not 0) while the worker publishes no
        # workload counters, so "no signal" is never rendered as "no backlog".
        self.consumer_lag: Optional[int] = None
        self.dlq_depth: Optional[int] = None
        self.telemetry_error: Optional[str] = None
        # Restart budget consumed since the last sustained healthy run. Reset
        # when the worker proves it recovered, so the number always answers
        # "how close is this worker to being given up on?".
        self.restarts: int = 0
        # Every restart this worker has ever had. Never reset, so a worker that
        # flaps once a week is still distinguishable from one that has never
        # crashed — the budget reset must not erase that evidence.
        self.total_restarts: int = 0
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
        watchdog_interval_s: float = _WATCHDOG_INTERVAL_S,
    ) -> None:
        # ``environment=None`` resolves config.settings.settings.env lazily at
        # start_all() time (keeps tests able to monkeypatch settings.env).
        self._environment = environment
        self._first_start_grace_s = first_start_grace_s
        self._watchdog_interval_s = watchdog_interval_s
        self._records: dict[str, _WorkerRecord] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._watchdog: Optional[asyncio.Task] = None
        self._started = False
        self._stopping = False
        # Identity of the process executing these workers. Resolved at
        # construction (after run_role has exported AETHER_ROLE) rather than at
        # import, so the value names the role this process was actually booted
        # as. This is what a status map needs to answer "who is running this
        # worker right now" when several tasks host the same logical role.
        self._lease_owner = (
            f"{os.environ.get('AETHER_ROLE') or 'unset'}@"
            f"{socket.gethostname()}:{os.getpid()}"
        )

    @property
    def lease_owner(self) -> str:
        """Process identity holding the lease on every worker this instance runs."""
        return self._lease_owner

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

        # Started last so a boot that aborts above never leaves a watchdog task
        # orphaned on the loop.
        self._watchdog = asyncio.create_task(
            self._watch(), name="aether-worker-supervisor:watchdog",
        )

        logger.info(
            "worker_supervisor_started env=%s workers=%d disabled=%d owner=%s",
            env.value,
            len(self._tasks),
            sum(1 for r in self._records.values() if r.state == STATE_DISABLED),
            self._lease_owner,
        )

    async def stop_all(self) -> None:
        """Cancel and await every guard task (running or backoff-restarting).

        Idempotent: safe to call multiple times.
        """
        self._stopping = True
        if self._watchdog is not None:
            self._watchdog.cancel()
            try:
                await self._watchdog
            except asyncio.CancelledError:
                pass
            self._watchdog = None
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
        """Run the worker coroutine; on crash, backoff-restart up to max_restarts.

        The restart budget is a *rate* limit, not a lifetime quota. ``attempt``
        used to only ever grow, so ``max_restarts`` counted crashes across the
        entire life of the process: six unrelated transient failures spread over
        weeks — a broker blip in week one, another in week three — permanently
        marked the role ``failed``, and it stayed that way while the task
        happily reported itself alive. That is the opposite of what a supervisor
        is for; the budget exists to stop a *crash loop*, and a worker that ran
        healthily for ``healthy_run_s`` between two crashes is not in one.

        So a run that lasted at least ``spec.healthy_run_s`` returns the budget
        to full before the crash is counted. Crash-looping is unaffected: those
        runs are far shorter than the threshold, so the budget still drains and
        the worker still reaches ``failed``.
        """
        loop = asyncio.get_running_loop()
        attempt = 0  # restart budget consumed (reset by a sustained healthy run)
        while True:
            started_at = loop.time()
            try:
                record.state = STATE_RUNNING
                # First beat of this run: a worker must look alive from the
                # instant it starts, not only from the watchdog's first tick.
                record.heartbeat_at = time.time()
                await spec.factory()
                # Worker coroutine returned on its own — clean completion.
                record.state = STATE_STOPPED
                record.last_success_at = time.time()
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
                uptime_s = loop.time() - started_at
                if attempt and uptime_s >= spec.healthy_run_s:
                    # The worker demonstrably recovered from the previous crash
                    # and ran normally for a sustained period. This crash starts
                    # a new incident, not a continuation of the old one.
                    logger.info(
                        "worker_restart_budget_reset name=%s role=%s "
                        "healthy_uptime_s=%.1f budget_returned=%d",
                        spec.name, spec.role or "unattributed", uptime_s, attempt,
                    )
                    metrics.increment(
                        "worker_supervisor_restart_budget_reset", labels=labels,
                    )
                    attempt = 0
                    record.restarts = 0
                logger.error(
                    "worker_crashed name=%s role=%s attempt=%d uptime_s=%.1f error=%s",
                    spec.name, spec.role or "unattributed", attempt + 1, uptime_s,
                    record.last_error,
                )
                metrics.increment("worker_supervisor_crash", labels=labels)
                if attempt == 0:
                    self._resolve_first_start(record, exc)
                if attempt >= spec.max_restarts:
                    record.state = STATE_FAILED
                    metrics.increment("worker_supervisor_failed", labels=labels)
                    # Emitted with the role as well, because this is the moment a
                    # logical role stops doing its job for the rest of the
                    # process's life. status_by_role() is only read at shutdown,
                    # so without this signal the degradation is invisible until
                    # the task happens to stop.
                    metrics.increment("worker_supervisor_role_unhealthy", labels=labels)
                    logger.error(
                        "worker_failed name=%s role=%s restarts_exhausted=%d "
                        "total_restarts=%d last_error=%s — this role is now "
                        "permanently inactive in this process",
                        spec.name, spec.role or "unattributed", spec.max_restarts,
                        record.total_restarts, record.last_error,
                    )
                    return
                attempt += 1
                record.restarts = attempt
                record.total_restarts += 1
                record.state = STATE_RESTARTING
                metrics.increment("worker_supervisor_restart", labels=labels)
                delay = spec.backoff_base_s * (2 ** (attempt - 1))
                try:
                    await asyncio.sleep(delay)
                except asyncio.CancelledError:
                    record.state = STATE_STOPPED
                    raise

    # ── watchdog ──────────────────────────────────────────────────────────

    async def _watch(self) -> None:
        """Re-stamp liveness and re-read telemetry on a fixed interval.

        This runs as its own task on purpose. Sampling lazily from
        :meth:`status` would make the heartbeat worthless as a liveness signal:
        ``status()`` is called from the readiness handler on this same event
        loop, so a loop that is too stalled to advance a heartbeat is also too
        stalled to serve the probe that would have stamped it. An independent
        task advances only while the loop is genuinely running work.
        """
        while True:
            await asyncio.sleep(self._watchdog_interval_s)
            now = time.time()
            for name, record in self._records.items():
                task = self._tasks.get(name)
                # Only a worker whose guard task is still executing gets a beat.
                # A failed or completed worker's task is done, so its heartbeat
                # freezes and readiness sees the staleness.
                if (
                    record.state in _LIVE_STATES
                    and task is not None
                    and not task.done()
                ):
                    record.heartbeat_at = now
                self._sample_telemetry(record, now)

    @staticmethod
    def _sample_telemetry(record: _WorkerRecord, now: float) -> None:
        """Fold one worker's own counters into backlog / progress observations.

        Progress is derived from the pending count (work taken but not yet
        acknowledged) rather than asserted by the worker, because nothing on the
        consumer path publishes a cumulative processed counter. The two
        transitions that carry information are:

        - 0 → >0: work has just been taken, so the oldest pending item cannot
          predate this instant.
        - >0 → 0: everything taken has been acknowledged, which is precisely an
          observed successful unit of processing.
        """
        provider = record.spec.telemetry
        if provider is None:
            return
        try:
            sample = provider() or {}
        except Exception as exc:  # pragma: no cover — defensive
            # A telemetry provider that raises leaves the previous sample in
            # place and records why, rather than reporting a fabricated zero.
            record.telemetry_error = f"{type(exc).__name__}: {exc}"
            return
        record.telemetry_error = None
        pending = int(sample.get("in_flight", 0)) + int(sample.get("unacked", 0))
        record.consumer_lag = pending
        record.dlq_depth = int(sample.get("dlq_depth", 0))
        if pending > 0:
            if record.pending_since is None:
                record.pending_since = now
        elif record.pending_since is not None:
            record.pending_since = None
            record.last_success_at = now

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

        Beyond the last state transition, each entry carries the signals a
        readiness decision actually needs — a state of ``running`` only says
        nothing has crashed, not that anything is happening:

        - ``lease_owner``          — the process executing this worker, or None
                                     when nothing holds it (failed/stopped).
        - ``heartbeat_at`` /
          ``heartbeat_age_s``      — when the guard task was last observed
                                     alive. Freezes on death or loop stall.
        - ``last_success_at``      — when this worker last completed and
                                     acknowledged the work it had taken.
        - ``consumer_lag``         — items taken but not yet acknowledged.
        - ``oldest_pending_age_s`` — how long work has been pending
                                     uninterrupted (0.0 when nothing pends).
        - ``dlq_depth``            — dead letters held by this worker.

        The last four are None for a worker that publishes no telemetry, which
        is a different statement from zero and is reported as such.
        """
        now = time.time()
        status: dict[str, dict[str, Any]] = {}
        for name, record in self._records.items():
            # Sampled at probe time as well as on the watchdog tick, so a
            # readiness response never reports backlog up to one interval stale.
            self._sample_telemetry(record, now)
            status[name] = {
                "state": record.state,
                # Budget consumed since the last sustained healthy run — i.e.
                # how close this worker is to being given up on. Deliberately
                # NOT the lifetime count; see :meth:`restart_totals`.
                "restarts": record.restarts,
                "last_error": record.last_error,
                "required": record.spec.required,
                "role": record.spec.role,
                "lease_owner": (
                    self._lease_owner if record.state in _LIVE_STATES else None
                ),
                "heartbeat_at": _iso(record.heartbeat_at),
                "heartbeat_age_s": (
                    None if record.heartbeat_at is None
                    else round(now - record.heartbeat_at, 3)
                ),
                "last_success_at": _iso(record.last_success_at),
                "consumer_lag": record.consumer_lag,
                "oldest_pending_age_s": (
                    round(now - record.pending_since, 3)
                    if record.pending_since is not None
                    else (0.0 if record.consumer_lag is not None else None)
                ),
                "dlq_depth": record.dlq_depth,
                "telemetry_error": record.telemetry_error,
            }
        return status

    def restart_totals(self) -> dict[str, int]:
        """Lifetime restart count per worker, never reset by a budget reset.

        Kept out of :meth:`status` on purpose. That map's key set is a pinned
        contract (``/v1/ready`` and its own shape test), and the two numbers
        answer different questions: ``status()['restarts']`` is "how much budget
        is left", this is "has this worker been flapping for months". Erasing
        the second when the first resets would trade one blind spot for another.
        """
        return {
            name: record.total_restarts for name, record in self._records.items()
        }

    def unhealthy_roles(self) -> dict[str, dict[str, Any]]:
        """Just the roles with at least one permanently failed worker.

        The signal a health check or readiness probe needs. Kept as its own
        accessor because ``status_by_role()`` returns every role and a caller
        that only wants "is anything broken?" should not have to filter it.
        """
        return {
            role: health
            for role, health in self.status_by_role().items()
            if not health["healthy"]
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


# ── readiness evaluation ─────────────────────────────────────────────────────

def _role_state(
    members: Mapping[str, Mapping[str, Any]],
    heartbeat_timeout_s: float,
    supervised: bool,
) -> tuple[str, str]:
    """Return ``(state, detail)`` for one logical role's supervised workers.

    Fail-closed throughout: every outcome other than "observed working" or
    "deliberately switched off" is unavailable. An empty member set is the case
    that matters most — a role the process is supposed to host but for which no
    worker is registered has produced no evidence of health, and reading that
    silence as success is the defect this function replaces.
    """
    if not members:
        return (
            ROLE_UNKNOWN,
            "worker supervisor not initialised" if not supervised
            else "no supervised worker registered for this role in this process",
        )

    failed: list[str] = []
    stale: list[str] = []
    stopped: list[str] = []
    disabled: list[str] = []
    for name, info in sorted(members.items()):
        state = info.get("state")
        if state == STATE_FAILED:
            failed.append(name)
        elif state == STATE_DISABLED:
            disabled.append(name)
        elif state == STATE_STOPPED:
            stopped.append(name)
        else:
            age = info.get("heartbeat_age_s")
            if age is None or age > heartbeat_timeout_s:
                stale.append(name)

    if failed:
        return ROLE_FAILED, f"failed worker(s): {', '.join(failed)}"
    if stale:
        return (
            ROLE_STALE,
            f"no heartbeat within {heartbeat_timeout_s:.0f}s: {', '.join(stale)}",
        )
    if stopped:
        return ROLE_STOPPED, f"worker(s) no longer running: {', '.join(stopped)}"
    if len(disabled) == len(members):
        return ROLE_DISABLED, "every worker for this role is disabled by configuration"
    return ROLE_OK, f"{len(members) - len(disabled)} worker(s) running"


def evaluate_worker_readiness(
    supervisor: Optional[WorkerSupervisor],
    expected_roles: Iterable[str],
    *,
    heartbeat_timeout_s: float = HEARTBEAT_TIMEOUT_S,
) -> dict[str, Any]:
    """Fold supervisor state into per-role and per-capability readiness.

    ``expected_roles`` is the set of logical roles the *calling process* is
    responsible for. It is supplied by the caller rather than derived here
    because the two boot paths register different things: the FastAPI lifespan
    registers supervised loop specs only, while ``run_role`` additionally
    registers a consumer receive loop for every consumer-attached role. Roles
    that are observed in the status map but absent from ``expected_roles`` are
    evaluated too, so a worker that turns up unannounced is never ignored.

    Returns ``ready`` (False only when a *release-critical* role is
    unavailable), the per-role detail, the per-capability map, and the two
    failure lists. A non-critical role's failure leaves ``ready`` True while its
    capability is marked unavailable: a rollout should not be blocked by a
    degraded enrichment path, and a caller should not be told enrichment works.
    """
    workers = supervisor.status() if supervisor is not None else {}

    by_role: dict[str, dict[str, Mapping[str, Any]]] = {}
    for name, info in workers.items():
        # A spec registered without an explicit owner (the FastAPI lifespan
        # registers build_worker_specs() unstamped) is still attributable
        # through the canonical spec→role index, so per-role readiness does not
        # depend on which boot path registered the worker.
        role = info.get("role") or owning_role(name) or UNATTRIBUTED_ROLE
        by_role.setdefault(role, {})[name] = info

    roles: dict[str, dict[str, Any]] = {}
    for role in sorted(set(expected_roles) | set(by_role)):
        state, detail = _role_state(
            by_role.get(role, {}), heartbeat_timeout_s, supervisor is not None
        )
        roles[role] = {
            "state": state,
            "available": state in _AVAILABLE_ROLE_STATES,
            "release_critical": is_release_critical(role),
            "capability": capability_for(role),
            "detail": detail,
            "workers": sorted(by_role.get(role, {})),
        }

    capabilities = {
        health["capability"]: {
            "available": health["available"],
            "state": health["state"],
            "role": role,
            "release_critical": health["release_critical"],
            "detail": health["detail"],
        }
        for role, health in roles.items()
    }
    critical = sorted(
        role for role, health in roles.items()
        if not health["available"] and health["release_critical"]
    )
    degraded = sorted(
        role for role, health in roles.items()
        if not health["available"] and not health["release_critical"]
    )
    return {
        "ready": not critical,
        "roles": roles,
        "capabilities": capabilities,
        "critical_failures": critical,
        "degraded_roles": degraded,
    }
