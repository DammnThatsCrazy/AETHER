"""Durable consent-erasure job (``consent.erasure`` on the jobs platform).

Replaces the fire-and-forget ``asyncio.create_task(handle_erasure_background(...))``
path in services/consent/routes.py: the DSR route now opens a DSR propagation
record and durably enqueues a ``consent.erasure`` job, and this handler executes
the measurement erasure — so a process death between request and completion is
recovered by the jobs worker (lease sweep + retry) instead of silently lost.

Evidence contract: the handler marks the propagation step ONLY for the store it
actually erased, carrying that store's own receipt (tombstone counts, the job id
as the audit pointer). ``MeasurementPrivacyHandler.handle_erasure`` decomposes
into per-store try blocks (touchpoint tombstones, conversion tombstones, journey
rebuild) that all live in the measurement/attribution store, so exactly one
registry component — ``attribution_records`` — is marked here. Marking any other
component would fabricate completion evidence for stores this handler never
touched.
"""

from __future__ import annotations

from shared.logger.logger import get_logger, metrics

from services.jobs.handlers import (
    HANDLER_REGISTRY,
    JobContext,
    JobOutcome,
    register_handler,
)

logger = get_logger("aether.consent.erasure_jobs")

ERASURE_JOB_TYPE = "consent.erasure"

# The single dsr_propagation component the measurement erasure produces real
# evidence for (see module docstring).
MEASUREMENT_COMPONENT = "attribution_records"


def register_consent_erasure_handler() -> None:
    """Register the internal-only erasure job handler exactly once at startup."""
    if ERASURE_JOB_TYPE in HANDLER_REGISTRY:
        return

    @register_handler(ERASURE_JOB_TYPE, tenant_invocable=False)
    async def _handle(payload: dict, ctx: JobContext) -> JobOutcome:
        # Local imports keep startup registration free of repository imports.
        from repositories.repos import ConsentRepository
        from services.dsr_propagation.service import dsr_propagation_service
        from services.measurement.privacy import handle_erasure_background

        user_id = str(payload.get("user_id") or "")
        if not user_id:
            return JobOutcome(status="failed", result={}, error="user_id is required")
        propagation_request_id = payload.get("propagation_request_id")
        dsr_id = payload.get("dsr_id")

        if propagation_request_id:
            await dsr_propagation_service.mark_step(
                propagation_request_id,
                MEASUREMENT_COMPONENT,
                "running",
                tenant_id=ctx.tenant_id,
            )

        result = await handle_erasure_background(ctx.tenant_id, user_id)
        errors = [str(e) for e in (result.get("errors") or [])]
        records_impacted = int(result.get("touchpoints_tombstoned") or 0) + int(
            result.get("conversions_tombstoned") or 0
        )

        if propagation_request_id:
            step_status = "failed" if errors else "completed"
            # Evidence is the store's OWN receipt: the rows it tombstoned and
            # the durable job id as the audit pointer for this execution.
            await dsr_propagation_service.mark_step(
                propagation_request_id,
                MEASUREMENT_COMPONENT,
                step_status,
                tenant_id=ctx.tenant_id,
                records_impacted=records_impacted,
                requires_recompute=not bool(result.get("journey_rebuild_triggered")),
                audit_event_id=ctx.job_id,
            )

        if dsr_id:
            repo = ConsentRepository()
            record_id = f"dsr_{dsr_id}"
            dsr_row = await repo.find_by_id(record_id)
            if dsr_row is not None and dsr_row.get("tenant_id") == ctx.tenant_id:
                await repo.update(
                    record_id,
                    {
                        "status": "failed" if errors else "completed",
                        "erasure_result": result,
                        "propagation_request_id": propagation_request_id,
                    },
                )

        await ctx.emit_event(
            "consent.erasure.measurement",
            {
                "user_id": user_id,
                "dsr_id": dsr_id,
                "propagation_request_id": propagation_request_id,
                "records_impacted": records_impacted,
                "journey_rebuild_triggered": bool(result.get("journey_rebuild_triggered")),
                "errors": errors,
            },
        )
        metrics.increment(
            "consent_erasure_jobs",
            labels={"outcome": "failed" if errors else "succeeded"},
        )

        if errors:
            # Every operation above is idempotent, so a per-store failure is
            # retryable: fail the attempt and let the worker re-run the whole
            # erasure with backoff (dead-letter after max attempts).
            return JobOutcome(status="failed", result=result, error="; ".join(errors))
        return JobOutcome(status="succeeded", result=result)
