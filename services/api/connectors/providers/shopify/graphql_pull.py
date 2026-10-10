"""Version-pinned Shopify GraphQL Admin order pull.

This transport is opt-in through ``orders_api=graphql``. Its cursor is scoped to
one tenant, connection, and shop and cannot be confused with REST ``page_info``
or ``since_id`` cursors. A completed window returns a durable updated-at
checkpoint even when Shopify returned no orders. The next window re-reads its
boundary to avoid losing updates with the same timestamp.

The selected GraphQL fields are the provider payload. They are kept intact in
the raw record; the normalizer projects them separately. No partial GraphQL
response, incomplete nested line-item connection, or GraphQL error is accepted.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import ReadBatch, compute_checksum, make_raw_record
from shared.integration_contracts.results import AdapterResult, AdapterStatus, RateLimitInfo

from connectors.providers.shopify.auth import (
    _credential_dict,
    _raw_shop_domain,
    _shop_domain,
    _source_account_realm,
)

# A stable, explicitly reviewed schema. Do not use ``latest`` or a tenant value
# for this URL: field and money semantics must not drift during a sync.
GRAPHQL_API_VERSION = "2026-07"
PAYLOAD_SCHEMA_VERSION = f"shopify-admin-graphql/{GRAPHQL_API_VERSION}"
GRAPHQL_CURSOR_PREFIX = "shopify-gql-v1:"
_MAX_ORDERS_PER_PAGE = 10
_LINE_ITEMS_FIRST = 25
_LINE_ITEMS_NEXT = 100
_MAX_LINE_ITEM_PAGES = 50
_MAX_CURSOR_LENGTH = 8192
_REQUEST_TIMEOUT_SECONDS = 10.0
_HISTORICAL_ORDER_ACCESS_DAYS = 60
_ORDER_GID_RE = re.compile(r"^gid://shopify/Order/([1-9][0-9]*)$")
_SHOP_GID_RE = re.compile(r"^gid://shopify/Shop/[1-9][0-9]*$")

_MONEY_FIELDS = """
  currentSubtotalPriceSet { shopMoney { amount currencyCode } }
  currentShippingPriceSet { shopMoney { amount currencyCode } }
  currentTotalTaxSet { shopMoney { amount currencyCode } }
  currentTotalDiscountsSet { shopMoney { amount currencyCode } }
  currentTotalPriceSet { shopMoney { amount currencyCode } }
"""
_LINE_ITEM_FIELDS = """
  id quantity sku title
  originalUnitPriceSet { shopMoney { amount currencyCode } }
  totalDiscountSet { shopMoney { amount currencyCode } }
  product { id }
  variant { id }
"""
ORDERS_QUERY = f"""
query AetherOrders($first: Int!, $after: String, $search: String!) {{
  shop {{ id }}
  currentAppInstallation {{ accessScopes {{ handle }} }}
  orders(first: $first, after: $after, sortKey: UPDATED_AT, query: $search) {{
    nodes {{
      id legacyResourceId name email createdAt updatedAt cancelledAt closedAt
      currencyCode displayFinancialStatus displayFulfillmentStatus note
      customAttributes {{ key value }}
      {_MONEY_FIELDS}
      refunds {{ id processedAt totalRefundedSet {{ shopMoney {{ amount currencyCode }} }} }}
      fulfillments {{ id status updatedAt }}
      transactions {{ id kind status amountSet {{ shopMoney {{ amount currencyCode }} }} }}
      customer {{ id legacyResourceId email phone firstName lastName }}
      lineItems(first: {_LINE_ITEMS_FIRST}) {{
        nodes {{ {_LINE_ITEM_FIELDS} }}
        pageInfo {{ hasNextPage endCursor }}
      }}
    }}
    pageInfo {{ hasNextPage endCursor }}
  }}
}}
"""
LINE_ITEMS_QUERY = f"""
query AetherOrderLines($id: ID!, $after: String) {{
  order(id: $id) {{
    id updatedAt
    lineItems(first: {_LINE_ITEMS_NEXT}, after: $after) {{
      nodes {{ {_LINE_ITEM_FIELDS} }}
      pageInfo {{ hasNextPage endCursor }}
    }}
  }}
}}
"""


def _http_client():
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any) -> str:
    """Accept only explicit timezone-bearing timestamps; normalize to UTC."""
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _requires_historical_scope(lower: Optional[str], upper: str) -> bool:
    """Whether the requested update window can include orders beyond 60 days.

    Shopify grants ``read_orders`` access to recent orders. A lower bound that
    is absent or older than the rolling window needs the separately approved
    ``read_all_orders`` scope; recent polling can proceed without it.
    """
    if lower is None:
        return True
    lower_dt = datetime.fromisoformat(_timestamp(lower).replace("Z", "+00:00"))
    upper_dt = datetime.fromisoformat(_timestamp(upper).replace("Z", "+00:00"))
    return lower_dt < upper_dt - timedelta(days=_HISTORICAL_ORDER_ACCESS_DAYS)


@dataclass(frozen=True)
class _Cursor:
    tenant: str
    connection: str
    shop: str
    shop_gid: Optional[str]
    realm: str
    lower: Optional[str]
    upper: Optional[str]
    after: Optional[str]


def _encode_cursor(state: _Cursor) -> str:
    payload = {
        "v": 1,
        "tenant": state.tenant,
        "connection": state.connection,
        "shop": state.shop,
        "shop_gid": state.shop_gid,
        "realm": state.realm,
        "lower": state.lower,
        "upper": state.upper,
        "after": state.after,
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    return GRAPHQL_CURSOR_PREFIX + encoded


def _decode_cursor(value: str, context: AcquisitionContext, shop: str, realm: str) -> _Cursor:
    if not value.startswith(GRAPHQL_CURSOR_PREFIX) or len(value) > _MAX_CURSOR_LENGTH:
        raise ValueError("incompatible cursor")
    raw = value[len(GRAPHQL_CURSOR_PREFIX) :]
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise ValueError("malformed cursor") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "v",
        "tenant",
        "connection",
        "shop",
        "shop_gid",
        "realm",
        "lower",
        "upper",
        "after",
    }:
        raise ValueError("malformed cursor")
    if (
        payload["v"] != 1
        or payload["tenant"] != context.tenant_id
        or payload["connection"] != context.connection_id
        or payload["shop"] != shop
        or payload["realm"] != realm
    ):
        raise ValueError("cursor scope mismatch")
    lower = payload["lower"]
    upper = payload["upper"]
    after = payload["after"]
    shop_gid = payload["shop_gid"]
    if shop_gid is not None and (
        not isinstance(shop_gid, str) or not _SHOP_GID_RE.fullmatch(shop_gid)
    ):
        raise ValueError("invalid shop identity")
    if lower is not None:
        lower = _timestamp(lower)
    if upper is not None:
        upper = _timestamp(upper)
    if after is not None and (not isinstance(after, str) or not after or len(after) > 4096):
        raise ValueError("invalid page cursor")
    if after and not upper:
        raise ValueError("page cursor without window")
    if (
        lower
        and upper
        and datetime.fromisoformat(lower.replace("Z", "+00:00"))
        > datetime.fromisoformat(upper.replace("Z", "+00:00"))
    ):
        raise ValueError("inverted window")
    return _Cursor(
        context.tenant_id, context.connection_id, shop, shop_gid, realm, lower, upper, after
    )


def _rate_limit(body: dict[str, Any]) -> Optional[RateLimitInfo]:
    extensions = body.get("extensions")
    if not isinstance(extensions, dict):
        return None
    cost = extensions.get("cost") or {}
    if not isinstance(cost, dict):
        return None
    throttle = cost.get("throttleStatus") or {}
    if not isinstance(throttle, dict):
        return None
    try:
        return RateLimitInfo(
            limit=int(throttle["maximumAvailable"]),
            remaining=int(throttle["currentlyAvailable"]),
            reset_epoch_ms=None,
        )
    except (KeyError, TypeError, ValueError):
        return None


class _GraphQLFailure(Exception):
    def __init__(self, status: AdapterStatus, code: str, *, retry_after_ms: Optional[float] = None):
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after_ms = retry_after_ms


def _graphql_errors(errors: Any, body: dict[str, Any]) -> _GraphQLFailure:
    if not isinstance(errors, list):
        return _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "graphql_error")
    codes = {
        str((error.get("extensions") or {}).get("code", ""))
        for error in errors
        if isinstance(error, dict)
    }
    if "THROTTLED" in codes:
        extensions = body.get("extensions") or {}
        cost = extensions.get("cost") if isinstance(extensions, dict) else {}
        cost = cost if isinstance(cost, dict) else {}
        throttle = cost.get("throttleStatus") or {}
        throttle = throttle if isinstance(throttle, dict) else {}
        try:
            deficit = max(
                1,
                float(cost.get("requestedQueryCost", 1))
                - float(throttle.get("currentlyAvailable", 0)),
            )
            delay = 1000.0 * deficit / float(throttle["restoreRate"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            delay = 1000.0
        return _GraphQLFailure(
            AdapterStatus.RATE_LIMITED, "graphql_throttled", retry_after_ms=delay
        )
    if "ACCESS_DENIED" in codes or "UNAUTHORIZED" in codes:
        return _GraphQLFailure(AdapterStatus.UNAUTHORIZED, "graphql_access_denied")
    if "INTERNAL_SERVER_ERROR" in codes:
        return _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "graphql_internal_error")
    return _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "graphql_error")


async def _post(
    client: Any, url: str, token: str, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    try:
        response = await client.post(
            url,
            json={"query": query, "variables": variables},
            headers={
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    except Exception as exc:  # noqa: BLE001 - no network exception text (may include secrets)
        raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "connection_failed") from exc
    if response.status_code == 429:
        try:
            retry_ms = float(response.headers.get("Retry-After", "1")) * 1000.0
        except ValueError:
            retry_ms = 1000.0
        raise _GraphQLFailure(AdapterStatus.RATE_LIMITED, "rate_limited", retry_after_ms=retry_ms)
    if response.status_code in (401, 403):
        raise _GraphQLFailure(AdapterStatus.UNAUTHORIZED, "unauthorized")
    if 500 <= response.status_code < 600:
        raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, f"http_{response.status_code}")
    if response.status_code != 200:
        raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, f"http_{response.status_code}")
    try:
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - sparse success must fail closed
        raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "invalid_json") from exc
    if not isinstance(body, dict):
        raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "invalid_json")
    if body.get("errors"):
        raise _graphql_errors(body["errors"], body)
    if not isinstance(body.get("data"), dict):
        raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "graphql_data_missing")
    return body


def _money_amount(bag: Any, currency: str) -> str:
    if not isinstance(bag, dict) or not isinstance(bag.get("shopMoney"), dict):
        raise ValueError("money bag missing")
    money = bag["shopMoney"]
    amount = money.get("amount")
    if not isinstance(amount, str) or money.get("currencyCode") != currency:
        raise ValueError("money currency or amount invalid")
    try:
        parsed = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("money amount invalid") from exc
    if not parsed.is_finite():
        raise ValueError("money amount nonfinite")
    return amount


def _validate_order(node: Any) -> None:
    if not isinstance(node, dict):
        raise ValueError("order missing")
    match = _ORDER_GID_RE.fullmatch(str(node.get("id", "")))
    if not match or str(node.get("legacyResourceId")) != match.group(1):
        raise ValueError("order identity mismatch")
    _timestamp(node.get("createdAt"))
    _timestamp(node.get("updatedAt"))
    for optional_timestamp in ("cancelledAt", "closedAt"):
        if node.get(optional_timestamp) is not None:
            _timestamp(node[optional_timestamp])
    if not isinstance(node.get("name"), str) or not isinstance(
        node.get("displayFulfillmentStatus"), str
    ):
        raise ValueError("order status or name missing")
    if "displayFinancialStatus" not in node or "email" not in node or "note" not in node:
        raise ValueError("order fields missing")
    if not isinstance(node.get("customAttributes"), list) or any(
        not isinstance(attr, dict) or not isinstance(attr.get("key"), str) or "value" not in attr
        for attr in node["customAttributes"]
    ):
        raise ValueError("custom attributes incomplete")
    customer = node.get("customer")
    if customer is not None and (
        not isinstance(customer, dict)
        or not isinstance(customer.get("id"), str)
        or not str(customer.get("legacyResourceId", "")).isdigit()
    ):
        raise ValueError("customer identity invalid")
    currency = node.get("currencyCode")
    if not isinstance(currency, str) or not currency:
        raise ValueError("currency missing")
    for field in (
        "currentSubtotalPriceSet",
        "currentShippingPriceSet",
        "currentTotalTaxSet",
        "currentTotalDiscountsSet",
        "currentTotalPriceSet",
    ):
        _money_amount(node.get(field), currency)
    for field, resource, required in (
        ("refunds", "Refund", ("id", "processedAt", "totalRefundedSet")),
        ("fulfillments", "Fulfillment", ("id", "status", "updatedAt")),
        ("transactions", "OrderTransaction", ("id", "kind", "status", "amountSet")),
    ):
        values = node.get(field)
        if not isinstance(values, list):
            raise ValueError(f"{field} missing")
        seen_refs: set[str] = set()
        for value in values:
            if not isinstance(value, dict) or not all(key in value for key in required):
                raise ValueError(f"{field} incomplete")
            ref = value["id"]
            if (
                not isinstance(ref, str)
                or not re.fullmatch(rf"gid://shopify/{resource}/[1-9][0-9]*", ref)
                or ref in seen_refs
            ):
                raise ValueError(f"{field} identity invalid")
            seen_refs.add(ref)
            if field == "refunds":
                _timestamp(value["processedAt"])
            elif field == "fulfillments":
                _timestamp(value["updatedAt"])
                if not isinstance(value["status"], str):
                    raise ValueError("fulfillment status missing")
            elif not isinstance(value["kind"], str) or not isinstance(value["status"], str):
                raise ValueError("transaction status missing")
            if field in ("refunds", "transactions"):
                _money_amount(
                    value.get("totalRefundedSet" if field == "refunds" else "amountSet"), currency
                )
    lines = node.get("lineItems")
    if not isinstance(lines, dict) or not isinstance(lines.get("nodes"), list):
        raise ValueError("line items missing")
    page = lines.get("pageInfo")
    if not isinstance(page, dict) or not isinstance(page.get("hasNextPage"), bool):
        raise ValueError("line item page info missing")
    seen_line_ids: set[str] = set()
    for line in lines["nodes"]:
        if (
            not isinstance(line, dict)
            or not isinstance(line.get("id"), str)
            or not re.fullmatch(r"gid://shopify/LineItem/[1-9][0-9]*", line["id"])
        ):
            raise ValueError("line item identity invalid")
        if line["id"] in seen_line_ids:
            raise ValueError("duplicate line item")
        seen_line_ids.add(line["id"])
        if not isinstance(line.get("quantity"), int) or line["quantity"] < 0:
            raise ValueError("line item quantity invalid")
        if (
            not isinstance(line.get("title"), str)
            or "sku" not in line
            or "product" not in line
            or "variant" not in line
        ):
            raise ValueError("line item fields missing")
        for field, resource in (("product", "Product"), ("variant", "ProductVariant")):
            ref = line[field]
            if ref is not None and (
                not isinstance(ref, dict)
                or not isinstance(ref.get("id"), str)
                or not re.fullmatch(rf"gid://shopify/{resource}/[1-9][0-9]*", ref["id"])
            ):
                raise ValueError("line item reference invalid")
        _money_amount(line.get("originalUnitPriceSet"), currency)
        _money_amount(line.get("totalDiscountSet"), currency)


def _economic_revision_key(node: dict[str, Any]) -> str:
    """Hash versioned order economics and lifecycle, excluding contact edits."""
    currency = node["currencyCode"]

    def amount(bag: dict[str, Any]) -> str:
        return format(Decimal(_money_amount(bag, currency)).normalize(), "f")

    material = {
        "order_id": node["id"],
        "created_at": _timestamp(node["createdAt"]),
        "cancelled_at": _timestamp(node["cancelledAt"]) if node.get("cancelledAt") else None,
        "closed_at": _timestamp(node["closedAt"]) if node.get("closedAt") else None,
        "currency": currency,
        # Shopify display status is order state, not processor settlement.
        "shopify_display_financial_status": node["displayFinancialStatus"],
        "shopify_display_fulfillment_status": node["displayFulfillmentStatus"],
        "customer_id": node["customer"]["id"] if node.get("customer") else None,
        "totals": {
            field: amount(node[field])
            for field in (
                "currentSubtotalPriceSet",
                "currentShippingPriceSet",
                "currentTotalTaxSet",
                "currentTotalDiscountsSet",
                "currentTotalPriceSet",
            )
        },
        "line_items": sorted(
            (
                {
                    "id": line["id"],
                    "quantity": line["quantity"],
                    "unit_price": amount(line["originalUnitPriceSet"]),
                    "total_discount": amount(line["totalDiscountSet"]),
                    "product_id": (line.get("product") or {}).get("id"),
                    "variant_id": (line.get("variant") or {}).get("id"),
                }
                for line in node["lineItems"]["nodes"]
            ),
            key=lambda line: line["id"],
        ),
        "refunds": sorted(
            (
                {
                    "id": ref["id"],
                    "processed_at": _timestamp(ref["processedAt"]),
                    "amount": amount(ref["totalRefundedSet"]),
                }
                for ref in node["refunds"]
            ),
            key=lambda ref: ref["id"],
        ),
        "fulfillments": sorted(
            (
                {
                    "id": ref["id"],
                    "status": ref["status"],
                    "updated_at": _timestamp(ref["updatedAt"]),
                }
                for ref in node["fulfillments"]
            ),
            key=lambda ref: ref["id"],
        ),
        "transactions": sorted(
            (
                {
                    "id": ref["id"],
                    "kind": ref["kind"],
                    "status": ref["status"],
                    "amount": amount(ref["amountSet"]),
                }
                for ref in node["transactions"]
            ),
            key=lambda ref: ref["id"],
        ),
    }
    digest = compute_checksum({"contract": "shopify-order-economic-v1", "material": material})
    return f"snapshot:none:{digest}"


def _source_revision_key(node: dict[str, Any]) -> str:
    """Identify each acquired provider revision for protected raw Bronze.

    Full provider material, including contact changes, is hashed with the
    Shopify update watermark. Transport pagination is excluded from identity.
    The canonical event uses ``_economic_revision_key`` separately.
    """
    material = dict(node)
    lines = node.get("lineItems")
    if isinstance(lines, dict):
        material["lineItems"] = {key: value for key, value in lines.items() if key != "pageInfo"}
    digest = compute_checksum({"contract": PAYLOAD_SCHEMA_VERSION, "material": material})
    return f"snapshot:{_timestamp(node['updatedAt'])}:{digest}"


class ShopifyGraphQLPullAdapter:
    """GraphQL orders adapter; the legacy REST transport remains the default."""

    def __init__(self, *, provider_identity: str) -> None:
        self.provider_identity = provider_identity

    async def initial_backfill(self, context: AcquisitionContext) -> AdapterResult[ReadBatch]:
        return await self.fetch(context, cursor=None)

    async def fetch(
        self, context: AcquisitionContext, *, cursor: Optional[str], limit: Optional[int] = None
    ) -> AdapterResult[ReadBatch]:
        if context.stream_id not in (None, "orders"):
            return self._failure(AdapterStatus.PERMANENT_ERROR, "shopify_stream_mode_mismatch")
        raw_domain = _raw_shop_domain(context)
        shop = _shop_domain(context)
        if not raw_domain or not shop:
            code = "shop_domain_missing" if not raw_domain else "shop_domain_invalid"
            return self._failure(AdapterStatus.PERMANENT_ERROR, code)
        token = str(_credential_dict(context).get("shop_access_token") or "").strip()
        if not token:
            return self._failure(AdapterStatus.PERMANENT_ERROR, "shop_access_token_missing")
        if context.account_id != f"shop:{shop}":
            return self._failure(AdapterStatus.PERMANENT_ERROR, "account_mismatch")
        realm = _source_account_realm(context)
        if realm is None:
            return self._failure(AdapterStatus.PERMANENT_ERROR, "source_account_realm_invalid")
        expected_shop_gid = context.config.get("_verified_shop_gid")
        if not isinstance(expected_shop_gid, str) or not _SHOP_GID_RE.fullmatch(expected_shop_gid):
            return self._failure(AdapterStatus.PERMANENT_ERROR, "selected_shop_unverified")
        try:
            state = (
                _decode_cursor(cursor, context, shop, realm)
                if cursor
                else _Cursor(
                    context.tenant_id,
                    context.connection_id,
                    shop,
                    None,
                    realm,
                    _timestamp(context.config["updated_since"])
                    if context.config.get("updated_since")
                    else None,
                    None,
                    None,
                )
            )
            if state.upper is None:
                state = _Cursor(
                    state.tenant,
                    state.connection,
                    state.shop,
                    state.shop_gid,
                    state.realm,
                    state.lower,
                    _utc_now(),
                    None,
                )
            if state.lower and datetime.fromisoformat(
                state.lower.replace("Z", "+00:00")
            ) > datetime.fromisoformat(state.upper.replace("Z", "+00:00")):
                raise ValueError("future lower bound")
            page_size = (
                _MAX_ORDERS_PER_PAGE
                if limit is None
                else max(1, min(int(limit), _MAX_ORDERS_PER_PAGE))
            )
        except (ValueError, TypeError, KeyError):
            return self._failure(AdapterStatus.PERMANENT_ERROR, "graphql_cursor_invalid")

        terms = [f"updated_at:<='{state.upper}'"]
        if state.lower:
            terms.insert(0, f"updated_at:>='{state.lower}'")
        url = f"https://{shop}/admin/api/{GRAPHQL_API_VERSION}/graphql.json"
        try:
            async with _http_client() as client:
                body = await _post(
                    client,
                    url,
                    token,
                    ORDERS_QUERY,
                    {
                        "first": page_size,
                        "after": state.after,
                        "search": " ".join(terms),
                    },
                )
                data = body["data"]
                shop_data = data.get("shop")
                shop_gid = shop_data.get("id") if isinstance(shop_data, dict) else None
                if not isinstance(shop_gid, str) or not _SHOP_GID_RE.fullmatch(shop_gid):
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "shop_identity_missing")
                if state.shop_gid is not None and state.shop_gid != shop_gid:
                    raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "shop_identity_changed")
                if shop_gid != expected_shop_gid:
                    raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "selected_shop_mismatch")
                installation = data.get("currentAppInstallation")
                scopes = (
                    installation.get("accessScopes") if isinstance(installation, dict) else None
                )
                if not isinstance(scopes, list) or any(
                    not isinstance(scope, dict) or not isinstance(scope.get("handle"), str)
                    for scope in scopes
                ):
                    raise _GraphQLFailure(
                        AdapterStatus.RETRYABLE_ERROR, "order_scope_evidence_missing"
                    )
                scope_handles = {scope["handle"] for scope in scopes}
                if "read_orders" not in scope_handles:
                    raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "read_orders_required")
                # Keep recent sync available to apps with read_orders. A full
                # backfill or incremental cursor older than the rolling scope
                # must not advance a checkpoint without read_all_orders.
                if "read_all_orders" not in scope_handles and _requires_historical_scope(
                    state.lower, state.upper
                ):
                    raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "read_all_orders_required")
                orders = data.get("orders")
                if not isinstance(orders, dict) or not isinstance(orders.get("nodes"), list):
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "orders_missing")
                page = orders.get("pageInfo")
                if not isinstance(page, dict) or not isinstance(page.get("hasNextPage"), bool):
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "page_info_missing")
                nodes = orders["nodes"]
                if len(nodes) > page_size:
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "order_page_oversized")
                if page["hasNextPage"] and (
                    not nodes
                    or not isinstance(page.get("endCursor"), str)
                    or not page["endCursor"]
                    or page["endCursor"] == state.after
                ):
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "page_cursor_missing")
                for node in nodes:
                    try:
                        _validate_order(node)
                        updated_at = datetime.fromisoformat(
                            node["updatedAt"].replace("Z", "+00:00")
                        )
                        if updated_at > datetime.fromisoformat(state.upper.replace("Z", "+00:00")):
                            raise ValueError("order after window")
                        if state.lower and updated_at < datetime.fromisoformat(
                            state.lower.replace("Z", "+00:00")
                        ):
                            raise ValueError("order before window")
                    except ValueError as exc:
                        raise _GraphQLFailure(
                            AdapterStatus.RETRYABLE_ERROR, "order_payload_incomplete"
                        ) from exc
                    await self._complete_lines(client, url, token, node)
                    try:
                        _validate_order(node)
                    except ValueError as exc:
                        raise _GraphQLFailure(
                            AdapterStatus.RETRYABLE_ERROR, "order_payload_incomplete"
                        ) from exc
        except _GraphQLFailure as exc:
            return self._failure(exc.status, exc.code, retry_after_ms=exc.retry_after_ms)

        records = [
            make_raw_record(
                provider_identity=self.provider_identity,
                provider_record_id=str(node["legacyResourceId"]),
                provider_record_type="order",
                source_account_key=shop_gid,
                source_account_realm=realm,
                source_object_type="order",
                source_object_id=node["id"],
                source_revision_key=_source_revision_key(node),
                stream_id="orders",
                provider_occurred_at=node["updatedAt"],
                payload=node,
                payload_schema_version=PAYLOAD_SCHEMA_VERSION,
                schema_version="2",
                acquisition_mode="poll",
                account_id=context.account_id,
                connection_id=context.connection_id,
                tenant_id=context.tenant_id,
                cursor=cursor,
                metadata={
                    "shopify_shop_gid": shop_gid,
                    "source_account_realm": realm,
                    "shopify_order_gid": node["id"],
                    "shopify_updated_at": node["updatedAt"],
                    "admin_api_version": GRAPHQL_API_VERSION,
                },
            )
            for node in nodes
        ]
        next_state = (
            _Cursor(
                state.tenant,
                state.connection,
                shop,
                shop_gid,
                realm,
                state.lower,
                state.upper,
                page["endCursor"],
            )
            if page["hasNextPage"]
            else _Cursor(
                state.tenant, state.connection, shop, shop_gid, realm, state.upper, None, None
            )
        )
        return AdapterResult.ok(
            ReadBatch(
                records=records,
                next_cursor=_encode_cursor(next_state),
                has_more=page["hasNextPage"],
            ),
            rate_limit=_rate_limit(body),
        )

    async def _complete_lines(
        self, client: Any, url: str, token: str, node: dict[str, Any]
    ) -> None:
        lines = node["lineItems"]
        seen = set()
        count = 0
        while lines["pageInfo"]["hasNextPage"]:
            count += 1
            if count > _MAX_LINE_ITEM_PAGES:
                raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "line_item_page_cap")
            after = lines["pageInfo"].get("endCursor")
            if not isinstance(after, str) or not after or after in seen:
                raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "line_item_cursor_invalid")
            seen.add(after)
            body = await _post(
                client, url, token, LINE_ITEMS_QUERY, {"id": node["id"], "after": after}
            )
            extra_order = body["data"].get("order")
            if (
                not isinstance(extra_order, dict)
                or extra_order.get("id") != node["id"]
                or extra_order.get("updatedAt") != node["updatedAt"]
            ):
                raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "order_changed_during_fetch")
            extra = extra_order.get("lineItems")
            if (
                not isinstance(extra, dict)
                or not isinstance(extra.get("nodes"), list)
                or not isinstance(extra.get("pageInfo"), dict)
                or not isinstance(extra["pageInfo"].get("hasNextPage"), bool)
            ):
                raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "line_item_page_missing")
            if not extra["nodes"]:
                raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "line_item_page_empty")
            lines["nodes"].extend(extra["nodes"])
            lines["pageInfo"] = extra["pageInfo"]

    @staticmethod
    def _failure(
        status: AdapterStatus, code: str, *, retry_after_ms: Optional[float] = None
    ) -> AdapterResult[ReadBatch]:
        return AdapterResult(
            success=False,
            status=status,
            error_code=code,
            retryable=status in (AdapterStatus.RETRYABLE_ERROR, AdapterStatus.RATE_LIMITED),
            rate_limit=RateLimitInfo(retry_after_ms=retry_after_ms)
            if retry_after_ms is not None
            else None,
            data={"detail": code.replace("_", " ")},
        )


__all__ = [
    "GRAPHQL_API_VERSION",
    "PAYLOAD_SCHEMA_VERSION",
    "GRAPHQL_CURSOR_PREFIX",
    "ORDERS_QUERY",
    "LINE_ITEMS_QUERY",
    "ShopifyGraphQLPullAdapter",
]
