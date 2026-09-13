"""
Aether Service — Jobs Platform Scheduler

Cron-driven job scheduling over the durable ``job_schedules`` table.
Every ~30s the tick loop:

1. loads due schedules (enabled, next_run_at <= now — all tenants);
2. applies the overlap policy — ``skip`` refuses to enqueue while an
   active job for the schedule exists (schedule.skipped event);
3. applies the misfire policy when the schedule is more than one cron
   interval behind — ``fire_once`` coalesces all missed fires into a
   single run, ``skip`` drops them (schedule.misfired event);
4. enqueues with the STABLE idempotency key ``{schedule_id}:{fire_time}``
   so a crashed/replayed tick can never double-fire;
5. advances next_run_at via croniter evaluated in the schedule's IANA
   timezone (zoneinfo) — DST gaps/overlaps are handled by croniter;
6. tracks last_run_* / consecutive_failures and auto-disables a schedule
   after MAX_SCHEDULE_CONSECUTIVE_FAILURES consecutive tick failures.

Supervisor wiring: ``build_schedule_tick_coro()`` (zero-arg factory).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Coroutine, Optional
from zoneinfo import ZoneInfo

from croniter import croniter

from shared.common.common import BadRequestError, utc_now
from shared.logger.logger import get_logger, metrics

from repositories.jobs_repo import JobsRepository, _to_dt, get_jobs_repository
from services.jobs.models import (
    MAX_SCHEDULE_CONSECUTIVE_FAILURES,
    MisfirePolicy,
    OverlapPolicy,
)
from services.jobs.service import _job_event_payload, publish_platform_topic

logger = get_logger("aether.service.jobs.scheduler")

SCHEDULE_TICK_SECONDS = float(os.getenv("JOBS_SCHEDULE_TICK_SECONDS", "30"))


def validate_cron_expression(cron_expression: str) -> None:
    """Raise BadRequestError for an invalid 5-field cron expression."""
    if not cron_expression or not croniter.is_valid(cron_expression):
        raise BadRequestError(f"Invalid cron expression: {cron_expression!r}")


def validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except Exception:  # ZoneInfoNotFoundError, ValueError
        raise BadRequestError(f"Unknown IANA timezone: {timezone_name!r}")


def compute_next_run(
    cron_expression: str, timezone_name: str, after: datetime
) -> datetime:
    """Next fire time strictly after ``after``, returned tz-aware in UTC.

    The cron expression is evaluated in the schedule's IANA timezone so
    wall-clock semantics survive DST transitions (croniter rolls times that
    fall into a spring-forward gap onto the next valid instant).
    """
    tz = ZoneInfo(timezone_name or "UTC")
    if after.tzinfo is None:
        after = after.replace(tzinfo=timezone.utc)
    local_after = after.astimezone(tz)
    next_local = croniter(cron_expression, local_after).get_next(datetime)
    return next_local.astimezone(timezone.utc)


class JobScheduler:
    """30-second tick loop that turns due job_schedules rows into jobs."""

    def __init__(
        self,
        repo: Optional[JobsRepository] = None,
        tick_seconds: float = SCHEDULE_TICK_SECONDS,
    ) -> None:
        self.repo = repo or get_jobs_repository()
        self.tick_seconds = tick_seconds

    async def run_forever(self) -> None:
        logger.info("Job scheduler started")
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                logger.info("Job scheduler stopped")
                raise
            except Exception as exc:  # noqa: BLE001 — the loop must survive anything
                logger.error(f"Job scheduler tick error: {exc}")
            await asyncio.sleep(self.tick_seconds)

    async def tick(self, now: Any = None) -> list[dict]:
        """Process all due schedules; returns per-schedule action records
        (``{"schedule_id", "action", "job_id"?}``) for observability/tests."""
        now_dt = _to_dt(now) or utc_now()
        actions: list[dict] = []
        for schedule in await self.repo.due_schedules(now_dt):
            try:
                actions.append(await self._process_schedule(schedule, now_dt))
            except Exception as exc:  # noqa: BLE001 — one broken schedule must not stall the rest
                actions.append(await self._record_failure(schedule, now_dt, exc))
        return actions

    # ── Per-schedule processing ──────────────────────────────────────────

    async def _process_schedule(self, schedule: dict, now: datetime) -> dict:
        schedule_id = schedule["id"]
        tenant_id = schedule["tenant_id"]
        cron = schedule["cron_expression"]
        tz_name = schedule.get("timezone") or "UTC"
        due = _to_dt(schedule["next_run_at"])
        fire_time = due

        # One cron interval, measured from the due fire itself.
        interval = compute_next_run(cron, tz_name, after=due) - due
        misfired = (now - due) > interval
        next_run = compute_next_run(cron, tz_name, after=now)

        # Overlap policy first: a still-active previous run wins over misfire
        # handling — firing on top of it is what the policy forbids.
        if (
            schedule.get("overlap_policy") == OverlapPolicy.SKIP.value
            and await self.repo.count_active_for_schedule(schedule_id) > 0
        ):
            await self._schedule_event(
                schedule, "schedule.skipped",
                {"reason": "previous run still active", "due": due.isoformat()},
                topic_attr="SCHEDULE_SKIPPED",
            )
            await self.repo.mark_fired(
                schedule_id,
                last_run_at=now, next_run_at=next_run,
                last_job_id=schedule.get("last_job_id"),
                last_run_status="skipped",
                consecutive_failures=int(schedule.get("consecutive_failures") or 0),
            )
            metrics.increment("job_schedule_skipped")
            return {"schedule_id": schedule_id, "action": "skipped_overlap"}

        if misfired:
            await self._schedule_event(
                schedule, "schedule.misfired",
                {
                    "due": due.isoformat(),
                    "behind_seconds": (now - due).total_seconds(),
                    "misfire_policy": schedule.get("misfire_policy"),
                },
                topic_attr="SCHEDULE_MISFIRED",
            )
            metrics.increment("job_schedule_misfired")
            if schedule.get("misfire_policy") == MisfirePolicy.SKIP.value:
                # Drop the missed fires entirely and realign with the cron.
                await self.repo.mark_fired(
                    schedule_id,
                    last_run_at=now, next_run_at=next_run,
                    last_job_id=schedule.get("last_job_id"),
                    last_run_status="misfired",
                    consecutive_failures=int(schedule.get("consecutive_failures") or 0),
                )
                return {"schedule_id": schedule_id, "action": "misfire_skipped"}
            # fire_once: coalesce every missed fire into ONE run for the
            # original due time (stable fire_time → stable idempotency key).

        # Enqueue directly through the repository so the schedule linkage
        # (schedule_id column) is recorded with the job row.
        job = await self.repo.enqueue(
            tenant_id,
            schedule["job_type"],
            schedule.get("payload") or {},
            idempotency_key=f"{schedule_id}:{fire_time.isoformat()}",
            correlation_id=f"schedule:{schedule_id}",
            requested_by="scheduler",
            schedule_id=schedule_id,
        )
        if not job.get("replayed"):
            await self.repo.append_job_event(
                tenant_id, job["id"], "job.queued",
                payload={**_job_event_payload(job), "fire_time": fire_time.isoformat()},
                correlation_id=job.get("correlation_id"),
            )
            await publish_platform_topic(
                "JOB_QUEUED", tenant_id, _job_event_payload(job),
                correlation_id=job.get("correlation_id") or "",
            )
        await self._schedule_event(
            schedule, "schedule.fired",
            {
                "job_id": job["id"],
                "fire_time": fire_time.isoformat(),
                "coalesced": misfired,
                "replayed": bool(job.get("replayed")),
            },
            topic_attr="SCHEDULE_FIRED",
        )
        await self.repo.mark_fired(
            schedule_id,
            last_run_at=now, next_run_at=next_run,
            last_job_id=job["id"],
            last_run_status="fired",
            consecutive_failures=0,
        )
        metrics.increment("job_schedule_fired")
        return {"schedule_id": schedule_id, "action": "fired", "job_id": job["id"]}

    async def _record_failure(
        self, schedule: dict, now: datetime, exc: Exception
    ) -> dict:
        """A tick failed for this schedule: count it, advance next_run_at so a
        broken schedule cannot hot-loop, auto-disable after too many."""
        schedule_id = schedule["id"]
        failures = int(schedule.get("consecutive_failures") or 0) + 1
        disable = failures >= MAX_SCHEDULE_CONSECUTIVE_FAILURES
        logger.error(
            f"Schedule {schedule_id} tick failed ({failures} consecutive): {exc}"
        )
        try:
            next_run = compute_next_run(
                schedule["cron_expression"], schedule.get("timezone") or "UTC", after=now
            )
        except Exception:  # noqa: BLE001 — even an invalid cron must not crash the tick
            next_run = None
            disable = True  # unschedulable: disable immediately
            failures = max(failures, MAX_SCHEDULE_CONSECUTIVE_FAILURES)
        await self.repo.mark_fired(
            schedule_id,
            last_run_at=now, next_run_at=next_run,
            last_job_id=schedule.get("last_job_id"),
            last_run_status="error",
            consecutive_failures=failures,
            enabled=False if disable else None,
        )
        if disable:
            await self._schedule_event(
                schedule, "schedule.disabled",
                {"reason": f"auto-disabled after {failures} consecutive failures",
                 "error": str(exc)[:500]},
                topic_attr="SCHEDULE_DISABLED",
            )
            metrics.increment("job_schedule_disabled")
        return {
            "schedule_id": schedule_id,
            "action": "disabled" if disable else "error",
            "consecutive_failures": failures,
        }

    async def _schedule_event(
        self, schedule: dict, event_type: str, payload: dict, topic_attr: str
    ) -> None:
        """Durable timeline row (job_id = schedule id) + best-effort topic."""
        base = {
            "schedule_id": schedule["id"],
            "tenant_id": schedule["tenant_id"],
            "job_type": schedule["job_type"],
            "schedule_name": schedule.get("name"),
            **payload,
        }
        try:
            await self.repo.append_job_event(
                schedule["tenant_id"], schedule["id"], event_type,
                payload=base, correlation_id=f"schedule:{schedule['id']}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to append {event_type} for schedule {schedule['id']}: {exc}")
        await publish_platform_topic(
            topic_attr, schedule["tenant_id"], base,
            correlation_id=f"schedule:{schedule['id']}",
        )


# ── Supervisor coroutine factory (wired by the runtime orchestrator) ────────

def build_schedule_tick_coro() -> Coroutine:
    """Zero-arg factory: a fresh long-running scheduler tick coroutine."""
    return JobScheduler().run_forever()
