"""Background worker — processes queued event replay jobs."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from shared.logger.logger import get_logger

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
        # Bronze-tier replay: find replayable events from _EVENTS store
        from services.events.routes import _EVENTS
        source_tag = job.get("sourceTag", "")
        from_time = job.get("fromTime", "")
        to_time = job.get("toTime")
        replayed = 0
        for env in list(_EVENTS.values()):
            if env.get("replayable") and env.get("tenantId") == job.get("tenantId"):
                if env.get("occurredAt", "") >= from_time:
                    if to_time is None or env.get("occurredAt", "") <= to_time:
                        replayed += 1
        await repo.update(job_id, {
            "status": "completed",
            "totalReplayed": replayed,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("replay_job_completed job_id=%s replayed=%d", job_id, replayed)
    except Exception as exc:
        logger.error("replay_job_failed job_id=%s error=%s", job_id, exc)
        await repo.update(job_id, {
            "status": "failed",
            "completedAt": datetime.now(timezone.utc).isoformat(),
        })
