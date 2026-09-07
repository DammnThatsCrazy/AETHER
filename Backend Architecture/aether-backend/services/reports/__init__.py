"""Aether Service — Data Exchange reports plane (M5).

The reports plane renders **human-readable PDF report artifacts** (reportlab)
through the same M1 ``data_artifacts`` / ObjectStore artifact seam as every
other Data Exchange artifact (``artifact_type="report"``, direction ``egress``).
PDF is never a structured ``EgressFormat``.

Surface (mounted by the coordinator behind
``settings.data_exchange.reports_enabled`` = ``DATA_EXCHANGE_REPORTS_ENABLED``):

- ``routes.reports_router``        — ``/v1/data-exchange/reports`` (M5 table).
- ``request_report``               — create the egress artifact + enqueue the
  ``report.generate`` durable job (``POST /reports`` driver).
- ``render_report``                — pure core: render PDF bytes, persist to
  ObjectStore, mark the artifact ``available`` with a verified checksum.
- ``jobs_reports.register_report_jobs`` — ``report.generate`` handler
  registration, wired from the FastAPI lifespan.
- ``renderers.pdf.render_report_pdf`` — reportlab renderer (lazy import; fails
  cleanly with ``ReportRenderError`` when reportlab is absent).
"""

from services.reports.jobs_reports import register_report_jobs
from services.reports.routes import router as reports_router
from services.reports.service import (
    REPORT_ARTIFACT_TYPE,
    REPORT_CONTENT_TYPE,
    REPORT_FORMAT,
    REPORT_JOB_TYPE,
    SCHEMA_SQL,
    delete_report,
    download_report,
    emit_report_downloaded,
    get_report_detail,
    list_report_artifacts,
    mark_report_failed,
    new_report_artifact_id,
    render_report,
    request_report,
    reset_report_render_store,
    validate_template,
)
from services.reports.renderers import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    ReportRenderError,
    UnknownTemplateError,
    register_template,
    render_report_pdf,
    resolve_template_name,
)

__all__ = [
    "reports_router",
    "register_report_jobs",
    "request_report",
    "render_report",
    "mark_report_failed",
    "delete_report",
    "download_report",
    "emit_report_downloaded",
    "get_report_detail",
    "list_report_artifacts",
    "validate_template",
    "new_report_artifact_id",
    "reset_report_render_store",
    "SCHEMA_SQL",
    "REPORT_ARTIFACT_TYPE",
    "REPORT_JOB_TYPE",
    "REPORT_CONTENT_TYPE",
    "REPORT_FORMAT",
    "DEFAULT_TEMPLATE",
    "TEMPLATES",
    "ReportRenderError",
    "UnknownTemplateError",
    "register_template",
    "render_report_pdf",
    "resolve_template_name",
]
