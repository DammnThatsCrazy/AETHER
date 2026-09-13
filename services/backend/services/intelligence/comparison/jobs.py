"""Comparison runs on the EXISTING durable jobs plane.

Runs execute as ``comparison.run`` jobs claimed by the shared lease worker
(``services.jobs``) — no ad-hoc workers, no parallel scheduler. The handler
is registered from main.py's flag-gated Unified Intelligence Plane block, so
the comparison package stays lazily imported while the flag is off.
"""

from __future__ import annotations

from functools import lru_cache

from shared.logger.logger import get_logger

from services.jobs.handlers import HANDLER_REGISTRY, JobContext, JobOutcome, register_handler

COMPARISON_RUN_JOB_TYPE = "comparison.run"

logger = get_logger("aether.intelligence.comparison.jobs")


@lru_cache(maxsize=1)
def _default_engine():
    """Process-wide engine wired to the shared analytics plane."""
    from dependencies.providers import get_cache
    from repositories.repos import AnalyticsRepository
    from services.intelligence.comparison.collection import AnalyticsDimensionCollector
    from services.intelligence.comparison.engine import ComparisonEngine

    collector = AnalyticsDimensionCollector(AnalyticsRepository(get_cache()))
    return ComparisonEngine(collector)


async def run_comparison_job(payload: dict, ctx: JobContext) -> JobOutcome:
    """Execute one queued comparison run to a terminal state."""
    run_id = str(payload.get("run_id") or "")
    if not run_id:
        return JobOutcome(status="failed", result={}, error="payload.run_id is required")

    engine = _default_engine()
    await ctx.emit_event("comparison.run.started", {"run_id": run_id})
    final = await engine.execute_run(ctx.tenant_id, run_id)
    state = final.get("state")
    await ctx.emit_event(
        "comparison.run.finished", {"run_id": run_id, "state": state}
    )
    result = {
        "run_id": run_id,
        "state": state,
        "finding_count": final.get("finding_count"),
        "alignment_outcome": final.get("alignment_outcome"),
        "degraded_reason": final.get("degraded_reason"),
    }
    if state in ("completed", "completed_degraded", "suppressed"):
        return JobOutcome(status="succeeded", result=result)
    if state in ("cancelled", "expired"):
        return JobOutcome(status="partially_succeeded", result=result)
    return JobOutcome(
        status="failed", result=result, error=final.get("degraded_reason") or state
    )


def register_comparison_handlers() -> None:
    """Register comparison job types with the jobs platform (idempotent)."""
    if COMPARISON_RUN_JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(COMPARISON_RUN_JOB_TYPE)(run_comparison_job)
        logger.info("Registered jobs-plane handler %s", COMPARISON_RUN_JOB_TYPE)


__all__ = [
    "COMPARISON_RUN_JOB_TYPE",
    "register_comparison_handlers",
    "run_comparison_job",
]
