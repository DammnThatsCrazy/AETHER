"""Shopify pull ingestion (:class:`PullAdapter`).

GET ``{base}/admin/api/{version}/orders.json?status=any&limit=250`` with
``page_info`` (opaque next-page token) or ``since_id`` (legacy-style
incremental id) cursors.

Cursor strategy (documented in :data:`CURSOR_SCHEME`):

* a next-page token from the Shopify ``Link rel="next"`` header (or
  ``X-Shopify-Next-Page-Token``) is stored prefixed ``page_info:<token>`` and
  echoed back as the ``page_info`` query parameter;
* a cursor that is all digits is treated as a legacy incremental order id and
  sent as ``since_id``.

Auth header: ``X-Shopify-Access-Token`` when a ``shop_access_token`` credential
is present, otherwise HTTP Basic ``(api_key, password)`` — mirroring the legacy
connector's auth style.

Error mapping: network/5xx -> RETRYABLE_ERROR, 401 -> UNAUTHORIZED,
429 -> RATE_LIMITED (honoring ``Retry-After``), else PERMANENT_ERROR.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import ReadBatch, make_raw_record
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
)

from services.providers.shopify.auth import (
    _api_version,
    _credential_dict,
    _raw_shop_domain,
    _safe_json,
    _shop_domain,
)

# Next-page tokens are opaque Shopify page_info values; prefix them so a token
# can never be confused with a legacy numeric since_id cursor.
PAGE_INFO_PREFIX = "page_info:"

# Cursor scheme: "page_info:<opaque>" -> page_info=<opaque>; "<int>" -> since_id=<int>.
CURSOR_SCHEME = f"{PAGE_INFO_PREFIX}<opaque> | <int> (since_id)"

_MAX_LIMIT = 250
_REQUEST_TIMEOUT_SECONDS = 10.0
_REL_NEXT_RE = re.compile(r'<([^>]+)>\s*;\s*rel="next"')


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _build_params(cursor: Optional[str], limit: Optional[int]) -> dict[str, str]:
    """Map a cursor + limit onto Shopify query parameters (documented scheme).

    ``limit`` is clamped to ``[1, _MAX_LIMIT]`` (0/negative would be rejected by
    Shopify; values above the page cap are truncated).
    """
    if limit is None:
        clamped = _MAX_LIMIT
    else:
        clamped = max(1, min(int(limit), _MAX_LIMIT))
    params: dict[str, str] = {
        "status": "any",
        "limit": str(clamped),
    }
    if cursor:
        if cursor.startswith(PAGE_INFO_PREFIX):
            params["page_info"] = cursor[len(PAGE_INFO_PREFIX):]
        elif cursor.isdigit():
            params["since_id"] = cursor
        # Any other cursor shape is dropped: it is neither a page token nor an
        # id we can honor, and sending it would corrupt the query.
    return params


def _request_auth(cred: dict[str, Any]):
    """Return (headers, httpx_auth). Prefers the OAuth-style access token."""
    import httpx

    token = cred.get("shop_access_token")
    if token:
        return {"X-Shopify-Access-Token": str(token), "Accept": "application/json"}, None
    return (
        {"Accept": "application/json"},
        httpx.BasicAuth(str(cred.get("api_key", "")), str(cred.get("password", ""))),
    )


def _next_cursor_from_headers(headers) -> Optional[str]:
    """Extract the next-page token from Link rel=next / X-Shopify-Next-Page-Token."""
    token = headers.get("X-Shopify-Next-Page-Token")
    if token:
        return f"{PAGE_INFO_PREFIX}{token}"
    link = headers.get("Link") or ""
    for part in link.split(","):
        match = _REL_NEXT_RE.match(part.strip())
        if not match:
            continue
        query = urllib.parse.urlparse(match.group(1)).query
        page_info = urllib.parse.parse_qs(query).get("page_info")
        if page_info:
            return f"{PAGE_INFO_PREFIX}{page_info[0]}"
    return None


def _rate_limit_from_headers(headers) -> Optional[RateLimitInfo]:
    """Parse ``X-Shopify-Shop-Api-Call-Limit: "<reported>/<limit>"``.

    Per the UPR seam, the first value is treated as the reported remaining
    capacity and the second as the bucket limit. ``reset_epoch_ms`` is not
    derivable from Shopify's rolling bucket header and is left ``None``.
    """
    raw = headers.get("X-Shopify-Shop-Api-Call-Limit") or headers.get(
        "x-shopify-shop-api-call-limit"
    )
    if not raw:
        return None
    # Tolerate optional surrounding quotes on either side of the slash.
    parts = [part.strip().strip('"').strip("'") for part in str(raw).split("/")]
    if len(parts) != 2:
        return None
    try:
        reported = int(parts[0])
        limit = int(parts[1])
    except ValueError:
        return None
    return RateLimitInfo(limit=limit, remaining=reported, reset_epoch_ms=None, retry_after_ms=0)


def _retry_after_ms(headers) -> Optional[float]:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


class ShopifyPullAdapter:
    """PullAdapter: cursor-addressable order ingestion (poll sync)."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: ``status=any`` with no cursor."""
        return await self.fetch(context, cursor=None)

    async def fetch(
        self,
        context: AcquisitionContext,
        *,
        cursor: Optional[str],
        limit: Optional[int] = None,
    ) -> AdapterResult[ReadBatch]:
        cred = _credential_dict(context)
        raw_domain = _raw_shop_domain(context)
        # The validated host (allowlisted *.myshopify.com) — never a raw tenant value.
        shop_domain = _shop_domain(context)
        if not raw_domain:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_missing",
                retryable=False,
                data={"detail": "shop_domain is required for pull"},
            )
        if not shop_domain:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_invalid",
                retryable=False,
                data={"detail": "shop_domain is not a valid *.myshopify.com host"},
            )
        missing = [name for name in ("api_key", "password") if not str(cred.get(name) or "").strip()]
        if missing and not cred.get("shop_access_token"):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )

        headers, auth = _request_auth(cred)
        params = _build_params(cursor, limit)
        url = (
            f"https://{shop_domain}/admin/api/{_api_version(context)}/orders.json?"
            + urllib.parse.urlencode(params)
        )
        try:
            async with _http_client() as client:
                response = await client.get(url, headers=headers, auth=auth)
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
                data={"detail": "shopify rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "shopify rejected the credential (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"shopify returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"shopify returned HTTP {response.status_code}"},
            )

        body = _safe_json(response)
        orders = body.get("orders") or []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(order["id"]),
                provider_record_type="order",
                provider_occurred_at=order.get("updated_at"),
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
        next_cursor = _next_cursor_from_headers(response.headers)
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch, rate_limit=_rate_limit_from_headers(response.headers))


__all__ = [
    "CURSOR_SCHEME",
    "PAGE_INFO_PREFIX",
    "ShopifyPullAdapter",
    "_build_params",
]
