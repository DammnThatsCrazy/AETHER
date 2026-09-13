"""Data Exchange reports plane — ``report.generate`` durable job (M5).

The reports plane renders report artifacts through a durable job on the jobs
platform, exactly like ``export.generate`` drives the canonical export path.
The core render logic lives in ``service.render_report`` (directly unit-testable
DB-free); this module registers the thin ``(payload, ctx) -> JobOutcome``
adapter and mirrors the ``export.generate`` handler shape
(``services/jobs/handlers.py``):

- a handler MUST return a ``JobOutcome`` whose status is
  ``succeeded`` | ``partially_succeeded`` | ``failed``;
- ``JobContext`` carries ``tenant_id`` / ``job_id`` / ``correlation_id`` and the
  heartbeat / ``emit_event`` seams;
- registration is idempotent and is wired from the FastAPI lifespan alongside
  ``register_export_handlers()`` / ``register_import_handlers()``.

Unknown/absent job types are rejected by the worker before a handler is ever
invoked; this registration is what makes ``report.generate`` a known type.
"""

from __future__ import annotations

from typing import Any

from services.data_exchange.contracts import ReportSpecContract
from shared.logger.logger import get_logger

logger = get_logger("aether.data_exchange.reports.jobs")

REPORT_JOB_TYPE = "report.generate"


async def generate_report_artifact(payload: dict, ctx: Any) -> Any:
    """``report.generate`` job handler: render + persist + notify.

    Mirrors ``export.generate``: resolves the report spec from the enqueued
    payload, calls the service core, heartbeats, and returns a ``JobOutcome``.
    Any render failure (including reportlab being unavailable) is converted into
    a ``failed`` outcome with the artifact moved to ``failed`` — the durable job
    never crashes the worker and the error is observable on the job + artifact.
    """
    from services.jobs.handlers import JobOutcome

    from services.reports.service import mark_report_failed, render_report

    artifact_id = (payload or {}).get("artifact_id", "")
    report_id = (payload or {}).get("report_id", "")
    spec_dict = ((payload or {}).get("spec") or {}) if isinstance(payload, dict) else {}
    if not isinstance(spec_dict, dict) or not spec_dict:
        await mark_report_failed(
            getattr(ctx, "tenant_id", ""),
            artifact_id,
            report_id=report_id,
            error="report.generate payload carried no report spec",
        )
        return JobOutcome(
            status="failed",
            result={"artifact_id": artifact_id, "report_id": report_id},
            error="report.generate payload carried no report spec",
        )

    try:
        spec = ReportSpecContract(**spec_dict)
        result = await render_report(
            ctx.tenant_id,
            spec,
            artifact_id=artifact_id,
            correlation_id=ctx.correlation_id,
            job_id=ctx.job_id,
        )
        await ctx.heartbeat()
        logger.info(
            "report.generate succeeded tenant=%s report=%s artifact=%s bytes=%s sha=%s",
            ctx.tenant_id,
            spec.report_id,
            artifact_id,
            result.get("size_bytes"),
            result.get("sha256"),
        )
        return JobOutcome(status="succeeded", result=result)
    except Exception as exc:  # noqa: BLE001 — a failed render is a failed outcome
        logger.warning(
            "report.generate failed tenant=%s report=%s artifact=%s: %s",
            getattr(ctx, "tenant_id", ""),
            report_id,
            artifact_id,
            exc,
        )
        await mark_report_failed(
            ctx.tenant_id,
            artifact_id,
            report_id=report_id,
            error=str(exc),
        )
        await ctx.heartbeat()  # keep lease fresh on the failure path (best effort)
        return JobOutcome(
            status="failed",
            result={"artifact_id": artifact_id, "report_id": report_id},
            error=str(exc),
        )


def register_report_jobs() -> None:
    """Register the ``report.generate`` handler (idempotent).

    Called from the FastAPI lifespan startup alongside
    ``register_export_handlers()``.  Registration is inert until a job is
    enqueued; enqueuing is gated on ``settings.data_exchange.reports_enabled``
    by the coordinator at mount time.
    """
    from services.jobs.handlers import HANDLER_REGISTRY, register_handler

    if REPORT_JOB_TYPE in HANDLER_REGISTRY:
        return
    register_handler(REPORT_JOB_TYPE)(generate_report_artifact)
    logger.info("registered report.generate job handler")
