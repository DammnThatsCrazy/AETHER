"""
Aether Service — Jobs Platform Service Layer

Tenant-facing operations over the durable jobs control plane. Every state
transition is persisted through JobsRepository first, then mirrored to the
job_events timeline and (best-effort) the event bus — a bus outage can never
roll back or block a durable transition.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.logger.logger import get_logger, metrics

from repositories.jobs_repo import JobsRepository, get_jobs_repository
from services.jobs.models import JobStatus, TERMINAL_STATUSES
from shared.observability import new_traceparent

logger = get_logger("aether.service.jobs")

# Job lifecycle → bus topic (Topic enum member names in shared.events.events).
_STATUS_TOPIC_ATTR = {
    JobStatus.ACCEPTED.value: "JOB_ACCEPTED",
    JobStatus.QUEUED.value: "JOB_QUEUED",
    JobStatus.RUNNING.value: "JOB_STARTED",
    JobStatus.RETRYING.value: "JOB_RETRYING",
    JobStatus.SUCCEEDED.value: "JOB_SUCCEEDED",
    JobStatus.PARTIALLY_SUCCEEDED.value: "JOB_PARTIALLY_SUCCEEDED",
    JobStatus.FAILED.value: "JOB_FAILED",
    JobStatus.CANCELLED.value: "JOB_CANCELLED",
    JobStatus.EXPIRED.value: "JOB_EXPIRED",
}


async def publish_platform_topic(
    topic_attr: str,
    tenant_id: str,
    payload: dict,
    correlation_id: str = "",
) -> None:
    """Best-effort bus publish for jobs-platform lifecycle topics.

    Mirrors services/suggestions/events.py: durable state is already
    committed by the time this runs, so every failure (missing topic,
    unreachable broker, provider wiring) is logged and swallowed.
    """
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_attr, None)
        if topic is None:
            logger.warning(f"Unknown jobs-platform topic attr {topic_attr!r} — skipping emit")
            return

        from dependencies.providers import get_producer

        event = Event(
            topic=topic,
            tenant_id=tenant_id,
            source_service="jobs",
            correlation_id=correlation_id or "",
            payload=payload,
        )
        await get_producer().publish(event)
    except Exception as exc:  # noqa: BLE001 — bus emit must never break the control plane
        logger.warning(f"Jobs-platform event publish failed ({topic_attr}): {exc}")


def job_status_topic_attr(status: str) -> Optional[str]:
    """Topic enum attr for a job lifecycle status (None for cancel_requested)."""
    return _STATUS_TOPIC_ATTR.get(status)


def _job_event_payload(job: dict) -> dict:
    return {
        "job_id": job.get("id"),
        "tenant_id": job.get("tenant_id"),
        "job_type": job.get("job_type"),
        "status": job.get("status"),
        "attempts": job.get("attempts"),
        "schedule_id": job.get("schedule_id"),
    }


class JobsService:
    """Tenant-scoped orchestration over JobsRepository."""

    def __init__(self, repo: Optional[JobsRepository] = None) -> None:
        self._repo = repo or get_jobs_repository()

    @property
    def repo(self) -> JobsRepository:
        return self._repo

    # ── Enqueue ──────────────────────────────────────────────────────────

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
    ) -> dict:
        """Durably enqueue a job. Replays (idempotency hits) are returned
        with ``replayed=True`` and emit no new events."""
        if not tenant_id:
            raise BadRequestError("tenant_id is required")
        if not job_type or not isinstance(job_type, str):
            raise BadRequestError("job_type must be a non-empty string")
        if payload is not None and not isinstance(payload, dict):
            raise BadRequestError("payload must be an object")
        if max_attempts < 1:
            raise BadRequestError("max_attempts must be >= 1")

        payload = dict(payload or {})
        # Trace-context seam: stamp the enqueue hop so the worker's execution
        # can continue the same trace. No-op unless AETHER_OTEL_ENABLED.
        if "_traceparent" not in payload:
            traceparent = new_traceparent()
            if traceparent is not None:
                payload["_traceparent"] = traceparent

        job = await self._repo.enqueue(
            tenant_id,
            job_type,
            payload,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            requested_by=requested_by,
            priority=priority,
            max_attempts=max_attempts,
            scheduled_for=scheduled_for,
        )
        if not job.get("replayed"):
            await self._repo.append_job_event(
                tenant_id, job["id"], "job.queued",
                payload=_job_event_payload(job),
                correlation_id=job.get("correlation_id"),
            )
            await publish_platform_topic(
                "JOB_QUEUED", tenant_id, _job_event_payload(job),
                correlation_id=job.get("correlation_id") or "",
            )
            metrics.increment("jobs_enqueued", labels={"job_type": job_type})
        else:
            metrics.increment("jobs_enqueue_replayed", labels={"job_type": job_type})
        return job

    # ── Reads ────────────────────────────────────────────────────────────

    async def get_job(self, tenant_id: str, job_id: str) -> Optional[dict]:
        return await self._repo.get_job(tenant_id, job_id)

    async def list_jobs(
        self,
        tenant_id: str,
        *,
        status: Optional[str] = None,
        job_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        if status is not None:
            try:
                status = JobStatus(status).value
            except ValueError:
                raise BadRequestError(f"Unknown job status {status!r}")
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        return await self._repo.list_jobs(
            tenant_id, status=status, job_type=job_type, limit=limit, offset=offset
        )

    async def list_events(self, tenant_id: str, job_id: str) -> list[dict]:
        job = await self._repo.get_job(tenant_id, job_id)
        if job is None:
            raise NotFoundError("job")
        return await self._repo.list_events(tenant_id, job_id)

    async def summary(self, tenant_id: str) -> dict:
        counts = await self._repo.counts_by_status(tenant_id)
        return {
            "by_status": {s.value: counts.get(s.value, 0) for s in JobStatus},
            "total": sum(counts.values()),
            "active": sum(
                counts.get(s, 0) for s in counts if s not in TERMINAL_STATUSES
            ),
        }

    # ── Cancel / retry ───────────────────────────────────────────────────

    async def cancel(self, tenant_id: str, job_id: str) -> dict:
        """queued/retrying/accepted → cancelled; running → cancel_requested."""
        job = await self._repo.get_job(tenant_id, job_id)
        if job is None:
            raise NotFoundError("job")
        if job["status"] in TERMINAL_STATUSES:
            raise ConflictError(f"Cannot cancel job in status '{job['status']}'")
        if job["status"] == JobStatus.CANCEL_REQUESTED.value:
            return job  # idempotent duplicate cancel

        updated = await self._repo.request_cancel(tenant_id, job_id)
        event_type = (
            "job.cancelled"
            if updated["status"] == JobStatus.CANCELLED.value
            else "job.cancel_requested"
        )
        await self._repo.append_job_event(
            tenant_id, job_id, event_type,
            payload=_job_event_payload(updated),
            correlation_id=updated.get("correlation_id"),
        )
        if updated["status"] == JobStatus.CANCELLED.value:
            await publish_platform_topic(
                "JOB_CANCELLED", tenant_id, _job_event_payload(updated),
                correlation_id=updated.get("correlation_id") or "",
            )
        metrics.increment("jobs_cancel_requested", labels={"job_type": updated["job_type"]})
        return updated

    async def retry(self, tenant_id: str, job_id: str) -> dict:
        """Reset a failed job to queued (attempts=0)."""
        job = await self._repo.get_job(tenant_id, job_id)
        if job is None:
            raise NotFoundError("job")
        if job["status"] != JobStatus.FAILED.value:
            raise ConflictError(f"Cannot retry job in status '{job['status']}'")

        updated = await self._repo.retry(tenant_id, job_id)
        if updated is None:  # lost a race with another transition
            raise ConflictError("Job left 'failed' concurrently; retry aborted")
        await self._repo.append_job_event(
            tenant_id, job_id, "job.queued",
            payload={**_job_event_payload(updated), "retried": True},
            correlation_id=updated.get("correlation_id"),
        )
        await publish_platform_topic(
            "JOB_QUEUED", tenant_id,
            {**_job_event_payload(updated), "retried": True},
            correlation_id=updated.get("correlation_id") or "",
        )
        metrics.increment("jobs_retried", labels={"job_type": updated["job_type"]})
        return updated


_service: Optional[JobsService] = None


def get_jobs_service() -> JobsService:
    """Lazy process-wide singleton."""
    global _service
    if _service is None:
        _service = JobsService()
    return _service
