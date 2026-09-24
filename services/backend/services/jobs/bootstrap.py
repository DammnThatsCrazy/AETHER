"""Durable job handler registration shared by every process that runs jobs.

Handlers live in a per-process registry (``services.jobs.handlers``). The
``job_worker`` resolves each claimed job's type there and fails the job as
``unknown job_type`` when nothing registered it. Registration used to happen
only in the FastAPI lifespan (``main.py``), so a dedicated worker process
started by ``services.runtime.run_role`` (for example the staging
``lean-worker``, which hosts the ``maintenance`` role and its ``job_worker``)
claimed jobs with an empty registry: every durable job the API enqueued —
DSR erasure, exports, imports — failed there without running.

Both entry points now call :func:`register_durable_job_handlers`. Every
registration below is idempotent, so calling it more than once per process is
safe. Flag-gated handlers keep their existing gates.
"""

from __future__ import annotations

from typing import Any, Optional


def register_durable_job_handlers(settings: Optional[Any] = None) -> None:
    """Register every durable job handler this build ships (idempotent)."""
    if settings is None:
        from config.settings import settings as _settings

        settings = _settings

    from services.consent.erasure_jobs import register_consent_erasure_handler
    from services.export import register_export_handlers
    from services.imports.commit import register_import_handlers
    from services.semantic_intelligence.jobs import register_semantic_replay_handler
    from services.traffic.repair import register_source_classification_repair_handler

    register_export_handlers()  # export.generate / export.expire_sweep
    register_import_handlers()  # import.commit / import.replay
    register_source_classification_repair_handler()
    register_consent_erasure_handler()  # consent.erasure (durable DSR erasure)
    register_semantic_replay_handler()  # semantic.replay (flag-gated inside)

    # Data Exchange Plane — durable jobs + canonical exporter registration
    # (flag-gated; the surfaces only exist when the matching flag is ON).
    dex = settings.data_exchange
    if dex.enabled:
        from services.data_exchange.exporters import register_data_exchange_exporters
        from services.data_exchange.jobs_migrate import (
            register as register_data_exchange_migrate_handlers,
        )
        from services.data_exchange.jobs_ops import register as register_data_exchange_ops_jobs
        from services.data_exchange.metrics import (
            register_metrics as register_data_exchange_metrics,
        )

        register_data_exchange_migrate_handlers()  # data_exchange.migrate_legacy_artifact
        register_data_exchange_exporters()  # canonical EXPORTERS += envelope exporters
        register_data_exchange_ops_jobs()  # M7 ops: expire / reconcile / cleanup / finalize
        register_data_exchange_metrics()  # M7 metric-family no-op seam
    if dex.reports_enabled:
        from services.reports.jobs_reports import register_report_jobs

        register_report_jobs()  # report.generate (PDF report artifacts)
