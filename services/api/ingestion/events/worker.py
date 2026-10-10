"""Background worker — processes queued event replay jobs."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from shared.events.events import Event, Topic
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.events.worker")


async def start_replay_worker() -> None:
    """Polls for queued replay jobs every 10 s and processes them."""
    from repositories.repos import EventReplayRepository, EventEnvelopeRepository
    from dependencies.providers import get_producer
    repo = EventReplayRepository()
    envelope_repo = EventEnvelopeRepository()
    producer = get_producer()
    while True:
        try:
            jobs = await repo.list_queued(limit=10)
            for job in jobs:
                await _process_job(repo, envelope_repo, producer, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("replay_worker_error: %s", exc)
        await asyncio.sleep(10)


async def _process_job(repo, envelope_repo, producer, job: dict) -> None:
    job_id = job["id"]
    now = datetime.now(timezone.utc).isoformat()
    try:
        await repo.update(job_id, {"status": "running", "updatedAt": now})
        dry_run: bool = bool(job.get("dryRun", False))
        envelopes = await envelope_repo.list_replayable(
            tenant_id=job.get("tenantId", ""),
            source_tag=job.get("sourceTag", ""),
            event_types=job.get("eventTypes") or [],
            from_time=job.get("fromTime", ""),
            to_time=job.get("toTime"),
        )
        replayed = 0
        for env in envelopes:
            try:
                topic = Topic(env.get("type", ""))
            except ValueError:
                continue  # skip envelopes whose type isn't a known Topic
            if not dry_run:
                await producer.publish(Event(
                    topic=topic,
                    tenant_id=env.get("tenantId", ""),
                    payload=env.get("payload", {}),
                ))
            replayed += 1
        await repo.update(job_id, {
            "status": "completed",
            "totalReplayed": replayed,
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
        try:
            await producer.publish(Event(
                topic=Topic.EVENT_REPLAY_COMPLETED,
                tenant_id=job.get("tenantId", ""),
                payload={"job_id": job_id, "total_replayed": replayed, "dry_run": dry_run},
            ))
        except Exception as notify_exc:
            # Replay succeeded — don't let a transient notification failure
            # overwrite the completed status or mask the success.
            logger.warning("replay_completion_notify_failed job_id=%s error=%s", job_id, notify_exc)
        logger.info(
            "replay_job_completed job_id=%s replayed=%d dry_run=%s",
            job_id, replayed, dry_run,
        )
        metrics.increment("event_replay_job_completed")
    except Exception as exc:
        logger.error("replay_job_failed job_id=%s error=%s", job_id, exc)
        await repo.update(job_id, {
            "status": "failed",
            "completedAt": datetime.now(timezone.utc).isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
        metrics.increment("event_replay_job_failed")
