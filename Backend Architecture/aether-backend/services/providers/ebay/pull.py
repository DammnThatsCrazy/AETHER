"""eBay pull ingestion (:class:`PullAdapter`).

GET ``{base}/sell/fulfillment/v1/order`` (base = ``https://api.ebay.com``) with
the eBay Fulfillment order-search contract:

* the incremental window is ``filter=lastmodifieddate:[<iso>..]`` (the manifest's
  ``sync.cursor`` is ``lastmodifieddate``);
* in-window pagination advances the opaque ``continuationToken`` returned in the
  response body.

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``after:<iso>`` -> ``filter=lastmodifieddate:[<iso>..]`` (window start);
* ``after:<iso>:token:<cont>`` -> window + ``continuationToken=<cont>``;
* ``token:<cont>`` -> ``continuationToken=<cont>`` only (backfill paging).

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

from services.providers.ebay.auth import _base_url, _credential_dict

_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: after:<iso> (lastmodifieddate window) | after:<iso>:token:<cont> | token:<cont>.
CURSOR_SCHEME = "after:<iso> (lastmodifieddate window) | after:<iso>:token:<cont> | token:<cont>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a cursor into ``(after_iso, continuation_token)``; malformed degrade."""
    if not cursor:
        return None, None
    if cursor.startswith("after:"):
        parts = cursor.split(":token:")
        after = parts[0][len("after:"):]
        token = parts[1] if len(parts) > 1 else None
        return (after or None), token
    if cursor.startswith("token:"):
        return None, cursor[len("token:"):]
    return None, None


def _build_query(cursor: Optional[str]) -> dict[str, str]:
    """Map a cursor onto eBay query parameters (documented scheme)."""
    after, token = _parse_cursor(cursor)
    params: dict[str, str] = {"limit": "200"}
    if after:
        params["filter"] = f"lastmodifieddate:[{after}..]"
    if token:
        params["continuationToken"] = token
    return params


def _next_cursor(body: dict[str, Any], *, window: Optional[str]) -> Optional[str]:
    """Advance the cursor: continuationToken paging, then the lastmodifieddate window.

    Mid-pagination the cursor keeps the ``after:<iso>`` incremental window
    (``after:<iso>:token:<cont>``) so a resumption carries the window even if
    the provider's opaque continuation token expires.
    """
    token = body.get("continuationToken")
    if token:
        return f"after:{window}:token:{token}" if window else f"token:{token}"
    orders = body.get("orders") if isinstance(body, dict) else []
    dates = [
        o.get("modifiedDate")
        for o in orders
        if isinstance(o, dict) and isinstance(o.get("modifiedDate"), str) and o["modifiedDate"]
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


def _safe_json(response) -> dict[str, Any]:
    """Best-effort JSON body parse; never raises (adapter must return AdapterResult)."""
    if not getattr(response, "content", None):
        return {}
    try:
        parsed = response.json()
    except Exception:  # noqa: BLE001 - malformed body degrades to an empty dict
        return {}
    return parsed if isinstance(parsed, dict) else {}


class EbayPullAdapter:
    """PullAdapter: continuation-token-paginated, cursor-addressable ingestion."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``lastmodifieddate`` filter."""
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
            # The long-lived refresh secret is NEVER sent as a Bearer access
            # token — a missing access_token fails the adapter honestly.
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": "a valid access_token is required for pull "
                               "(refresh_token is never used as a bearer credential)"},
            )
        base = _base_url(context)
        if not base:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="api_base_invalid",
                retryable=False,
                data={"detail": "ebay api base failed SSRF allowlist validation"},
            )

        params = _build_query(cursor)
        url = f"{base}/sell/fulfillment/v1/order?" + urllib.parse.urlencode(params)
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
                data={"detail": "ebay rate-limited (HTTP 429)"},
            )
        if response.status_code == 401:
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": "ebay rejected the access token (HTTP 401)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"ebay returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"ebay returned HTTP {response.status_code}"},
            )

        body = _safe_json(response)
        orders = body.get("orders") if isinstance(body, dict) else []
        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(order["orderId"]),
                provider_record_type="order",
                provider_occurred_at=order.get("modifiedDate"),
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
        after, _ = _parse_cursor(cursor)
        next_cursor = _next_cursor(body, window=after)
        batch = ReadBatch(records=records, next_cursor=next_cursor, has_more=next_cursor is not None)
        return AdapterResult.ok(batch)


__all__ = [
    "CURSOR_SCHEME",
    "EbayPullAdapter",
    "_build_query",
    "_next_cursor",
    "_parse_cursor",
]
