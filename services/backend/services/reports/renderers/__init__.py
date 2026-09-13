"""Data Exchange reports plane — PDF renderers (M5).

``render_report_pdf`` is the day-one reportlab renderer.  It imports reportlab
lazily so the package imports cleanly without the dependency and fails cleanly
(``ReportRenderError``) if a render is attempted without reportlab installed.
"""

from services.reports.renderers.pdf import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    ReportRenderError,
    UnknownTemplateError,
    format_generated_at,
    get_template_builder,
    register_template,
    render_report_pdf,
    resolve_template_name,
)

__all__ = [
    "DEFAULT_TEMPLATE",
    "TEMPLATES",
    "ReportRenderError",
    "UnknownTemplateError",
    "format_generated_at",
    "get_template_builder",
    "register_template",
    "render_report_pdf",
    "resolve_template_name",
]
