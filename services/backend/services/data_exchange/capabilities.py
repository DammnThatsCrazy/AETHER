"""Data Exchange Plane — read adapters (M3): ``/settings`` ``/capabilities`` ``/usage``.

Read-only envelopes under ``/v1/data-exchange``.  ``/settings`` and
``/capabilities`` derive their surface from ``DataExchangeConfig`` flags
(``config/settings.py``) plus the M0 contract tuples
(``services/data_exchange/contracts.py``); ``/usage`` derives per-tenant
counts from the M1 ``data_artifacts`` metadata rows so it needs no external
metering service.  M6 (frontend) builds its Settings → Data Exchange sections
against exactly these three adapters (freeze ``docs/plans/data-exchange-api.md``
M3 / M6).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request

from repositories.data_artifacts import get_data_artifact_repository
from services.data_exchange.authz import require_data_exchange
from shared.temporal.instant import coerce_utc_lenient
from services.data_exchange.contracts import (
    DATA_ARTIFACT_STATUSES,
    DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS,
    DATA_EXCHANGE_CLASSIFICATIONS,
    DATA_EXCHANGE_DIRECTIONS,
    DATA_EXCHANGE_EGRESS_FORMATS,
    DATA_EXCHANGE_INGRESS_FORMATS,
    DATA_EXCHANGE_SOURCE_TYPES,
)

router = APIRouter(prefix="/v1/data-exchange", tags=["Data Exchange Capabilities"])


def _tenant(request: Request, permission: str = "data_exchange.read"):
    tenant = request.state.tenant
    require_data_exchange(tenant, permission)
    return tenant


def _de_config():
    """Lazy settings access so tests can monkeypatch ``config.settings.settings``."""
    from config.settings import settings

    return settings.data_exchange


def _max_upload_bytes() -> int:
    try:
        from services.imports.service import DEFAULT_MAX_UPLOAD_BYTES

        return int(DEFAULT_MAX_UPLOAD_BYTES)
    except Exception:  # pragma: no cover — defensive default
        return 25 * 1024 * 1024


def _egress_formats() -> list[str]:
    dq = _de_config()
    formats = list(DATA_EXCHANGE_EGRESS_FORMATS)
    if not getattr(dq, "parquet_enabled", False):
        formats = [f for f in formats if f != "parquet"]
    return formats


# ── GET /v1/data-exchange/settings ──────────────────────────────────────────


def _imports_settings(dq) -> dict:
    return {
        "enabled": bool(getattr(dq, "enabled", False)),
        "sources": list(DATA_EXCHANGE_SOURCE_TYPES),
        "formats": list(DATA_EXCHANGE_INGRESS_FORMATS),
        "max_upload_bytes": _max_upload_bytes(),
        "saved_mappings_enabled": True,
        "identity_preview_enabled": True,
        "graph_preview_enabled": True,
        "blocked_classifications": list(DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS),
    }


def _exports_settings(dq) -> dict:
    return {
        "enabled": bool(getattr(dq, "enabled", False)),
        "formats": _egress_formats(),
        "parquet_enabled": bool(getattr(dq, "parquet_enabled", False)),
    }


def _reports_settings(dq) -> dict:
    return {
        "enabled": bool(getattr(dq, "reports_enabled", False)),
        "formats": ["pdf"],
    }


def _transfers_settings(dq) -> dict:
    object_store = bool(getattr(dq, "object_store_enabled", False))
    signed = bool(getattr(dq, "signed_transfers_enabled", False))
    return {
        "enabled": bool(object_store and signed),
        "object_store_enabled": object_store,
        "signed_transfers_enabled": signed,
    }


def _capabilities_settings(dq) -> dict:
    return {
        "enabled": bool(getattr(dq, "enabled", False)),
        "directions": list(DATA_EXCHANGE_DIRECTIONS),
        "artifact_statuses": list(DATA_ARTIFACT_STATUSES),
        "classifications": list(DATA_EXCHANGE_CLASSIFICATIONS),
    }


@router.get("/settings")
async def data_exchange_settings(request: Request):
    """M6 settings source: per-family availability + capability surface."""
    tenant = _tenant(request, "data_exchange.read")
    dq = _de_config()
    return {
        "tenant_id": tenant.tenant_id,
        "imports": _imports_settings(dq),
        "exports": _exports_settings(dq),
        "reports": _reports_settings(dq),
        "transfers": _transfers_settings(dq),
        "capabilities": _capabilities_settings(dq),
    }


# ── GET /v1/data-exchange/capabilities ──────────────────────────────────────


@router.get("/capabilities")
async def data_exchange_capabilities(request: Request):
    """M6 capability gate: what the Data Exchange plane exposes today."""
    tenant = _tenant(request, "data_exchange.read")
    dq = _de_config()
    return {
        "tenant_id": tenant.tenant_id,
        "data_exchange": {
            "enabled": bool(getattr(dq, "enabled", False)),
            "flags": {
                "object_store_enabled": bool(getattr(dq, "object_store_enabled", False)),
                "parquet_enabled": bool(getattr(dq, "parquet_enabled", False)),
                "reports_enabled": bool(getattr(dq, "reports_enabled", False)),
                "signed_transfers_enabled": bool(
                    getattr(dq, "signed_transfers_enabled", False)
                ),
            },
        },
        "available_formats": {
            "ingress": list(DATA_EXCHANGE_INGRESS_FORMATS),
            "egress": _egress_formats(),
        },
        "available_sources": list(DATA_EXCHANGE_SOURCE_TYPES),
        "available_directions": list(DATA_EXCHANGE_DIRECTIONS),
        "available_classifications": list(DATA_EXCHANGE_CLASSIFICATIONS),
        "blocked_classifications": list(DATA_EXCHANGE_BLOCKED_CLASSIFICATIONS),
    }


# ── GET /v1/data-exchange/usage ─────────────────────────────────────────────


async def _artifact_rows(tenant_id: str) -> list[dict]:
    """All the tenant's data-artifact metadata rows (usage aggregation).

    Uses the repository's projected, uncapped ``usage_rows`` (not
    ``list_for_tenant(limit=100000)``) so the aggregation overcounts no tenant
    and drags only the five columns it actually reads (finding #13).
    """
    repo = get_data_artifact_repository()
    rows = await repo.usage_rows(tenant_id)
    return rows


def _in_window(created_at: Optional[str], since: datetime) -> bool:
    if not created_at:
        return False
    # Kernel-sanctioned instant parse (assumes UTC on a tz-less input).
    dt = coerce_utc_lenient(created_at)
    return dt is not None and dt >= since


async def _import_usage(tenant_id: str, rows: list[dict]) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    count = 0
    last_30 = 0
    for row in rows:
        src = row.get("source_or_destination") or {}
        if row.get("direction") == "ingress" or src.get("import_id") or (
            row.get("artifact_type") == "import_source"
        ):
            count += 1
            if _in_window(row.get("created_at"), since):
                last_30 += 1
    return {"count": count, "last_30_days": last_30}


async def _export_usage(rows: list[dict]) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=30)
    count = 0
    bytes_total = 0
    last_30 = 0
    last_30_bytes = 0
    for row in rows:
        if row.get("direction") != "egress":
            continue
        if row.get("artifact_type") in ("export", "report", None):
            count += 1
            bytes_total += int(row.get("size_bytes") or 0)
            if _in_window(row.get("created_at"), since):
                last_30 += 1
                last_30_bytes += int(row.get("size_bytes") or 0)
    return {
        "count": count,
        "bytes": bytes_total,
        "last_30_days": last_30,
        "last_30_days_bytes": last_30_bytes,
    }


async def _report_usage(rows: list[dict]) -> dict:
    count = 0
    for row in rows:
        if row.get("artifact_type") == "report" and row.get("direction") == "egress":
            count += 1
    return {"count": count}


@router.get("/usage")
async def data_exchange_usage(request: Request):
    """Per-tenant usage over ``data_artifacts`` metadata (no metering service)."""
    tenant = _tenant(request, "data_exchange.read")
    rows = await _artifact_rows(tenant.tenant_id)
    return {
        "tenant_id": tenant.tenant_id,
        "imports": await _import_usage(tenant.tenant_id, rows),
        "exports": await _export_usage(rows),
        "reports": await _report_usage(rows),
        "quotas": {
            # Plan-tier quotas are supplied by the canonical entitlement layer;
            # the Data Exchange surface reflects no standalone quota today.
            "enforced": False,
            "families": [],
        },
    }
