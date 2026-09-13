"""TikTok Shop pull ingestion (:class:`PullAdapter`).

POST ``{base}/order/search`` (base = ``https://open-api.tiktokglobalshop.com``)
with the TikTok Shop order-search contract:

* request body ``{"page_size": <n>, "page_token": <token>}``;
* the incremental window is a ``update_time`` range (``update_time_ge`` /
  ``update_time_lt`` epoch-seconds), advancing from the manifest's
  ``sync.cursor`` ``update_time``;
* in-window pagination advances the opaque ``next_page_token`` returned in the
  response body.

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``update_time:<epoch>`` -> ``{"update_time_ge": <epoch>}`` (window start);
* ``update_time:<epoch>:token:<tok>`` -> window + ``page_token=<tok>``;
* ``token:<tok>`` -> ``page_token=<tok>`` only (backfill pagination).

Every request is signed with :func:`services.providers.tiktok.auth.sign_request`
(``app_secret`` + sorted params + timestamp + nonce). Error mapping: network/5xx
-> RETRYABLE_ERROR, 401 -> UNAUTHORIZED, 429 -> RATE_LIMITED, else
PERMANENT_ERROR.
"""

from __future__ import annotations

import secrets
import time as _time
import urllib.parse
from typing import Any, Optional

from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import ReadBatch, make_raw_record
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
)

from services.providers.tiktok.auth import (
    _base_url,
    _credential_dict,
    _safe_json,
    sign_request,
)
from services.providers.tiktok.normalizer import _epoch_to_iso

_MAX_PAGE_SIZE = 100
_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: update_time:<epoch> | update_time:<epoch>:token:<tok> | token:<tok>.
CURSOR_SCHEME = "update_time:<epoch> (update_time range) | update_time:<epoch>:token:<tok> | token:<tok>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a cursor into ``(update_time_ge, page_token)``; malformed degrade."""
    if not cursor:
        return None, None
    if cursor.startswith("update_time:"):
        parts = cursor.split(":token:")
        window = parts[0][len("update_time:"):]
        token = parts[1] if len(parts) > 1 else None
        return (window or None), token
    if cursor.startswith("token:"):
        return None, cursor[len("token:"):]
    return None, None


def _build_body(cursor: Optional[str], limit: Optional[int]) -> dict[str, Any]:
    """Map a cursor + limit onto the TikTok order/search body (documented scheme)."""
    if limit is None:
        clamped = _MAX_PAGE_SIZE
    else:
        clamped = max(1, min(int(limit), _MAX_PAGE_SIZE))
    window, token = _parse_cursor(cursor)
    body: dict[str, Any] = {"page_size": clamped}
    if token:
        body["page_token"] = token
    if window:
        try:
            body["update_time_ge"] = int(window)
        except (TypeError, ValueError):
            pass
    return body


def _to_int(value: Any) -> Optional[int]:
    """Coerce an epoch value to int; non-numeric/missing -> None (never raises)."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _next_cursor(body: dict[str, Any], orders: list[dict], *, window: Optional[str]) -> Optional[str]:
    """Advance the cursor: ``next_page_token`` paging, then the update_time range.

    Non-numeric ``update_time`` values are skipped; if no numeric window value is
    seen this page the cursor falls back to the previous window (never raises
    out of ``fetch``).
    """
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, dict):
        token = data.get("next_page_token")
        if token:
            base = f"update_time:{window}:token:{token}" if window else f"token:{token}"
            return base
    numeric: list[int] = []
    for o in orders:
        if not isinstance(o, dict):
            continue
        ts = _to_int(o.get("update_time"))
        if ts is not None:
            numeric.append(ts)
    if numeric:
        return f"update_time:{max(numeric)}"
    if window:
        return f"update_time:{window}"
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


class TikTokPullAdapter:
    """PullAdapter: page_token-paginated, cursor-addressable order ingestion."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``update_time`` range."""
        return await self.fetch(context, cursor=None)

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        cred = _credential_dict(context)
        missing = [
            name for name in ("app_key", "app_secret", "shop_id")
            if not str(cred.get(name) or "").strip()
        ]
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
                data={"detail": "tiktok api base failed SSRF allowlist validation"},
            )

        body = _build_body(cursor, limit)
        # The signed material is EXACTLY what is transmitted: every signed param
        # (app_key/shop_id/path + the body state merged in) rides the query
        # string alongside a wall-clock timestamp and a real per-request nonce,
        # so a server can recompute the HMAC from the request alone. The JSON
        # body is the API's request body; ``sign`` is the recomputable HMAC.
        params: dict[str, Any] = {
            "app_key": cred["app_key"],
            "shop_id": cred["shop_id"],
            "path": "/order/search",
        }
        params.update(body)
        timestamp = int(_time.time())
        nonce = secrets.token_hex(8)  # never a constant — per-request nonce
        signature = sign_request(
            app_secret=cred["app_secret"],
            params=params,
            timestamp=timestamp,
            nonce=nonce,
        )

        transmitted = dict(params)
        transmitted["timestamp"] = str(timestamp)
        transmitted["nonce"] = nonce
        transmitted["sign"] = signature
        url = f"{base}/order/search?" + urllib.parse.urlencode(transmitted)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            async with _http_client() as client:
                response = await client.post(url, json=body, headers=headers)
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
                data={"detail": "tiktok rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "tiktok rejected the app credential (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"tiktok returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"tiktok returned HTTP {response.status_code}"},
            )

        body_resp = _safe_json(response)
        data = body_resp.get("data") if isinstance(body_resp, dict) else None
        orders = data.get("orders") if isinstance(data, dict) else None
        orders = orders or []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(order["order_id"]),
                provider_record_type="order",
                provider_occurred_at=_occurred_at(order.get("update_time")),
                payload=order,
                acquisition_mode="poll",
                account_id=context.account_id,
                connection_id=context.connection_id,
                tenant_id=context.tenant_id,
                cursor=cursor,
            )
            for order in orders
            if isinstance(order, dict) and order.get("order_id") is not None
        ]
        window, _ = _parse_cursor(cursor)
        next_cursor = _next_cursor(
            body_resp,
            [o for o in orders if isinstance(o, dict)],
            window=window,
        )
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch)


__all__ = [
    "CURSOR_SCHEME",
    "TikTokPullAdapter",
    "_build_body",
    "_next_cursor",
    "_parse_cursor",
]
