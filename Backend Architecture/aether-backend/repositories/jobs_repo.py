"""
Aether Repositories — Durable Jobs Control Plane

Direct-SQL repository for the ``jobs``, ``job_events`` and ``job_schedules``
tables created by alembic migration 20260713_platform_control_plane. These
tables need semantics the JSONB BaseRepository cannot express: FOR UPDATE
SKIP LOCKED claims, lease expiry sweeps and a partial unique idempotency
index — hence real columns and hand-written SQL.

DDL parity
----------
The alembic ``versions`` directory is not an importable package and
``alembic`` itself is not a runtime dependency of the backend, so the DDL
constants below are duplicated VERBATIM from
``alembic/versions/20260713_platform_control_plane.py``.
``tests/unit/test_jobs_ddl_parity.py`` AST-extracts the migration's
constants and asserts exact string equality — when changing table shape,
edit the migration first, then mirror it here.

Backend selection mirrors repositories/repos.py:
- ``get_pool()`` returns None (AETHER_ENV=local without DATABASE_URL) →
  shared in-memory dicts guarded by an asyncio.Lock, with semantics
  identical to the SQL paths.
- Otherwise asyncpg over the shared pool.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from shared.common.common import utc_now
from shared.logger.logger import get_logger

from services.jobs.models import (
    ACTIVE_STATUSES,
    CLAIMABLE_STATUSES,
    JobStatus,
    TERMINAL_STATUSES,
)

logger = get_logger("aether.repository.jobs")

# ─────────────────────────────────────────────────────────────────────────────
# DDL — duplicated verbatim from alembic migration
# 20260713_platform_control_plane.py (see module docstring; parity-tested).
# ─────────────────────────────────────────────────────────────────────────────

JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'accepted',
    priority INT NOT NULL DEFAULT 100,
    idempotency_key TEXT,
    correlation_id TEXT,
    requested_by TEXT,
    schedule_id TEXT,
    scheduled_for TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    leased_by TEXT,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    timeout_seconds INT NOT NULL DEFAULT 3600,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
)
"""

JOB_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS job_events (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    correlation_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

JOB_SCHEDULES_DDL = """
CREATE TABLE IF NOT EXISTS job_schedules (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    job_type TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    misfire_policy TEXT NOT NULL DEFAULT 'fire_once',
    overlap_policy TEXT NOT NULL DEFAULT 'skip',
    enabled BOOLEAN NOT NULL DEFAULT true,
    owner_id TEXT,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    last_job_id TEXT,
    last_run_status TEXT,
    consecutive_failures INT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# Indexes owned by this repository (the jobs-platform subset of the
# migration's INDEXES list — also parity-tested).
JOBS_INDEXES = [
    # Idempotent job creation per tenant+type.
    "CREATE UNIQUE INDEX IF NOT EXISTS uix_jobs_tenant_type_idem "
    "ON jobs (tenant_id, job_type, idempotency_key) WHERE idempotency_key IS NOT NULL",
    # Claim path: status scan ordered by priority/schedule.
    "CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs (status, priority, scheduled_for)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_tenant_status_created "
    "ON jobs (tenant_id, status, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_lease ON jobs (status, lease_expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_events_job ON job_events (job_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_events_tenant_created "
    "ON job_events (tenant_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_job_schedules_due "
    "ON job_schedules (enabled, next_run_at)",
    "CREATE INDEX IF NOT EXISTS ix_job_schedules_tenant ON job_schedules (tenant_id)",
]

# ─────────────────────────────────────────────────────────────────────────────
# In-memory backing stores (local mode). Shared across repository instances
# so route singletons and workers observe one consistent view — mirroring
# repositories/repos.py::_IN_MEMORY_STORES.
# ─────────────────────────────────────────────────────────────────────────────

_MEM_JOBS: dict[str, dict] = {}
_MEM_JOB_EVENTS: dict[str, dict] = {}
_MEM_SCHEDULES: dict[str, dict] = {}

# The lock is (re)created per running event loop: tests run each coroutine in
# a fresh asyncio.run() loop, and an asyncio.Lock bound to a dead loop raises
# "is bound to a different event loop" on reuse.
_MEM_LOCK: Optional[asyncio.Lock] = None
_MEM_LOCK_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _mem_lock() -> asyncio.Lock:
    global _MEM_LOCK, _MEM_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _MEM_LOCK is None or _MEM_LOCK_LOOP is not loop:
        _MEM_LOCK = asyncio.Lock()
        _MEM_LOCK_LOOP = loop
    return _MEM_LOCK


def reset_jobs_memory() -> None:
    """Test helper: clear every in-memory jobs-platform store."""
    _MEM_JOBS.clear()
    _MEM_JOB_EVENTS.clear()
    _MEM_SCHEDULES.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Value normalization helpers — rows are returned as plain dicts with ISO-8601
# timestamp strings and parsed JSON payloads on BOTH backends.
# ─────────────────────────────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _to_dt(value: Any) -> Optional[datetime]:
    """Coerce ISO string / datetime / None to a tz-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    dt = _to_dt(value)
    return dt.isoformat() if dt is not None else None


def _json_load(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


_JOB_TS_FIELDS = (
    "scheduled_for", "lease_expires_at", "expires_at",
    "created_at", "updated_at", "started_at", "completed_at",
)
_SCHEDULE_TS_FIELDS = ("next_run_at", "last_run_at", "created_at", "updated_at")


def _normalize_row(record: dict, ts_fields: tuple, json_fields: tuple) -> dict:
    row = dict(record)
    for f in ts_fields:
        if f in row:
            row[f] = _iso(row[f])
    for f in json_fields:
        if f in row and row[f] is not None:
            row[f] = _json_load(row[f])
    return row


def _job_row(record: dict) -> dict:
    return _normalize_row(record, _JOB_TS_FIELDS, ("payload", "result"))


def _event_row(record: dict) -> dict:
    return _normalize_row(record, ("created_at",), ("payload",))


def _schedule_row(record: dict) -> dict:
    return _normalize_row(record, _SCHEDULE_TS_FIELDS, ("payload",))


# ─────────────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────────────

class JobsRepository:
    """Durable access to jobs / job_events / job_schedules.

    Every method persists before returning — callers may treat a returned
    row as durably recorded (Postgres) or committed to the shared local
    store (in-memory mode).
    """

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._tables_ensured = False

    async def _ensure_pool(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        return self._pool

    async def _ensure_tables(self, pool: Any) -> None:
        if self._tables_ensured or pool is None:
            return
        for ddl in (JOBS_DDL, JOB_EVENTS_DDL, JOB_SCHEDULES_DDL):
            await pool.execute(ddl)
        for idx in JOBS_INDEXES:
            await pool.execute(idx)
        self._tables_ensured = True

    async def _backend(self) -> Optional[Any]:
        pool = await self._ensure_pool()
        if pool is not None:
            await self._ensure_tables(pool)
        return pool

    # ── Jobs: enqueue ────────────────────────────────────────────────────

    async def enqueue(
        self,
        tenant_id: str,
        job_type: str,
        payload: dict,
        *,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        requested_by: Optional[str] = None,
        priority: int = 100,
        max_attempts: int = 5,
        scheduled_for: Any = None,
        schedule_id: Optional[str] = None,
        timeout_seconds: int = 3600,
        expires_at: Any = None,
    ) -> dict:
        """Insert a queued job, idempotently.

        Idempotency contract for (tenant_id, job_type, idempotency_key):
        - existing NON-failed row → return it with ``replayed=True``
          (no new row, no state change);
        - existing FAILED row → the same key re-submits the work: the row
          is re-queued in place (attempts reset) and returned with
          ``replayed=False``. A brand-new insert is impossible anyway —
          the partial unique index covers the key regardless of status.
        """
        now = utc_now()
        job_id = new_id("job")
        sched_dt = _to_dt(scheduled_for)
        expires_dt = _to_dt(expires_at)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                if idempotency_key:
                    for rec in _MEM_JOBS.values():
                        if (
                            rec["tenant_id"] == tenant_id
                            and rec["job_type"] == job_type
                            and rec.get("idempotency_key") == idempotency_key
                        ):
                            if rec["status"] != JobStatus.FAILED.value:
                                return {**_job_row(rec), "replayed": True}
                            self._mem_requeue(rec, now)
                            rec["scheduled_for"] = _iso(sched_dt)
                            return {**_job_row(rec), "replayed": False}
                record = {
                    "id": job_id,
                    "tenant_id": tenant_id,
                    "job_type": job_type,
                    "status": JobStatus.QUEUED.value,
                    "priority": int(priority),
                    "idempotency_key": idempotency_key,
                    "correlation_id": correlation_id,
                    "requested_by": requested_by,
                    "schedule_id": schedule_id,
                    "scheduled_for": _iso(sched_dt),
                    "lease_expires_at": None,
                    "leased_by": None,
                    "attempts": 0,
                    "max_attempts": int(max_attempts),
                    "timeout_seconds": int(timeout_seconds),
                    "payload": copy.deepcopy(payload or {}),
                    "result": None,
                    "error": None,
                    "expires_at": _iso(expires_dt),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                    "started_at": None,
                    "completed_at": None,
                }
                _MEM_JOBS[job_id] = record
                return {**_job_row(record), "replayed": False}

        if idempotency_key:
            existing = await pool.fetchrow(
                "SELECT * FROM jobs WHERE tenant_id = $1 AND job_type = $2 "
                "AND idempotency_key = $3",
                tenant_id, job_type, idempotency_key,
            )
            if existing is not None:
                if existing["status"] != JobStatus.FAILED.value:
                    return {**_job_row(dict(existing)), "replayed": True}
                requeued = await pool.fetchrow(
                    "UPDATE jobs SET status = $2, attempts = 0, error = NULL, "
                    "result = NULL, completed_at = NULL, leased_by = NULL, "
                    "lease_expires_at = NULL, scheduled_for = $3, updated_at = $4 "
                    "WHERE id = $1 RETURNING *",
                    existing["id"], JobStatus.QUEUED.value, sched_dt, now,
                )
                return {**_job_row(dict(requeued)), "replayed": False}

        inserted = await pool.fetchrow(
            """
            INSERT INTO jobs (
                id, tenant_id, job_type, status, priority, idempotency_key,
                correlation_id, requested_by, schedule_id, scheduled_for,
                attempts, max_attempts, timeout_seconds, payload, expires_at,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,0,$11,$12,$13::jsonb,$14,$15,$15)
            ON CONFLICT (tenant_id, job_type, idempotency_key)
                WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING *
            """,
            job_id, tenant_id, job_type, JobStatus.QUEUED.value, int(priority),
            idempotency_key, correlation_id, requested_by, schedule_id, sched_dt,
            int(max_attempts), int(timeout_seconds),
            json.dumps(payload or {}, default=str), expires_dt, now,
        )
        if inserted is not None:
            return {**_job_row(dict(inserted)), "replayed": False}
        # Lost a concurrent-insert race on the idempotency key — replay it.
        existing = await pool.fetchrow(
            "SELECT * FROM jobs WHERE tenant_id = $1 AND job_type = $2 "
            "AND idempotency_key = $3",
            tenant_id, job_type, idempotency_key,
        )
        return {**_job_row(dict(existing)), "replayed": True}

    @staticmethod
    def _mem_requeue(rec: dict, now: datetime) -> None:
        rec.update({
            "status": JobStatus.QUEUED.value,
            "attempts": 0,
            "error": None,
            "result": None,
            "completed_at": None,
            "leased_by": None,
            "lease_expires_at": None,
            "scheduled_for": None,
            "updated_at": now.isoformat(),
        })

    # ── Jobs: claim / lease / finish ─────────────────────────────────────

    async def claim_next(
        self,
        worker_id: str,
        job_types: Optional[list[str]] = None,
        lease_seconds: int = 60,
    ) -> Optional[dict]:
        """Claim the next due queued/retrying job for ``worker_id``.

        Postgres path uses FOR UPDATE SKIP LOCKED so concurrent workers never
        double-claim. Ordering: priority ASC then created_at ASC.
        """
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                candidates = [
                    rec for rec in _MEM_JOBS.values()
                    if rec["status"] in CLAIMABLE_STATUSES
                    and (
                        rec.get("scheduled_for") is None
                        or _to_dt(rec["scheduled_for"]) <= now
                    )
                    and (job_types is None or rec["job_type"] in job_types)
                ]
                if not candidates:
                    return None
                candidates.sort(key=lambda r: (r["priority"], r["created_at"]))
                rec = candidates[0]
                rec.update({
                    "status": JobStatus.RUNNING.value,
                    "leased_by": worker_id,
                    "lease_expires_at": lease_until.isoformat(),
                    "attempts": rec["attempts"] + 1,
                    "started_at": rec["started_at"] or now.isoformat(),
                    "updated_at": now.isoformat(),
                })
                return _job_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE jobs
            SET status = 'running', leased_by = $1, lease_expires_at = $2,
                attempts = attempts + 1,
                started_at = COALESCE(started_at, $3), updated_at = $3
            WHERE id = (
                SELECT id FROM jobs
                WHERE status IN ('queued', 'retrying')
                  AND (scheduled_for IS NULL OR scheduled_for <= $3)
                  AND ($4::text[] IS NULL OR job_type = ANY($4::text[]))
                ORDER BY priority ASC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING *
            """,
            worker_id, lease_until, now, job_types,
        )
        return _job_row(dict(row)) if row is not None else None

    async def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 60) -> bool:
        """Extend the lease. False when the lease was lost (another worker
        holds it / the row left ``running``) or cancellation was requested."""
        now = utc_now()
        lease_until = now + timedelta(seconds=lease_seconds)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if (
                    rec is None
                    or rec.get("leased_by") != worker_id
                    or rec["status"] != JobStatus.RUNNING.value
                ):
                    return False
                rec["lease_expires_at"] = lease_until.isoformat()
                rec["updated_at"] = now.isoformat()
                return True

        result = await pool.fetchrow(
            "UPDATE jobs SET lease_expires_at = $3, updated_at = $4 "
            "WHERE id = $1 AND leased_by = $2 AND status = 'running' RETURNING id",
            job_id, worker_id, lease_until, now,
        )
        return result is not None

    async def update_payload(self, job_id: str, payload: dict) -> Optional[dict]:
        """Durably replace a running job's payload — handler checkpointing.

        Used by resumable handlers (e.g. ``semantic.replay``) to persist a
        progress cursor into the job row itself, so a retry/restart resumes
        from the checkpoint instead of row 0. Returns the updated row, or
        None when the job does not exist.
        """
        now = utc_now()
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if rec is None:
                    return None
                rec["payload"] = copy.deepcopy(payload or {})
                rec["updated_at"] = now.isoformat()
                return _job_row(rec)

        row = await pool.fetchrow(
            "UPDATE jobs SET payload = $2::jsonb, updated_at = $3 "
            "WHERE id = $1 RETURNING *",
            job_id, json.dumps(payload or {}, default=str), now,
        )
        return _job_row(dict(row)) if row is not None else None

    async def finish(
        self,
        job_id: str,
        status: str,
        result: Optional[dict] = None,
        error: Optional[str] = None,
        scheduled_for: Any = None,
    ) -> Optional[dict]:
        """Record a job's post-execution state and release its lease.

        ``status='retrying'`` keeps the job claimable (optionally deferred to
        ``scheduled_for`` for backoff); terminal statuses stamp completed_at.
        """
        status = JobStatus(status).value  # validate
        now = utc_now()
        terminal = status in TERMINAL_STATUSES
        sched_dt = _to_dt(scheduled_for)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if rec is None:
                    return None
                rec.update({
                    "status": status,
                    "result": copy.deepcopy(result) if result is not None else rec.get("result"),
                    "error": error,
                    "leased_by": None,
                    "lease_expires_at": None,
                    "updated_at": now.isoformat(),
                })
                if status == JobStatus.RETRYING.value:
                    rec["scheduled_for"] = _iso(sched_dt)
                if terminal:
                    rec["completed_at"] = now.isoformat()
                return _job_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE jobs
            SET status = $2,
                result = COALESCE($3::jsonb, result),
                error = $4,
                scheduled_for = CASE WHEN $2 = 'retrying' THEN $5 ELSE scheduled_for END,
                completed_at = CASE WHEN $6 THEN $7 ELSE completed_at END,
                leased_by = NULL, lease_expires_at = NULL, updated_at = $7
            WHERE id = $1
            RETURNING *
            """,
            job_id, status,
            json.dumps(result, default=str) if result is not None else None,
            error, sched_dt, terminal, now,
        )
        return _job_row(dict(row)) if row is not None else None

    # ── Jobs: sweeps ─────────────────────────────────────────────────────

    async def sweep_expired_leases(self) -> list[dict]:
        """Reap running jobs whose lease expired (worker died).

        cancel_requested → cancelled; attempts < max_attempts → retrying;
        otherwise → failed. Returns the affected rows (post-transition).
        """
        now = utc_now()
        pool = await self._backend()

        if pool is None:
            affected: list[dict] = []
            async with _mem_lock():
                for rec in _MEM_JOBS.values():
                    if rec["status"] not in (
                        JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value
                    ):
                        continue
                    lease = _to_dt(rec.get("lease_expires_at"))
                    if lease is None or lease >= now:
                        continue
                    if rec["status"] == JobStatus.CANCEL_REQUESTED.value:
                        rec["status"] = JobStatus.CANCELLED.value
                        rec["completed_at"] = now.isoformat()
                    elif rec["attempts"] < rec["max_attempts"]:
                        rec["status"] = JobStatus.RETRYING.value
                    else:
                        rec["status"] = JobStatus.FAILED.value
                        rec["error"] = rec.get("error") or "lease expired"
                        rec["completed_at"] = now.isoformat()
                    rec["leased_by"] = None
                    rec["lease_expires_at"] = None
                    rec["updated_at"] = now.isoformat()
                    affected.append(_job_row(rec))
            return affected

        rows = await pool.fetch(
            """
            UPDATE jobs
            SET status = CASE
                    WHEN status = 'cancel_requested' THEN 'cancelled'
                    WHEN attempts < max_attempts THEN 'retrying'
                    ELSE 'failed'
                END,
                error = CASE
                    WHEN status = 'running' AND attempts >= max_attempts
                        THEN COALESCE(error, 'lease expired')
                    ELSE error
                END,
                completed_at = CASE
                    WHEN status = 'cancel_requested' OR attempts >= max_attempts
                        THEN $1
                    ELSE completed_at
                END,
                leased_by = NULL, lease_expires_at = NULL, updated_at = $1
            WHERE status IN ('running', 'cancel_requested')
              AND lease_expires_at IS NOT NULL AND lease_expires_at < $1
            RETURNING *
            """,
            now,
        )
        return [_job_row(dict(r)) for r in rows]

    async def sweep_expired_jobs(self) -> list[dict]:
        """Expire queued/retrying jobs whose expires_at deadline passed."""
        now = utc_now()
        pool = await self._backend()

        if pool is None:
            affected: list[dict] = []
            async with _mem_lock():
                for rec in _MEM_JOBS.values():
                    if rec["status"] not in CLAIMABLE_STATUSES:
                        continue
                    deadline = _to_dt(rec.get("expires_at"))
                    if deadline is None or deadline >= now:
                        continue
                    rec["status"] = JobStatus.EXPIRED.value
                    rec["completed_at"] = now.isoformat()
                    rec["updated_at"] = now.isoformat()
                    affected.append(_job_row(rec))
            return affected

        rows = await pool.fetch(
            """
            UPDATE jobs
            SET status = 'expired', completed_at = $1, updated_at = $1
            WHERE status IN ('queued', 'retrying')
              AND expires_at IS NOT NULL AND expires_at < $1
            RETURNING *
            """,
            now,
        )
        return [_job_row(dict(r)) for r in rows]

    # ── Jobs: cancel / retry / requeue ───────────────────────────────────

    async def request_cancel(self, tenant_id: str, job_id: str) -> Optional[dict]:
        """queued/retrying/accepted → cancelled; running → cancel_requested.

        Terminal (and already cancel_requested) rows are returned unchanged —
        the service layer decides whether that is a conflict.
        """
        now = utc_now()
        pool = await self._backend()
        cancellable = {
            JobStatus.ACCEPTED.value, JobStatus.QUEUED.value, JobStatus.RETRYING.value,
        }

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if rec is None or rec["tenant_id"] != tenant_id:
                    return None
                if rec["status"] in cancellable:
                    rec["status"] = JobStatus.CANCELLED.value
                    rec["completed_at"] = now.isoformat()
                    rec["updated_at"] = now.isoformat()
                elif rec["status"] == JobStatus.RUNNING.value:
                    rec["status"] = JobStatus.CANCEL_REQUESTED.value
                    rec["updated_at"] = now.isoformat()
                return _job_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE jobs
            SET status = CASE
                    WHEN status IN ('accepted', 'queued', 'retrying') THEN 'cancelled'
                    WHEN status = 'running' THEN 'cancel_requested'
                    ELSE status
                END,
                completed_at = CASE
                    WHEN status IN ('accepted', 'queued', 'retrying') THEN $3
                    ELSE completed_at
                END,
                updated_at = CASE
                    WHEN status IN ('accepted', 'queued', 'retrying', 'running') THEN $3
                    ELSE updated_at
                END
            WHERE id = $1 AND tenant_id = $2
            RETURNING *
            """,
            job_id, tenant_id, now,
        )
        return _job_row(dict(row)) if row is not None else None

    async def retry(self, tenant_id: str, job_id: str) -> Optional[dict]:
        """Reset a FAILED job to queued with attempts=0. None when the row is
        missing, belongs to another tenant, or is not in ``failed``."""
        now = utc_now()
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if (
                    rec is None
                    or rec["tenant_id"] != tenant_id
                    or rec["status"] != JobStatus.FAILED.value
                ):
                    return None
                self._mem_requeue(rec, now)
                return _job_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE jobs
            SET status = 'queued', attempts = 0, error = NULL, result = NULL,
                completed_at = NULL, leased_by = NULL, lease_expires_at = NULL,
                scheduled_for = NULL, updated_at = $3
            WHERE id = $1 AND tenant_id = $2 AND status = 'failed'
            RETURNING *
            """,
            job_id, tenant_id, now,
        )
        return _job_row(dict(row)) if row is not None else None

    async def requeue_any(self, job_id: str) -> Optional[dict]:
        """Kyber operator requeue (cross-tenant): failed/expired/cancelled →
        queued with attempts reset. None when missing or not requeueable."""
        now = utc_now()
        requeueable = {
            JobStatus.FAILED.value, JobStatus.EXPIRED.value, JobStatus.CANCELLED.value,
        }
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_JOBS.get(job_id)
                if rec is None or rec["status"] not in requeueable:
                    return None
                self._mem_requeue(rec, now)
                return _job_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE jobs
            SET status = 'queued', attempts = 0, error = NULL, result = NULL,
                completed_at = NULL, leased_by = NULL, lease_expires_at = NULL,
                scheduled_for = NULL, updated_at = $2
            WHERE id = $1 AND status IN ('failed', 'expired', 'cancelled')
            RETURNING *
            """,
            job_id, now,
        )
        return _job_row(dict(row)) if row is not None else None

    # ── Jobs: reads ──────────────────────────────────────────────────────

    async def get_job(self, tenant_id: str, job_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            rec = _MEM_JOBS.get(job_id)
            if rec is None or rec["tenant_id"] != tenant_id:
                return None
            return _job_row(rec)
        row = await pool.fetchrow(
            "SELECT * FROM jobs WHERE id = $1 AND tenant_id = $2", job_id, tenant_id
        )
        return _job_row(dict(row)) if row is not None else None

    async def get_job_any(self, job_id: str) -> Optional[dict]:
        """Unscoped fetch — worker/operator internals only, never routes."""
        pool = await self._backend()
        if pool is None:
            rec = _MEM_JOBS.get(job_id)
            return _job_row(rec) if rec is not None else None
        row = await pool.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
        return _job_row(dict(row)) if row is not None else None

    async def list_jobs(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                _job_row(rec) for rec in _MEM_JOBS.values()
                if rec["tenant_id"] == tenant_id
                and (status is None or rec["status"] == status)
                and (job_type is None or rec["job_type"] == job_type)
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[offset: offset + limit]

        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        if status is not None:
            params.append(status)
            conditions.append(f"status = ${len(params)}")
        if job_type is not None:
            params.append(job_type)
            conditions.append(f"job_type = ${len(params)}")
        params.extend([limit, offset])
        rows = await pool.fetch(
            f"SELECT * FROM jobs WHERE {' AND '.join(conditions)} "
            f"ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}",
            *params,
        )
        return [_job_row(dict(r)) for r in rows]

    async def counts_by_status(self, tenant_id: str) -> dict[str, int]:
        pool = await self._backend()
        if pool is None:
            counts: dict[str, int] = {}
            for rec in _MEM_JOBS.values():
                if rec["tenant_id"] == tenant_id:
                    counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            return counts
        rows = await pool.fetch(
            "SELECT status, COUNT(*) AS cnt FROM jobs WHERE tenant_id = $1 GROUP BY status",
            tenant_id,
        )
        return {r["status"]: r["cnt"] for r in rows}

    async def count_active_for_schedule(self, schedule_id: str) -> int:
        pool = await self._backend()
        if pool is None:
            return len([
                rec for rec in _MEM_JOBS.values()
                if rec.get("schedule_id") == schedule_id
                and rec["status"] in ACTIVE_STATUSES
            ])
        row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM jobs WHERE schedule_id = $1 AND status = ANY($2::text[])",
            schedule_id, sorted(ACTIVE_STATUSES),
        )
        return row["cnt"] if row else 0

    # ── Job events ───────────────────────────────────────────────────────

    async def append_job_event(
        self,
        tenant_id: str,
        job_id: str,
        event_type: str,
        payload: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> dict:
        now = utc_now()
        event_id = new_id("jevt")
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                record = {
                    "id": event_id,
                    "tenant_id": tenant_id,
                    "job_id": job_id,
                    "event_type": event_type,
                    "correlation_id": correlation_id,
                    "payload": copy.deepcopy(payload or {}),
                    "created_at": now.isoformat(),
                }
                _MEM_JOB_EVENTS[event_id] = record
                return _event_row(record)

        row = await pool.fetchrow(
            "INSERT INTO job_events (id, tenant_id, job_id, event_type, correlation_id, "
            "payload, created_at) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7) RETURNING *",
            event_id, tenant_id, job_id, event_type, correlation_id,
            json.dumps(payload or {}, default=str), now,
        )
        return _event_row(dict(row))

    async def list_events(self, tenant_id: str, job_id: str) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                _event_row(rec) for rec in _MEM_JOB_EVENTS.values()
                if rec["tenant_id"] == tenant_id and rec["job_id"] == job_id
            ]
            rows.sort(key=lambda r: r["created_at"])
            return rows
        rows = await pool.fetch(
            "SELECT * FROM job_events WHERE tenant_id = $1 AND job_id = $2 "
            "ORDER BY created_at ASC",
            tenant_id, job_id,
        )
        return [_event_row(dict(r)) for r in rows]

    async def recent_events(
        self, *, tenant_id: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        """Newest-first event feed; unscoped when tenant_id is None (Kyber)."""
        pool = await self._backend()
        if pool is None:
            rows = [
                _event_row(rec) for rec in _MEM_JOB_EVENTS.values()
                if tenant_id is None or rec["tenant_id"] == tenant_id
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[:limit]
        if tenant_id is None:
            rows = await pool.fetch(
                "SELECT * FROM job_events ORDER BY created_at DESC LIMIT $1", limit
            )
        else:
            rows = await pool.fetch(
                "SELECT * FROM job_events WHERE tenant_id = $1 "
                "ORDER BY created_at DESC LIMIT $2",
                tenant_id, limit,
            )
        return [_event_row(dict(r)) for r in rows]

    # ── Schedules ────────────────────────────────────────────────────────

    async def create_schedule(
        self,
        tenant_id: str,
        *,
        name: str,
        job_type: str,
        cron_expression: str,
        timezone_name: str = "UTC",
        misfire_policy: str = "fire_once",
        overlap_policy: str = "skip",
        enabled: bool = True,
        owner_id: Optional[str] = None,
        payload: Optional[dict] = None,
        next_run_at: Any = None,
    ) -> dict:
        now = utc_now()
        schedule_id = new_id("sched")
        next_dt = _to_dt(next_run_at)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                record = {
                    "id": schedule_id,
                    "tenant_id": tenant_id,
                    "name": name,
                    "job_type": job_type,
                    "cron_expression": cron_expression,
                    "timezone": timezone_name,
                    "misfire_policy": misfire_policy,
                    "overlap_policy": overlap_policy,
                    "enabled": bool(enabled),
                    "owner_id": owner_id,
                    "next_run_at": _iso(next_dt),
                    "last_run_at": None,
                    "last_job_id": None,
                    "last_run_status": None,
                    "consecutive_failures": 0,
                    "payload": copy.deepcopy(payload or {}),
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                _MEM_SCHEDULES[schedule_id] = record
                return _schedule_row(record)

        row = await pool.fetchrow(
            """
            INSERT INTO job_schedules (
                id, tenant_id, name, job_type, cron_expression, timezone,
                misfire_policy, overlap_policy, enabled, owner_id, next_run_at,
                payload, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$13)
            RETURNING *
            """,
            schedule_id, tenant_id, name, job_type, cron_expression, timezone_name,
            misfire_policy, overlap_policy, bool(enabled), owner_id, next_dt,
            json.dumps(payload or {}, default=str), now,
        )
        return _schedule_row(dict(row))

    async def get_schedule(self, tenant_id: str, schedule_id: str) -> Optional[dict]:
        pool = await self._backend()
        if pool is None:
            rec = _MEM_SCHEDULES.get(schedule_id)
            if rec is None or rec["tenant_id"] != tenant_id:
                return None
            return _schedule_row(rec)
        row = await pool.fetchrow(
            "SELECT * FROM job_schedules WHERE id = $1 AND tenant_id = $2",
            schedule_id, tenant_id,
        )
        return _schedule_row(dict(row)) if row is not None else None

    async def list_schedules(
        self, tenant_id: str, *, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        pool = await self._backend()
        if pool is None:
            rows = [
                _schedule_row(rec) for rec in _MEM_SCHEDULES.values()
                if rec["tenant_id"] == tenant_id
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows[offset: offset + limit]
        rows = await pool.fetch(
            "SELECT * FROM job_schedules WHERE tenant_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            tenant_id, limit, offset,
        )
        return [_schedule_row(dict(r)) for r in rows]

    _SCHEDULE_UPDATABLE = {
        "name", "cron_expression", "timezone", "misfire_policy",
        "overlap_policy", "enabled", "payload", "next_run_at",
        "consecutive_failures",
    }

    async def update_schedule(
        self, tenant_id: str, schedule_id: str, updates: dict
    ) -> Optional[dict]:
        fields = {k: v for k, v in updates.items() if k in self._SCHEDULE_UPDATABLE}
        if not fields:
            return await self.get_schedule(tenant_id, schedule_id)
        now = utc_now()
        if "next_run_at" in fields:
            fields["next_run_at"] = _to_dt(fields["next_run_at"])
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_SCHEDULES.get(schedule_id)
                if rec is None or rec["tenant_id"] != tenant_id:
                    return None
                for key, value in fields.items():
                    if key == "next_run_at":
                        rec[key] = _iso(value)
                    elif key == "payload":
                        rec[key] = copy.deepcopy(value or {})
                    else:
                        rec[key] = value
                rec["updated_at"] = now.isoformat()
                return _schedule_row(rec)

        sets, params = [], []
        for key, value in fields.items():
            if key == "payload":
                params.append(json.dumps(value or {}, default=str))
                sets.append(f"payload = ${len(params) + 2}::jsonb")
            else:
                params.append(value)
                sets.append(f"{key} = ${len(params) + 2}")
        row = await pool.fetchrow(
            f"UPDATE job_schedules SET {', '.join(sets)}, "
            f"updated_at = ${len(params) + 3} "
            "WHERE id = $1 AND tenant_id = $2 RETURNING *",
            schedule_id, tenant_id, *params, now,
        )
        return _schedule_row(dict(row)) if row is not None else None

    async def delete_schedule(self, tenant_id: str, schedule_id: str) -> bool:
        pool = await self._backend()
        if pool is None:
            async with _mem_lock():
                rec = _MEM_SCHEDULES.get(schedule_id)
                if rec is None or rec["tenant_id"] != tenant_id:
                    return False
                del _MEM_SCHEDULES[schedule_id]
                return True
        result = await pool.execute(
            "DELETE FROM job_schedules WHERE id = $1 AND tenant_id = $2",
            schedule_id, tenant_id,
        )
        return bool(result) and result.endswith("1")

    async def due_schedules(self, now: Any = None) -> list[dict]:
        """Enabled schedules whose next_run_at is due — ALL tenants (the
        scheduler tick is a platform loop, not a tenant request path)."""
        now_dt = _to_dt(now) or utc_now()
        pool = await self._backend()
        if pool is None:
            rows = [
                _schedule_row(rec) for rec in _MEM_SCHEDULES.values()
                if rec["enabled"]
                and rec.get("next_run_at") is not None
                and _to_dt(rec["next_run_at"]) <= now_dt
            ]
            rows.sort(key=lambda r: r["next_run_at"])
            return rows
        rows = await pool.fetch(
            "SELECT * FROM job_schedules WHERE enabled = true "
            "AND next_run_at IS NOT NULL AND next_run_at <= $1 "
            "ORDER BY next_run_at ASC",
            now_dt,
        )
        return [_schedule_row(dict(r)) for r in rows]

    async def mark_fired(
        self,
        schedule_id: str,
        *,
        last_run_at: Any,
        next_run_at: Any,
        last_job_id: Optional[str] = None,
        last_run_status: str = "fired",
        consecutive_failures: int = 0,
        enabled: Optional[bool] = None,
    ) -> Optional[dict]:
        """Record the outcome of a scheduler tick for one schedule."""
        now = utc_now()
        last_dt = _to_dt(last_run_at)
        next_dt = _to_dt(next_run_at)
        pool = await self._backend()

        if pool is None:
            async with _mem_lock():
                rec = _MEM_SCHEDULES.get(schedule_id)
                if rec is None:
                    return None
                rec.update({
                    "last_run_at": _iso(last_dt),
                    "next_run_at": _iso(next_dt),
                    "last_job_id": last_job_id,
                    "last_run_status": last_run_status,
                    "consecutive_failures": int(consecutive_failures),
                    "updated_at": now.isoformat(),
                })
                if enabled is not None:
                    rec["enabled"] = bool(enabled)
                return _schedule_row(rec)

        row = await pool.fetchrow(
            """
            UPDATE job_schedules
            SET last_run_at = $2, next_run_at = $3, last_job_id = $4,
                last_run_status = $5, consecutive_failures = $6,
                enabled = COALESCE($7, enabled), updated_at = $8
            WHERE id = $1
            RETURNING *
            """,
            schedule_id, last_dt, next_dt, last_job_id, last_run_status,
            int(consecutive_failures), enabled, now,
        )
        return _schedule_row(dict(row)) if row is not None else None


_repo: Optional[JobsRepository] = None


def get_jobs_repository() -> JobsRepository:
    """Lazy process-wide singleton."""
    global _repo
    if _repo is None:
        _repo = JobsRepository()
    return _repo
