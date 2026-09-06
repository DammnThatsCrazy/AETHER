"""Data Exchange Plane — export exporter(s) over the canonical registry (M4).

M4 is a *control envelope* over the canonical export engine
(``services/export/service.py``): it never builds a second export engine.  This
module contributes three things to the canonical ``EXPORTERS`` registry and the
canonical ``serialize_rows`` surface:

- ``data_exchange_export`` — a canonical-style exporter registered under the
  stable export_type ``data_exchange``.  Its signature mirrors the existing
  exporters (``async (tenant_id, params) -> ExportPayload``); ``params`` carry
  the envelope's resource / scope / fields / filters / temporal plus ``format``.
  For a resource that is itself a registered canonical domain exporter
  (``audit_log``, ``targeting_package``, ``governance_evidence_pack``, …) it
  delegates to that exporter — the envelope is a thin translation, never a new
  reader.  Rows may also be injected directly via ``params["rows"]`` for
  envelope-local payloads and tests.
- ``data_exchange_parquet`` — the parquet-specific stable export_type.  It is
  the same envelope exporter registered under a second name so a caller can
  target a parquet job explicitly through the canonical surface (which has
  understood parquet since the M4 serializer delta).
- ``produce_export_bytes`` — the M4 serializer dispatcher.  ``csv`` / ``json`` /
  ``ndjson`` go through the *canonical* ``serialize_rows`` (formula-safe CSV);
  ``parquet`` goes through :mod:`services.data_exchange.parquet`.  This is the
  single seam a parquet-capable caller (the canonical ``export.generate``
  handler, which routes ``parquet`` through ``serialize_rows`` since the M4
  coordinator delta, or a direct caller) invokes.

Registration is **not** a decorator side effect: exporters register only when
``register_data_exchange_exporters()`` runs (coordinator invokes it from the
FastAPI lifespan alongside ``register_export_handlers()``), mirroring the M1
``data_exchange.migrate_legacy_artifact`` job-registration pattern.  The call is
idempotent across test sys.modules churn.
"""

from __future__ import annotations

from typing import Any, Optional

from services.data_exchange.parquet import (
    PARQUET_COMPRESSIONS,
    PARQUET_CONTENT_TYPE,
    PARQUET_FORMAT,
)
from shared.common.common import BadRequestError
from shared.logger.logger import get_logger

logger = get_logger("aether.data_exchange.export")

# ── stable export_type names registered in the canonical EXPORTERS registry ──

#: Generic data-exchange envelope export.  Envelope specs whose ``resource`` is
#: not a registered canonical domain exporter target this type.
EXPORT_TYPE_DATA_EXCHANGE = "data_exchange"

#: Parquet-targeting alias of the envelope exporter.  Registered so a caller can
#: express "I want a data-exchange artifact in parquet" through the canonical
#: ``request_export`` vocabulary — the canonical serializer surface has accepted
#: ``parquet`` (in ``SUPPORTED_FORMATS``, routed through ``serialize_rows``)
#: since the M4 coordinator delta.
EXPORT_TYPE_DATA_EXCHANGE_PARQUET = "data_exchange_parquet"

#: These export types are the envelope's own — never re-entered as a "resource".
_SELF_EXPORT_TYPES = frozenset(
    {EXPORT_TYPE_DATA_EXCHANGE, EXPORT_TYPE_DATA_EXCHANGE_PARQUET}
)

#: Egress formats the envelope can express today (EgressFormat vocabulary).
EGRESS_FORMATS: tuple[str, ...] = ("csv", "json", "ndjson", PARQUET_FORMAT)

#: Content types the envelope records on egress data_artifacts rows.
EGRESS_CONTENT_TYPES: dict[str, str] = {
    "json": "application/json",
    "csv": "text/csv",
    "ndjson": "application/x-ndjson",
    PARQUET_FORMAT: PARQUET_CONTENT_TYPE,
}


# ── serializer dispatcher ────────────────────────────────────────────────────
# Canonical serialize_rows owns csv/json/ndjson (including its CSV formula
# protection).  Parquet is M4's addition via parquet.py.  All formats return the
# canonical (bytes, content_type, columns_used) triple so a caller cannot tell
# which serializer produced the payload.


def produce_export_bytes(
    rows: list[dict],
    *,
    format: str,  # noqa: A002 - shadows builtin like canonical serialize_rows
    columns: Optional[list[str]] = None,
    compression: Optional[str] = None,
) -> tuple[bytes, str, list[str]]:
    """Serialize rows into one of ``{json, csv, ndjson, parquet}`` payload bytes.

    ``csv`` / ``json`` / ``ndjson`` delegate to the canonical
    ``serialize_rows`` (so CSV formula protection and content types are
    byte-identical to the canonical engine).  ``parquet`` delegates to
    :mod:`services.data_exchange.parquet`; ``compression`` applies only to the
    parquet path and accepts ``gzip`` / ``snappy`` / ``zstd``.

    Returns ``(bytes, content_type, columns_used)`` matching the canonical
    serializer's return contract.
    """
    fmt = str(format or "json").strip().lower()
    if fmt == PARQUET_FORMAT:
        from services.data_exchange.parquet import rows_to_parquet_bytes

        content = rows_to_parquet_bytes(rows, columns=columns, compression=compression)
        used = columns or sorted({k for r in rows for k in r})
        return content, PARQUET_CONTENT_TYPE, used

    # Canonical surface owns csv/json/ndjson and (since the M4 serializer delta)
    # parquet too, and raises BadRequestError for anything it does not know.
    from services.export.service import serialize_rows

    return serialize_rows(rows, fmt, columns)


# ── envelope exporter (canonical-style) ──────────────────────────────────────


def _project_rows(rows: list[dict], fields: Optional[list[str]]) -> list[dict]:
    """Apply the envelope ``fields`` allowlist (None/empty keeps every column)."""
    if not fields:
        return rows
    allowed = set(fields)
    return [{k: row[k] for k in row if k in allowed} for row in rows]


async def data_exchange_export(tenant_id: str, params: dict) -> Any:
    """Envelope exporter: translate a Data Exchange export request to rows.

    Canonical-style exporter (signature mirrors ``services/export/service.py``
    exporters: ``async (tenant_id, params) -> ExportPayload``).  ``params``
    carry the envelope vocabulary — ``resource``, ``scope``, ``fields``,
    ``filters``, ``temporal`` and ``format``.

    Row resolution, in order:

    1. ``resource`` names a registered canonical domain exporter → delegate to
       it (tenant-scoped canonical reader; no new data path).
    2. ``params["rows"]`` is present → use those rows directly (envelope-local
       payloads and tests), projected onto the ``fields`` allowlist.
    3. otherwise → ``BadRequestError`` listing what M4 can actually export.
    """
    if not tenant_id:
        raise BadRequestError("tenant_id is required")
    resource = (params or {}).get("resource") or ""
    fields = params.get("fields")

    from services.export.service import EXPORTERS, ExportPayload

    if resource and resource not in _SELF_EXPORT_TYPES and resource in EXPORTERS:
        # The envelope proxies an existing canonical domain exporter — never a
        # second reader.  The delegated exporter is itself tenant-scoped.
        result = await EXPORTERS[resource](tenant_id, params)
        if isinstance(result, ExportPayload):
            return ExportPayload(
                rows=_project_rows(result.rows, fields),
                columns=result.columns,
                per_source=result.per_source,
            )
        return result

    rows = params.get("rows")
    if isinstance(rows, list):
        projected = _project_rows(rows, fields)
        columns = fields or sorted({k for r in projected for k in r})
        return ExportPayload(rows=projected, columns=columns, per_source={"rows": len(projected)})

    supported = sorted(
        k for k in EXPORTERS if k not in _SELF_EXPORT_TYPES
    ) or ["<rows injected via params>"]
    raise BadRequestError(
        f"data_exchange export resource {resource!r} is not supported. "
        f"Registered resources: {supported}"
    )


async def data_exchange_parquet_export(tenant_id: str, params: dict) -> Any:
    """Parquet-targeting alias of :func:`data_exchange_export`.

    Registered under ``data_exchange_parquet`` so the parquet intent is stable
    and addressable through the canonical ``request_export`` export_type
    vocabulary.  Forcing ``format=parquet`` here keeps the registry entry honest
    about what it produces.
    """
    fmt = (params or {}).get("format") or PARQUET_FORMAT
    if str(fmt).strip().lower() != PARQUET_FORMAT:
        raise BadRequestError(
            f"export_type {EXPORT_TYPE_DATA_EXCHANGE_PARQUET!r} only supports "
            f"format {PARQUET_FORMAT!r} (got {fmt!r})"
        )
    return await data_exchange_export(tenant_id, params)


# ── registration ─────────────────────────────────────────────────────────────


def register_data_exchange_exporters() -> None:
    """Register the Data Exchange envelope exporters in the canonical registry.

    Idempotent: re-imports and repeated lifespan calls never double-register
    (the canonical ``register_exporter`` raises on a duplicate key, so each
    registration is guarded by a membership check).  The coordinator calls this
    from the FastAPI lifespan alongside ``register_export_handlers()``.

    Coordinator delta to invoke (main.py lifespan, gated by
    ``settings.data_exchange.enabled``):

        from services.data_exchange.exporters import (
            register_data_exchange_exporters,
        )
        register_data_exchange_exporters()
    """
    from services.export.service import EXPORTERS, register_exporter

    if EXPORT_TYPE_DATA_EXCHANGE not in EXPORTERS:
        register_exporter(EXPORT_TYPE_DATA_EXCHANGE)(data_exchange_export)
        logger.info("registered canonical exporter export_type=%s", EXPORT_TYPE_DATA_EXCHANGE)
    if EXPORT_TYPE_DATA_EXCHANGE_PARQUET not in EXPORTERS:
        register_exporter(EXPORT_TYPE_DATA_EXCHANGE_PARQUET)(data_exchange_parquet_export)
        logger.info(
            "registered canonical exporter export_type=%s", EXPORT_TYPE_DATA_EXCHANGE_PARQUET
        )


def parquet_compressions_available() -> tuple[str, ...]:
    """Expose the accepted parquet compression codes for capability surfaces."""
    return PARQUET_COMPRESSIONS
