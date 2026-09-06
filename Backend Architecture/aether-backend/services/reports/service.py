"""Data Exchange reports plane — request/render orchestration (M5).

The reports plane produces **human-readable PDF report artifacts** through the
same M1 ``data_artifacts`` / ObjectStore seam as every other Data Exchange
artifact.  A PDF report is an ``artifact_type="report"`` egress artifact and is
*never* a structured ``EgressFormat``.

Flow
----
1. ``request_report`` validates the template, creates the egress
   ``data_artifacts`` intent row (``status="generating"``, object key derived
   through ``object_key_for``), and enqueues the durable ``report.generate``
   job.  The row is created *after* a successful enqueue so the ``job_id`` can
   be stamped on the row at insert time (``data_artifacts`` has no later field
   update path besides status).
2. ``render_report`` (invoked by the ``report.generate`` handler) renders PDF
   bytes (reportlab), writes them to ObjectStore at the row's object key, and
   flips the artifact to ``available`` through ``repo.mark_available(...,
   size_bytes=..., sha256=...)`` so the envelope ``data_artifacts`` row itself
   carries the authoritative size/verified checksum.  A small ``report_renders``
   render-state record captures the non-envelope render fields (template /
   rendered_at / error).
3. The ``/v1/data-exchange/reports`` routes (``routes.py``) read the envelope
   from ``data_artifacts`` (authoritative byte metadata) and merge the
   render-state for detail/download.

Why a ``report_renders`` render-state table?
--------------------------------------------
The envelope ``data_artifacts`` row is the authoritative byte-metadata store:
``render_report`` back-fills the verified ``size_bytes``/``sha256`` through the
M4/M5 materialization transition ``DataArtifactRepository.mark_available``, so
report detail and the download ``X-Checksum-SHA256`` header are always backed
by the verified checksum recorded on the row.  ``report_renders``
(``SCHEMA_SQL`` below) is the *secondary* render-state store — it keeps the
template, ``rendered_at`` and (on failure) the error that the envelope has no
columns for, and is what list/detail/download merge for those fields.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from repositories.data_artifacts import (
    DataArtifactRepository,
    get_data_artifact_repository,
)
from repositories.repos import get_pool
from services.data_exchange.contracts import ReportSpecContract
from services.data_exchange.storage import object_key_for
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.logger.logger import get_logger, metrics
from shared.storage.object_store import (
    ObjectNotFoundError,
    ObjectStore,
    get_object_store,
)
from shared.temporal.instant import coerce_utc_lenient

logger = get_logger("aether.data_exchange.reports")

# ── constants ────────────────────────────────────────────────────────────────

REPORT_ARTIFACT_TYPE = "report"
REPORT_JOB_TYPE = "report.generate"
REPORT_CONTENT_TYPE = "application/pdf"
REPORT_FORMAT = "pdf"  # format column on the envelope — PDF is not an EgressFormat
REPORT_CLASSIFICATION = "none"
REPORT_SHA256_PENDING = "0" * 64  # placeholder until the render records real bytes
REPORT_DIRECTION = "egress"
DEFAULT_REPORT_TTL_DAYS = 7

# Lifecycle vocabulary for report envelope rows (subset of the shared
# DATA_ARTIFACT_STATUSES).  Durable-byte statuses own real ObjectStore bytes
# plus a verified checksum; tombstones are absorbing and byte-free — no
# transition may resurrect one, and bytes are never written for a tombstone.
REPORT_DURABLE_STATUSES = frozenset({"available", "committed", "partially_committed"})
REPORT_TOMBSTONE_STATUSES = frozenset({"failed", "expired", "deleted", "revoked"})

# Topic *attribute* names emitted by this plane via ``_emit`` (best-effort).
# The four ``REPORT_*`` members ARE registered on the live ``Topic`` enum
# (``shared/events/events.py``) as ``aether.report.requested`` /
# ``aether.report.available`` / ``aether.report.failed`` /
# ``aether.report.downloaded`` — values stay in lockstep with the
# ``services/data_exchange/events.py`` catalog; ``REPORT_DOWNLOADED`` mirrors
# the canonical ``EXPORT_DOWNLOADED`` topic.  ``_emit`` publishes them for real;
# it only skips silently when a member is absent (a guard against future drift).
REPORT_REQUESTED_TOPIC = "REPORT_REQUESTED"
REPORT_AVAILABLE_TOPIC = "REPORT_AVAILABLE"
REPORT_FAILED_TOPIC = "REPORT_FAILED"
REPORT_DOWNLOADED_TOPIC = "REPORT_DOWNLOADED"

# ── SCHEMA_SQL (render-state table; proposed alembic delta) ─────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS report_renders (
    report_id TEXT NOT NULL,
    artifact_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    object_key TEXT NOT NULL,
    template TEXT NOT NULL,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    rendered_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_report_renders_tenant_report
    ON report_renders (tenant_id, report_id);
CREATE INDEX IF NOT EXISTS ix_report_renders_tenant_artifact
    ON report_renders (tenant_id, artifact_id);
"""

# Module-local in-memory backing store mirroring repositories/data_artifacts.py
# (the DB-free test path).  Shared by every ReportRenderStateRepository instance.
_LOCAL_RENDER_STORE: dict[tuple[str, str], dict] = {}


def reset_report_render_store() -> None:
    """Test helper: empty the module-local render-state store."""
    _LOCAL_RENDER_STORE.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return (coerce_utc_lenient(raw) or raw).isoformat()
    return str(raw)


def _slug(value: str) -> str:
    """Lowercase filename-safe slug for the report artifact filename."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", (value or "report").lower()).strip("-")
    return slug[:60] or "report"


def new_report_artifact_id() -> str:
    """Opaque Data Exchange artifact id for a report (tenant-scoped key uses it)."""
    return f"rep_{uuid.uuid4().hex}"


# ── render-state repository (module-owned; SCHEMA_SQL above) ────────────────


class ReportRenderStateRepository:
    """Authoritative render metadata for report artifacts (Postgres / local)."""

    def __init__(self) -> None:
        self._pool: Optional[Any] = None
        self._table_ensured = False

    @property
    def _store(self) -> dict[tuple[str, str], dict]:
        # Composite-keyed by (tenant_id, artifact_id) so tenant isolation is
        # structural: a cross-tenant lookup can never collide with another
        # tenant's row and a non-owner delete is a strict no-op.
        return _LOCAL_RENDER_STORE

    @staticmethod
    def _key(tenant_id: str, artifact_id: str) -> tuple[str, str]:
        return (tenant_id, artifact_id)

    @staticmethod
    def _tenant_conflict_message(artifact_id: str, owner: str, tenant_id: str) -> str:
        return (
            f"report render state artifact_id {artifact_id!r} is owned by tenant "
            f"{owner!r}; refusing cross-tenant save for tenant {tenant_id!r}"
        )

    async def _ensure(self) -> Optional[Any]:
        if self._pool is None:
            self._pool = await get_pool()
        if self._pool is not None and not self._table_ensured:
            await self._pool.execute(SCHEMA_SQL)
            self._table_ensured = True
        return self._pool

    @staticmethod
    def _meta_from(row: dict) -> dict:
        out = {
            "report_id": row.get("report_id"),
            "artifact_id": row.get("artifact_id"),
            "tenant_id": row.get("tenant_id"),
            "object_key": row.get("object_key"),
            "template": row.get("template"),
            "filename": row.get("filename"),
            "status": row.get("status"),
            "size_bytes": int(row.get("size_bytes") or 0),
            "sha256": row.get("sha256") or "",
            "rendered_at": _iso(row.get("rendered_at")),
            "error": row.get("error"),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        out["updated_at"] = out["updated_at"] or out["created_at"]
        return out

    async def save(
        self,
        *,
        tenant_id: str,
        report_id: str,
        artifact_id: str,
        object_key: str,
        template: str,
        filename: str,
        status: str,
        size_bytes: int = 0,
        sha256: str = "",
        rendered_at: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> dict:
        now = _now()
        row = {
            "report_id": report_id,
            "artifact_id": artifact_id,
            "tenant_id": tenant_id,
            "object_key": object_key,
            "template": template,
            "filename": filename,
            "status": status,
            "size_bytes": int(size_bytes),
            "sha256": sha256,
            "rendered_at": _iso(rendered_at),
            "error": error,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        pool = await self._ensure()
        if pool is None:
            # Refuse to let one tenant create/overwrite a row for an artifact_id
            # another tenant already owns (isolation, not just absence of reads).
            for existing in self._store.values():
                if (
                    existing.get("artifact_id") == artifact_id
                    and existing.get("tenant_id") != tenant_id
                ):
                    raise ValueError(
                        self._tenant_conflict_message(
                            artifact_id, existing.get("tenant_id"), tenant_id
                        )
                    )
            self._store[self._key(tenant_id, artifact_id)] = dict(row)
            return self._meta_from(self._store[self._key(tenant_id, artifact_id)])
        # Postgres backstop + explicit refusal: the upsert is scoped to rows the
        # caller's tenant owns (artifact_id is the PK), so a cross-tenant save
        # can never hijack or partially clobber another tenant's row.
        owner = await pool.fetchval(
            "SELECT tenant_id FROM report_renders WHERE artifact_id = $1",
            artifact_id,
        )
        if owner is not None and owner != tenant_id:
            raise ValueError(
                self._tenant_conflict_message(artifact_id, owner, tenant_id)
            )
        await pool.execute(
            """
            INSERT INTO report_renders
                (report_id, artifact_id, tenant_id, object_key, template,
                 filename, status, size_bytes, sha256, rendered_at, error,
                 created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11, now(), now())
            ON CONFLICT (artifact_id) DO UPDATE SET
                status = EXCLUDED.status,
                size_bytes = EXCLUDED.size_bytes,
                sha256 = EXCLUDED.sha256,
                rendered_at = EXCLUDED.rendered_at,
                error = EXCLUDED.error,
                updated_at = now()
            WHERE report_renders.tenant_id = EXCLUDED.tenant_id
            """,
            report_id,
            artifact_id,
            tenant_id,
            object_key,
            template,
            filename,
            status,
            int(size_bytes),
            sha256,
            _parse_ts(rendered_at) if rendered_at is not None else None,
            error,
        )
        return dict(await self.get(tenant_id, artifact_id))

    async def get(self, tenant_id: str, artifact_id: str) -> Optional[dict]:
        pool = await self._ensure()
        if pool is None:
            row = self._store.get(self._key(tenant_id, artifact_id))
            if row is None:
                return None
            return self._meta_from(row)
        record = await pool.fetchrow(
            "SELECT report_id, artifact_id, tenant_id, object_key, template, "
            "filename, status, size_bytes, sha256, rendered_at, error, "
            "created_at, updated_at FROM report_renders "
            "WHERE tenant_id = $1 AND artifact_id = $2",
            tenant_id,
            artifact_id,
        )
        if record is None:
            return None
        return self._meta_from(dict(record))

    async def delete(self, tenant_id: str, artifact_id: str) -> bool:
        pool = await self._ensure()
        if pool is None:
            # Strict no-op for a non-owner: only remove the row keyed to this
            # exact (tenant_id, artifact_id), never a same-artifact row another
            # tenant owns.
            key = self._key(tenant_id, artifact_id)
            if key not in self._store:
                return False
            del self._store[key]
            return True
        result = await pool.execute(
            "DELETE FROM report_renders WHERE tenant_id = $1 AND artifact_id = $2",
            tenant_id,
            artifact_id,
        )
        return bool(getattr(result, "rowcount", 0))


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, datetime):
        return coerce_utc_lenient(raw) or raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


_render_state_repo: Optional[ReportRenderStateRepository] = None


def get_report_render_state_repository() -> ReportRenderStateRepository:
    """Module singleton mirroring ``get_data_artifact_repository()``."""
    global _render_state_repo
    if _render_state_repo is None:
        _render_state_repo = ReportRenderStateRepository()
    return _render_state_repo


# ── events (best-effort) ────────────────────────────────────────────────────


async def _emit(topic_attr: str, tenant_id: str, payload: dict) -> None:
    """Best-effort bus publish; the report flow never fails on telemetry.

    Skips silently when the ``Topic`` member does not exist yet (report topic
    members are added by the coordinator at integration, per
    ``docs/plans/data-exchange-api.md`` shared-surface deltas).
    """
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_attr, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        producer = get_producer()
        await producer.publish(
            Event(
                topic=topic,
                tenant_id=tenant_id,
                source_service="reports",
                payload=payload,
            )
        )
    except Exception as exc:  # noqa: BLE001 — telemetry must not break reports
        logger.debug(f"report event publish skipped ({topic_attr}): {exc}")


# ── template policy ─────────────────────────────────────────────────────────


def validate_template(template: str) -> str:
    """Validate a requested template strictly; returns the effective name.

    Unknown template names raise ``BadRequestError`` so ``POST /reports`` fails
    fast (400) before a durable job is enqueued.
    """
    from services.reports.renderers import resolve_template_name

    try:
        return resolve_template_name(template, strict=True)
    except Exception as exc:  # UnknownTemplateError subclasses ReportRenderError
        raise BadRequestError(str(exc)) from exc


def _resolve_template_lenient(template: Optional[str]) -> str:
    from services.reports.renderers import resolve_template_name

    return resolve_template_name(template, strict=False)


def _report_request_is_live(row: dict) -> bool:
    """True when an existing envelope row is a reusable live request intent.

    A replayed request must not stack a duplicate ``generating`` row onto a
    report_id that already has one in flight, nor mint a fresh envelope for a
    report whose durable bytes are still within TTL.  Tombstones are absorbing
    (a deleted/expired/failed/revoked report is a genuinely new request), and a
    durable row that has outlived its ``expires_at`` is logically expired even
    before the sweep tombstones it — both mint a fresh envelope.
    """
    status = row.get("status")
    if status in REPORT_TOMBSTONE_STATUSES:
        return False
    if status in REPORT_DURABLE_STATUSES:
        expires_at = _parse_ts(row.get("expires_at"))
        return expires_at is None or expires_at > _now()
    return status == "generating"


# ── request: create intent row + enqueue durable job ────────────────────────


async def request_report(
    tenant_id: str,
    spec: ReportSpecContract,
    *,
    requested_by: Optional[str] = None,
    correlation_id: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
    jobs_service: Optional[Any] = None,
) -> dict:
    """Create the egress report artifact row + enqueue ``report.generate``.

    Returns ``{report_id, artifact_id, job_id, status, replayed}``.  For a
    genuinely new report_id the artifact row is created *after* a successful
    enqueue so ``job_id`` is stamped at insert time (the M1 repo has no later
    field-update path) and ``status`` is ``generating``.  A replayed request for
    a report_id that already has a live row (still ``generating``, or a durable
    ``available`` row within TTL) returns the existing intent with
    ``replayed: True`` — no duplicate envelope row and no second enqueue.
    """
    del object_store  # reserved for a future "intent object" — bytes land at render
    if not tenant_id:
        raise BadRequestError("tenant_id is required")
    if not spec or not spec.report_id:
        raise BadRequestError("report_id is required")
    if spec.tenant_id and spec.tenant_id != tenant_id:
        raise BadRequestError(
            "cross-tenant report request refused — spec.tenant_id must match "
            "the authenticated tenant"
        )

    template_name = validate_template(spec.template)
    if spec.tenant_id != tenant_id:
        spec = spec.model_copy(update={"tenant_id": tenant_id})

    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()

    # Replay guard: a replayed request for a report_id that already has a live
    # row (still ``generating``, or a durable ``available`` row within TTL)
    # returns the existing intent instead of minting a duplicate ``generating``
    # envelope + enqueue.  Only a genuinely new report_id (or one whose prior
    # row is an absorbing tombstone / past TTL) creates a fresh row below.
    existing = await repo.get_by_canonical_id(tenant_id, spec.report_id)
    if existing is not None and _report_request_is_live(existing):
        return {
            "report_id": spec.report_id,
            "artifact_id": existing["artifact_id"],
            "job_id": existing.get("job_id"),
            "status": existing.get("status"),
            "replayed": True,
        }

    artifact_id = new_report_artifact_id()
    object_key = object_key_for(
        tenant_id, direction=REPORT_DIRECTION, artifact_id=artifact_id
    )
    stamp = _now()
    filename = (
        f"{_slug(spec.resource)}-report-{stamp.strftime('%Y%m%d')}.pdf"
    )

    spec_json = spec.model_dump(mode="json")
    hour_bucket = stamp.strftime("%Y%m%d%H")
    idem_raw = (
        f"{tenant_id}:report:{spec.report_id}:"
        f"{hashlib.sha256(str(spec_json).encode('utf-8')).hexdigest()}:{hour_bucket}"
    )
    idempotency_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()[:40]

    if jobs_service is None:
        from services.jobs.service import get_jobs_service

        jobs_service = get_jobs_service()

    job = await jobs_service.enqueue(
        tenant_id,
        REPORT_JOB_TYPE,
        {
            "report_id": spec.report_id,
            "artifact_id": artifact_id,
            "object_key": object_key,
            "template": template_name,
            "spec": spec_json,
        },
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        requested_by=requested_by,
    )

    expires_at = _now() + timedelta(days=DEFAULT_REPORT_TTL_DAYS)
    row = await repo.create_artifact(
        artifact_id,
        tenant_id,
        direction=REPORT_DIRECTION,
        artifact_type=REPORT_ARTIFACT_TYPE,
        object_key=object_key,
        filename=filename,
        format=REPORT_FORMAT,
        content_type=REPORT_CONTENT_TYPE,
        size_bytes=0,
        sha256=REPORT_SHA256_PENDING,
        classification=REPORT_CLASSIFICATION,
        status="generating",
        canonical_id=spec.report_id,
        job_id=job.get("id"),
        source_or_destination={
            "resource": spec.resource,
            "report": True,
            "destination": {"plane": "reports"},
        },
        schema_version="1",
        encryption={},
        manifest={
            "report_id": spec.report_id,
            "template": template_name,
            "spec": spec_json,
        },
        created_by=requested_by or spec.requested_by,
        correlation_id=correlation_id,
        expires_at=expires_at.isoformat(),
    )

    metrics.increment("data_exchange_report_requested_total", labels={"template": template_name})
    await _emit(
        REPORT_REQUESTED_TOPIC,
        tenant_id,
        {
            "job_id": job.get("id"),
            "report_id": spec.report_id,
            "artifact_id": row["artifact_id"],
        },
    )
    return {
        "report_id": spec.report_id,
        "artifact_id": row["artifact_id"],
        "job_id": job.get("id"),
        "status": "generating",
        "replayed": bool(job.get("replayed")),
    }


# ── render: bytes → ObjectStore → available ─────────────────────────────────


async def render_report(
    tenant_id: str,
    spec: ReportSpecContract,
    *,
    artifact_id: str,
    correlation_id: Optional[str] = None,
    job_id: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
    renderer: Optional[Callable[..., bytes]] = None,
    source_rows: Optional[list[dict]] = None,
    source_meta: Optional[dict] = None,
) -> dict:
    """Render + persist the report PDF and mark the artifact ``available``.

    Pure core of the ``report.generate`` job.  Lifecycle rules:

    - a live (``generating``) row is rendered, its bytes are put to ObjectStore
      *first*, then the envelope is flipped to ``available`` via
      ``repo.mark_available(..., size_bytes=..., sha256=...)`` so the row
      carries the authoritative verified checksum ("bytes first, metadata
      second" — never an ``available`` row without bytes);
    - a replayed render on an already-``available`` (durable) row is an
      idempotent no-op success — never a second write or a second event;
    - a render that reaches a tombstone (``deleted`` / ``expired`` / ``failed``
      / ``revoked``) fails fast *before* any render/write work: tombstones are
      absorbing and must not be resurrected by bytes.
    """
    if not tenant_id or not artifact_id:
        raise BadRequestError("tenant_id and artifact_id are required")

    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()
    row = await repo.get(tenant_id, artifact_id)  # NotFound -> propagate
    if row.get("artifact_type") != REPORT_ARTIFACT_TYPE:
        raise NotFoundError("data exchange report")

    template_name = _resolve_template_lenient(spec.template)

    # Tombstone guard — fail fast with a clear outcome before any render/write.
    status = row.get("status") or ""
    if status in REPORT_TOMBSTONE_STATUSES:
        raise ConflictError(
            f"report artifact {artifact_id!r} is tombstoned "
            f"(status={status!r}) and cannot be rendered"
        )

    # Idempotent replay: an already-available (durable) row is a no-op success.
    # The bytes are already durable and the envelope already carries the real
    # checksum; re-rendering would only double-write bytes and re-emit.
    if status in REPORT_DURABLE_STATUSES:
        render_state = await get_report_render_state_repository().get(
            tenant_id, artifact_id
        )
        return {
            "report_id": spec.report_id,
            "artifact_id": artifact_id,
            "template": template_name,
            "filename": row.get("filename"),
            "object_key": row["object_key"],
            "status": status,
            "sha256": row.get("sha256"),
            "size_bytes": row.get("size_bytes"),
            "rendered_at": (render_state or {}).get("rendered_at"),
            "download_url": f"/v1/data-exchange/reports/{spec.report_id}/download",
        }

    if renderer is None:
        from services.reports.renderers import render_report_pdf

        renderer = render_report_pdf

    content = renderer(
        spec.model_dump(mode="json"),
        template=template_name,
        include_methodology=spec.include_methodology,
        include_provenance_summary=spec.include_provenance_summary,
        display_timezone=spec.display_timezone,
        source_rows=source_rows,
        source_meta=source_meta,
    )
    if not isinstance(content, bytes) or not content:
        raise BadRequestError("report renderer returned no PDF bytes")

    sha256 = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)
    # Bytes first, metadata second — never an ``available`` row without bytes.
    store.put(row["object_key"], content)
    updated = await repo.mark_available(
        tenant_id,
        artifact_id,
        size_bytes=size_bytes,
        sha256=sha256,
    )

    rendered_at = _now()
    await get_report_render_state_repository().save(
        tenant_id=tenant_id,
        report_id=spec.report_id,
        artifact_id=artifact_id,
        object_key=row["object_key"],
        template=template_name,
        filename=row.get("filename") or "",
        status="available",
        size_bytes=size_bytes,
        sha256=sha256,
        rendered_at=rendered_at,
    )

    metrics.increment("data_exchange_report_ready_total", labels={"template": template_name})
    await _emit(
        REPORT_AVAILABLE_TOPIC,
        tenant_id,
        {
            "job_id": job_id,
            "artifact_id": artifact_id,
            "report_id": spec.report_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
        },
    )
    return {
        "report_id": spec.report_id,
        "artifact_id": artifact_id,
        "template": template_name,
        "filename": row.get("filename"),
        "object_key": row["object_key"],
        "status": updated.get("status") or "available",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "rendered_at": rendered_at.isoformat(),
        "download_url": f"/v1/data-exchange/reports/{spec.report_id}/download",
    }


async def mark_report_failed(
    tenant_id: str,
    artifact_id: str,
    *,
    error: str,
    report_id: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Best-effort failure bookkeeping: artifact ``failed`` + render record.

    Only a genuinely non-available row (still ``generating``) is flipped to
    ``failed``.  A durable-byte artifact (``available``/``committed``/…) must
    never be silently tombstoned as ``failed``, and an already-absorbing
    tombstone (``deleted``/``expired``/``revoked``/``failed``) is never
    overwritten — both are best-effort successes with no failed flip and the row
    is left untouched (only a real ``generating``→``failed`` flip records a
    failed render-state record and emits ``REPORT_FAILED``).
    Exception-safe: never raises, so failure bookkeeping can never break the
    durable job that calls it.
    """
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    failed = {"report_id": report_id or "", "artifact_id": artifact_id, "status": "failed"}
    try:
        row = await repo.get(tenant_id, artifact_id)
        if row.get("artifact_type") != REPORT_ARTIFACT_TYPE:
            return failed
        failed["report_id"] = report_id or row.get("canonical_id") or ""
        failed["filename"] = row.get("filename")
        current_status = row.get("status") or ""
        if (
            current_status in REPORT_DURABLE_STATUSES
            or current_status in REPORT_TOMBSTONE_STATUSES
        ):
            # No flip: durable bytes are never tombstoned as ``failed`` and an
            # absorbing tombstone is not overwritten.  This is a silent
            # best-effort no-op (no failed telemetry for bytes that survive, no
            # mutation of an already-absorbing row).
            return failed
        await repo.update_status(tenant_id, artifact_id, "failed")
        await get_report_render_state_repository().save(
            tenant_id=tenant_id,
            report_id=failed["report_id"],
            artifact_id=artifact_id,
            object_key=row.get("object_key") or "",
            template="",
            filename=row.get("filename") or "",
            status="failed",
            error=error,
        )
        await _emit(
            REPORT_FAILED_TOPIC,
            tenant_id,
            {
                "artifact_id": artifact_id,
                "report_id": failed["report_id"],
                "error": (error or "")[:200],
            },
        )
    except Exception as exc:  # noqa: BLE001 — failure bookkeeping is best effort
        logger.debug(f"report failure bookkeeping skipped for {artifact_id}: {exc}")
    return failed


# ── reads ────────────────────────────────────────────────────────────────────


async def get_report_artifact(
    tenant_id: str,
    report_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Resolve the newest report artifact row for a tenant-scoped report id."""
    if not tenant_id or not report_id:
        raise BadRequestError("tenant_id and report_id are required")
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    row = await repo.get_by_canonical_id(tenant_id, report_id)
    if (
        row is None
        or row.get("artifact_type") != REPORT_ARTIFACT_TYPE
        or row.get("direction") != REPORT_DIRECTION
    ):
        raise NotFoundError("data exchange report")
    return row


def _merge_render_meta(row: dict, render_state: Optional[dict]) -> dict:
    """Envelope + render meta for the report routes.

    The envelope ``data_artifacts`` row is authoritative for byte metadata:
    ``render_report`` back-fills the verified ``size_bytes``/``sha256`` via
    ``repo.mark_available``.  The render-state record is secondary — it adds
    the non-envelope fields (rendered_at / template / error).
    """
    meta = dict(render_state or {})
    envelope = dict(row)
    if meta:
        envelope["rendered_at"] = meta.get("rendered_at") or envelope.get("rendered_at")
        envelope["template"] = meta.get("template") or envelope.get("template")
    return {
        "report_id": envelope.get("canonical_id"),
        "artifact": envelope,
        "render_meta": meta if meta else None,
    }


async def list_report_artifacts(
    tenant_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """List the tenant's egress report artifacts (newest first)."""
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    limit = max(0, int(limit))
    offset = max(0, int(offset))
    rows = await repo.list_for_tenant(
        tenant_id,
        limit=limit,
        offset=offset,
        direction=REPORT_DIRECTION,
        artifact_type=REPORT_ARTIFACT_TYPE,
        status=status,
    )
    artifacts: list[dict] = []
    render_state_repo = get_report_render_state_repository()
    for row in rows:
        render_state = await render_state_repo.get(tenant_id, row["artifact_id"])
        merged = _merge_render_meta(row, render_state)
        artifacts.append(
            {
                "report_id": merged["report_id"],
                "artifact_id": row["artifact_id"],
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "expires_at": row.get("expires_at"),
                "filename": row.get("filename"),
                "content_type": row.get("content_type"),
                "size_bytes": merged["artifact"].get("size_bytes"),
                "sha256": merged["artifact"].get("sha256"),
                "template": (render_state or {}).get("template"),
                "rendered_at": (render_state or {}).get("rendered_at"),
                "manifest": row.get("manifest"),
            }
        )
    return {"artifacts": artifacts, "count": len(artifacts)}


async def get_report_detail(
    tenant_id: str,
    report_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
) -> dict:
    """Envelope + render meta for ``GET /reports/{report_id}``."""
    row = await get_report_artifact(tenant_id, report_id, artifact_repo=artifact_repo)
    render_state = await get_report_render_state_repository().get(
        tenant_id, row["artifact_id"]
    )
    merged = _merge_render_meta(row, render_state)
    return {
        "report_id": merged["report_id"],
        "artifact": merged["artifact"],
        "render_meta": merged["render_meta"],
    }


async def download_report(
    tenant_id: str,
    report_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
) -> tuple[dict, bytes]:
    """Return ``(meta, bytes)`` for a downloadable report.

    Mirrors canonical export download semantics: only ``available`` artifacts
    are served.  Tombstoned reports (``deleted`` / ``expired`` / ``failed`` /
    ``revoked``) and still-``generating`` reports refuse with a canonical error
    rather than an empty file, and an ``available`` row that has outlived its
    ``expires_at`` is treated as expired even before the sweep tombstones it.
    Real bytes are served only when the row carries a verified checksum.
    """
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()
    row = await get_report_artifact(tenant_id, report_id, artifact_repo=repo)

    status = row.get("status") or ""
    if status in REPORT_TOMBSTONE_STATUSES:
        raise NotFoundError("data exchange report (deleted, expired, failed or revoked)")
    # TTL consistency: an available row past its expires_at is logically expired
    # (mirrors the canonical export-download gate refusing expired artifacts).
    expires_at = _parse_ts(row.get("expires_at"))
    if expires_at is not None and expires_at <= _now():
        raise NotFoundError("data exchange report (deleted or expired)")
    if status != "available":
        raise ConflictError(f"report {report_id!r} is not available (status={status!r})")
    # ``available`` means durable bytes + a verified checksum on the row; never
    # serve a byte-less/placeholder row as if it were real content.
    row_sha = row.get("sha256") or ""
    row_size = int(row.get("size_bytes") or 0)
    if row_sha == REPORT_SHA256_PENDING or row_size <= 0:
        raise ConflictError(f"report {report_id!r} is not available (no verified checksum)")

    render_state = await get_report_render_state_repository().get(
        tenant_id, row["artifact_id"]
    )
    try:
        content = store.get(row["object_key"])
    except ObjectNotFoundError:
        raise NotFoundError("data exchange report content") from None
    if not content:
        raise NotFoundError("data exchange report content")

    meta = {
        "report_id": report_id,
        "artifact_id": row["artifact_id"],
        "object_key": row["object_key"],
        "filename": row.get("filename") or f"{_slug(report_id)}.pdf",
        "content_type": REPORT_CONTENT_TYPE,
        "size_bytes": row_size,
        "sha256": row_sha,
        "rendered_at": (render_state or {}).get("rendered_at"),
        "template": (render_state or {}).get("template"),
    }
    return meta, content


async def emit_report_downloaded(tenant_id: str, meta: dict) -> None:
    """Best-effort ``REPORT_DOWNLOADED`` bus event (download mirror of export).

    Called by the download route after bytes are served; never blocks the
    response.  Skips silently until the coordinator adds the report topic
    members to the live ``Topic`` enum.
    """
    await _emit(
        REPORT_DOWNLOADED_TOPIC,
        tenant_id,
        {
            "artifact_id": meta.get("artifact_id"),
            "report_id": meta.get("report_id"),
            "sha256": meta.get("sha256"),
            "size_bytes": meta.get("size_bytes"),
        },
    )


async def delete_report(
    tenant_id: str,
    report_id: str,
    *,
    artifact_repo: Optional[DataArtifactRepository] = None,
    object_store: Optional[ObjectStore] = None,
) -> dict:
    """Revoke a report: tombstone the envelope row + drop the render record.

    Physical ObjectStore deletion is left to the M7 expiry sweep; this removes
    the render state so the tombstone carries the verified checksum as an audit
    trace.  Deleting an already-tombstoned report is an idempotent no-op — an
    absorbing tombstone (``deleted``/``expired``/``failed``/``revoked``) is
    never overwritten with ``deleted`` (the repo would refuse the transition).
    """
    repo = artifact_repo if artifact_repo is not None else get_data_artifact_repository()
    store = object_store if object_store is not None else get_object_store()
    row = await get_report_artifact(tenant_id, report_id, artifact_repo=repo)
    render_state = await get_report_render_state_repository().get(
        tenant_id, row["artifact_id"]
    )
    tombstone_sha256 = (render_state or {}).get("sha256") or row.get("sha256")
    status = row.get("status") or ""
    if status not in REPORT_TOMBSTONE_STATUSES:
        await repo.mark_deleted(tenant_id, row["artifact_id"])
    await get_report_render_state_repository().delete(tenant_id, row["artifact_id"])
    if store:
        try:
            store.delete(row["object_key"])
        except Exception:  # noqa: BLE001 — M7 sweep is authoritative for physical deletes
            logger.debug(f"report object delete best-effort failed for {row['object_key']}")
    return {
        "deleted": True,
        "report_id": report_id,
        "artifact_id": row["artifact_id"],
        "tombstone_sha256": tombstone_sha256,
    }
