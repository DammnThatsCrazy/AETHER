"""WooCommerce pull ingestion (:class:`PullAdapter`).

GET ``{base}/orders`` (base = ``https://<site>/wp-json/wc/v3``) with the
WooCommerce paging contract:

* ``per_page`` clamped to ``[1, 100]``;
* the incremental window is ``after=<date_modified ISO>`` (the manifest's
  ``sync.cursor`` is ``date_modified``);
* in-window pagination is ``page=<n>`` advanced off the ``X-WP-TotalPages``
  response header (falling back to a single page when the header is absent).

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``after:<iso>`` -> ``after=<iso>``, page 1 (incremental window start);
* ``after:<iso>:page:<n>`` -> ``after=<iso>``, page ``n`` (in-window paging);
* ``page:<n>`` -> no window, page ``n`` (backfill paging);
* ``after:<max date_modified>`` is emitted on the last page of a window so the
  next incremental read advances by the newest ``date_modified`` seen.

Auth: HTTP Basic ``(consumer_key, consumer_secret)``. The request URL is built
from the SSRF-validated host only — the path is pinned in code.

Error mapping: network/5xx -> RETRYABLE_ERROR, 401 -> UNAUTHORIZED,
429 -> RATE_LIMITED (honoring ``Retry-After``), else PERMANENT_ERROR.
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

from services.providers.woocommerce.auth import (
    _base_url,
    _credential_dict,
    _raw_site_url,
    _safe_json,
    _site_host,
)

# WooCommerce caps per_page at 100; values above it are truncated server-side.
_MAX_PER_PAGE = 100
_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: after:<iso> | after:<iso>:page:<n> | page:<n> (see module docstring).
CURSOR_SCHEME = "after:<iso> (date_modified window) | after:<iso>:page:<n> | page:<n>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], int]:
    """Split a cursor into ``(after_iso, page)``; malformed cursors degrade to (None, 1)."""
    if not cursor:
        return None, 1
    if cursor.startswith("after:"):
        parts = cursor.split(":page:")
        after = parts[0][len("after:"):]
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        return after or None, page
    if cursor.startswith("page:"):
        n = cursor[len("page:"):]
        return None, int(n) if n.isdigit() else 1
    return None, 1


def _build_params(cursor: Optional[str], limit: Optional[int]) -> dict[str, str]:
    """Map a cursor + limit onto WooCommerce query parameters (documented scheme)."""
    if limit is None:
        clamped = _MAX_PER_PAGE
    else:
        clamped = max(1, min(int(limit), _MAX_PER_PAGE))
    after, page = _parse_cursor(cursor)
    params: dict[str, str] = {"per_page": str(clamped)}
    if after:
        params["after"] = after
    if page > 1:
        params["page"] = str(page)
    return params


def _total_pages(headers) -> Optional[int]:
    """WooCommerce page count from ``X-WP-TotalPages`` (absent -> single page)."""
    raw = headers.get("X-WP-TotalPages") or headers.get("x-wp-totalpages")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _next_cursor(
    headers,
    orders: list[dict],
    *,
    after: Optional[str],
    page: int,
) -> Optional[str]:
    """Advance the cursor: in-window page first, then the date_modified window."""
    total_pages = _total_pages(headers)
    if total_pages is not None and page < total_pages:
        base = f"after:{after}:page:{page + 1}" if after else f"page:{page + 1}"
        return base
    dates = [
        o.get("date_modified")
        for o in orders
        if isinstance(o, dict) and isinstance(o.get("date_modified"), str) and o["date_modified"]
    ]
    if dates:
        return f"after:{max(dates)}"
    return None


def _retry_after_ms(headers) -> Optional[float]:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


class WooCommercePullAdapter:
    """PullAdapter: cursor-addressable order ingestion (poll sync)."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``after`` window."""
        return await self.fetch(context, cursor=None)

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        cred = _credential_dict(context)
        raw_url = _raw_site_url(context)
        # The validated host (public FQDN of site_url) — never a raw tenant value.
        host = _site_host(context)
        if not raw_url:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_missing",
                retryable=False,
                data={"detail": "site_url is required for pull"},
            )
        if not host:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_invalid",
                retryable=False,
                data={
                    "detail": "site_url is not a valid public https host "
                    "(structural gate; resolver-level check required at live-auth time)"
                },
            )
        missing = [
            name for name in ("consumer_key", "consumer_secret")
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
        after, page = _parse_cursor(cursor)
        params = _build_params(cursor, limit)
        url = f"{base}/orders?" + urllib.parse.urlencode(params)

        import httpx

        try:
            async with _http_client() as client:
                response = await client.get(
                    url,
                    headers={"Accept": "application/json"},
                    auth=httpx.BasicAuth(cred["consumer_key"], cred["consumer_secret"]),
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
                data={"detail": "woocommerce rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "woocommerce rejected the consumer credential (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"woocommerce returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"woocommerce returned HTTP {response.status_code}"},
            )

        body = _safe_json(response)
        orders = body.get("orders") if isinstance(body, dict) else None
        if orders is None:
            # WooCommerce returns a bare JSON array for /orders.
            orders = body if isinstance(body, list) else []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(order["id"]),
                provider_record_type="order",
                provider_occurred_at=order.get("date_modified"),
                payload=order,
                acquisition_mode="poll",
                account_id=context.account_id,
                connection_id=context.connection_id,
                tenant_id=context.tenant_id,
                cursor=cursor,
            )
            for order in orders
            if isinstance(order, dict) and order.get("id") is not None
        ]
        next_cursor = _next_cursor(
            response.headers,
            [o for o in orders if isinstance(o, dict)],
            after=after,
            page=page,
        )
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch)


__all__ = [
    "CURSOR_SCHEME",
    "WooCommercePullAdapter",
    "_build_params",
    "_next_cursor",
    "_parse_cursor",
]
