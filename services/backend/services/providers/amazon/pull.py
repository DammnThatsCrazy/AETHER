"""Amazon pull ingestion (:class:`PullAdapter`).

GET ``{base}/orders/v0/orders`` (base = regional SP-API allowlist, resolved by
:func:`services.providers.amazon.auth._base_url`) with the Amazon Orders
contract:

* the incremental window is ``CreatedAfter=<iso>`` (the manifest's
  ``sync.cursor`` is ``created``);
* in-window pagination advances the opaque ``NextToken`` returned in the
  response body under ``payload.NextToken``.

Each order in a page is enriched with its line items via the per-order
endpoint ``GET /orders/v0/orders/{orderId}/orderItems`` (best-effort: a failed
items fetch never drops the order record — the order is emitted with
``items_fetched=False`` visible metadata, never silently lost).

Cursor scheme (:data:`CURSOR_SCHEME`):

* ``created:<iso>`` -> ``CreatedAfter=<iso>`` (window start);
* ``created:<iso>:token:<cont>`` -> window + ``NextToken=<cont>``;
* ``token:<cont>`` -> ``NextToken=<cont>`` only (backfill paging).

Auth: the LWA ``access_token`` travels as the ``x-amz-access-token`` header.
Full SP-API transport (live LWA exchange + AWS SigV4 request signing) is a
certification-level follow-on and is NOT claimed this build — the adapter's
structural surface (URL/query/cursor/error mapping) is what tests replay.
Error mapping: network/5xx -> RETRYABLE_ERROR, 401/403 -> UNAUTHORIZED,
429 -> RATE_LIMITED, else PERMANENT_ERROR.
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

from services.providers.amazon.auth import _base_url, _credential_dict

_REQUEST_TIMEOUT_SECONDS = 10.0


# Cursor scheme: created:<iso> (CreatedAfter window) | created:<iso>:token:<cont> | token:<cont>.
CURSOR_SCHEME = "created:<iso> (CreatedAfter window) | created:<iso>:token:<cont> | token:<cont>"


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _parse_cursor(cursor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a cursor into ``(created_iso, next_token)``; malformed degrade."""
    if not cursor:
        return None, None
    if cursor.startswith("created:"):
        parts = cursor.split(":token:")
        after = parts[0][len("created:"):]
        token = parts[1] if len(parts) > 1 else None
        return (after or None), token
    if cursor.startswith("token:"):
        return None, cursor[len("token:"):]
    return None, None


def _build_query(cursor: Optional[str]) -> dict[str, str]:
    """Map a cursor onto Amazon Orders query parameters (documented scheme)."""
    after, token = _parse_cursor(cursor)
    params: dict[str, str] = {"MaxResultsPerPage": "100"}
    if after:
        params["CreatedAfter"] = after
    if token:
        params["NextToken"] = token
    return params


def _next_cursor(body: dict[str, Any], *, window: Optional[str]) -> Optional[str]:
    """Advance the cursor: NextToken paging, then the CreatedAfter window.

    Mid-pagination the cursor keeps the ``created:<iso>`` incremental window
    (``created:<iso>:token:<cont>``) so a resumption carries the window even if
    the provider's opaque ``NextToken`` expires.
    """
    payload = body.get("payload") if isinstance(body, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    token = payload.get("NextToken")
    if token:
        return f"created:{window}:token:{token}" if window else f"token:{token}"
    orders = payload.get("Orders") if isinstance(payload, dict) else []
    dates = [
        o.get("PurchaseDate")
        for o in orders
        if isinstance(o, dict) and isinstance(o.get("PurchaseDate"), str) and o["PurchaseDate"]
    ]
    if dates:
        return f"created:{max(dates)}"
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


def _items_url(base: str, order_id: str) -> str:
    """The per-order OrderItems endpoint URL (order_id is URL-path-encoded)."""
    safe = urllib.parse.quote(order_id, safe="")
    return f"{base}/orders/v0/orders/{safe}/orderItems"


async def _fetch_order_items(
    client, base: str, order_id: str, access_token: str
) -> tuple[bool, list[dict[str, Any]]]:
    """Best-effort OrderItems fetch. Returns ``(fetched, items)`` — never raises."""
    try:
        response = await client.get(
            _items_url(base, order_id),
            headers={
                "Accept": "application/json",
                "x-amz-access-token": access_token,
            },
        )
    except Exception:  # noqa: BLE001 - enrichment failure is non-fatal
        return False, []
    if response.status_code != 200:
        return False, []
    body = _safe_json(response)
    payload = body.get("payload") if isinstance(body, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    # An absent/malformed ``OrderItems`` key degrades to an empty list — never
    # raises (the enrichment is best-effort and non-fatal by contract).
    items = payload.get("OrderItems") if isinstance(payload, dict) else None
    return True, [i for i in (items or []) if isinstance(i, dict)]


def _enrich_order_items(order: dict[str, Any]) -> dict[str, Any]:
    """Merge fetched items into a copy of the order dict (never mutates in place)."""
    out = dict(order)
    out["_amazon_items_fetched"] = True
    out["OrderItems"] = list(order.get("OrderItems") or [])
    return out


class AmazonPullAdapter:
    """PullAdapter: NextToken-paginated, cursor-addressable SP-API ingestion."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        """Full-history backfill: no ``CreatedAfter`` filter."""
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
                data={"detail": "amazon SP-API base failed SSRF allowlist validation"},
            )

        params = _build_query(cursor)
        url = f"{base}/orders/v0/orders?" + urllib.parse.urlencode(params)
        try:
            async with _http_client() as client:
                response = await client.get(
                    url,
                    headers={
                        "Accept": "application/json",
                        "x-amz-access-token": access_token,
                    },
                )
                if response.status_code == 200:
                    body = _safe_json(response)
                    payload = body.get("payload") if isinstance(body, dict) else {}
                    payload = payload if isinstance(payload, dict) else {}
                    orders = payload.get("Orders") if isinstance(payload, dict) else []
                    records: list = []
                    for order in orders:
                        if not isinstance(order, dict) or not order.get("AmazonOrderId"):
                            continue
                        order_id = order["AmazonOrderId"]
                        fetched, items = await _fetch_order_items(
                            client, base, order_id, access_token
                        )
                        enriched = dict(order)
                        if fetched:
                            enriched = _enrich_order_items(order)
                            enriched["OrderItems"] = items
                        else:
                            enriched["_amazon_items_fetched"] = False
                        records.append(
                            make_raw_record(
                                provider_identity=self.provider_identity,
                                provider_record_id=order_id,
                                provider_record_type="order",
                                provider_occurred_at=order.get("LastUpdateDate"),
                                payload=enriched,
                                acquisition_mode="poll",
                                account_id=context.account_id,
                                connection_id=context.connection_id,
                                tenant_id=context.tenant_id,
                                cursor=cursor,
                            )
                        )
                    after, _ = _parse_cursor(cursor)
                    next_cursor = _next_cursor(body, window=after)
                    batch = ReadBatch(
                        records=records,
                        next_cursor=next_cursor,
                        has_more=next_cursor is not None,
                    )
                    return AdapterResult.ok(batch)
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
                data={"detail": "amazon SP-API rate-limited (HTTP 429)"},
            )
        if response.status_code in (401, 403):
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                data={"detail": f"amazon SP-API rejected the access token (HTTP {response.status_code})"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                data={"detail": f"amazon SP-API returned HTTP {response.status_code}"},
            )
        if response.status_code != 200:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=False,
                data={"detail": f"amazon SP-API returned HTTP {response.status_code}"},
            )
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code="unexpected",
            retryable=False,
            data={"detail": "amazon SP-API returned an unexpected empty page"},
        )


__all__ = [
    "CURSOR_SCHEME",
    "AmazonPullAdapter",
    "_build_query",
    "_enrich_order_items",
    "_fetch_order_items",
    "_items_url",
    "_next_cursor",
    "_parse_cursor",
]
