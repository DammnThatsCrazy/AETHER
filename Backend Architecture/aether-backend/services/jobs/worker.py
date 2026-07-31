"""
Aether Service — Jobs Platform Worker

Claims durable jobs from JobsRepository (FOR UPDATE SKIP LOCKED in Postgres,
lock-guarded dicts locally), resolves the handler from HANDLER_REGISTRY and
drives the execution lifecycle:

    queued/retrying ──claim──▶ running ──▶ succeeded | partially_succeeded
                                  │
                                  ├─ JobCancelled ──▶ cancelled
                                  ├─ exception / timeout / JobOutcome(failed)
                                  │      attempts < max ──▶ retrying (backoff)
                                  │      else ──▶ failed + dead-letter
                                  └─ lease lost ──▶ (sweeper reclaims)

Every transition appends a job_events row (durable, always) and publishes the
matching ``aether.job.*`` topic (best-effort, never crashes the worker).

Supervisor wiring: the runtime supervisor (wired by the orchestrator) calls
``build_job_worker_coro()`` / ``build_lease_sweeper_coro()`` — zero-arg
factories returning long-running coroutines.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import timedelta
from typing import Coroutine, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.observability import child_traceparent

from repositories.jobs_repo import JobsRepository, get_jobs_repository
from services.jobs.handlers import (
    HANDLER_REGISTRY,
    VALID_OUTCOME_STATUSES,
    JobContext,
    JobOutcome,
)
from services.jobs.models import JobStatus
from services.jobs.service import (
    _job_event_payload,
    job_status_topic_attr,
    publish_platform_topic,
)

logger = get_logger("aether.service.jobs.worker")

DEFAULT_LEASE_SECONDS = int(os.getenv("JOBS_LEASE_SECONDS", "60"))
DEFAULT_POLL_INTERVAL_SECONDS = float(os.getenv("JOBS_POLL_INTERVAL_SECONDS", "1.0"))
SWEEP_INTERVAL_SECONDS = float(os.getenv("JOBS_SWEEP_INTERVAL_SECONDS", "30"))
# Retry backoff: BASE * 2^(attempts-1), capped.
BACKOFF_BASE_SECONDS = float(os.getenv("JOBS_BACKOFF_BASE_SECONDS", "5"))
BACKOFF_CAP_SECONDS = float(os.getenv("JOBS_BACKOFF_CAP_SECONDS", "300"))

_ERROR_MAX_LENGTH = 2000


class JobCancelled(Exception):
    """Raised inside a handler (via ctx.heartbeat) when cancellation was
    requested for the running job."""


def _bounded_error(error: object) -> str:
    text = str(error) if error is not None else ""
    return text[:_ERROR_MAX_LENGTH] or "unknown error"


async def _notify_dead_letter(job: dict) -> None:
    """Best-effort operator inbox notification for a dead-lettered job.

    services.notification_intelligence.inbox is developed in parallel —
    guard both its absence (ImportError) and any runtime failure so the
    worker never crashes on notification delivery.

    Best-effort does not mean silent: a dropped dead-letter notification is
    an operator alert that never arrived, so every drop is logged at error
    level with the job id and counted, instead of vanishing.
    """
    try:
        from services.notification_intelligence.inbox import create_inbox_notification
    except ImportError:
        logger.error(
            f"Dead-letter notification dropped for job {job.get('id')}: "
            "notification_intelligence inbox is unavailable"
        )
        metrics.increment(
            "jobs_dead_letter_notify_dropped", labels={"reason": "inbox_unavailable"}
        )
        return
    except Exception as exc:  # noqa: BLE001 — import-time side effects must not kill the worker
        logger.error(
            f"Dead-letter notification dropped for job {job.get('id')}: "
            f"inbox module failed to import: {exc}",
            exc_info=True,
        )
        metrics.increment(
            "jobs_dead_letter_notify_dropped", labels={"reason": "inbox_import_failed"}
        )
        return
    try:
        await create_inbox_notification(
            job["tenant_id"],
            category="jobs",
            severity="error",
            title=f"Job dead-lettered: {job.get('job_type')}",
            body=(
                f"Job {job.get('id')} ({job.get('job_type')}) failed after "
                f"{job.get('attempts')} attempt(s): {job.get('error') or 'unknown error'}"
            ),
            correlation_id=job.get("correlation_id"),
            dedupe_key=f"job:{job.get('id')}:dead_lettered",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            f"Dead-letter notification dropped for job {job.get('id')}: "
            f"inbox delivery failed: {exc}",
            exc_info=True,
        )
        metrics.increment(
            "jobs_dead_letter_notify_dropped", labels={"reason": "delivery_failed"}
        )


class JobWorker:
    """Single-consumer claim/execute loop over the durable jobs table."""

    def __init__(
        self,
        repo: Optional[JobsRepository] = None,
        worker_id: Optional[str] = None,
        job_types: Optional[list[str]] = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        backoff_cap_seconds: float = BACKOFF_CAP_SECONDS,
    ) -> None:
        self.repo = repo or get_jobs_repository()
        self.worker_id = worker_id or f"jobworker_{uuid.uuid4().hex[:12]}"
        self.job_types = job_types
        self.lease_seconds = lease_seconds
        self.poll_interval = poll_interval
        self.backoff_base_seconds = backoff_base_seconds
        self.backoff_cap_seconds = backoff_cap_seconds

    # ── Loop ─────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        logger.info(f"JobWorker {self.worker_id} started (types={self.job_types or 'all'})")
        while True:
            try:
                claimed = await self.run_once()
            except asyncio.CancelledError:
                logger.info(f"JobWorker {self.worker_id} stopped")
                raise
            except Exception as exc:  # noqa: BLE001 — the loop must survive anything
                logger.error(f"JobWorker {self.worker_id} loop error: {exc}")
                claimed = False
            if not claimed:
                await asyncio.sleep(self.poll_interval)

    async def run_once(self) -> bool:
        """Claim and fully process at most one job. True when one was claimed."""
        job = await self.repo.claim_next(
            self.worker_id, job_types=self.job_types, lease_seconds=self.lease_seconds
        )
        if job is None:
            return False
        await self._execute(job)
        return True

    # ── Execution ────────────────────────────────────────────────────────

    async def _execute(self, job: dict) -> None:
        tenant_id = job["tenant_id"]
        job_id = job["id"]
        correlation_id = job.get("correlation_id") or ""

        started_extra: dict = {"worker_id": self.worker_id}
        # Trace-context seam: continue the enqueue hop's trace (new span, same
        # trace id) so enqueue and execution correlate. None unless
        # AETHER_OTEL_ENABLED — see shared/observability.py.
        traceparent = child_traceparent((job.get("payload") or {}).get("_traceparent"))
        if traceparent is not None:
            started_extra["traceparent"] = traceparent

        await self._record(job, "job.started", extra=started_extra)

        handler = HANDLER_REGISTRY.get(job["job_type"])
        if handler is None:
            failed = await self.repo.finish(
                job_id, JobStatus.FAILED.value,
                error=f"unknown job_type '{job['job_type']}' — no handler registered",
            )
            await self._record(failed or job, "job.failed", extra={"reason": "unknown_job_type"})
            metrics.increment("jobs_unknown_type", labels={"job_type": job["job_type"]})
            return

        async def heartbeat() -> bool:
            ok = await self.repo.heartbeat(job_id, self.worker_id, self.lease_seconds)
            if ok:
                return True
            current = await self.repo.get_job_any(job_id)
            if current and current.get("status") == JobStatus.CANCEL_REQUESTED.value:
                raise JobCancelled(f"Cancellation requested for job {job_id}")
            return False  # lease lost — the sweeper owns this row now

        async def emit_event(event_type: str, payload: dict) -> None:
            try:
                await self.repo.append_job_event(
                    tenant_id, job_id, event_type,
                    payload=payload, correlation_id=correlation_id,
                )
            except Exception as exc:  # noqa: BLE001 — progress events are best-effort
                logger.warning(f"emit_event({event_type}) failed for {job_id}: {exc}")

        ctx = JobContext(
            job_id=job_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            heartbeat=heartbeat,
            emit_event=emit_event,
        )

        timeout = job.get("timeout_seconds") or 3600
        try:
            outcome = await asyncio.wait_for(
                handler(job.get("payload") or {}, ctx), timeout=timeout
            )
        except JobCancelled:
            cancelled = await self.repo.finish(
                job_id, JobStatus.CANCELLED.value, error="cancelled by request"
            )
            await self._record(cancelled or job, "job.cancelled")
            metrics.increment("jobs_cancelled", labels={"job_type": job["job_type"]})
            return
        except asyncio.CancelledError:
            raise  # worker shutdown — the lease sweeper will reclaim the job
        except asyncio.TimeoutError:
            await self._fail_or_retry(job, f"timed out after {timeout}s")
            return
        except Exception as exc:  # noqa: BLE001 — handler failures are data, not crashes
            await self._fail_or_retry(job, _bounded_error(exc))
            return

        if not isinstance(outcome, JobOutcome) or outcome.status not in VALID_OUTCOME_STATUSES:
            await self._fail_or_retry(
                job, f"handler returned invalid outcome: {outcome!r}"
            )
            return

        if outcome.status == "failed":
            await self._fail_or_retry(job, _bounded_error(outcome.error or "handler reported failure"))
            return

        status = (
            JobStatus.SUCCEEDED.value
            if outcome.status == "succeeded"
            else JobStatus.PARTIALLY_SUCCEEDED.value
        )
        finished = await self.repo.finish(
            job_id, status, result=outcome.result or {}, error=outcome.error
        )
        await self._record(finished or job, f"job.{status}")
        metrics.increment("jobs_completed", labels={"job_type": job["job_type"], "status": status})

    async def _fail_or_retry(self, job: dict, error: str) -> None:
        """attempts < max → retrying with exponential backoff; else failed + DLQ."""
        attempts = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or 1)
        if attempts < max_attempts:
            backoff = min(
                self.backoff_cap_seconds,
                self.backoff_base_seconds * (2 ** max(0, attempts - 1)),
            )
            retrying = await self.repo.finish(
                job["id"], JobStatus.RETRYING.value, error=error,
                scheduled_for=utc_now() + timedelta(seconds=backoff),
            )
            await self._record(
                retrying or job, "job.retrying",
                extra={"error": error, "backoff_seconds": backoff},
            )
            metrics.increment("jobs_retrying", labels={"job_type": job["job_type"]})
            return
        failed = await self.repo.finish(job["id"], JobStatus.FAILED.value, error=error)
        await self.dead_letter(failed or {**job, "status": JobStatus.FAILED.value, "error": error})

    async def dead_letter(self, job: dict) -> None:
        """Terminal failure: job.failed + job.dead_lettered events, topics,
        and a best-effort operator inbox notification."""
        await self._record(job, "job.failed", extra={"error": job.get("error")})
        try:
            await self.repo.append_job_event(
                job["tenant_id"], job["id"], "job.dead_lettered",
                payload={**_job_event_payload(job), "error": job.get("error")},
                correlation_id=job.get("correlation_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to append dead-letter event for {job.get('id')}: {exc}")
        await publish_platform_topic(
            "JOB_DEAD_LETTERED", job["tenant_id"],
            {**_job_event_payload(job), "error": job.get("error")},
            correlation_id=job.get("correlation_id") or "",
        )
        await _notify_dead_letter(job)
        metrics.increment("jobs_dead_lettered", labels={"job_type": job.get("job_type", "")})

    async def _record(self, job: dict, event_type: str, extra: Optional[dict] = None) -> None:
        """Durable job_events append + best-effort topic publish for a
        lifecycle transition."""
        payload = {**_job_event_payload(job), **(extra or {})}
        try:
            await self.repo.append_job_event(
                job["tenant_id"], job["id"], event_type,
                payload=payload, correlation_id=job.get("correlation_id"),
            )
        except Exception as exc:  # noqa: BLE001 — timeline must not kill execution
            logger.error(f"Failed to append {event_type} for {job.get('id')}: {exc}")
        topic_attr = job_status_topic_attr(job.get("status", ""))
        # job.started fires while status is 'running'; map through the status.
        if topic_attr:
            await publish_platform_topic(
                topic_attr, job["tenant_id"], payload,
                correlation_id=job.get("correlation_id") or "",
            )


class LeaseSweeper:
    """Periodic reaper for expired leases and expired queued jobs."""

    def __init__(
        self,
        repo: Optional[JobsRepository] = None,
        interval_seconds: float = SWEEP_INTERVAL_SECONDS,
    ) -> None:
        self.repo = repo or get_jobs_repository()
        self.interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        logger.info("Jobs lease sweeper started")
        while True:
            try:
                await self.sweep_once()
            except asyncio.CancelledError:
                logger.info("Jobs lease sweeper stopped")
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Jobs lease sweep error: {exc}")
            await asyncio.sleep(self.interval_seconds)

    async def sweep_once(self) -> dict:
        """One sweep pass; returns counts for observability/tests."""
        lease_swept = await self.repo.sweep_expired_leases()
        for job in lease_swept:
            await self._record_swept(job)
        expired = await self.repo.sweep_expired_jobs()
        for job in expired:
            await self._append_and_publish(job, "job.expired", {"reason": "expires_at passed"})
        if lease_swept or expired:
            metrics.increment("jobs_swept", value=len(lease_swept) + len(expired))
        return {"lease_swept": len(lease_swept), "expired": len(expired)}

    async def _record_swept(self, job: dict) -> None:
        status = job.get("status")
        if status == JobStatus.RETRYING.value:
            await self._append_and_publish(job, "job.retrying", {"reason": "lease expired"})
        elif status == JobStatus.CANCELLED.value:
            await self._append_and_publish(job, "job.cancelled", {"reason": "lease expired"})
        elif status == JobStatus.FAILED.value:
            # Exhausted attempts via a dead worker — full dead-letter flow.
            await JobWorker(repo=self.repo).dead_letter(job)

    async def _append_and_publish(self, job: dict, event_type: str, extra: dict) -> None:
        try:
            await self.repo.append_job_event(
                job["tenant_id"], job["id"], event_type,
                payload={**_job_event_payload(job), **extra},
                correlation_id=job.get("correlation_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to append {event_type} for {job.get('id')}: {exc}")
        topic_attr = job_status_topic_attr(job.get("status", ""))
        if topic_attr:
            await publish_platform_topic(
                topic_attr, job["tenant_id"],
                {**_job_event_payload(job), **extra},
                correlation_id=job.get("correlation_id") or "",
            )


# ── Supervisor coroutine factories (wired by the runtime orchestrator) ──────

def build_job_worker_coro() -> Coroutine:
    """Zero-arg factory: a fresh long-running job worker coroutine."""
    return JobWorker().run_forever()


def build_lease_sweeper_coro() -> Coroutine:
    """Zero-arg factory: a fresh long-running lease/expiry sweeper coroutine."""
    return LeaseSweeper().run_forever()
