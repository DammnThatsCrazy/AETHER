"""Data Exchange reports plane — reportlab PDF renderer (M5).

Renders a human-readable PDF **report artifact** (``artifact_type="report"``,
egress) from the field dict of a ``ReportSpecContract`` plus optional resolved
source rows.  A PDF report is deliberately *not* a structured ``EgressFormat``:
it never enters the CSV/JSON/NDJSON/PARQUET export path and always flows
through the ``data_artifacts``/ObjectStore artifact seam.

Reportlab is imported **lazily inside ``render_report_pdf``** so importing this
module never requires the dependency.  If reportlab is unavailable the render
fails cleanly with :class:`ReportRenderError` at render time (the durable
``report.generate`` job observes the failure through the failed ``JobOutcome``
and the artifact is moved to ``failed``).

Determinism
-----------
Two renders of the same spec with the same ``generated_at`` produce
byte-identical PDFs.  Three invariants keep the bytes stable:

- the footer/content timestamp is formatted once from the *provided*
  ``generated_at`` (never a bare clock read mid-layout);
- every document is built through a canvas factory that pins ``invariant=True``
  so reportlab omits the wall-clock ``CreationDate`` and the per-document ID;
- JSON payload blocks are serialised with ``sort_keys`` so dictionary ordering
  can never leak into the bytes.

Template registry
-----------------
A small, extensible template registry maps a template name onto a *pure*
section builder (a function returning reportlab-free section descriptors).
Day-one ships the ``"default"`` template.  ``resolve_template_name`` applies the
module policy to unknown names: fall back to ``"default"`` (used by the render
path) or raise :class:`UnknownTemplateError`` when ``strict=True`` (used by
``request_report`` so a bad template fails fast with a 400 before a durable job
is enqueued).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from xml.sax.saxutils import escape as _xml_escape
from zoneinfo import ZoneInfo

from shared.temporal.instant import coerce_utc_lenient

# ── template registry ───────────────────────────────────────────────────────

DEFAULT_TEMPLATE = "default"

# Registered template section builders, keyed by template name.  A builder is a
# pure function ``(spec_fields, *, include_methodology, include_provenance_summary,
# display_timezone, generated_at, source_rows, source_meta) -> list[dict]`` where
# each dict is a section descriptor (title / subtitle / heading / paragraph /
# bullets / kv / rows / spacer).  Builders never import reportlab; the platypus
# layout happens in one place below.
TEMPLATES: dict[str, Callable[..., list[dict]]] = {}


def register_template(name: str) -> Callable:
    """Decorator registering a report template section builder."""

    def decorator(fn: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
        if name in TEMPLATES:
            raise ValueError(f"Report template already registered for {name!r}")
        TEMPLATES[name] = fn
        return fn

    return decorator


class ReportRenderError(RuntimeError):
    """Raised when a report PDF cannot be rendered (e.g. reportlab missing)."""


class UnknownTemplateError(ReportRenderError):
    """Raised when a requested report template is not registered and strict
    resolution is requested (``resolve_template_name(..., strict=True)``)."""


def get_template_builder(template: str) -> Optional[Callable[..., list[dict]]]:
    """Return the registered builder for ``template`` (None when unknown)."""
    return TEMPLATES.get(template)


def resolve_template_name(
    template: Optional[str] = None,
    *,
    strict: bool = False,
) -> str:
    """Resolve a template request against the registry.

    - ``None`` / empty  -> :data:`DEFAULT_TEMPLATE`.
    - a registered name -> that name.
    - an unknown name with ``strict=False`` -> :data:`DEFAULT_TEMPLATE`
      (render-path policy: a report still renders).
    - an unknown name with ``strict=True`` -> raise
      :class:`UnknownTemplateError` (request-path policy: fail fast with 400).
    """
    name = (template or "").strip() or DEFAULT_TEMPLATE
    if name in TEMPLATES:
        return name
    if strict:
        known = ", ".join(sorted(TEMPLATES)) if TEMPLATES else DEFAULT_TEMPLATE
        raise UnknownTemplateError(
            f"Unknown report template {template!r}. Registered templates: {known}"
        )
    return DEFAULT_TEMPLATE


# ── pure helpers ────────────────────────────────────────────────────────────


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return coerce_utc_lenient(dt) or dt  # assume UTC on a naive instant
    return dt.astimezone(timezone.utc)


def format_generated_at(dt: datetime, display_timezone: str) -> str:
    """Stable, human-readable generation timestamp.

    Always derived from the provided datetime (never ``now()``) so two renders
    with the same ``generated_at`` format identically.
    """
    utc = _as_utc(dt)
    try:
        local = utc.astimezone(ZoneInfo(display_timezone or "UTC"))
    except Exception:  # noqa: BLE001 — unknown/invalid zone falls back to UTC
        local = utc.astimezone(timezone.utc)
    return local.strftime("%Y-%m-%d %H:%M:%S %Z")


def _json_block(value: Any) -> str:
    """Deterministic JSON summary of an arbitrary spec dict (sorted keys)."""
    if value is None:
        return "—"
    if isinstance(value, dict) and not value:
        return "—"
    if isinstance(value, list) and not value:
        return "—"
    return json.dumps(value, sort_keys=True, default=str, separators=(",", ": "))


def _pick(spec_fields: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if spec_fields.get(key) not in (None, "", {}, []):
            return spec_fields.get(key)
    return default


# ── day-one default template ────────────────────────────────────────────────


@register_template(DEFAULT_TEMPLATE)
def _default_template_sections(
    spec_fields: dict,
    *,
    include_methodology: bool = True,
    include_provenance_summary: bool = True,
    display_timezone: str = "UTC",
    generated_at: datetime,
    source_rows: Optional[list[dict]] = None,
    source_meta: Optional[dict] = None,
) -> list[dict]:
    """Section descriptors for the default report layout.

    Pure (no reportlab) so it is unit-testable and registry-extensible without
    the PDF dependency.
    """
    resource = str(_pick(spec_fields, "resource", "resource_type", default="Data"))
    report_id = str(_pick(spec_fields, "report_id", default=""))
    scope = _pick(spec_fields, "scope", default={})
    temporal = _pick(spec_fields, "temporal", default={})
    filters = _pick(spec_fields, "filters", default={})
    requested_by = _pick(spec_fields, "requested_by", default=None)
    generated_text = format_generated_at(generated_at, display_timezone)

    sections: list[dict] = [
        {"kind": "title", "text": f"{resource} Report"},
        {
            "kind": "subtitle",
            "text": "Aether Data Exchange Plane — report artifact",
        },
        {
            "kind": "kv",
            "rows": [
                ("Report ID", report_id or "—"),
                ("Resource", resource),
                ("Scope", _json_block(scope)),
                ("Temporal window", _json_block(temporal)),
                ("Filters", _json_block(filters)),
                ("Display timezone", display_timezone or "UTC"),
                ("Requested by", requested_by if requested_by else "—"),
            ],
        },
        {"kind": "spacer", "height": 10},
    ]

    if include_methodology:
        sections.append({"kind": "heading", "text": "Methodology"})
        methodology_body = (
            "This report is a human-readable summary produced from canonical, "
            "tenant-scoped records through the Aether Data Exchange reports plane. "
            "It was generated at {ts}. The selection encoded in the request's "
            "scope, temporal window and filters is reproduced above verbatim; no "
            "transform is applied to the values shown."
        ).format(ts=generated_text)
        sections.append({"kind": "paragraph", "text": methodology_body})
        detail_bullets = [
            "Requested scope is rendered directly from the report spec.",
            "Rows are grouped by source and listed in the section below "
            "when resolved source data was provided.",
        ]
        if source_meta and isinstance(source_meta, dict):
            per_source = source_meta.get("per_source")
            if per_source and isinstance(per_source, dict):
                detail_bullets.append(
                    "Source record counts: "
                    + ", ".join(
                        f"{k}={v}" for k, v in sorted(per_source.items())
                    )
                )
        sections.append({"kind": "bullets", "items": detail_bullets})
        sections.append({"kind": "spacer", "height": 6})

    if source_rows:
        sections.append({"kind": "heading", "text": "Reported rows"})
        headers = []
        if source_meta and isinstance(source_meta, dict):
            headers = source_meta.get("columns") or []
        if not headers:
            headers = sorted({k for row in source_rows for k in row})
        table_rows = [
            [row.get(col, "") for col in headers] for row in source_rows
        ]
        sections.append(
            {"kind": "rows", "headers": headers, "rows": table_rows}
        )
        sections.append({"kind": "spacer", "height": 6})

    if include_provenance_summary:
        sections.append({"kind": "heading", "text": "Provenance summary"})
        provenance = [
            ("Report ID", report_id or "—"),
            ("Template", str(_pick(spec_fields, "template", default=DEFAULT_TEMPLATE))),
            ("Generated at", generated_text),
            ("Renderer", "reportlab"),
            ("Stored via", "data_artifacts metadata + shared ObjectStore"),
            ("Classification", str(_pick(spec_fields, "classification", default="none"))),
        ]
        if requested_by:
            provenance.append(("Requested by", requested_by))
        sections.append({"kind": "kv", "rows": provenance})
        sections.append({"kind": "spacer", "height": 6})

    sections.append(
        {
            "kind": "paragraph",
            "text": "— End of report —",
        }
    )
    return sections


# ── platypus layout ─────────────────────────────────────────────────────────


def render_report_pdf(
    spec_fields: dict,
    *,
    template: Optional[str] = None,
    include_methodology: bool = True,
    include_provenance_summary: bool = True,
    display_timezone: str = "UTC",
    generated_at: Optional[datetime] = None,
    source_rows: Optional[list[dict]] = None,
    source_meta: Optional[dict] = None,
) -> bytes:
    """Render ``spec_fields`` (a serialised ``ReportSpecContract``) into PDF
    bytes using reportlab platypus.

    Raises :class:`ReportRenderError` with a clear message when reportlab is not
    installed, and :class:`UnknownTemplateError` (a subclass) when a strict
    template request cannot be satisfied.  Deterministic for a fixed
    ``generated_at`` (see module docstring).
    """
    if not isinstance(spec_fields, dict) or not spec_fields:
        raise ReportRenderError("spec_fields must be a non-empty dict")

    try:  # reportlab is only required at render time
        from reportlab.lib import colors  # noqa: F401
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas as _pdfgen_canvas
        from reportlab.platypus import (
            ListFlowable,
            ListItem,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:  # pragma: no cover — exercised when reportlab is absent
        raise ReportRenderError(
            "reportlab is required to render PDF report artifacts — "
            "install the backend reportlab extra (pyproject: "
            "reportlab>=4.0) and retry"
        ) from exc

    effective_template = resolve_template_name(template, strict=False)
    builder = get_template_builder(effective_template)
    if builder is None:  # pragma: no cover — guarded by resolve_template_name
        raise ReportRenderError(
            f"Report template {effective_template!r} is registered but has no builder"
        )

    generated = generated_at if generated_at is not None else datetime.now(timezone.utc)
    sections = builder(
        spec_fields,
        include_methodology=include_methodology,
        include_provenance_summary=include_provenance_summary,
        display_timezone=display_timezone,
        generated_at=generated,
        source_rows=source_rows,
        source_meta=source_meta,
    )

    return _build_pdf(
        sections,
        generated=generated,
        display_timezone=display_timezone,
        pagesize=letter,
        stylesheet=getSampleStyleSheet(),
        ParagraphStyle=ParagraphStyle,
        Paragraph=Paragraph,
        ListFlowable=ListFlowable,
        ListItem=ListItem,
        SimpleDocTemplate=SimpleDocTemplate,
        Spacer=Spacer,
        Table=Table,
        TableStyle=TableStyle,
        inch=inch,
        pdfgen_canvas=_pdfgen_canvas,
    )


def _esc(text: Any) -> str:
    """Escape free text that reportlab will parse as Paragraph markup."""
    return _xml_escape(str(text), entities={'"': "&quot;"})


def _build_pdf(
    sections: list[dict],
    *,
    generated: datetime,
    display_timezone: str,
    pagesize,
    stylesheet,
    ParagraphStyle,
    Paragraph,
    ListFlowable,
    ListItem,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    inch,
    pdfgen_canvas,
) -> bytes:
    """Convert pure section descriptors into a deterministic PDF byte stream."""
    body = stylesheet["BodyText"]
    styles = {
        "title": ParagraphStyle(
            "DxTitle",
            parent=stylesheet["Title"],
            fontSize=17,
            leading=20,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "DxSubtitle",
            parent=body,
            fontSize=9,
            textColor=_as_color(0.35),
            spaceAfter=12,
        ),
        "heading": ParagraphStyle(
            "DxHeading",
            parent=stylesheet["Heading2"],
            fontSize=12,
            spaceBefore=10,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "DxBody", parent=body, fontSize=9.5, leading=13, spaceAfter=6
        ),
        "cell": ParagraphStyle(
            "DxCell",
            parent=body,
            fontSize=8.5,
            leading=10.5,
            wordWrap="CJK",
        ),
        "label": ParagraphStyle(
            "DxLabel",
            parent=body,
            fontSize=8.5,
            leading=10.5,
            textColor=_as_color(0.3),
        ),
    }

    def canvasmaker(*args: Any, **kwargs: Any) -> Any:
        # ``invariant=True`` makes reportlab omit the wall-clock CreationDate and
        # the unique document ID, so two renders of one spec are byte-equal.
        kwargs["invariant"] = True
        return pdfgen_canvas.Canvas(*args, **kwargs)

    footer_text = f"Generated {format_generated_at(generated, display_timezone)}"
    title_text = ""
    for section in sections:
        if section.get("kind") == "title":
            title_text = str(section.get("text", ""))
            break
    doc_title = f"{title_text} — Aether Data Exchange" if title_text else "Aether Data Exchange report"

    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_as_color(0.35))
        page_w, page_h = pagesize
        canvas.drawString(
            doc.leftMargin, 0.5 * inch, "Aether Data Exchange — governed report artifact"
        )
        canvas.drawRightString(page_w - doc.rightMargin, 0.5 * inch, footer_text)
        canvas.drawCentredString(page_w / 2.0, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    import io

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=doc_title,
        author="Aether",
        creator="Aether Data Exchange reports plane",
    )

    flowables: list[Any] = []
    for section in sections:
        kind = section.get("kind")
        if kind == "title":
            flowables.append(Paragraph(_esc(section["text"]), styles["title"]))
        elif kind == "subtitle":
            flowables.append(Paragraph(_esc(section["text"]), styles["subtitle"]))
        elif kind == "heading":
            flowables.append(Paragraph(_esc(section["text"]), styles["heading"]))
        elif kind == "paragraph":
            flowables.append(Paragraph(_esc(section["text"]), styles["body"]))
        elif kind == "bullets":
            items = [
                ListItem(Paragraph(_esc(item), styles["body"]), leftIndent=8)
                for item in section.get("items", [])
            ]
            flowables.append(
                ListFlowable(
                    items,
                    bulletType="bullet",
                    start="bullet",
                    bulletFontSize=7,
                    leftIndent=14,
                )
            )
        elif kind == "kv":
            data = [
                [
                    Paragraph(_esc(str(k)), styles["label"]),
                    Paragraph(_esc(str(v)), styles["cell"]),
                ]
                for k, v in section.get("rows", [])
            ]
            if data:
                table = Table(data, colWidths=[1.9 * inch, None], hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, _as_color(0.8)),
                            ("BOX", (0, 0), (-1, -1), 0.5, _as_color(0.6)),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                flowables.append(table)
        elif kind == "rows":
            headers = section.get("headers", []) or []
            rows = section.get("rows", []) or []
            if headers and rows:
                data = [
                    [Paragraph(_esc(h), styles["label"]) for h in headers]
                ] + [
                    [Paragraph(_esc(c), styles["cell"]) for c in row] for row in rows
                ]
                table = Table(data, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("INNERGRID", (0, 0), (-1, -1), 0.25, _as_color(0.8)),
                            ("BOX", (0, 0), (-1, -1), 0.5, _as_color(0.6)),
                            ("BACKGROUND", (0, 0), (-1, 0), _as_color(0.93)),
                            ("FONTSIZE", (0, 0), (-1, -1), 8),
                            ("LEFTPADDING", (0, 0), (-1, -1), 4),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                            ("TOPPADDING", (0, 0), (-1, -1), 2),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                        ]
                    )
                )
                flowables.append(table)
        elif kind == "spacer":
            flowables.append(Spacer(1, int(section.get("height", 6))))

    doc.build(
        flowables,
        canvasmaker=canvasmaker,
        onFirstPage=_on_page,
        onLaterPages=_on_page,
    )
    return buffer.getvalue()


def _as_color(value: Any) -> Any:
    """Translate a grey 0..1 scalar or hex into a reportlab color lazily."""
    from reportlab.lib.colors import Color, HexColor  # noqa: PLC0415

    if isinstance(value, (int, float)):
        return Color(value, value, value)
    if isinstance(value, str) and value.startswith("#"):
        return HexColor(value)
    return value
