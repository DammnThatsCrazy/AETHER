"""
Aether Backend — Abandoned Budget Reservation Release Worker (A6)

Closes the reservation-leak gap in the durable budget lifecycle
(:mod:`services.rewards.budget`). Reservations are currently released only at
request time — reject/cancel/enqueue-failure paths in ``routes.py``. If a
reward's reservation never reaches a terminal state — the linked action sits in
``created``/``pending``/``ready``/``pending_approval`` forever, or the action row
never materialized — the outstanding budget is leaked until a human intervenes.

This module adds the recurring, durable release path:

    scan (expired, ``reserved``-only) → enqueue release job (idempotent per
    reservation) → lease → resolve (release OR commit) → audit trail → bounded
    retry → dead-letter

Design rules
------------
* **TTL-based.** Only reservations in ``reserved`` state older than
  ``REWARD_RESERVATION_TTL_SECONDS`` (default 3600s) are candidates. ``reserved``
  is the only state that leaks budget (``committed`` is final spend, ``released``
  already freed it), so scanning exactly that state is safe and minimal.
* **Resolve, don't blindly release.** If the linked reward action was actually
  delivered, the reservation is **committed** (spend is final and the budget
  usage is correct). Otherwise it is **released** (budget freed) and any leaked
  non-terminal action is marked ``failed``/abandoned so operators can see it.
* **Durable outbox.** Every resolution is a row in
  ``reward_reservation_release_jobs`` keyed by reservation id. A crash between
  release and audit still leaves a trace; failures retry with exponential
  backoff, bounded by ``REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS`` (default 5),
  and dead-letter after exhaustion.
* **Idempotent / concurrency-safe.** ``BudgetReservationService.release()`` and
  ``.commit()`` only transition ``reserved`` rows, and the job id is derived
  deterministically from the reservation id, so a re-scan or a concurrent worker
  can never double-release or double-commit.
* **Audit trail.** Every resolution appends an immutable entry to the reward
  audit log (``reward_audit_log``) with before/after state.

The worker is **not** auto-started here. The integration pass wires
``get_reservation_release_service().build_release_loop()`` into the runtime
supervisor (see wiringNeeds).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import timedelta
from typing import Any, Awaitable, Callable, Optional

from repositories.repos import BaseRepository
from services.rewards.budget import BudgetReservationService
from services.rewards.repositories import RewardActionRepository, RewardAuditRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.reservation_release")

_DEFAULT_TTL_SECONDS = 3600
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_INTERVAL_SECONDS = 300
_DEFAULT_BATCH_SIZE = 20
_DEFAULT_LEASE_SECONDS = 120

# Terminal action states where a reward is no longer "abandoned".
_DELIVERED_STATES = frozenset({"delivered"})
_TERMINAL_STATES = frozenset({"delivered", "committed", "rejected", "cancelled", "failed"})


def _now_iso() -> str:
    return utc_now().isoformat()


def _ttl_seconds() -> int:
    raw = os.getenv("REWARD_RESERVATION_TTL_SECONDS", "")
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            logger.warning("ignoring non-integer REWARD_RESERVATION_TTL_SECONDS %r", raw)
    return _DEFAULT_TTL_SECONDS


def _max_attempts() -> int:
    raw = os.getenv("REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS", "")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning("ignoring non-integer REWARD_RESERVATION_RELEASE_MAX_ATTEMPTS %r", raw)
    return _DEFAULT_MAX_ATTEMPTS


def _interval_seconds() -> float:
    raw = os.getenv("REWARD_RESERVATION_RELEASE_INTERVAL_SECONDS", "")
    if raw:
        try:
            return max(10.0, float(raw))
        except ValueError:
            logger.warning("ignoring non-numeric REWARD_RESERVATION_RELEASE_INTERVAL_SECONDS %r", raw)
    return _DEFAULT_INTERVAL_SECONDS


def _job_id(reservation_id: str) -> str:
    """Deterministic release-job id per reservation → idempotent enqueue."""
    return "rrj_" + hashlib.sha256(str(reservation_id).encode()).hexdigest()[:32]


# ═══════════════════════════════════════════════════════════════════════════
# READ-SIDE RESERVATION REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class RewardBudgetReservationRepository(BaseRepository):
    """Read-side access to ``reward_budget_reservations`` for the scanner.

    Shares the same backing store as ``BudgetReservationService``'s private
    reservation repo (both keyed by the table name), so a reservation created
    through the service is visible here — on Postgres and in-memory alike.
    """

    def __init__(self) -> None:
        super().__init__("reward_budget_reservations")

    async def find_expired(self, ttl_seconds: int, limit: int = 50) -> list[dict]:
        """Reservations in ``reserved`` state older than ``ttl_seconds``.

        Only ``reserved`` reservations can leak budget, so anything else
        (``committed``/``released``) is intentionally not a candidate.
        """
        pool = await self._ensure_pool()
        if pool is None:
            cutoff = (utc_now() - timedelta(seconds=ttl_seconds)).isoformat()
            return [
                r for r in self._store.values()
                if r.get("state") == "reserved"
                and r.get("reserved_at") and str(r["reserved_at"]) <= cutoff
            ][:limit]

        await self._ensure_table()
        try:
            rows = await pool.fetch(
                f"""
                SELECT data FROM {self.table_name}
                WHERE data->>'state' = 'reserved'
                  AND data->>'reserved_at' IS NOT NULL
                  AND (data->>'reserved_at')::timestamptz <= NOW() - ($1 * INTERVAL '1 second')
                ORDER BY (data->>'reserved_at')::timestamptz ASC
                LIMIT $2
                """,
                ttl_seconds, limit,
            )
            return [json.loads(row["data"]) for row in rows]
        except Exception as exc:
            # Fail-safe: on a query error fall back to the in-memory scan so the
            # worker never silently stops releasing abandoned reservations.
            logger.warning("reward reservation find_expired SQL failed, falling back: %s", exc)
            cutoff = (utc_now() - timedelta(seconds=ttl_seconds)).isoformat()
            return [
                r for r in self._store.values()
                if r.get("state") == "reserved"
                and r.get("reserved_at") and str(r["reserved_at"]) <= cutoff
            ][:limit]


# ═══════════════════════════════════════════════════════════════════════════
# DURABLE RELEASE-OUTBOX JOB REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class ReservationReleaseJobRepository(BaseRepository):
    """Durable outbox of abandoned-reservation resolution decisions.

    State machine: ``queued → leased → released | committed | skipped |
    dead_letter``. The job id is deterministic per reservation, so a re-scan
    re-arms only jobs that previously dead-lettered (never creates a duplicate
    runnable job).
    """

    def __init__(self) -> None:
        super().__init__("reward_reservation_release_jobs")

    async def ensure_enqueued(self, reservation: dict, reason: str) -> dict:
        """Idempotent enqueue. Returns the existing runnable job, or inserts."""
        res_id = str(reservation.get("id", ""))
        job_id = _job_id(res_id)
        existing = await self.find_by_id(job_id)
        if existing is not None and existing.get("state") not in ("released", "committed", "dead_letter"):
            return existing
        job = {
            "id": job_id,
            "reservation_id": res_id,
            "tenant_id": reservation.get("tenant_id"),
            "campaign_id": reservation.get("campaign_id"),
            "decision_id": reservation.get("decision_id"),
            "action_id": reservation.get("action_id"),
            "amount": reservation.get("amount"),
            "reason": reason,
            "state": "queued",
            "attempt_count": 0,
            "max_attempts": _max_attempts(),
            "next_attempt_at": _now_iso(),
            "lease_expires_at": None,
            "leased_by": None,
            "last_error": None,
        }
        if existing is not None:
            # Re-arm a previously dead-lettered job for the next scan.
            return await self.update(job_id, {**job, "attempt_count": 0})
        return await self.insert(job_id, job)

    async def lease_next(self, worker_id: str, batch_size: int, lease_seconds: int) -> list[dict]:
        """Lease runnable (queued/failed-with-due-attempt) jobs, lease-guarded.

        PostgreSQL: ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent workers
        never double-process. In-memory: cooperative lease with expiry.
        """
        pool = await self._ensure_pool()
        now_str = _now_iso()
        if pool is None:
            results: list[dict] = []
            for job in list(self._store.values()):
                if len(results) >= batch_size:
                    break
                state = job.get("state", "")
                lease_expires_at = job.get("lease_expires_at", "")
                expired_lease = state == "leased" and lease_expires_at and lease_expires_at <= now_str
                if not expired_lease and state not in ("queued", "failed"):
                    continue
                next_at = job.get("next_attempt_at", "")
                if next_at and next_at > now_str:
                    continue
                expire = (utc_now() + timedelta(seconds=lease_seconds)).isoformat()
                job["state"] = "leased"
                job["leased_by"] = worker_id
                job["lease_expires_at"] = expire
                job["updated_at"] = now_str
                results.append(job)
            return results

        await self._ensure_table()
        try:
            rows = await pool.fetch(
                f"""
                UPDATE {self.table_name}
                SET data = jsonb_set(
                        jsonb_set(
                            jsonb_set(data, '{{state}}', '"leased"'),
                            '{{leased_by}}', $1::jsonb
                        ),
                        '{{lease_expires_at}}',
                        to_jsonb((NOW() + ($3 * INTERVAL '1 second'))::text)
                    ),
                    updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM {self.table_name}
                    WHERE (
                            data->>'state' IN ('queued', 'failed')
                            OR (data->>'state' = 'leased'
                                AND (data->>'lease_expires_at')::timestamptz <= NOW())
                          )
                      AND (data->>'next_attempt_at' IS NULL
                           OR (data->>'next_attempt_at')::timestamptz <= NOW())
                    ORDER BY (data->>'next_attempt_at')::timestamptz ASC
                    LIMIT $2
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING data
                """,
                json.dumps(worker_id), batch_size, lease_seconds,
            )
            return [json.loads(r["data"]) for r in rows]
        except Exception as exc:
            logger.warning("reservation release lease_next failed: %s", exc)
            return []

    async def release_job(self, job_id: str, worker_id: str, update: dict) -> Optional[dict]:
        """Apply a post-processing state update only while this worker owns the
        lease — a stale worker must not overwrite a re-claimed job."""
        pool = await self._ensure_pool()
        now_str = _now_iso()
        if pool is None:
            job = self._store.get(job_id)
            if job is None:
                return None
            current_owner = job.get("leased_by")
            if current_owner is not None and current_owner != worker_id:
                logger.warning(
                    "reservation release_job skipped job=%s: lease held by %r (stale)",
                    job_id, current_owner,
                )
                return None
            job.update(update)
            job["updated_at"] = now_str
            return job

        await self._ensure_table()
        existing = await self.find_by_id(job_id)
        if existing is None:
            return None
        if existing.get("leased_by") not in (None, worker_id):
            logger.warning(
                "reservation release_job skipped job=%s: lease held by %r (stale)",
                job_id, existing.get("leased_by"),
            )
            return None
        merged = {**existing, **update}
        merged["updated_at"] = now_str
        try:
            row = await pool.fetchrow(
                f"""
                UPDATE {self.table_name}
                SET data = $2::jsonb, updated_at = NOW()
                WHERE id = $1
                  AND (data->>'leased_by' IS NULL OR data->>'leased_by' = $3)
                RETURNING data
                """,
                job_id, json.dumps(merged, default=str), worker_id,
            )
        except Exception as exc:
            logger.warning("reservation release_job update failed job=%s: %s", job_id, exc)
            return None
        if row is None:
            logger.warning("reservation release_job skipped job=%s: lease re-claimed while releasing", job_id)
            return None
        return json.loads(row["data"])

    async def status_counts(self) -> dict[str, int]:
        jobs = await self.find_many(filters={}, limit=100000)
        counts: dict[str, int] = {}
        for j in jobs:
            counts[j.get("state", "unknown")] = counts.get(j.get("state", "unknown"), 0) + 1
        return counts


# ═══════════════════════════════════════════════════════════════════════════
# RELEASE SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class ReservationReleaseService:
    """Scans expired reservations and durably resolves them (release/commit)."""

    def __init__(
        self,
        reservation_repo: Optional[RewardBudgetReservationRepository] = None,
        job_repo: Optional[ReservationReleaseJobRepository] = None,
        budget_service: Optional[BudgetReservationService] = None,
        action_repo: Optional[RewardActionRepository] = None,
        audit_repo: Optional[RewardAuditRepository] = None,
        *,
        worker_id: Optional[str] = None,
    ) -> None:
        self._reservations = reservation_repo or RewardBudgetReservationRepository()
        self._jobs = job_repo or ReservationReleaseJobRepository()
        self._budget = budget_service or BudgetReservationService()
        self._actions = action_repo or RewardActionRepository()
        self._audit = audit_repo or RewardAuditRepository()
        self._worker_id = worker_id or f"reservation-release-{uuid.uuid4().hex[:8]}"

    # ── public API ────────────────────────────────────────────────────────

    async def run_once(
        self,
        ttl_seconds: Optional[int] = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> dict:
        """Scan expired reservations, enqueue, lease, and resolve. Summary dict."""
        ttl = ttl_seconds or _ttl_seconds()
        expired = await self._reservations.find_expired(ttl, limit=batch_size)
        for res in expired:
            try:
                await self._jobs.ensure_enqueued(res, "reservation.ttl_expired")
            except Exception as exc:  # noqa: BLE001 - one bad enqueue must not stop the scan
                logger.warning("reservation release enqueue failed res=%s: %s", res.get("id"), exc)

        jobs = await self._jobs.lease_next(self._worker_id, batch_size, _DEFAULT_LEASE_SECONDS)
        released = committed = skipped = dead_lettered = 0
        for job in jobs:
            outcome = await self._resolve_job(job)
            if outcome == "released":
                released += 1
            elif outcome == "committed":
                committed += 1
            elif outcome == "dead_letter":
                dead_lettered += 1
            else:
                skipped += 1

        logger.info(
            "reservation release run_once scanned=%s leased=%s released=%s committed=%s skipped=%s dlq=%s",
            len(expired), len(jobs), released, committed, skipped, dead_lettered,
        )
        return {
            "scanned": len(expired),
            "leased": len(jobs),
            "released": released,
            "committed": committed,
            "dead_lettered": dead_lettered,
            "skipped": skipped,
            "ttl_seconds": ttl,
        }

    async def _resolve_job(self, job: dict) -> str:
        """Resolve one release job. Returns an outcome string."""
        job_id = job["id"]
        res_id = job.get("reservation_id")
        tenant_id = job.get("tenant_id", "")
        attempt = int(job.get("attempt_count", 0)) + 1
        max_attempts = int(job.get("max_attempts", _max_attempts()))

        reservation = await self._reservations.find_by_id(res_id) if res_id else None
        if reservation is None:
            # Reservation vanished → nothing left to free; resolve as released.
            await self._jobs.release_job(job_id, self._worker_id, {
                "state": "released", "attempt_count": attempt,
                "resolved_at": _now_iso(), "last_error": None,
                "leased_by": None, "lease_expires_at": None,
            })
            return "released"

        if reservation.get("state") != "reserved":
            # A request-time path already committed/released it → no-op.
            await self._jobs.release_job(job_id, self._worker_id, {
                "state": "skipped", "attempt_count": attempt,
                "resolved_at": _now_iso(), "last_error": f"already_{reservation.get('state')}",
                "leased_by": None, "lease_expires_at": None,
            })
            return "skipped"

        try:
            return await self._resolve_reserved(job, reservation, attempt, max_attempts, tenant_id)
        except Exception as exc:  # noqa: BLE001 - bounded retry on transient failure
            logger.warning("reservation release attempt failed job=%s: %s", job_id, exc)
            return await self._schedule_retry_or_dlq(job, attempt, max_attempts, str(exc))

    async def _resolve_reserved(self, job: dict, reservation: dict, attempt: int, max_attempts: int, tenant_id: str) -> str:
        job_id = job["id"]
        res_id = reservation["id"]
        action = await self._find_linked_action(reservation)

        if action is not None and action.get("status") in _DELIVERED_STATES:
            # The reward was actually delivered; the reservation is final spend.
            result = await self._budget.commit(res_id, tenant_id=tenant_id)
            kind = "committed"
            audit_action = "reservation.committed_recovered"
            audit_reason = "reservation.ttl_expired:action_delivered"
        else:
            # Abandoned (or no action): release the budget back to the campaign.
            result = await self._budget.release(res_id, tenant_id=tenant_id)
            kind = "released"
            audit_action = "reservation.released_abandoned"
            audit_reason = "reservation.ttl_expired:reward_abandoned"
            if action is not None and action.get("status") not in _TERMINAL_STATES:
                await self._mark_action_abandoned(action, tenant_id)

        if not result.ok:
            # Not reserved anymore (concurrent request-time path) → no-op, not a retry.
            await self._jobs.release_job(job_id, self._worker_id, {
                "state": "skipped", "attempt_count": attempt,
                "resolved_at": _now_iso(), "last_error": result.reason,
                "leased_by": None, "lease_expires_at": None,
            })
            return "skipped"

        await self._jobs.release_job(job_id, self._worker_id, {
            "state": kind, "attempt_count": attempt, "resolved_at": _now_iso(),
            f"{kind}_at": _now_iso(),
            "leased_by": None, "lease_expires_at": None, "last_error": None,
        })
        await self._append_audit(reservation, action, tenant_id, audit_action, audit_reason, result)
        metrics.increment(
            "rewards_reservation_release_resolved",
            labels={"tenant_id": tenant_id, "outcome": kind},
        )
        logger.info("reservation release resolved res=%s outcome=%s tenant=%s", res_id, kind, tenant_id)
        return kind

    async def _schedule_retry_or_dlq(self, job: dict, attempt: int, max_attempts: int, error: str) -> str:
        if attempt >= max_attempts:
            await self._jobs.release_job(job["id"], self._worker_id, {
                "state": "dead_letter", "attempt_count": attempt, "last_error": error[:500],
                "leased_by": None, "lease_expires_at": None,
            })
            metrics.increment(
                "rewards_reservation_release_dead_lettered",
                labels={"tenant_id": job.get("tenant_id", "")},
            )
            logger.error("reservation release DEAD-LETTER job=%s attempt=%s err=%s", job["id"], attempt, error[:200])
            return "dead_letter"
        from services.delivery.worker import _compute_next_attempt_at
        next_at = _compute_next_attempt_at(attempt)
        await self._jobs.release_job(job["id"], self._worker_id, {
            "state": "failed", "attempt_count": attempt, "last_error": error[:500],
            "next_attempt_at": next_at, "leased_by": None, "lease_expires_at": None,
        })
        logger.warning("reservation release retry job=%s attempt=%s/%s next=%s err=%s",
                       job["id"], attempt, max_attempts, next_at, error[:200])
        return "retry"

    # ── helpers ───────────────────────────────────────────────────────────

    async def _find_linked_action(self, reservation: dict) -> Optional[dict]:
        """Locate the reward action carrying this reservation (or decision)."""
        res_id = reservation.get("id")
        decision_id = reservation.get("decision_id")
        candidates: list[dict] = []
        if res_id:
            try:
                candidates.extend(
                    await self._actions.find_many(filters={"reservation_id": res_id}, limit=5)
                )
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("reservation action lookup by reservation failed: %s", exc)
        if not candidates and decision_id:
            try:
                candidates.extend(
                    await self._actions.find_many(filters={"decision_id": decision_id}, limit=5)
                )
            except Exception as exc:  # pragma: no cover - best-effort
                logger.warning("reservation action lookup by decision failed: %s", exc)
        if not candidates:
            return None
        candidates.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
        return candidates[0]

    async def _mark_action_abandoned(self, action: dict, tenant_id: str) -> None:
        action_id = action.get("id")
        if not action_id:
            return
        try:
            await self._actions.transition(
                action_id, tenant_id, "failed",
                extra={"abandoned_reason": "reservation.ttl_expired", "abandoned_by": "reservation_release_worker"},
            )
        except Exception as exc:  # pragma: no cover - non-fatal to the release
            logger.warning("reward action abandoned-mark failed action=%s: %s", action_id, exc)

    async def _append_audit(
        self,
        reservation: dict,
        action: Optional[dict],
        tenant_id: str,
        audit_action: str,
        reason: str,
        result: Any,
    ) -> None:
        try:
            await self._audit.append({
                "tenant_id": tenant_id,
                "actor_type": "system",
                "actor_id": "reservation_release_worker",
                "action": audit_action,
                "target_type": "reward_budget_reservation",
                "target_id": reservation.get("id"),
                "before_state": {
                    "state": reservation.get("state"),
                    "amount": reservation.get("amount"),
                    "campaign_id": reservation.get("campaign_id"),
                    "decision_id": reservation.get("decision_id"),
                },
                "after_state": {
                    "state": result.state,
                    "used": result.used,
                    "cap": result.cap,
                    "action_status": (action or {}).get("status"),
                },
                "reason": reason,
            })
        except Exception as exc:  # noqa: BLE001 - audit write must not break the release
            logger.warning("reservation release audit append failed (non-fatal): %s", exc)

    # ── supervised worker loop ────────────────────────────────────────────

    def build_release_loop(
        self,
        interval_s: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Callable[[], Awaitable[None]]:
        """Return an async loop that releases abandoned reservations periodically."""
        interval = interval_s or _interval_seconds()
        ttl = ttl_seconds or _ttl_seconds()

        async def _loop() -> None:
            logger.info("reservation_release_loop started interval=%ss ttl=%ss", interval, ttl)
            while True:
                try:
                    summary = await self.run_once(ttl_seconds=ttl)
                    if summary["leased"]:
                        logger.info(
                            "reservation release iteration leased=%s released=%s committed=%s dlq=%s",
                            summary["leased"], summary["released"], summary["committed"], summary["dead_lettered"],
                        )
                except asyncio.CancelledError:
                    logger.info("reservation_release_loop stopped")
                    raise
                except Exception as exc:  # noqa: BLE001 - loop survives transient failures
                    logger.error("reservation release iteration failed: %s", exc)
                await asyncio.sleep(interval)

        return _loop


# ── Module-level singleton ──────────────────────────────────────────────

_release_service: Optional[ReservationReleaseService] = None


def get_reservation_release_service() -> ReservationReleaseService:
    global _release_service
    if _release_service is None:
        _release_service = ReservationReleaseService()
    return _release_service


def reset_reservation_release_service() -> None:
    """Reset the release service singleton — for tests only."""
    global _release_service
    _release_service = None


__all__ = [
    "RewardBudgetReservationRepository",
    "ReservationReleaseJobRepository",
    "ReservationReleaseService",
    "get_reservation_release_service",
    "reset_reservation_release_service",
]
