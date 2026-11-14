"""Durable journey rebuild after a redeemed cross-device handoff.

Redeeming a handoff (``routes.redeem``) records explicit evidence that one party
controlled both sessions. The journey compiler only reads that evidence when it
compiles, so redemption queues ``journey.handoff_continuation`` on the durable
jobs plane: the continuation journey is rebuilt once, under its root anonymous
ID, and every profile journey that already owns activity on either end is
rebuilt so its steps carry the ``explicit_handoff`` link.

The job is idempotent per handoff (``journey_handoff:<handoff_id>``) and
internal-only; tenants cannot enqueue it. Enqueue is fail-soft: a jobs-plane
outage never fails the redemption, and the next compile for either identity
still picks the handoff up.
"""
from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.journeys.handoff.continuation_jobs")

JOB_TYPE = "journey.handoff_continuation"
MAX_PROFILE_REBUILDS = 4


async def queue_handoff_continuation(tenant_id: str, link: dict[str, Any], *, jobs: Any = None) -> bool:
    """Enqueue the continuation rebuild for one redeemed handoff. Never raises."""
    try:
        if jobs is None:
            from workers.jobs.service import get_jobs_service

            jobs = get_jobs_service()
        await jobs.enqueue(
            tenant_id,
            JOB_TYPE,
            {
                "handoff_id": link["handoff_id"],
                "source_anonymous_id": link["from"]["anonymous_id"],
                "redeemed_anonymous_id": link["to"]["anonymous_id"],
            },
            idempotency_key=f"journey_handoff:{link['handoff_id']}",
            requested_by="journey_handoff",
            max_attempts=5,
        )
        metrics.increment("journey_handoff_continuation_queued_total")
        return True
    except Exception as exc:  # noqa: BLE001 — redemption already succeeded
        metrics.increment("journey_handoff_continuation_queue_failed_total")
        logger.warning(
            "journey handoff continuation enqueue failed tenant=%s: %s",
            tenant_id, type(exc).__name__,
        )
        return False


async def run_handoff_continuation(tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the continuation journey and the profile journeys touching it."""
    from journeys.measurement.engine.journey_compiler import JourneyCompiler
    from journeys.measurement.repositories.activity_repo import ActivityRepository

    ends = [
        str(payload.get("source_anonymous_id") or ""),
        str(payload.get("redeemed_anonymous_id") or ""),
    ]
    ends = [e for e in ends if e]
    if not ends:
        raise ValueError("handoff continuation payload has no anonymous IDs")
    reason = f"handoff_redeemed:{payload.get('handoff_id', '')}"
    compiler = JourneyCompiler()
    # Compiling the redeemed end resolves the root and retires the redeemed
    # end's standalone journey, so this one call owns the anonymous lineage.
    anonymous_version = await compiler.compile_for_profile(
        tenant_id, ends[-1], identity_type="anonymous", trigger_reason=reason,
    )
    profiles: list[str] = []
    activity_repo = ActivityRepository()
    for anonymous_id in ends:
        for row in await activity_repo.list_by_profile(
            tenant_id, anonymous_id, identity_type="anonymous", limit=2000,
        ):
            pid = row.get("profile_id")
            if pid and pid not in profiles:
                profiles.append(str(pid))
    profiles = sorted(profiles)[:MAX_PROFILE_REBUILDS]
    for pid in profiles:
        await compiler.compile_for_profile(
            tenant_id, pid, identity_type="profile", trigger_reason=reason,
        )
    return {
        "journey_id": anonymous_version.get("journey_id"),
        "journey_version_id": anonymous_version.get("journey_version_id"),
        "step_count": anonymous_version.get("step_count", 0),
        "profile_journeys_rebuilt": len(profiles),
    }


def register_handoff_continuation_handler() -> None:
    """Register the internal-only handler exactly once per process."""
    from workers.jobs.handlers import HANDLER_REGISTRY, JobContext, JobOutcome, register_handler

    if JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx: JobContext) -> JobOutcome:
        try:
            result = await run_handoff_continuation(ctx.tenant_id, payload)
        except Exception as exc:  # noqa: BLE001 — the worker retries failed jobs
            logger.warning("journey handoff continuation failed: %s", type(exc).__name__)
            return JobOutcome(status="failed", result={}, error=type(exc).__name__)
        return JobOutcome(status="succeeded", result=result)
