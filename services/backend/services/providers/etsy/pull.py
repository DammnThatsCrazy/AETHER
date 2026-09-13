"""Etsy pull ingestion (:class:`PullAdapter`).

GET ``{base}/application/shops/{shop_id}/receipts`` (base =
``https://openapi.etsy.com/v3``) with Etsy's offset pagination:

* ``limit`` clamped to ``[1, 100]``, ``offset`` for in-window paging;
* the incremental window filter is ``last_updated=<update_ts>`` where
  ``update_ts`` is the receipt's epoch-seconds cursor field (documented as the
  plugin's pull contract).

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``update_ts:<epoch>`` -> ``last_updated=<epoch>``, offset 0 (window start);
* ``update_ts:<epoch>:offset:<n>`` -> ``last_updated=<epoch>``, offset ``n``;
* ``offset:<n>`` -> no window, offset ``n`` (backfill pagination).

Next-cursor: the Etsy response's ``next_offset`` (when non-null) advances the
offset; on the final page the window advances to the max ``update_ts`` seen so
the next incremental read continues from the newest receipt.

Auth: bearer ``access_token``. Error mapping: network/5xx -> RETRYABLE_ERROR,
401 -> UNAUTHORIZED, 429 -> RATE_LIMITED, else PERMANENT_ERROR.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Optional

from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import ReadBatch, make_raw_record
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
)

from services.providers.etsy.auth import _base_url, _credential_dict, _safe_json
from services.providers.etsy.normalizer import _epoch_to_iso

_MAX_PER_PAGE = 100
_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: update_ts:<epoch> | update_ts:<epoch>:offset:<n> | offset:<n>.
CURSOR_SCHEME = "update_ts:<epoch> (last_updated window) | update_ts:<epoch>:offset:<n> | offset:<n>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], int]:
    """Split a cursor into ``(window_ts, offset)``; malformed cursors degrade."""
    if not cursor:
        return None, 0
    if cursor.startswith("update_ts:"):
        parts = cursor.split(":offset:")
        window = parts[0][len("update_ts:"):]
        offset = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return window or None, offset
    if cursor.startswith("offset:"):
        n = cursor[len("offset:"):]
        return None, int(n) if n.isdigit() else 0
    return None, 0


def _build_params(cursor: Optional[str], limit: Optional[int], shop_id: str) -> dict[str, str]:
    """Map a cursor + limit onto Etsy query parameters (documented scheme)."""
    if limit is None:
        clamped = _MAX_PER_PAGE
    else:
        clamped = max(1, min(int(limit), _MAX_PER_PAGE))
    window, offset = _parse_cursor(cursor)
    params: dict[str, str] = {"limit": str(clamped)}
    if offset > 0:
        params["offset"] = str(offset)
    if window:
        params["last_updated"] = window
    return params


def _to_int(value: Any) -> Optional[int]:
    """Coerce an epoch value to int; non-numeric/missing -> None (never raises)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _next_cursor(body: dict[str, Any], orders: list[dict], *, window: Optional[str], offset: int) -> Optional[str]:
    """Advance the cursor: ``next_offset`` paging, then the update_ts window.

    Non-numeric ``update_ts`` values are skipped; if no numeric window value is
    seen this page the cursor falls back to the previous window (never raises
    out of ``fetch``).
    """
    next_offset = body.get("next_offset")
    if next_offset is not None:
        n = _to_int(next_offset)
        if n is None:
            n = offset
        if n != offset:
            base = f"update_ts:{window}:offset:{n}" if window else f"offset:{n}"
            return base
    numeric: list[int] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        ts = _to_int(o.get("update_ts"))
        if ts is not None:
            numeric.append(ts)
    if numeric:
        return f"update_ts:{max(numeric)}"
    if window:
        return f"update_ts:{window}"
    return None


def _occurred_at(ts: Any) -> str:
    """Epoch seconds -> ISO-8601 UTC; missing/non-numeric -> "" (never raises)."""
    epoch = _to_int(ts)
    if epoch is None:
        return ""
    return _epoch_to_iso(epoch)


def _retry_after_ms(headers) -> Optional[float]:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


class EtsyPullAdapter:
    """PullAdapter: offset-paginated, cursor-addressable receipt ingestion."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``last_updated`` window."""
        return await self.fetch(context, cursor=None)

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        cred = _credential_dict(context)
        shop_id = str(cred.get("shop_id") or "").strip()
        access_token = str(cred.get("access_token") or "").strip()
        missing = []
        if not shop_id:
            missing.append("shop_id")
        if not access_token:
            missing.append("access_token")
        if missing:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )
        base = _base_url(context)
        if not base:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="api_base_invalid",
                retryable=False,
                data={"detail": "etsy api base failed SSRF allowlist validation"},
            )

        params = _build_params(cursor, limit, shop_id)
        url = f"{base}/application/shops/{shop_id}/receipts?" + urllib.parse.urlencode(params)
        try:
            async with _http_client() as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {access_token}",
                    },
                )
        except Exception as exc:  # noqa: BLE001 - network failures are classified
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code="connection_failed",
                retryable=True,
                data={"detail": f"connection failed: {type(exc).__name__}"},
            )

        if response.status_code == 429:
            retry_after = _retry_after_ms(response.headers)
            return AdapterResult(
                success=False,
                status=AdapterStatus.RATE_LIMITED,
                error_code="rate_limited",
                retryable=True,
                rate_limit=RateLimitInfo(retry_after_ms=retry_after),
                data={"detail": "etsy rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "etsy rejected the access token (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"etsy returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"etsy returned HTTP {response.status_code}"},
            )

        body = _safe_json(response)
        receipts = body.get("results") if isinstance(body, dict) else []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(receipt["receipt_id"]),
                provider_record_type="order",
                provider_occurred_at=_occurred_at(receipt.get("update_ts")),
                payload=receipt,
                acquisition_mode="poll",
                account_id=context.account_id,
                connection_id=context.connection_id,
                tenant_id=context.tenant_id,
                cursor=cursor,
            )
            for receipt in receipts
            if isinstance(receipt, dict) and receipt.get("receipt_id") is not None
        ]
        window, offset = _parse_cursor(cursor)
        next_cursor = _next_cursor(
            body,
            [r for r in receipts if isinstance(r, dict)],
            window=window,
            offset=offset,
        )
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch)


__all__ = [
    "CURSOR_SCHEME",
    "EtsyPullAdapter",
    "_build_params",
    "_next_cursor",
    "_parse_cursor",
]
