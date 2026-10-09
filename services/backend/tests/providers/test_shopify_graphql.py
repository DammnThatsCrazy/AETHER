"""Synthetic Shopify GraphQL Admin order pull tests (no live credentials)."""

from __future__ import annotations

import copy
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from shared.commerce_contracts.money import Money
from shared.credentials.types import ApiKeyCredential, MultiCredential
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import compute_checksum
from shared.integration_contracts.results import AdapterStatus
from shared.integration_contracts.source_objects import (
    event_revision_id_for_parts,
    logical_event_id_for_source_parts,
)
from services.providers.shopify.account import ShopifyAccountAdapter
from services.providers.shopify.auth import ShopifyAuthAdapter
from services.providers.shopify.graphql_pull import (
    GRAPHQL_API_VERSION,
    GRAPHQL_CURSOR_PREFIX,
    PAYLOAD_SCHEMA_VERSION,
    ShopifyGraphQLPullAdapter,
)
from services.providers.shopify.normalizer import (
    ShopifyOrderNormalizer,
    _graphql_order_to_rest_shape,
    to_commerce_order,
)
from services.providers.shopify.payloads import ShopifyOrder
from services.providers.shopify.pull import ShopifyPullAdapter

SHOP = "synthetic-store.myshopify.com"
SHOP_GID = "gid://shopify/Shop/123456"
ORDER_GID = "gid://shopify/Order/9000100001"


def _context(*, config: dict | None = None, shop: str = SHOP) -> AcquisitionContext:
    return AcquisitionContext.model_construct(
        tenant_id="tenant-1",
        provider_identity="shopify.admin.orders_read",
        connection_id="connection-1",
        account_id=f"shop:{shop}",
        config={
            "orders_api": "graphql",
            "source_account_realm": "test",
            "_verified_shop_gid": SHOP_GID,
            **(config or {}),
        },
        credential={"shop_domain": shop, "shop_access_token": "synthetic-secret"},
    )


def _bag(amount: str, currency: str = "USD") -> dict:
    return {"shopMoney": {"amount": amount, "currencyCode": currency}}


def _line(number: int = 1) -> dict:
    return {
        "id": f"gid://shopify/LineItem/{number}",
        "quantity": 2,
        "sku": "SYNTH-WIDGET",
        "title": "Synthetic Widget",
        "originalUnitPriceSet": _bag("0.05"),
        "totalDiscountSet": _bag("0.00"),
        "product": {"id": "gid://shopify/Product/8001"},
        "variant": {"id": "gid://shopify/ProductVariant/7001"},
    }


def _order() -> dict:
    return {
        "id": ORDER_GID,
        "legacyResourceId": "9000100001",
        "name": "#SYNTH-1",
        "email": "buyer@synth.example",
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-02T00:00:00Z",
        "cancelledAt": None,
        "closedAt": None,
        "currencyCode": "USD",
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "note": "Leave the synthetic package by the side door",
        "customAttributes": [{"key": "buyer_phone", "value": "+1-555-0102"}],
        "currentSubtotalPriceSet": _bag("0.10"),
        "currentShippingPriceSet": _bag("0.02"),
        "currentTotalTaxSet": _bag("0.01"),
        "currentTotalDiscountsSet": _bag("0.00"),
        "currentTotalPriceSet": _bag("0.13"),
        "refunds": [],
        "fulfillments": [],
        "transactions": [],
        "customer": {
            "id": "gid://shopify/Customer/6001",
            "legacyResourceId": "6001",
            "email": "buyer@synth.example",
            "phone": "+1-555-0102",
            "firstName": "SYNTHETIC_FIRST_NAME",
            "lastName": "SYNTHETIC_LAST_NAME",
        },
        "lineItems": {
            "nodes": [_line()],
            "pageInfo": {"hasNextPage": False, "endCursor": "line-end-1"},
        },
    }


def _orders_response(nodes: list[dict], *, has_next: bool = False, end: str | None = None) -> dict:
    return {
        "data": {
            "shop": {"id": SHOP_GID},
            "currentAppInstallation": {
                "accessScopes": [{"handle": "read_orders"}, {"handle": "read_all_orders"}],
            },
            "orders": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": has_next, "endCursor": end},
            },
        },
        "extensions": {
            "cost": {"throttleStatus": {"maximumAvailable": 1000, "currentlyAvailable": 925}}
        },
    }


def _transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    import services.providers.shopify.graphql_pull as graph

    monkeypatch.setattr(
        graph, "_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(graph, "_utc_now", lambda: "2026-08-03T00:00:00Z")


@pytest.mark.asyncio
async def test_graphql_orders_two_pages_checkpoint_and_exact_money(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == f"https://{SHOP}/admin/api/{GRAPHQL_API_VERSION}/graphql.json"
        assert request.headers.get("X-Shopify-Access-Token") == "synthetic-secret"
        assert request.headers.get("Authorization") is None
        payload = __import__("json").loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return httpx.Response(
                200, json=_orders_response([_order()], has_next=True, end="order-cursor-1")
            )
        if len(requests) == 2:
            assert payload["variables"]["after"] == "order-cursor-1"
        return httpx.Response(200, json=_orders_response([]))

    _transport(monkeypatch, handler)
    adapter = ShopifyPullAdapter(provider_identity="shopify.admin.orders_read")
    first = await adapter.fetch(_context(), cursor=None)
    assert first.success is True
    assert first.data.has_more is True
    assert first.data.next_cursor.startswith(GRAPHQL_CURSOR_PREFIX)
    assert first.rate_limit.remaining == 925
    raw = first.data.records[0]
    assert raw.provider_record_id == "9000100001"  # REST continuity
    assert raw.provider_occurred_at == "2026-08-02T00:00:00Z"
    assert raw.payload_schema_version == PAYLOAD_SCHEMA_VERSION
    assert raw.schema_version == "2"
    assert raw.source_account_key == SHOP_GID
    assert raw.source_account_realm == "test"
    assert raw.source_object_type == "order"
    assert raw.stream_id == "orders"
    assert raw.source_object_id == ORDER_GID
    assert raw.source_revision_key.startswith("snapshot:2026-08-02T00:00:00Z:")
    assert raw.payload == _order()  # native GraphQL payload, no money float conversion
    assert raw.metadata["shopify_shop_gid"] == SHOP_GID
    assert raw.metadata["source_account_realm"] == "test"
    assert raw.tenant_id == "tenant-1"
    assert raw.connection_id == "connection-1"
    assert raw.account_id == f"shop:{SHOP}"

    event_result = ShopifyOrderNormalizer().normalize(raw)
    assert not event_result.dropped
    event = event_result.events[0]
    assert event.event_type == "commerce.order.updated"
    assert event.data["order_id"] == "9000100001"
    assert event.data["total"]["amount"] == "0.13"
    projected = _graphql_order_to_rest_shape(raw.payload)
    commerce = to_commerce_order(ShopifyOrder.from_api_dict(projected))
    assert commerce.line_items[0].unit_price.amount == Decimal("0.05")
    assert commerce.line_items[0].line_total.amount == Decimal("0.10")
    assert commerce.line_items[0].product_id == "8001"
    assert projected["customer"] == {"id": "6001"}
    assert "email" not in projected and "note" not in projected
    assert commerce.customer.email is None and commerce.customer.phone is None
    assert commerce.customer.first_name is None and commerce.customer.last_name is None
    assert commerce.note is None and commerce.properties == {}
    assert "raw_provider_payload" not in event.context
    for marker in (
        "buyer@synth.example",
        "+1-555-0102",
        "SYNTHETIC_FIRST_NAME",
        "SYNTHETIC_LAST_NAME",
        "Leave the synthetic package by the side door",
    ):
        assert marker in str(raw.payload)  # protected raw payload remains intact
        assert marker not in str(projected)
        assert marker not in str(commerce.model_dump())
        assert marker not in str(event.model_dump())
    assert event.context["raw_provider_checksum"] == raw.checksum
    assert event.context["source_revision_key"] == raw.source_revision_key
    assert event.context["source_account_realm"] == "test"
    assert event.context["stream_id"] == "orders"
    assert event.context["economic_revision_key"].startswith("snapshot:none:")
    logical_event_id = logical_event_id_for_source_parts(
        tenant_id=raw.tenant_id,
        provider_family="shopify",
        source_account_realm=raw.source_account_realm,
        source_account_key=raw.source_account_key,
        source_object_type=raw.source_object_type,
        source_object_id=raw.source_object_id,
        source_revision_key=event.context["economic_revision_key"],
        semantic_slot="order.snapshot",
    )
    assert event.schema_version == "2"
    assert event.logical_event_id == logical_event_id
    assert event.event_revision_id == event.event_id
    assert event.mapping_version == "shopify.order.snapshot.v1"
    assert event.normalizer_version == ShopifyOrderNormalizer.normalizer_version
    assert event.source_revision_key == raw.source_revision_key
    assert event.canonical_payload_digest == compute_checksum(
        {"event_type": event.event_type, "event_family": event.event_family, "data": event.data}
    )
    assert event.event_id == event_revision_id_for_parts(
        logical_event_id=event.logical_event_id,
        event_schema_version="2",
        mapping_version=event.mapping_version,
        normalizer_version=event.normalizer_version,
        canonical_payload_digest=event.canonical_payload_digest,
    )
    assert event.data["provider"]["shopify_display_financial_status"] == "paid"

    second = await adapter.fetch(_context(), cursor=first.data.next_cursor)
    assert second.success is True
    assert second.data.has_more is False
    assert second.data.records == []
    assert second.data.next_cursor.startswith(GRAPHQL_CURSOR_PREFIX)
    assert requests[0]["variables"]["search"] == "updated_at:<='2026-08-03T00:00:00Z'"
    assert requests[1]["variables"]["search"] == requests[0]["variables"]["search"]

    # The terminal checkpoint starts a new window at the previous upper bound.
    third = await adapter.fetch(_context(), cursor=second.data.next_cursor)
    assert third.success is True
    assert requests[2]["variables"]["after"] is None
    assert requests[2]["variables"]["search"] == (
        "updated_at:>='2026-08-03T00:00:00Z' updated_at:<='2026-08-03T00:00:00Z'"
    )


@pytest.mark.asyncio
async def test_graphql_fetches_all_nested_line_items_before_emitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    order["lineItems"]["pageInfo"] = {"hasNextPage": True, "endCursor": "line-page-1"}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        if "AetherOrders" in payload["query"]:
            return httpx.Response(200, json=_orders_response([copy.deepcopy(order)]))
        seen.append(payload["variables"]["after"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "order": {
                        "id": ORDER_GID,
                        "updatedAt": order["updatedAt"],
                        "lineItems": {
                            "nodes": [_line(2)],
                            "pageInfo": {"hasNextPage": False, "endCursor": "line-page-2"},
                        },
                    }
                }
            },
        )

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert result.success is True
    assert seen == ["line-page-1"]
    assert len(result.data.records[0].payload["lineItems"]["nodes"]) == 2
    mapped = ShopifyOrder.from_api_dict(
        _graphql_order_to_rest_shape(result.data.records[0].payload)
    )
    assert len(to_commerce_order(mapped).line_items) == 2


@pytest.mark.asyncio
async def test_graphql_rejects_rest_cursor_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("network must not be reached")

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor="page_info:rest-token"
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "graphql_cursor_invalid"


@pytest.mark.asyncio
async def test_graphql_checkpoint_rejects_changed_immutable_shop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = _orders_response([])
        if calls == 2:
            body["data"]["shop"]["id"] = "gid://shopify/Shop/654321"
        return httpx.Response(200, json=body)

    _transport(monkeypatch, handler)
    adapter = ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read")
    first = await adapter.fetch(_context(), cursor=None)
    assert first.success is True
    second = await adapter.fetch(_context(), cursor=first.data.next_cursor)
    assert second.success is False
    assert second.status == AdapterStatus.PERMANENT_ERROR
    assert second.error_code == "shop_identity_changed"


@pytest.mark.asyncio
async def test_graphql_v2_revision_tracks_canonical_updates_and_economic_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _order()
    base["updatedAt"] = base["createdAt"]
    contact = copy.deepcopy(base)
    contact["updatedAt"] = "2026-08-02T00:00:01Z"
    contact["email"] = "new-address@synth.example"
    contact["note"] = "a free-text customer note"
    contact["name"] = "#renamed-order"
    contact["customer"]["email"] = "new-address@synth.example"
    contact["lineItems"]["nodes"][0]["title"] = "Renamed title"
    contact["customAttributes"] = [{"key": "contact", "value": "changed"}]
    amount = copy.deepcopy(contact)
    amount["updatedAt"] = "2026-08-02T00:00:02Z"
    amount["currentTotalPriceSet"] = _bag("0.14")
    lifecycle = copy.deepcopy(contact)
    lifecycle["updatedAt"] = "2026-08-02T00:00:03Z"
    lifecycle["displayFinancialStatus"] = "REFUNDED"
    versions = [base, contact, amount, lifecycle]
    index = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal index
        version = versions[index]
        index += 1
        return httpx.Response(200, json=_orders_response([version]))

    _transport(monkeypatch, handler)
    adapter = ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read")
    records = []
    for _ in versions:
        result = await adapter.fetch(_context(), cursor=None)
        assert result.success is True
        records.append(result.data.records[0])

    assert records[0].source_revision_key != records[1].source_revision_key
    assert records[0].bronze_provider_record_id != records[1].bronze_provider_record_id
    assert records[0].idempotency_key != records[1].idempotency_key
    assert records[0].checksum != records[1].checksum  # each contact edit has protected raw lineage
    assert records[2].bronze_provider_record_id != records[1].bronze_provider_record_id
    assert records[3].bronze_provider_record_id != records[1].bronze_provider_record_id
    assert records[2].source_revision_key != records[3].source_revision_key
    normalizer = ShopifyOrderNormalizer()
    events = [normalizer.normalize(record).events[0] for record in records]
    assert events[0].logical_event_id == events[1].logical_event_id
    # A contact-only provider change can still change canonical lifecycle
    # output (created -> updated and updated_at), so it receives a new durable
    # event revision under the v2 payload-digest contract.
    assert events[0].event_id != events[1].event_id
    assert events[0].canonical_payload_digest != events[1].canonical_payload_digest
    assert events[0].context["economic_revision_key"] == events[1].context["economic_revision_key"]
    assert (
        events[0].context["bronze_provider_record_id"]
        != events[1].context["bronze_provider_record_id"]
    )
    assert events[0].event_id != events[2].event_id
    assert events[0].event_id != events[3].event_id
    retry = records[0].model_copy(update={"record_id": "retry-of-first-read"})
    assert retry.bronze_provider_record_id == records[0].bronze_provider_record_id
    assert normalizer.normalize(retry).events[0].event_id == events[0].event_id
    assert normalizer.normalize(records[0]).events[0].event_type == "commerce.order.updated"
    assert "new-address@synth.example" not in str(
        normalizer.normalize(records[1]).events[0].model_dump()
    )
    assert normalizer.normalize(records[3]).events[0].event_type == "commerce.order.updated"
    assert (
        normalizer.normalize(records[3])
        .events[0]
        .data["provider"]["shopify_display_financial_status"]
        == "refunded"
    )


@pytest.mark.asyncio
async def test_graphql_event_revision_id_tracks_interpretation_versions_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.normalizer as normalizer_mod

    def handler(_request: httpx.Request) -> httpx.Response:
        order = _order()
        order["createdAt"] = order["updatedAt"]
        return httpx.Response(200, json=_orders_response([order]))

    _transport(monkeypatch, handler)
    pulled = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert pulled.success is True
    record = pulled.data.records[0]
    normalizer = ShopifyOrderNormalizer()
    original = normalizer.normalize(record).events[0]
    replay = normalizer.normalize(record.model_copy(update={"record_id": "retry-record"})).events[0]
    assert replay.logical_event_id == original.logical_event_id
    assert replay.event_id == original.event_id

    with monkeypatch.context() as patch:
        patch.setattr(normalizer_mod, "GRAPHQL_MAPPING_VERSION", "shopify.order.snapshot.v2")
        remapped = normalizer.normalize(record).events[0]
    assert remapped.logical_event_id == original.logical_event_id
    assert remapped.event_id != original.event_id

    normalizer_v2 = ShopifyOrderNormalizer()
    normalizer_v2.normalizer_version = "2"
    renormalized = normalizer_v2.normalize(record).events[0]
    assert renormalized.logical_event_id == original.logical_event_id
    assert renormalized.event_id != original.event_id

    with monkeypatch.context() as patch:
        original_snapshot = normalizer_mod.order_to_snapshot

        def changed_snapshot(commerce):
            snapshot = original_snapshot(commerce)
            return snapshot.model_copy(
                update={"total": Money(amount=Decimal("0.14"), currency="USD")}
            )

        patch.setattr(normalizer_mod, "order_to_snapshot", changed_snapshot)
        payload_changed = normalizer.normalize(record).events[0]
    assert payload_changed.logical_event_id == original.logical_event_id
    assert payload_changed.canonical_payload_digest != original.canonical_payload_digest
    assert payload_changed.event_id != original.event_id

    # Each revision identifier binds all interpretation inputs independently.
    for field, changed_value in (
        ("mapping_version", "shopify.order.snapshot.v2"),
        ("normalizer_version", "2"),
        ("canonical_payload_digest", "0" * 64),
    ):
        inputs = {
            "logical_event_id": original.logical_event_id,
            "event_schema_version": "2",
            "mapping_version": original.mapping_version,
            "normalizer_version": original.normalizer_version,
            "canonical_payload_digest": original.canonical_payload_digest,
        }
        inputs[field] = changed_value
        assert event_revision_id_for_parts(**inputs) != original.event_id


@pytest.mark.asyncio
@pytest.mark.parametrize("realm", [None, "", "unknown"])
async def test_graphql_requires_explicit_source_account_realm(
    monkeypatch: pytest.MonkeyPatch, realm: str | None
) -> None:
    import services.providers.shopify.account as account_mod
    import services.providers.shopify.auth as auth_mod

    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid realm must fail before network")

    def no_network(*_args, **_kwargs):
        pytest.fail("invalid realm must fail before network")

    _transport(monkeypatch, handler)
    monkeypatch.setattr(account_mod, "_http_client", no_network)
    monkeypatch.setattr(auth_mod, "_http_client", no_network)
    config = {"source_account_realm": realm}
    context = _context(config=config)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        context, cursor=None
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "source_account_realm_invalid"
    account_result = await ShopifyAccountAdapter().discover_accounts(context)
    assert account_result.status == AdapterStatus.PERMANENT_ERROR
    assert account_result.error_code == "source_account_realm_invalid"
    auth_result = await ShopifyAuthAdapter().validate_credentials(context)
    assert auth_result.status == AdapterStatus.PERMANENT_ERROR
    assert auth_result.error_code == "source_account_realm_invalid"
    connection_result = await ShopifyAuthAdapter().test(context)
    assert connection_result.status == AdapterStatus.PERMANENT_ERROR
    assert connection_result.error_code == "source_account_realm_invalid"


@pytest.mark.asyncio
async def test_shopify_account_rejects_invalid_orders_api_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.account as account_mod

    def no_network(*_args, **_kwargs):
        pytest.fail("invalid orders_api must fail before network")

    monkeypatch.setattr(account_mod, "_http_client", no_network)
    context = _context(config={"orders_api": "not-a-transport"})
    discovered = await ShopifyAccountAdapter().discover_accounts(context)
    assert discovered.status == AdapterStatus.PERMANENT_ERROR
    assert discovered.error_code == "orders_api_invalid"
    selected = await ShopifyAccountAdapter().select_account(context, account_id=f"shop:{SHOP}")
    assert selected.status == AdapterStatus.PERMANENT_ERROR
    assert selected.error_code == "orders_api_invalid"


@pytest.mark.asyncio
async def test_graphql_requires_all_orders_scope_before_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = _orders_response([_order()])
        body["data"]["currentAppInstallation"]["accessScopes"] = [{"handle": "read_orders"}]
        return httpx.Response(200, json=body)

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "read_all_orders_required"
    assert not result.data or "records" not in result.data


@pytest.mark.asyncio
async def test_graphql_recent_incremental_sync_needs_only_read_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = _orders_response([_order()])
        body["data"]["currentAppInstallation"]["accessScopes"] = [{"handle": "read_orders"}]
        return httpx.Response(200, json=body)

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(config={"updated_since": "2026-08-01T00:00:00Z"}), cursor=None
    )
    assert result.success is True
    assert len(result.data.records) == 1


@pytest.mark.asyncio
async def test_graphql_older_incremental_sync_needs_read_all_orders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = _orders_response([_order()])
        body["data"]["currentAppInstallation"]["accessScopes"] = [{"handle": "read_orders"}]
        return httpx.Response(200, json=body)

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(config={"updated_since": "2026-05-01T00:00:00Z"}), cursor=None
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "read_all_orders_required"
    assert not result.data or "records" not in result.data


@pytest.mark.asyncio
async def test_graphql_requires_base_read_orders_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = _orders_response([_order()])
        body["data"]["currentAppInstallation"]["accessScopes"] = []
        return httpx.Response(200, json=body)

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(config={"updated_since": "2026-08-01T00:00:00Z"}), cursor=None
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "read_orders_required"


@pytest.mark.asyncio
async def test_graphql_requires_verified_selected_shop_before_raw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_orders_response([_order()]))

    _transport(monkeypatch, handler)
    adapter = ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read")
    missing = await adapter.fetch(_context(config={"_verified_shop_gid": None}), cursor=None)
    assert missing.status == AdapterStatus.PERMANENT_ERROR
    assert missing.error_code == "selected_shop_unverified"
    mismatch = await adapter.fetch(
        _context(config={"_verified_shop_gid": "gid://shopify/Shop/999"}), cursor=None
    )
    assert mismatch.status == AdapterStatus.PERMANENT_ERROR
    assert mismatch.error_code == "selected_shop_mismatch"


@pytest.mark.asyncio
async def test_graphql_checkpoint_rejects_realm_change(monkeypatch: pytest.MonkeyPatch) -> None:
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, json=_orders_response([]))

    _transport(monkeypatch, handler)
    adapter = ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read")
    first = await adapter.fetch(_context(), cursor=None)
    assert first.success is True
    second = await adapter.fetch(
        _context(config={"source_account_realm": "live"}), cursor=first.data.next_cursor
    )
    assert second.status == AdapterStatus.PERMANENT_ERROR
    assert second.error_code == "graphql_cursor_invalid"
    assert requests == 1


@pytest.mark.asyncio
async def test_graphql_rejects_order_changed_during_nested_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _order()
    order["lineItems"]["pageInfo"] = {"hasNextPage": True, "endCursor": "line-page-1"}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        if "AetherOrders" in payload["query"]:
            return httpx.Response(200, json=_orders_response([order]))
        return httpx.Response(
            200,
            json={
                "data": {
                    "order": {
                        "id": ORDER_GID,
                        "updatedAt": "2026-08-02T00:00:01Z",
                        "lineItems": {
                            "nodes": [_line(2)],
                            "pageInfo": {"hasNextPage": False, "endCursor": "line-page-2"},
                        },
                    }
                }
            },
        )

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert result.success is False
    assert result.status == AdapterStatus.RETRYABLE_ERROR
    assert result.error_code == "order_changed_during_fetch"


@pytest.mark.parametrize(
    "invalid",
    [
        lambda body: {"errors": [{"extensions": {"code": "ACCESS_DENIED"}}], **body},
        lambda body: {"data": {"shop": {"id": SHOP_GID}, "orders": {"nodes": [_order()]}}},
        lambda body: {
            "data": {
                "shop": {"id": SHOP_GID},
                "orders": {"nodes": [{"id": ORDER_GID}], "pageInfo": {"hasNextPage": False}},
            }
        },
        lambda body: {
            "data": {
                "shop": {"id": SHOP_GID},
                "orders": {
                    "nodes": [{**_order(), "currentTotalPriceSet": _bag("0.13", "EUR")}],
                    "pageInfo": {"hasNextPage": False},
                },
            }
        },
    ],
)
@pytest.mark.asyncio
async def test_graphql_fails_closed_on_errors_and_sparse_payloads(
    monkeypatch: pytest.MonkeyPatch, invalid
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid(_orders_response([_order()])))

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert result.success is False
    assert result.data is None or not hasattr(result.data, "records")
    assert result.status in {AdapterStatus.UNAUTHORIZED, AdapterStatus.RETRYABLE_ERROR}


@pytest.mark.asyncio
async def test_graphql_throttle_is_classified_without_exposing_provider_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [{"message": "sensitive details", "extensions": {"code": "THROTTLED"}}],
                "extensions": {
                    "cost": {
                        "requestedQueryCost": 100,
                        "throttleStatus": {"currentlyAvailable": 50, "restoreRate": 25},
                    }
                },
            },
        )

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(), cursor=None
    )
    assert result.status == AdapterStatus.RATE_LIMITED
    assert result.retryable is True
    assert result.rate_limit.retry_after_ms == 2000
    assert "sensitive" not in str(result)


@pytest.mark.asyncio
async def test_graphql_token_only_auth_and_immutable_shop_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.account as account_mod
    import services.providers.shopify.auth as auth_mod

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers.get("X-Shopify-Access-Token") == "synthetic-secret"
        return httpx.Response(
            200,
            json={
                "data": {
                    "shop": {"id": SHOP_GID, "name": "Synthetic Store"},
                    "currentAppInstallation": {
                        "accessScopes": [{"handle": "read_orders"}],
                    },
                }
            },
        )

    factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", factory)
    monkeypatch.setattr(account_mod, "_http_client", factory)
    context = _context()
    assert (await ShopifyAuthAdapter().validate_credentials(context)).success is True
    auth_test = await ShopifyAuthAdapter().test(context)
    assert auth_test.success is True
    assert auth_test.data["read_orders"] is True
    assert auth_test.data["historical_backfill_available"] is False
    result = await ShopifyAccountAdapter().discover_accounts(context)
    assert result.success is True
    assert result.data[0].account_id == f"shop:{SHOP}"
    assert result.data[0].external_id == SHOP_GID
    assert result.data[0].metadata["shop_gid"] == SHOP_GID
    assert result.data[0].metadata["source_account_realm"] == "test"


@pytest.mark.asyncio
async def test_graphql_auth_probe_requires_base_scope_and_reports_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.account as account_mod
    import services.providers.shopify.auth as auth_mod

    def client_for(scopes: list[str]) -> httpx.AsyncClient:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "shop": {"id": SHOP_GID},
                        "currentAppInstallation": {
                            "accessScopes": [{"handle": scope} for scope in scopes],
                        },
                    }
                },
            )

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(auth_mod, "_http_client", lambda: client_for([]))
    monkeypatch.setattr(account_mod, "_http_client", lambda: client_for([]))
    missing_base_scope = await ShopifyAuthAdapter().test(_context())
    assert missing_base_scope.status == AdapterStatus.PERMANENT_ERROR
    assert missing_base_scope.error_code == "read_orders_required"
    missing_account_scope = await ShopifyAccountAdapter().discover_accounts(_context())
    assert missing_account_scope.status == AdapterStatus.PERMANENT_ERROR
    assert missing_account_scope.error_code == "read_orders_required"

    full_scope_client = lambda: client_for(["read_orders", "read_all_orders"])
    monkeypatch.setattr(auth_mod, "_http_client", full_scope_client)
    monkeypatch.setattr(account_mod, "_http_client", full_scope_client)
    full_access = await ShopifyAuthAdapter().test(_context())
    assert full_access.success is True
    assert full_access.data["read_orders"] is True
    assert full_access.data["historical_backfill_available"] is True
    full_scope_account = await ShopifyAccountAdapter().discover_accounts(_context())
    assert full_scope_account.success is True
    assert full_scope_account.data[0].external_id == SHOP_GID


@pytest.mark.asyncio
async def test_graphql_structured_multi_credential_and_missing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.account as account_mod
    import services.providers.shopify.auth as auth_mod

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Shopify-Access-Token"] == "synthetic-structured-token"
        return httpx.Response(
            200,
            json={
                "data": {
                    "shop": {"id": SHOP_GID, "name": "Store"},
                    "currentAppInstallation": {
                        "accessScopes": [{"handle": "read_orders"}],
                    },
                }
            },
        )

    factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", factory)
    monkeypatch.setattr(account_mod, "_http_client", factory)
    credential = MultiCredential(
        credentials={
            "shop_access_token": ApiKeyCredential(api_key=SecretStr("synthetic-structured-token")),
            "webhook_secret": ApiKeyCredential(api_key=SecretStr("synthetic-hmac-secret")),
        }
    )
    context = _context(config={"shop_domain": SHOP}).model_copy(update={"credential": credential})
    assert (await ShopifyAuthAdapter().validate_credentials(context)).success is True
    assert (await ShopifyAuthAdapter().test(context)).success is True
    discovered = await ShopifyAccountAdapter().discover_accounts(context)
    assert discovered.success is True
    assert discovered.data[0].external_id == SHOP_GID
    assert "synthetic-structured-token" not in str(discovered.data[0].model_dump())
    assert "synthetic-hmac-secret" not in str(discovered.data[0].model_dump())

    missing = MultiCredential(
        credentials={
            "webhook_secret": ApiKeyCredential(api_key=SecretStr("synthetic-hmac-secret")),
        }
    )
    missing_context = context.model_copy(update={"credential": missing})
    invalid = await ShopifyAuthAdapter().validate_credentials(missing_context)
    assert invalid.error_code == "credential_missing_fields"
    unverified = await ShopifyAccountAdapter().discover_accounts(missing_context)
    assert unverified.success is False
    assert unverified.error_code == "shop_identity_unverified"


@pytest.mark.asyncio
async def test_graphql_invalid_domain_never_sends_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        pytest.fail("network must not be reached")

    _transport(monkeypatch, handler)
    result = await ShopifyGraphQLPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(shop="127.0.0.1"), cursor=None
    )
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.error_code == "shop_domain_invalid"
