"""Walmart Marketplace pull ingestion (:class:`PullAdapter`).

GET ``{base}/v3/orders`` (base = ``https://marketplace.walmartapis.com``) with
the Walmart orders contract:

* the incremental window is ``createdStartDate=<iso>`` (the manifest's
  ``sync.cursor`` is ``nextCursor``, advanced from the response's ``nextCursor``
  and echoed as the ``nextCursor`` query parameter);
* ``limit`` clamped to ``[1, 200]``.

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``createdStartDate:<iso>`` -> ``createdStartDate=<iso>`` (window start);
* ``createdStartDate:<iso>:cursor:<next>`` -> window + ``nextCursor=<next>``;
* ``cursor:<next>`` -> ``nextCursor=<next>`` only (backfill pagination).

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

from services.providers.walmart.auth import _base_url, _credential_dict

_MAX_PER_PAGE = 200
_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: createdStartDate:<iso> | createdStartDate:<iso>:cursor:<next> | cursor:<next>.
CURSOR_SCHEME = "createdStartDate:<iso> (created window) | createdStartDate:<iso>:cursor:<next> | cursor:<next>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a cursor into ``(created_start, next_cursor)``; malformed degrade."""
    if not cursor:
        return None, None
    if cursor.startswith("createdStartDate:"):
        parts = cursor.split(":cursor:")
        start = parts[0][len("createdStartDate:"):]
        nxt = parts[1] if len(parts) > 1 else None
        return (start or None), nxt
    if cursor.startswith("cursor:"):
        return None, cursor[len("cursor:"):]
    return None, None


def _build_params(cursor: Optional[str], limit: Optional[int]) -> dict[str, str]:
    """Map a cursor + limit onto Walmart query parameters (documented scheme)."""
    if limit is None:
        clamped = _MAX_PER_PAGE
    else:
        clamped = max(1, min(int(limit), _MAX_PER_PAGE))
    start, nxt = _parse_cursor(cursor)
    params: dict[str, str] = {"limit": str(clamped)}
    if start:
        params["createdStartDate"] = start
    if nxt:
        params["nextCursor"] = nxt
    return params


def _next_cursor(body: dict[str, Any], *, window: Optional[str]) -> Optional[str]:
    """Advance the cursor: Walmart's ``nextCursor`` (else the created window).

    Mid-pagination the cursor keeps the ``createdStartDate:<iso>`` incremental
    window (``createdStartDate:<iso>:cursor:<next>``) so a resumption carries the
    window even if the provider's opaque ``nextCursor`` expires.
    """
    list_obj = body.get("list") if isinstance(body, dict) else None
    elements = list_obj.get("elements") if isinstance(list_obj, dict) else None
    nxt = list_obj.get("nextCursor") if isinstance(list_obj, dict) else None
    if nxt:
        return f"createdStartDate:{window}:cursor:{nxt}" if window else f"cursor:{nxt}"
    orders = elements if isinstance(elements, list) else body.get("orders")
    dates = [
        o.get("orderDate")
        for o in orders or []
        if isinstance(o, dict) and isinstance(o.get("orderDate"), str) and o["orderDate"]
    ]
    if dates:
        return f"createdStartDate:{max(dates)}"
    return None


def _retry_after_ms(headers) -> Optional[float]:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


def _safe_json(response) -> dict[str, Any]:
    """Best-effort JSON body parse; never raises (adapter must return AdapterResult)."""
    if not getattr(response, "content", None):
        return {}
    try:
        parsed = response.json()
    except Exception:  # noqa: BLE001 - malformed body degrades to an empty dict
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WalmartPullAdapter:
    """PullAdapter: nextCursor-paginated, cursor-addressable order ingestion."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``createdStartDate`` window."""
        return await self.fetch(context, cursor=None)

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        cred = _credential_dict(context)
        access_token = str(cred.get("access_token") or "").strip()
        if not access_token:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": "access_token is required for pull"},
            )
        base = _base_url(context)
        if not base:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="api_base_invalid",
                retryable=False,
                data={"detail": "walmart api base failed SSRF allowlist validation"},
            )

        params = _build_params(cursor, limit)
        url = f"{base}/v3/orders?" + urllib.parse.urlencode(params)
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
                data={"detail": "walmart rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "walmart rejected the access token (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"walmart returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"walmart returned HTTP {response.status_code}"},
            )

        body = _safe_json(response)
        list_obj = body.get("list") if isinstance(body, dict) else None
        elements = list_obj.get("elements") if isinstance(list_obj, dict) else None
        orders = elements if isinstance(elements, list) else body.get("orders")
        orders = orders or []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(order["orderId"]),
                provider_record_type="order",
                provider_occurred_at=order.get("orderDate"),
                payload=order,
                acquisition_mode="poll",
                account_id=context.account_id,
                connection_id=context.connection_id,
                tenant_id=context.tenant_id,
                cursor=cursor,
            )
            for order in orders
            if isinstance(order, dict) and order.get("orderId") is not None
        ]
        start, _ = _parse_cursor(cursor)
        next_cursor = _next_cursor(body, window=start)
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch)


__all__ = [
    "CURSOR_SCHEME",
    "WalmartPullAdapter",
    "_build_params",
    "_next_cursor",
    "_parse_cursor",
]
