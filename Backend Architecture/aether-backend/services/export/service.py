"""
Aether Service — Canonical Export Service

One export path for artifact-producing exports: a durable job on the jobs
platform generates the artifact, verifies its checksum, persists a manifest,
and only then reports success. No export is "ready" without a verified,
durable artifact — inline row responses (the legacy audit-export mode) remain
available on their original routes, but downloads always come from here.

Exporters are registered in EXPORTERS: an async callable
``(tenant_id, params) -> ExportPayload`` returning the rows plus metadata.
The first (reference) domain is the audit log, reusing the exact source
readers behind ``/v1/audit/exports`` so both paths share one implementation.

CSV serialization applies formula-injection protection: any cell beginning
with ``= + - @`` is prefixed with a single quote so spreadsheet clients never
execute attacker-controlled formulas.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

from repositories.artifacts import get_artifact_repository
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.export")

# Artifacts default to a 7-day life; the expiry sweep then physically deletes
# content and leaves a tombstone (id, sha256, manifest).
DEFAULT_ARTIFACT_TTL_DAYS = 7

SUPPORTED_FORMATS = ("json", "csv", "ndjson")

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass
class ExportPayload:
    """What an exporter returns: rows plus manifest metadata."""

    rows: list[dict]
    columns: Optional[list[str]] = None
    per_source: dict[str, int] = field(default_factory=dict)


Exporter = Callable[[str, dict], Awaitable[ExportPayload]]

# Registered exporters keyed by export_type.
EXPORTERS: dict[str, Exporter] = {}


def register_exporter(export_type: str) -> Callable:
    def decorator(fn: Exporter) -> Exporter:
        if export_type in EXPORTERS:
            raise ValueError(f"Exporter already registered for {export_type!r}")
        EXPORTERS[export_type] = fn
        return fn

    return decorator


# ── serialization ─────────────────────────────────────────────────────────


def _csv_safe(value: Any) -> Any:
    """Neutralize spreadsheet formula injection on string cells."""
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def serialize_rows(rows: list[dict], fmt: str, columns: Optional[list[str]] = None) -> tuple[bytes, str, list[str]]:
    """Serialize rows; returns (bytes, content_type, columns_used)."""
    if fmt == "json":
        return (
            json.dumps(rows, default=str, sort_keys=True).encode("utf-8"),
            "application/json",
            columns or [],
        )
    if fmt == "ndjson":
        body = "\n".join(json.dumps(r, default=str, sort_keys=True) for r in rows)
        return body.encode("utf-8"), "application/x-ndjson", columns or []
    if fmt == "csv":
        cols = columns or sorted({k for r in rows for k in r})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: _csv_safe(row.get(c, "")) for c in cols})
        return buf.getvalue().encode("utf-8"), "text/csv", cols
    raise BadRequestError(f"Unsupported export format {fmt!r}. Valid: {list(SUPPORTED_FORMATS)}")


# ── events ───────────────────────────────────────────────────────────────


async def _emit(topic_name: str, tenant_id: str, payload: dict) -> None:
    """Best-effort bus publish; export flow never fails on telemetry."""
    try:
        from shared.events.events import Event, Topic

        topic = getattr(Topic, topic_name, None)
        if topic is None:
            return
        from dependencies.providers import get_producer

        producer = get_producer()
        await producer.publish(Event(topic=topic, tenant_id=tenant_id, payload=payload))
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(f"export event publish skipped: {exc}")


# ── public API ───────────────────────────────────────────────────────────


async def request_export(
    tenant_id: str,
    *,
    export_type: str,
    params: dict,
    requested_by: Optional[str],
    correlation_id: Optional[str],
) -> dict:
    """Validate + enqueue a durable export job; returns {job_id, status, status_url}."""
    if export_type not in EXPORTERS:
        raise BadRequestError(
            f"Unknown export_type {export_type!r}. Registered: {sorted(EXPORTERS)}"
        )
    fmt = (params or {}).get("format", "json")
    if fmt not in SUPPORTED_FORMATS:
        raise BadRequestError(
            f"Unsupported export format {fmt!r}. Valid: {list(SUPPORTED_FORMATS)}"
        )
    from services.jobs.service import get_jobs_service

    # Same tenant+type+params within the hour replays the same job.
    hour_bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    idem_raw = f"{tenant_id}:{export_type}:{json.dumps(params, sort_keys=True, default=str)}:{hour_bucket}"
    idempotency_key = hashlib.sha256(idem_raw.encode()).hexdigest()[:40]

    job = await get_jobs_service().enqueue(
        tenant_id,
        "export.generate",
        {"export_type": export_type, "params": params or {}},
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        requested_by=requested_by,
    )
    metrics.increment("export_requested_total", labels={"export_type": export_type})
    await _emit("EXPORT_REQUESTED", tenant_id, {"job_id": job["id"], "export_type": export_type})
    return {
        "job_id": job["id"],
        "status": job.get("status", "queued"),
        "status_url": f"/v1/jobs/{job['id']}",
        "replayed": bool(job.get("replayed")),
    }


# ── job handlers ─────────────────────────────────────────────────────────


async def generate_export_artifact(payload: dict, ctx: Any) -> Any:
    """Job handler: run an exporter, persist + verify the artifact, notify."""
    from services.export.manifest import build_manifest
    from services.jobs.handlers import JobOutcome

    export_type = payload.get("export_type", "")
    params = payload.get("params", {}) or {}
    exporter = EXPORTERS.get(export_type)
    if exporter is None:
        return JobOutcome(
            status="failed",
            result={},
            error=f"no exporter registered for {export_type!r}",
        )

    result = await exporter(ctx.tenant_id, params)
    await ctx.heartbeat()

    fmt = params.get("format", "json")
    content, content_type, columns = serialize_rows(result.rows, fmt, result.columns)
    manifest = build_manifest(
        content,
        export_type=export_type,
        tenant_id=ctx.tenant_id,
        params=params,
        correlation_id=ctx.correlation_id,
        row_count=len(result.rows),
        columns=columns or None,
        per_source=result.per_source or None,
    )
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=DEFAULT_ARTIFACT_TTL_DAYS)
    ).isoformat()

    repo = get_artifact_repository()
    artifact = await repo.put(
        ctx.tenant_id,
        export_type=export_type,
        filename=f"{export_type.replace('.', '-')}-{manifest['generated_at'][:10]}.{fmt}",
        content=content,
        content_type=content_type,
        manifest=manifest,
        job_id=ctx.job_id,
        expires_at=expires_at,
    )
    # Never report success without verified durable bytes.
    if not await repo.verify(ctx.tenant_id, artifact["id"]):
        return JobOutcome(
            status="failed",
            result={"artifact_id": artifact["id"]},
            error="artifact checksum verification failed after write",
        )

    metrics.increment("export_ready_total", labels={"export_type": export_type})
    await ctx.emit_event(
        "export.ready",
        {"artifact_id": artifact["id"], "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"]},
    )
    await _emit(
        "EXPORT_READY",
        ctx.tenant_id,
        {"job_id": ctx.job_id, "artifact_id": artifact["id"], "export_type": export_type},
    )
    # Best-effort in-app notification; the durable artifact is the record.
    try:
        from services.notification_intelligence.inbox import create_inbox_notification

        await create_inbox_notification(
            ctx.tenant_id,
            category="export_ready",
            severity="info",
            title=f"Export ready: {export_type}",
            body=f"{artifact['filename']} ({artifact['size_bytes']} bytes) is ready to download.",
            link=f"/v1/exports/{artifact['id']}/download",
            correlation_id=ctx.correlation_id,
            dedupe_key=f"export:{artifact['id']}",
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(f"export inbox notification skipped: {exc}")

    return JobOutcome(
        status="succeeded",
        result={
            "artifact_id": artifact["id"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "download_url": f"/v1/exports/{artifact['id']}/download",
        },
    )


async def expire_export_artifacts(payload: dict, ctx: Any) -> Any:
    """Job handler: physically delete expired artifact content (tombstone stays)."""
    from services.jobs.handlers import JobOutcome

    swept = await get_artifact_repository().expire_sweep()
    if swept.get("swept"):
        metrics.increment("export_artifact_deleted_total", value=swept["swept"])
        await _emit("EXPORT_EXPIRED", ctx.tenant_id, {"swept": swept["swept"]})
    return JobOutcome(status="succeeded", result=swept)


def register_export_handlers() -> None:
    """Register export job handlers with the jobs platform (idempotent)."""
    from services.jobs.handlers import HANDLER_REGISTRY, register_handler

    if "export.generate" not in HANDLER_REGISTRY:
        register_handler("export.generate")(generate_export_artifact)
    if "export.expire_sweep" not in HANDLER_REGISTRY:
        register_handler("export.expire_sweep")(expire_export_artifacts)


async def run_export_expiry_sweep_loop(interval_seconds: int = 3600) -> None:
    """Supervised periodic sweep — physical deletion of expired artifacts."""
    import asyncio

    while True:
        try:
            swept = await get_artifact_repository().expire_sweep()
            if swept.get("swept"):
                metrics.increment("export_artifact_deleted_total", value=swept["swept"])
                logger.info(f"export expiry sweep removed {swept['swept']} artifact(s)")
        except Exception as exc:
            logger.warning(f"export expiry sweep failed: {exc}")
        await asyncio.sleep(interval_seconds)


def build_export_expiry_sweep_coro():
    return run_export_expiry_sweep_loop()


# ── reference exporter: audit log ────────────────────────────────────────


@register_exporter("audit_log")
async def _audit_log_exporter(tenant_id: str, params: dict) -> ExportPayload:
    """Audit-trail export reusing the exact source readers behind /v1/audit."""
    from services.consent.audit_routes import (
        AUDIT_SOURCES,
        _filter_by_time,
        _read_source,
        _sort_key,
    )

    sources = params.get("sources") or AUDIT_SOURCES
    unknown = [s for s in sources if s not in AUDIT_SOURCES]
    if unknown:
        raise BadRequestError(f"Unknown audit sources {unknown}. Valid: {AUDIT_SOURCES}")

    rows: list[dict] = []
    per_source: dict[str, int] = {}
    for source in sources:
        records = await _read_source(source, tenant_id)
        records = _filter_by_time(records, params.get("from_ts"), params.get("to_ts"))
        for record in records:
            record.setdefault("source", source)
        per_source[source] = len(records)
        rows.extend(records)
    rows.sort(key=_sort_key)
    return ExportPayload(rows=rows, per_source=per_source)
