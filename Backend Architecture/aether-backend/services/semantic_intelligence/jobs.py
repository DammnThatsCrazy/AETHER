"""Durable semantic replay job (``semantic.replay`` on the jobs platform).

Replaces the fire-and-forget ``asyncio.create_task(self._run_replay(...))``
path in services/semantic_intelligence/service.py: a real (non-dry-run) replay
is durably enqueued and executed by the jobs worker, so a process death mid-
backfill is recovered by lease sweep + retry instead of silently lost.

Resumability contract: the handler persists the runner's Bronze cursor into
the durable job payload (``payload["cursor"]``) at every checkpoint. When the
worker retries the job — after a crash, lease expiry, or failure — the handler
reads that cursor back and the runner resumes from it, not row 0.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from services.jobs.handlers import (
    HANDLER_REGISTRY,
    JobContext,
    JobOutcome,
    register_handler,
)

logger = get_logger("aether.semantic.jobs")

SEMANTIC_REPLAY_JOB_TYPE = "semantic.replay"


def register_semantic_replay_handler() -> None:
    """Register the internal-only replay job handler exactly once at startup.

    Gated on ``settings.semantic.replay_enabled`` — the kill-switch. Flag off
    (the default) means the handler is never registered, so an enqueued
    ``semantic.replay`` job fails as an unknown type instead of running; the
    ``/reprocess`` route refuses to enqueue one in the first place (routes.py).
    """
    from config.settings import settings

    if not settings.semantic.replay_enabled:
        return
    if SEMANTIC_REPLAY_JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(SEMANTIC_REPLAY_JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx: JobContext) -> JobOutcome:
        from repositories.jobs_repo import get_jobs_repository

        from .service import get_semantic_service

        replay_job_id = str(payload.get("replay_job_id") or "")
        if not replay_job_id:
            return JobOutcome(status="failed", result={}, error="replay_job_id is required")
        cursor = payload.get("cursor") or None
        jobs_repo = get_jobs_repository()

        async def checkpoint(new_cursor: Optional[dict[str, Any]]) -> None:
            # Persist the Bronze cursor into the durable job payload so a
            # retry/restart resumes from it, not row 0; the heartbeat keeps
            # the lease alive (and surfaces cancellation) on long backfills.
            # M8-B3: guard the checkpoint write with the current lease owner so
            # a stale worker (lease reaped, job re-claimed) cannot overwrite the
            # new owner's durable cursor.
            await jobs_repo.update_payload(
                ctx.job_id, {**payload, "cursor": new_cursor}, worker_id=ctx.worker_id
            )
            await ctx.heartbeat()

        result = await get_semantic_service().run_replay_for_job(
            ctx.tenant_id, replay_job_id, cursor=cursor, checkpoint=checkpoint
        )
        status = result.get("status")
        await ctx.emit_event(
            "semantic.replay.progress",
            {"replay_job_id": replay_job_id, **{k: result.get(k) for k in ("status", "scanned", "replayed", "skipped")}},
        )
        if status == "completed":
            return JobOutcome(status="succeeded", result=result)
        if status in ("paused", "cancelled"):
            # Operator-controlled early stop: the run did real durable work and
            # stopped on request; a resume enqueues a fresh job from the cursor.
            return JobOutcome(status="partially_succeeded", result=result)
        return JobOutcome(
            status="failed", result=result, error=f"replay ended in status {status!r}"
        )
