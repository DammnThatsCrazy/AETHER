"""
Aether Shared — Generic Durable Delivery Outbox Worker.

Generalizes the agentic-observability graph projection outbox pattern
(services/agentic_observability/outbox_worker.py) into a reusable worker
over any BaseRepository-shaped table (id, data JSONB, tenant_id,
created_at, updated_at).

Status vocabulary (kept in exact parity with the agentic projection outbox):

    queued          row awaiting its first delivery attempt
    processing      row currently being handed to the sink
    persisted       terminal success (default; graph projections)
    delivered       terminal success (external delivery outboxes —
                    configurable via ``success_status``)
    failed          sink raised; retried once next_attempt_at elapses
    dead_lettered   attempts reached max_attempts; terminal

Retry semantics mirror the agentic worker: exponential backoff
``min(backoff_cap_s, backoff_base_s * 2**attempts)`` recorded on the row as
``next_attempt_at`` (Z-suffixed ISO), attempts incremented on every sink
call, rows at or beyond ``max_attempts`` moved to ``dead_lettered``.

INVARIANT: The worker only moves rows through the status machine and calls
the injected sink. It owns no business logic; sinks own delivery semantics.

Supervisor wiring: hold a worker instance and pass ``worker.build_coro`` as
the zero-arg coroutine factory (same shape as services/jobs
``build_job_worker_coro``). ``drain_once()`` is exposed for tests and ops.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Coroutine, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.shared.outbox")

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_PERSISTED = "persisted"
STATUS_DELIVERED = "delivered"
STATUS_FAILED = "failed"
STATUS_DEAD_LETTERED = "dead_lettered"

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_CAP_S = 300.0
DEFAULT_BATCH_SIZE = 100
DEFAULT_POLL_INTERVAL_S = 5.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Z-suffixed ISO timestamp — same convention the agentic worker used."""
    return dt.isoformat().replace("+00:00", "Z")


def _retry_due(row: dict, now: datetime) -> bool:
    """True when a failed row's next_attempt_at window has elapsed.

    Malformed timestamps are treated as due (and logged) so a single bad row
    cannot silently pin itself in `failed` forever.
    """
    raw = row.get("next_attempt_at")
    if not raw:
        return True
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        logger.warning(
            "outbox row has malformed next_attempt_at — treating as due",
            extra={"outbox_id": row.get("outbox_id") or row.get("id", ""), "value": str(raw)},
        )
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= now


@dataclass
class OutboxDrainSummary:
    """Counts for one drain pass. ``succeeded`` counts rows that reached the
    worker's configured success status (persisted or delivered)."""

    name: str
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    dead_lettered: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outbox": self.name,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "dead_lettered": self.dead_lettered,
            "errors": list(self.errors),
        }


class GenericOutboxWorker:
    """Drains queued/retry-due rows from a BaseRepository-shaped outbox table
    through an async sink with bounded attempts, backoff, and dead-lettering.

    Args:
        repo: row source — anything exposing the BaseRepository API
            (``find_many``, ``insert``); typically a BaseRepository subclass.
        sink: ``async (row: dict) -> None``. Raise to signal a failed
            attempt (the row is retried with backoff). Sinks may mutate the
            row dict to record per-attempt detail; mutations are persisted
            with the status mark.
        max_attempts: attempts at/beyond which a row is dead-lettered.
        backoff_base_s: base of the exponential retry backoff.
        backoff_cap_s: upper bound on a single backoff window.
        batch_size: per-status fetch bound for one drain pass.
        poll_interval_s: sleep between passes in ``run_forever``.
        success_status: terminal success status ("persisted" for internal
            projections, "delivered" for external delivery outboxes).
        name: worker name used in logs and metric labels.
    """

    def __init__(
        self,
        repo: Any,
        sink: Callable[[dict], Awaitable[None]],
        *,
        name: str = "outbox",
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        backoff_cap_s: float = DEFAULT_BACKOFF_CAP_S,
        batch_size: int = DEFAULT_BATCH_SIZE,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        success_status: str = STATUS_PERSISTED,
    ) -> None:
        if success_status not in (STATUS_PERSISTED, STATUS_DELIVERED):
            raise ValueError(
                f"success_status must be {STATUS_PERSISTED!r} or {STATUS_DELIVERED!r}"
                f" (got {success_status!r})"
            )
        self._repo = repo
        self._sink = sink
        self._name = name
        self._max_attempts = max_attempts
        self._backoff_base_s = backoff_base_s
        self._backoff_cap_s = backoff_cap_s
        self._batch_size = batch_size
        self._poll_interval_s = poll_interval_s
        self._success_status = success_status

    @property
    def name(self) -> str:
        return self._name

    # ── drain ────────────────────────────────────────────────────────────────

    async def drain_once(
        self,
        tenant_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """Process one bounded batch of queued + retry-due rows.

        Returns the counts dict (see OutboxDrainSummary.to_dict) for
        tests/ops. A sink exception affects only its own row.
        """
        batch = limit if limit is not None else self._batch_size
        summary = OutboxDrainSummary(name=self._name)
        now = _utc_now()

        rows = await self._fetch_batch(tenant_id, batch, now)
        for row in rows:
            summary.processed += 1
            row_id = str(row.get("outbox_id") or row.get("id", ""))
            attempts = int(row.get("attempts", 0) or 0)

            if attempts >= self._max_attempts:
                await self._mark(row_id, row, STATUS_DEAD_LETTERED, attempts)
                summary.dead_lettered += 1
                self._count_outcome(STATUS_DEAD_LETTERED)
                continue

            await self._mark(row_id, row, STATUS_PROCESSING, attempts)
            try:
                await self._sink(row)
            except Exception as exc:
                backoff_s = min(self._backoff_cap_s, self._backoff_base_s * (2 ** attempts))
                logger.warning(
                    "outbox sink failed",
                    extra={
                        "outbox": self._name,
                        "outbox_id": row_id,
                        "attempts": attempts,
                        "backoff_s": backoff_s,
                        "error": str(exc),
                    },
                )
                failed_row = {
                    **row,
                    "next_attempt_at": _iso_z(now + timedelta(seconds=backoff_s)),
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
                await self._mark(row_id, failed_row, STATUS_FAILED, attempts + 1)
                summary.failed += 1
                summary.errors.append(f"{row_id}:{type(exc).__name__}")
                self._count_outcome(STATUS_FAILED)
                continue

            await self._mark(row_id, row, self._success_status, attempts + 1)
            summary.succeeded += 1
            self._count_outcome(self._success_status)

        return summary.to_dict()

    async def _fetch_batch(
        self, tenant_id: Optional[str], limit: int, now: datetime
    ) -> list[dict]:
        """Queued rows plus failed rows whose retry window elapsed,
        oldest-first, each status bounded by ``limit``."""
        queued_filters: dict[str, Any] = {"status": STATUS_QUEUED}
        failed_filters: dict[str, Any] = {"status": STATUS_FAILED}
        if tenant_id:
            queued_filters["tenant_id"] = tenant_id
            failed_filters["tenant_id"] = tenant_id

        queued = await self._repo.find_many(
            filters=queued_filters, limit=limit, sort_by="created_at", sort_order="asc"
        )
        failed = await self._repo.find_many(
            filters=failed_filters, limit=limit, sort_by="created_at", sort_order="asc"
        )
        eligible_failed = [r for r in failed if _retry_due(r, now)]
        return list(queued) + eligible_failed

    async def _mark(self, row_id: str, row: dict, status: str, attempts: int) -> None:
        """Upsert the row with a new status. Best-effort — a mark failure is
        logged, never raised (same contract as the agentic worker's _mark)."""
        from shared.common.common import utc_now

        try:
            updated = {
                **row,
                "status": status,
                "attempts": attempts,
                "updated_at": utc_now().isoformat(),
            }
            await self._repo.insert(row_id, updated)
        except Exception as exc:
            logger.warning(
                "outbox mark failed",
                extra={
                    "outbox": self._name,
                    "outbox_id": row_id,
                    "status": status,
                    "error": str(exc),
                },
            )

    def _count_outcome(self, outcome: str) -> None:
        try:
            metrics.increment(
                "aether_outbox_rows_processed_total",
                labels={"outbox": self._name, "outcome": outcome},
            )
        except Exception:  # metrics must never break the drain loop
            pass

    # ── supervisor surface ───────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Long-running drain loop for supervisor wiring. Drain errors are
        logged and the loop continues; cancellation propagates."""
        logger.info(
            "outbox worker started",
            extra={"outbox": self._name, "poll_interval_s": self._poll_interval_s},
        )
        while True:
            try:
                summary = await self.drain_once()
                if summary.get("processed"):
                    logger.info("outbox drain", extra={**summary})
            except Exception as exc:
                logger.error(
                    "outbox drain pass crashed",
                    extra={"outbox": self._name, "error": str(exc)},
                )
            await asyncio.sleep(self._poll_interval_s)

    def build_coro(self) -> Coroutine[Any, Any, None]:
        """Zero-arg coroutine factory: a fresh long-running drain-loop
        coroutine (same supervisor shape as services/jobs factories)."""
        return self.run_forever()
