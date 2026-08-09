"""Tests for the Shopify provider plugin (manifest honesty, identity,
normalization, webhook verification, pull pagination, payload tolerance).

All fixtures are SYNTHETIC (no real credentials, no real PII, no live network).
Async adapter tests use ``@pytest.mark.asyncio`` and a fake ``httpx`` transport.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
from decimal import Decimal
from pathlib import Path

import pytest

import httpx

from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import RawProviderRecord, compute_checksum
from shared.integration_contracts.manifest import validate_manifest
from shared.integration_contracts.plugin import capability_set, plugin_identity_key
from shared.integration_contracts.results import AdapterStatus

from services.providers.shopify.account import ShopifyAccountAdapter
from services.providers.shopify.auth import (
    ShopifyAuthAdapter,
    _credential_dict,
    _validated_shop_domain,
)
from services.providers.shopify.normalizer import ShopifyOrderNormalizer
from services.providers.shopify.payloads import ShopifyOrder, ShopifyWebhookEnvelope
from services.providers.shopify.plugin import ShopifyOrdersPlugin
from services.providers.shopify.pull import PAGE_INFO_PREFIX, ShopifyPullAdapter
from services.providers.shopify import install_shopify_providers
from services.providers.shopify.webhook import ShopifyWebhookAdapter

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "provider_payloads"
    / "shopify_orders.json"
)

SHOP_DOMAIN = "synth-demo.myshopify.com"
CREDENTIAL = {
    "api_key": "synth-api-key",
    "password": "synth-password",
    "shop_domain": SHOP_DOMAIN,
}
# Full credential shape the manifest now declares: API fields + the webhook HMAC
# secret required by the declared shopify_hmac verification scheme.
FULL_CREDENTIAL = {**CREDENTIAL, "webhook_secret": "synth-webhook-secret"}

# Synthetic order id -> expected provider-neutral event type.
EXPECTED_EVENT_TYPES = {
    9000100001: "commerce.order.created",
    9000100002: "commerce.order.updated",
    9000100003: "commerce.order.cancelled",
    9000100004: "commerce.order.refunded",
}


def _load_orders() -> list[dict]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["orders"]


def _context(
    *,
    tenant_id: str = "tenant-synth-1",
    connection_id: str = "conn-synth-1",
    account_id: str = "",
    config: dict | None = None,
    credential: dict | None = CREDENTIAL,
) -> AcquisitionContext:
    """Build an AcquisitionContext with a plain-dict credential.

    ``AcquisitionContext.credential`` is typed ``Optional[StructuredCredential]``,
    but Team D's broker reveals credentials as plaintext dicts; ``model_construct``
    bypasses validation so the dict travels to the adapter untouched (the adapter
    reads it defensively).
    """
    return AcquisitionContext.model_construct(
        tenant_id=tenant_id,
        provider_identity="shopify.admin.orders_read",
        connection_id=connection_id,
        account_id=account_id,
        config=config or {},
        credential=credential,
    )


def _raw_for(
    order: dict,
    *,
    record_id: str = "raw-synth-1",
    provider_record_type: str = "order",
    acquisition_mode: str = "poll",
    account_id: str = "",
    connection_id: str = "conn-synth-1",
) -> RawProviderRecord:
    return RawProviderRecord(
        record_id=record_id,
        provider_identity="shopify.admin.orders_read",
        tenant_id="tenant-synth-1",
        connection_id=connection_id,
        account_id=account_id,
        provider_record_type=provider_record_type,
        provider_record_id=str(order["id"]),
        acquisition_mode=acquisition_mode,
        observed_at="2026-08-08T00:00:00+00:00",
        provider_occurred_at=order.get("updated_at"),
        checksum=compute_checksum(order),
        payload=order,
    )


@pytest.fixture(scope="module")
def plugin() -> ShopifyOrdersPlugin:
    return ShopifyOrdersPlugin()


@pytest.fixture(scope="module")
def orders() -> list[dict]:
    return _load_orders()


@pytest.fixture(autouse=True)
def _restore_plugin_store() -> None:
    """Restore the module-level plugin store after every test.

    The store is process-global mutable state that other test files (and the
    registry's ``load_all``) read. A few tests here clear it to prove fresh
    registration; those clears must never leak — otherwise a later
    ``ProviderRegistry().load_all()`` re-imports the already-cached plugin
    modules (no re-registration) and silently ships an incomplete registry.
    Snap it before and restore after, exactly like ``test_plugin.py``.
    """
    from services.provider_runtime.plugin import (
        clear_registered_providers,
        register_provider,
        registered_providers,
    )

    before = registered_providers()
    yield
    clear_registered_providers()
    for plugin in before.values():
        register_provider(plugin)


# ── Manifest honesty + identity ─────────────────────────────────────────────


def test_manifest_passes_validate_manifest(plugin: ShopifyOrdersPlugin) -> None:
    manifest = plugin.manifest()
    validate_manifest(manifest)
    assert manifest.identity_key == "shopify.admin.orders_read"
    assert manifest.readiness.level >= 3  # env-visible capability
    assert manifest.category == "commerce"


def test_capability_set_is_honest(plugin: ShopifyOrdersPlugin) -> None:
    caps = capability_set(plugin)
    assert caps.auth is True
    assert caps.account is True
    assert caps.pull is True
    assert caps.webhook is True
    assert caps.report is False
    assert caps.stream is False
    assert caps.reconciliation is False


def test_plugin_identity_key(plugin: ShopifyOrdersPlugin) -> None:
    assert plugin_identity_key(plugin) == "shopify.admin.orders_read"


def test_plugin_version(plugin: ShopifyOrdersPlugin) -> None:
    assert plugin.version == "1.0.0"


def test_manifest_declares_webhook_secret(plugin: ShopifyOrdersPlugin) -> None:
    """The shopify_hmac scheme must be backed by a declared webhook secret."""
    manifest = plugin.manifest()
    assert manifest.webhooks.verification_scheme == "shopify_hmac"
    fields = {f.name: f for f in manifest.authentication.credential_schema}
    assert "webhook_secret" in fields
    assert fields["webhook_secret"].required is True
    assert fields["webhook_secret"].secret is True


def test_install_shopify_providers_matches_runtime_registry(plugin: ShopifyOrdersPlugin) -> None:
    """install_shopify_providers must satisfy Team C's registry.register(plugin,
    *, source=...) signature and register exactly the one capability."""
    from services.provider_runtime.plugin import clear_registered_providers
    from services.provider_runtime.registry import ProviderRegistry

    try:
        registry = ProviderRegistry(entry_points_enabled=False, auto_install_legacy=False)
        install_shopify_providers(registry)
        assert "shopify.admin.orders_read" in registry
        assert registry.sources() == {"shopify.admin.orders_read": "shopify"}
        assert registry.get("shopify.admin.orders_read").identity().key == (
            "shopify.admin.orders_read"
        )
        # Re-registering the SAME object is a no-op (idempotent).
        assert (
            registry.register(registry.get("shopify.admin.orders_read"), source="shopify")
            == "shopify.admin.orders_read"
        )
    finally:
        clear_registered_providers()


def test_module_self_registration_is_idempotent() -> None:
    """register_provider is idempotent per identity key (Team C's seam)."""
    from services.provider_runtime.plugin import (
        clear_registered_providers,
        register_provider,
        registered_providers,
    )

    try:
        clear_registered_providers()
        plugin = ShopifyOrdersPlugin()
        assert register_provider(plugin) == "shopify.admin.orders_read"
        # Re-registering the SAME object is a no-op returning the key (no raise).
        assert register_provider(plugin) == "shopify.admin.orders_read"
        assert registered_providers()["shopify.admin.orders_read"] is plugin
    finally:
        clear_registered_providers()


# ── Normalizer roundtrip ────────────────────────────────────────────────────


@pytest.mark.parametrize("order", _load_orders(), ids=lambda o: str(o["id"]))
def test_normalizer_roundtrip(order: dict) -> None:
    raw = _raw_for(order, record_id=f"raw-synth-{order['id']}")
    result = ShopifyOrderNormalizer().normalize(raw)

    assert result.dropped == []
    assert result.skipped == 0
    assert result.normalizer_version == "1"
    assert len(result.events) == 1

    event = result.events[0]
    expected = EXPECTED_EVENT_TYPES[order["id"]]
    assert event.event_type == expected
    assert event.event_family == "commerce"
    assert event.provider == "shopify"
    assert event.provider_identity == "shopify.admin.orders_read"
    assert event.source_record_id == raw.record_id
    assert event.occurred_at == raw.provider_occurred_at
    assert event.observed_at == raw.observed_at
    assert event.account_id == "default"  # raw.account_id empty -> "default"
    assert event.data["order_id"] == str(order["id"])
    assert event.data["currency"] == order["currency"]
    assert event.data["account_id"] == "default"
    assert isinstance(event.data["total"]["amount"], Decimal)
    assert event.data["total"]["currency"] == order["currency"]
    # No loss: full raw payload preserved, provider-specific fields surfaced.
    assert event.context["acquisition_mode"] == raw.acquisition_mode
    assert event.context["connection_id"] == raw.connection_id
    assert event.context["raw_provider_payload"] == order
    assert event.data["provider"]["financial_status"] == order["financial_status"]


@pytest.mark.parametrize(
    "order,expected_status",
    [
        (_load_orders()[0], "created"),
        (_load_orders()[1], "updated"),
        (_load_orders()[2], "cancelled"),
        (_load_orders()[3], "refunded"),
    ],
    ids=["created", "updated", "cancelled", "refunded"],
)
def test_normalizer_event_type_mapping(order: dict, expected_status: str) -> None:
    result = ShopifyOrderNormalizer().normalize(_raw_for(order))
    assert result.events[0].event_type == f"commerce.order.{expected_status}"


def test_normalizer_unknown_record_type_is_dropped_not_silent() -> None:
    order = _load_orders()[0]
    raw = _raw_for(order, provider_record_type="customer", record_id="raw-customer-1")
    result = ShopifyOrderNormalizer().normalize(raw)
    assert result.events == []
    assert result.dropped == ["raw-customer-1:customer"]


def test_normalizer_is_deterministic(orders: list[dict]) -> None:
    raw = _raw_for(orders[0])
    first = ShopifyOrderNormalizer().normalize(raw).events[0]
    second = ShopifyOrderNormalizer().normalize(raw).events[0]
    assert first.model_dump() == second.model_dump()


# ── Webhook HMAC verification + parse ───────────────────────────────────────


def _hmac_signature(raw_body: bytes, secret: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("utf-8")


def _webhook_adapter() -> ShopifyWebhookAdapter:
    return ShopifyWebhookAdapter(provider_identity="shopify.admin.orders_read")


def test_webhook_verify_correct_hmac_passes(orders: list[dict]) -> None:
    secret = "synth-webhook-secret"
    envelope = {
        "id": 7000100001,
        "domain": SHOP_DOMAIN,
        "topic": "orders/create",
        "created_at": "2026-08-01T10:00:00Z",
        "body": orders[0],
    }
    raw_body = json.dumps(envelope).encode("utf-8")
    signature = _hmac_signature(raw_body, secret)
    assert _webhook_adapter().verify(raw_body, {"X-Shopify-Hmac-SHA256": signature}, secret)


def test_webhook_verify_tampered_body_fails(orders: list[dict]) -> None:
    secret = "synth-webhook-secret"
    envelope = {
        "id": 7000100001,
        "domain": SHOP_DOMAIN,
        "topic": "orders/create",
        "created_at": "2026-08-01T10:00:00Z",
        "body": orders[0],
    }
    raw_body = json.dumps(envelope).encode("utf-8")
    signature = _hmac_signature(raw_body, secret)
    tampered = json.dumps({**envelope, "order_id": 999999}).encode("utf-8")
    assert not _webhook_adapter().verify(tampered, {"X-Shopify-Hmac-SHA256": signature}, secret)


def test_webhook_verify_wrong_secret_fails(orders: list[dict]) -> None:
    secret = "synth-webhook-secret"
    envelope = {"id": 7000100001, "domain": SHOP_DOMAIN, "body": orders[0]}
    raw_body = json.dumps(envelope).encode("utf-8")
    signature = _hmac_signature(raw_body, secret)
    assert not _webhook_adapter().verify(
        raw_body, {"X-Shopify-Hmac-SHA256": signature}, "a-different-secret"
    )


def test_webhook_verify_hmac_is_over_raw_body(orders: list[dict]) -> None:
    """HMAC covers the exact raw bytes: a re-serialized dict must NOT verify."""
    secret = "synth-webhook-secret"
    envelope = {"id": 7000100001, "domain": SHOP_DOMAIN, "body": orders[0]}
    raw_body = json.dumps(envelope).encode("utf-8")
    signature = _hmac_signature(raw_body, secret)
    re_serialized = json.dumps(envelope, sort_keys=True).encode("utf-8")
    assert re_serialized != raw_body
    assert not _webhook_adapter().verify(
        re_serialized, {"X-Shopify-Hmac-SHA256": signature}, secret
    )


def test_webhook_verify_no_secret_or_header_fails(orders: list[dict]) -> None:
    adapter = _webhook_adapter()
    envelope = {"id": 7000100001, "domain": SHOP_DOMAIN, "body": orders[0]}
    raw_body = json.dumps(envelope).encode("utf-8")
    assert not adapter.verify(raw_body, {"X-Shopify-Hmac-SHA256": "abc"}, None)
    assert not adapter.verify(raw_body, {}, "synth-webhook-secret")


def test_webhook_parse_emits_order_record(orders: list[dict]) -> None:
    envelope = {
        "id": 7000100001,
        "domain": SHOP_DOMAIN,
        "topic": "orders/create",
        "created_at": "2026-08-01T10:00:00Z",
        "body": orders[0],
    }
    records = _webhook_adapter().parse(envelope, headers={})
    assert len(records) == 1
    record = records[0]
    assert record.provider_record_type == "order"
    assert record.acquisition_mode == "webhook"
    assert record.webhook_delivery_id == "7000100001"
    assert record.provider_record_id == str(orders[0]["id"])
    assert record.payload == orders[0]


def test_webhook_parse_without_nested_body() -> None:
    envelope = {
        "id": 7000100002,
        "domain": SHOP_DOMAIN,
        "topic": "orders/update",
        "created_at": "2026-08-02T10:00:00Z",
        "order_id": 9000100002,
    }
    records = _webhook_adapter().parse(envelope, headers={})
    assert len(records) == 1
    assert records[0].provider_record_id == "9000100002"
    assert records[0].acquisition_mode == "webhook"


# ── Pull pagination, cursors, rate limiting ─────────────────────────────────


def _pull_adapter() -> ShopifyPullAdapter:
    return ShopifyPullAdapter(provider_identity="shopify.admin.orders_read")


async def _run_fetch(monkeypatch: pytest.MonkeyPatch, client, **kwargs):
    import services.providers.shopify.pull as pull_mod

    monkeypatch.setattr(pull_mod, "_http_client", lambda: client)
    return await _pull_adapter().fetch(_context(), **kwargs)


@pytest.mark.asyncio
async def test_pull_link_pagination_and_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            headers={
                "Link": (
                    f'<https://{SHOP_DOMAIN}/admin/api/2024-10/orders.json'
                    '?page_info=opaque-page-token&limit=250>; rel="next"'
                ),
                "X-Shopify-Shop-Api-Call-Limit": "39/40",
            },
            json={"orders": _load_orders()[:2]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=None)

    assert result.success is True
    assert result.status == AdapterStatus.OK
    assert result.data.has_more is True
    assert result.data.next_cursor == f"{PAGE_INFO_PREFIX}opaque-page-token"
    assert len(result.data.records) == 2
    assert result.data.records[0].provider_record_type == "order"
    assert result.data.records[0].provider_record_id == str(_load_orders()[0]["id"])
    assert result.data.records[0].acquisition_mode == "poll"
    assert "status=any" in captured["url"]
    assert result.rate_limit is not None
    assert result.rate_limit.limit == 40
    assert result.rate_limit.remaining == 39
    assert result.rate_limit.retry_after_ms == 0


@pytest.mark.asyncio
async def test_pull_next_page_token_header(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"X-Shopify-Next-Page-Token": "opaque-token-2"},
            json={"orders": []},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=None)
    assert result.data.has_more is True
    assert result.data.next_cursor == f"{PAGE_INFO_PREFIX}opaque-token-2"


@pytest.mark.asyncio
async def test_pull_cursor_sends_page_info(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["page_info"] = request.url.params.get("page_info")
        captured["since_id"] = request.url.params.get("since_id")
        return httpx.Response(200, json={"orders": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=f"{PAGE_INFO_PREFIX}opaque-page")
    assert result.data.has_more is False
    assert result.data.next_cursor is None
    assert captured["page_info"] == "opaque-page"
    assert captured["since_id"] is None


@pytest.mark.asyncio
async def test_pull_cursor_sends_since_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["page_info"] = request.url.params.get("page_info")
        captured["since_id"] = request.url.params.get("since_id")
        return httpx.Response(200, json={"orders": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor="9000100001")
    assert captured["since_id"] == "9000100001"
    assert captured["page_info"] is None
    assert result.data.has_more is False


@pytest.mark.asyncio
async def test_pull_limit_capped_at_250(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json={"orders": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await _run_fetch(monkeypatch, client, cursor=None, limit=1000)
    assert captured["limit"] == "250"


@pytest.mark.asyncio
async def test_pull_http_429_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=None)
    assert result.success is False
    assert result.status == AdapterStatus.RATE_LIMITED
    assert result.retryable is True
    assert result.rate_limit is not None
    assert result.rate_limit.retry_after_ms == 2000


@pytest.mark.asyncio
async def test_pull_http_401_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=None)
    assert result.status == AdapterStatus.UNAUTHORIZED
    assert result.retryable is False


@pytest.mark.asyncio
async def test_pull_http_500_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await _run_fetch(monkeypatch, client, cursor=None)
    assert result.status == AdapterStatus.RETRYABLE_ERROR
    assert result.retryable is True


@pytest.mark.asyncio
async def test_pull_sends_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"orders": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await _run_fetch(monkeypatch, client, cursor=None)
    assert captured["authorization"].startswith("Basic ")


# ── Auth adapter ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_validate_credentials() -> None:
    adapter = ShopifyAuthAdapter()
    ok = await adapter.validate_credentials(_context(credential=dict(CREDENTIAL)))
    assert ok.success is True
    assert ok.status == AdapterStatus.OK

    # The full manifest-declared shape (API fields + webhook_secret) validates.
    full = await adapter.validate_credentials(_context(credential=dict(FULL_CREDENTIAL)))
    assert full.success is True
    assert full.status == AdapterStatus.OK

    missing = await adapter.validate_credentials(
        _context(credential={"api_key": "k", "shop_domain": SHOP_DOMAIN})
    )
    assert missing.success is False
    assert missing.status == AdapterStatus.PERMANENT_ERROR
    assert missing.error_code == "credential_missing_fields"

    none = await adapter.validate_credentials(_context(credential=None))
    assert none.success is False
    assert none.status == AdapterStatus.PERMANENT_ERROR


def test_webhook_secret_never_aliases_to_api_password() -> None:
    """webhook_secret is a distinct credential: it must NEVER be used as the
    Basic-auth API password (regression guard for the manifest addition)."""
    context = _context(
        credential={"api_key": "k", "webhook_secret": "whs", "shop_domain": SHOP_DOMAIN}
    )
    cred = _credential_dict(context)
    assert cred["webhook_secret"] == "whs"
    assert "password" not in cred
    assert "password" not in cred.values()


@pytest.mark.asyncio
async def test_auth_test_success_basic_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.providers.shopify.auth as auth_mod

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"shop": {"name": "Synth Demo"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", lambda: client)
    result = await auth_mod.ShopifyAuthAdapter().test(_context())
    assert result.success is True
    assert result.status == AdapterStatus.OK
    assert result.latency_ms is not None
    assert f"https://{SHOP_DOMAIN}/admin/api/2024-10/shop.json" in captured["url"]
    assert captured["authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_auth_basic_auth_never_uses_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the full manifest credential, Basic auth must carry api_key:password —
    the webhook HMAC secret is a distinct credential and never substitutes."""
    import services.providers.shopify.auth as auth_mod

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json={"shop": {"name": "Synth Demo"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", lambda: client)
    result = await auth_mod.ShopifyAuthAdapter().test(
        _context(credential=dict(FULL_CREDENTIAL))
    )
    assert result.success is True
    assert result.status == AdapterStatus.OK
    basic = captured["authorization"].removeprefix("Basic ")
    decoded = base64.b64decode(basic).decode("utf-8")
    assert decoded == "synth-api-key:synth-password"
    assert "synth-webhook-secret" not in decoded


@pytest.mark.asyncio
async def test_auth_test_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.providers.shopify.auth as auth_mod

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", lambda: client)
    result = await auth_mod.ShopifyAuthAdapter().test(_context())
    assert result.status == AdapterStatus.UNAUTHORIZED
    assert "synth-api-key" not in result.data["detail"]  # no secrets in detail


@pytest.mark.asyncio
async def test_auth_test_missing_fields_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.providers.shopify.auth as auth_mod

    def boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("network attempted without complete credentials")

    monkeypatch.setattr(auth_mod, "_http_client", boom)
    result = await auth_mod.ShopifyAuthAdapter().test(_context(credential={"api_key": "k"}))
    assert result.success is False
    assert result.status == AdapterStatus.PERMANENT_ERROR


# ── SSRF: shop_domain must be an allowlisted *.myshopify.com host ────────────


INVALID_SHOP_DOMAINS = [
    "127.0.0.1",
    "127.0.0.1:8443",
    "[::1]",
    "169.254.169.254",
    "10.0.0.1",
    "192.168.1.1",
    "172.16.0.1",
    "https://evil.myshopify.com",
    "evil.com",
    "evil.myshopify.com.evil.net",
    "evil.myshopify.com/../../",
    "my-store.myshopify.com.",
]

VALID_SHOP_DOMAINS = ["my-store.myshopify.com", "MY-STORE.MYSHOPIFY.COM"]


@pytest.mark.parametrize("bad", INVALID_SHOP_DOMAINS)
def test_validated_shop_domain_rejects(bad: str) -> None:
    assert _validated_shop_domain(bad) is None


@pytest.mark.parametrize("good", VALID_SHOP_DOMAINS)
def test_validated_shop_domain_accepts(good: str) -> None:
    assert _validated_shop_domain(good) == "my-store.myshopify.com"


@pytest.mark.parametrize("bad", INVALID_SHOP_DOMAINS)
@pytest.mark.asyncio
async def test_auth_validate_credentials_rejects_bad_shop_domain(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    import services.providers.shopify.auth as auth_mod

    def boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("network attempted for an invalid shop_domain")

    monkeypatch.setattr(auth_mod, "_http_client", boom)
    result = await auth_mod.ShopifyAuthAdapter().validate_credentials(
        _context(credential={"api_key": "k", "password": "p", "shop_domain": bad})
    )
    assert result.success is False
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.retryable is False
    assert result.error_code == "shop_domain_invalid"
    assert bad not in result.data["detail"]  # never echo an attacker-controlled host


@pytest.mark.parametrize("bad", INVALID_SHOP_DOMAINS)
@pytest.mark.asyncio
async def test_pull_fetch_rejects_bad_shop_domain(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    import services.providers.shopify.pull as pull_mod

    def boom(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("network attempted for an invalid shop_domain")

    monkeypatch.setattr(pull_mod, "_http_client", boom)
    result = await ShopifyPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(credential={"api_key": "k", "password": "p", "shop_domain": bad}),
        cursor=None,
    )
    assert result.success is False
    assert result.status == AdapterStatus.PERMANENT_ERROR
    assert result.retryable is False
    assert result.error_code == "shop_domain_invalid"
    assert bad not in result.data["detail"]


@pytest.mark.asyncio
async def test_pull_fetch_accepts_valid_shop_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """The network path IS hit with the exact normalized URL for an accepted host."""
    import services.providers.shopify.pull as pull_mod

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"orders": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(pull_mod, "_http_client", lambda: client)
    result = await ShopifyPullAdapter(provider_identity="shopify.admin.orders_read").fetch(
        _context(
            credential={"api_key": "k", "password": "p", "shop_domain": "my-store.myshopify.com"}
        ),
        cursor=None,
    )
    assert result.success is True
    assert captured["url"].startswith(
        "https://my-store.myshopify.com/admin/api/2024-10/orders.json?"
    )


@pytest.mark.asyncio
async def test_auth_test_accepts_uppercase_domain_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uppercase allowlisted hosts are normalized to lowercase before the URL."""
    import services.providers.shopify.auth as auth_mod

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"shop": {"name": "Synth"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(auth_mod, "_http_client", lambda: client)
    result = await auth_mod.ShopifyAuthAdapter().test(
        _context(
            credential={"api_key": "k", "password": "p", "shop_domain": "MY-STORE.MYSHOPIFY.COM"}
        )
    )
    assert result.success is True
    assert result.status == AdapterStatus.OK
    assert captured["url"].startswith("https://my-store.myshopify.com/admin/api/2024-10/shop.json")


def test_api_version_rejects_path_injection() -> None:
    import services.providers.shopify.auth as auth_mod
    from services.providers.shopify.auth import _api_version

    assert _api_version(_context(config={"api_version": "2024-10/../../admin"})) == (
        auth_mod.DEFAULT_API_VERSION
    )
    assert _api_version(_context(config={"api_version": "2024-10"})) == "2024-10"


# ── Account adapter ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_discovery_no_credential_is_network_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.providers.shopify.account as acct_mod

    class _Boom:
        async def __aenter__(self):  # pragma: no cover - must never be reached
            raise AssertionError("discovery must not hit the network without a credential")

        async def __aexit__(self, *args):  # pragma: no cover
            return None

    monkeypatch.setattr(acct_mod, "_http_client", lambda: _Boom())
    result = await acct_mod.ShopifyAccountAdapter().discover_accounts(
        _context(config={"shop_domain": SHOP_DOMAIN}, credential=None)
    )
    assert result.success is True
    assert len(result.data) == 1
    account = result.data[0]
    assert account.account_id == f"shop:{SHOP_DOMAIN}"
    assert account.display_name == SHOP_DOMAIN
    assert account.metadata["shop_domain"] == SHOP_DOMAIN


@pytest.mark.asyncio
async def test_account_select_matches_resolved_shop() -> None:
    adapter = ShopifyAccountAdapter()
    context = _context(credential=dict(CREDENTIAL))
    ok = await adapter.select_account(context, account_id=f"shop:{SHOP_DOMAIN}")
    assert ok.success is True
    assert ok.data == {"account_id": f"shop:{SHOP_DOMAIN}"}

    bad = await adapter.select_account(context, account_id="shop:other.myshopify.com")
    assert bad.success is False
    assert bad.status == AdapterStatus.PERMANENT_ERROR


@pytest.mark.asyncio
async def test_account_discovery_missing_domain() -> None:
    result = await ShopifyAccountAdapter().discover_accounts(_context(credential=None, config={}))
    assert result.success is False
    assert result.status == AdapterStatus.PERMANENT_ERROR


# ── Payload tolerance ───────────────────────────────────────────────────────


def test_from_api_dict_tolerates_extra_fields(orders: list[dict]) -> None:
    # Fixture orders intentionally carry extra fields (billing_address,
    # payment_gateway_names, tags, extra_line_item_field, extra_customer_field).
    for order in orders:
        parsed = ShopifyOrder.from_api_dict(order)
        assert parsed.id == order["id"]
        assert parsed.line_items  # nested tolerance too
    assert ShopifyOrder.from_api_dict({}).id == 0


def test_webhook_envelope_from_api_dict_tolerates_extra_fields(orders: list[dict]) -> None:
    envelope = ShopifyWebhookEnvelope.from_api_dict(
        {"id": 7000100001, "topic": "orders/create", "extra_header_field": "ignored", "body": orders[0]}
    )
    assert envelope.id == 7000100001
    assert envelope.topic == "orders/create"
    assert envelope.order_id == orders[0]["id"]


# ── No network in pure seams ────────────────────────────────────────────────


def test_normalizer_and_webhook_verify_never_import_httpx() -> None:
    """The pure seams (payloads/normalizer/webhook) must not open connections."""
    from services.providers.shopify import normalizer, payloads, webhook

    for module in (normalizer, payloads, webhook):
        source = inspect.getsource(module)
        assert "httpx" not in source, f"{module.__name__} must not depend on httpx"
