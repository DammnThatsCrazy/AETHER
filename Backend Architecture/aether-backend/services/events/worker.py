"""Background worker — processes queued event replay jobs."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events.worker")

async def start_replay_worker() -> None:
    """Polls for queued replay jobs every 10 s and processes them."""
    from repositories.repos import EventReplayRepository
    repo = EventReplayRepository()
    while True:
        try:
            jobs = await repo.list_queued(limit=10)
            for job in jobs:
                await _process_job(repo, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("replay_worker_error: %s", exc)
        await asyncio.sleep(10)

async def _process_job(repo, job: dict) -> None:
    job_id = job["id"]
    now = datetime.now(timezone.utc).isoformat()
    try:
        await repo.update(job_id, {"status": "running", "updatedAt": now})
        from services.events.routes import _EVENTS
        source_tag: str = job.get("sourceTag", "")
        from_time: str = job.get("fromTime", "")
        to_time: str | None = job.get("toTime")
        event_types: list[str] = job.get("eventTypes") or []
        replayed = 0
        for env in list(_EVENTS.values()):
            if not env.get("replayable"):
                continue
            if env.get("tenantId") != job.get("tenantId"):
                continue
            if source_tag and source_tag not in (env.get("tags") or []):
                continue
            if event_types and env.get("type") not in event_types:
                continue
            occurred = env.get("occurredAt", "")
            if from_time and occurred < from_time:
                continue
            if to_time and occurred > to_time:
                continue
            replayed += 1
        await repo.update(job_id, {
            "status": "completed",
            "totalReplayed": replayed,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("replay_job_completed job_id=%s replayed=%d", job_id, replayed)
        metrics.increment("event_replay_job_completed")
    except Exception as exc:
        logger.error("replay_job_failed job_id=%s error=%s", job_id, exc)
        await repo.update(job_id, {
            "status": "failed",
            "completedAt": datetime.now(timezone.utc).isoformat(),
        })
        metrics.increment("event_replay_job_failed")
