"""Provider plugin honesty + determinism + SSRF tests (Team G, UPR follow-on).

Covers the six landed families — ``woocommerce``, ``etsy``, ``ebay``,
``walmart``, ``tiktok``, and ``amazon`` — for:

* manifest honesty (``assert_plugin_honest`` + ``validate_manifest``), identity
  key == manifest identity_key, honest webhook-claim invariants, env +
  readiness bounds;
* SSRF, parametrized per base URL (loopback/private/IP/metadata/host-header
  tricks rejected; the allowlisted base passes);
* fixture-replay determinism (exact ``event_id`` + ``Money`` ``Decimal``, byte-
  identical across replays) — payloads are synthetic and INLINE so the suite is
  self-contained;
* the two claimed webhook schemes (``wc_hmac`` and ``tiktok_hmac``) verify
  constant-time against a computed HMAC; TikTok request signing is deterministic;
* registry smoke: ``install_<family>_providers`` register the six identities,
  and ``load_all()`` installs all six native plugins + the legacy corpus.
"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.events import RawProviderRecord, compute_checksum
from shared.integration_contracts.manifest import validate_manifest
from shared.integration_contracts.plugin import capability_set, plugin_identity_key
from shared.security.ssrf import validated_https_host
from services.provider_runtime.validation import assert_plugin_honest

from services.providers.woocommerce.plugin import WooCommerceOrdersPlugin
from services.providers.etsy.plugin import EtsyOrdersPlugin
from services.providers.ebay.plugin import EbayOrdersPlugin
from services.providers.walmart.plugin import WalmartOrdersPlugin
from services.providers.tiktok.plugin import TikTokOrdersPlugin
from services.providers.amazon.plugin import AmazonOrdersPlugin

PLUGINS = [
    WooCommerceOrdersPlugin(),
    EtsyOrdersPlugin(),
    EbayOrdersPlugin(),
    WalmartOrdersPlugin(),
    TikTokOrdersPlugin(),
    AmazonOrdersPlugin(),
]


# ── Synthetic inline payloads (no secrets / no real PII) ───────────────────

WOO_ORDER = {
    "id": 9000200001,
    "number": "WOO-SYNTH-0001",
    "status": "completed",
    "currency": "USD",
    "date_created": "2026-08-01T10:00:00",
    "date_modified": "2026-08-02T11:30:00",
    "subtotal": "99.98",
    "total_tax": "8.00",
    "discount_total": "10.00",
    "shipping_total": "5.00",
    "total": "102.98",
    "line_items": [
        {
            "id": 8110200001,
            "product_id": 8200200001,
            "sku": "SYNTH-WIDGET",
            "name": "Synth Widget",
            "quantity": 2,
            "price": "24.99",
            "total": "49.98",
        }
    ],
    "customer_note": "Synthetic completed order",
}

ETSY_RECEIPT = {
    "receipt_id": 5001,
    "create_ts": 1782957600,
    "update_ts": 1783044000,
    "is_paid": True,
    "is_shipped": True,
    "currency_code": "USD",
    "grandtotal": {"amount": 1250, "divisor": 100, "currency_code": "USD"},
    "subtotal": {"amount": 1100, "divisor": 100, "currency_code": "USD"},
    "total_tax_cost": {"amount": 100, "divisor": 100, "currency_code": "USD"},
    "shipping_cost": {"amount": 50, "divisor": 100, "currency_code": "USD"},
    "discount_amt": 0,
    "buyer": {"user_id": 77, "email": "buyer-etsy@synth.example"},
    "transactions": [
        {
            "transaction_id": 6001,
            "title": "Etsy Synth Widget",
            "quantity": 2,
            "price": {"amount": 550, "divisor": 100, "currency_code": "USD"},
        }
    ],
}

EBAY_ORDER = {
    "orderId": "EB-SYNTH-1",
    "orderPaymentStatus": "PAID",
    "orderFulfillmentStatus": "NOT_STARTED",
    "creationDate": "2026-08-01T10:00:00Z",
    "modifiedDate": "2026-08-02T11:00:00Z",
    "total": {"value": "110.95", "currency": "USD"},
    "subtotal": {"value": "100.00", "currency": "USD"},
    "totalShippingCost": {"value": "6.00", "currency": "USD"},
    "totalTax": {"value": "4.95", "currency": "USD"},
    "buyer": {"username": "synth-buyer"},
    "lineItems": [
        {
            "lineItemId": "EB-SYNTH-L1",
            "sku": "EB-SYNTH-SKU",
            "title": "eBay Synth Widget",
            "quantity": 1,
            "lineItemCost": {"value": "100.00", "currency": "USD"},
        }
    ],
}

WALMART_ORDER = {
    "orderId": "WMT-SYNTH-1",
    "customerEmailId": "buyer-walmart@synth.example",
    "orderDate": "2026-08-01T10:00:00Z",
    "orderStatus": "SHIPPED",
    "orderType": "REGULAR",
    "orderLines": [
        {
            "lineNumber": "WMT-SYNTH-1",
            "itemStatus": "SHIPPED",
            "item": {"sku": "WMT-SYNTH-SKU", "productName": "Walmart Synth Widget"},
            "orderLineQuantity": {"amount": 2},
            "charges": [
                {
                    "chargeType": "PRODUCT",
                    "chargeAmount": {"currency": "USD", "amount": "25.00"},
                }
            ],
        }
    ],
    "orderSummary": {
        "totalAmount": {"currency": "USD", "amount": "55.00"},
        "subtotal": {"currency": "USD", "amount": "50.00"},
        "taxTotal": {"currency": "USD", "amount": "4.00"},
        "shippingHandling": {"currency": "USD", "amount": "1.00"},
    },
}

TIKTOK_ORDER = {
    "order_id": "TT-SYNTH-1",
    "order_status": "COMPLETED",
    "create_time": 1782957600,
    "update_time": 1783044000,
    "buyer_uid": "synth-buyer",
    "currency": "USD",
    "payment": {
        "sub_total": {"currency": "USD", "amount": "50.00"},
        "shipping_fee": {"currency": "USD", "amount": "5.00"},
        "tax_amount": {"currency": "USD", "amount": "4.00"},
        "total_amount": {"currency": "USD", "amount": "59.00"},
    },
    "order_line_list": [
        {
            "id": "TT-SYNTH-OL1",
            "product_name": "TikTok Synth Widget",
            "seller_sku": "TT-SYNTH-SKU",
            "quantity": 1,
            "sale_price": {"currency": "USD", "amount": "50.00"},
        }
    ],
}

AMAZON_ORDER = {
    "AmazonOrderId": "AMZ-SYNTH-1",
    "OrderStatus": "SHIPPED",
    "PurchaseDate": "2026-08-01T10:00:00Z",
    "LastUpdateDate": "2026-08-02T11:00:00Z",
    "OrderTotal": {"Amount": "49.99", "CurrencyCode": "USD"},
    "MarketplaceId": "ATVPDKIKX0DER",
    "SellerOrderId": "AMZ-SO-1",
    "FulfillmentChannel": "MFN",
    "PaymentMethod": "COD",
    "BuyerInfo": {
        "BuyerEmail": "buyer-amz@synth.example",
        "BuyerName": "Amazon Synth Buyer",
    },
    "OrderItems": [
        {
            "OrderItemId": "AMZ-SYNTH-L1",
            "ASIN": "AMZ-SYNTH-ASIN",
            "SellerSKU": "AMZ-SYNTH-SKU",
            "Title": "Amazon Synth Widget",
            "QuantityOrdered": 1,
            "QuantityShipped": 1,
            "ItemPrice": {"Amount": "49.99", "CurrencyCode": "USD"},
        }
    ],
}


def _raw_for(
    provider_identity: str,
    record_id: str,
    payload: dict,
    provider_record_id: str,
    *,
    observed_at: str = "2026-08-08T00:00:00+00:00",
    provider_occurred_at: str | None = None,
) -> RawProviderRecord:
    return RawProviderRecord(
        record_id=record_id,
        provider_identity=provider_identity,
        tenant_id="tenant-synth-1",
        connection_id="conn-synth-1",
        provider_record_type="order",
        provider_record_id=provider_record_id,
        acquisition_mode="poll",
        observed_at=observed_at,
        provider_occurred_at=provider_occurred_at,
        checksum=compute_checksum(payload),
        payload=payload,
    )


# ── Manifest honesty ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "plugin",
    PLUGINS,
    ids=lambda p: p.identity().key,
)
def test_manifest_honest(plugin):
    """Every landed plugin passes the §32 honesty gate and identity cross-check."""
    # Raises PluginValidationError / ManifestValidationError when dishonest.
    assert_plugin_honest(plugin)
    validate_manifest(plugin.manifest())
    # identity object == manifest identity_key.
    assert plugin.manifest().identity_key == plugin.identity().key
    assert plugin_identity_key(plugin) == plugin.identity().key
    # Capability set is honest: manifest claims iff the accessor returns a non-None adapter.
    caps = capability_set(plugin)
    assert caps.auth == (plugin.auth() is not None)
    assert caps.account == (plugin.account() is not None)
    assert caps.pull == (plugin.pull() is not None)
    assert caps.webhook == (plugin.webhook() is not None)
    # Webhook honesty: supported == a webhook adapter is present.
    assert plugin.manifest().webhooks.supported == (plugin.webhook() is not None)
    # Environments: local/integration ONLY — no staging/prod claims.
    envs = plugin.manifest().availability.environments
    assert envs.local is True
    assert envs.integration is True
    assert envs.staging is False
    assert envs.production is False
    # Certification state is honest.
    assert plugin.certification_state == "uncertified"
    # Env-visible capability needs level>=3; the offline replay evidence basis.
    readiness = plugin.manifest().readiness
    assert readiness.level >= 3
    assert readiness.state in (
        CredentialReadiness.REPLAY_VALIDATED,
        CredentialReadiness.CREDENTIAL_WAITING,
    )


@pytest.mark.parametrize(
    "plugin",
    PLUGINS,
    ids=lambda p: p.identity().key,
)
def test_identity_keys_are_exact(plugin):
    """The six-family identity contract: family.product.capability."""
    assert plugin.identity().key == plugin.manifest().identity_key
    assert plugin.identity().key.count(".") == 2
    assert plugin.identity().family in {
        "woocommerce", "etsy", "ebay", "walmart", "tiktok", "amazon",
    }
    assert plugin.identity().capability == "orders_read"


def test_webhooks_claimed_only_by_woocommerce_and_tiktok():
    """Only WooCommerce and TikTok Shop claim webhooks (both implemented)."""
    claims = {p.identity().key for p in PLUGINS if p.manifest().webhooks.supported}
    assert claims == {
        "woocommerce.admin.orders_read",
        "tiktok.shop.orders_read",
    }
    for plugin in PLUGINS:
        if plugin.manifest().webhooks.supported:
            assert plugin.webhook() is not None
            assert plugin.manifest().webhooks.verification_scheme in {"wc_hmac", "tiktok_hmac"}
        else:
            assert plugin.webhook() is None
            assert plugin.manifest().webhooks.verification_scheme is None


# ── SSRF, parametrized per base URL ────────────────────────────────────────

# Host-header / metadata / IP / loopback / private / scheme / port / userinfo
# / integer-hex-IP tricks that MUST be rejected fail-closed.
SSRF_BAD_VALUES = [
    "https://127.0.0.1",
    "127.0.0.1",
    "https://10.0.0.1",
    "10.0.0.1",
    "https://192.168.1.1",
    "https://169.254.169.254",
    "169.254.169.254",
    "https://[::1]",
    "::1",
    "https://0.0.0.0",
    "0.0.0.0",
    "https://localhost",
    "localhost",
    "http://synth-store.example.com",  # non-https scheme
    "https://synth-store.example.com:8443",  # explicit port
    "https://user@synth-store.example.com",  # userinfo
    "2130706433",  # integer IPv4 spelling
    "0x7f000001",  # hex IPv4 spelling
    "127.1",  # compact IPv4 spelling
]

# family -> (allowlist, values that must PASS the allowlist).
# woocommerce is the exception: tenant-supplied site_url with an EMPTY allowlist
# (public FQDN only) — the resolver-level check is a documented live-auth duty.
SSRF_CASES = [
    ("woocommerce", (), ["https://synth-store.example.com", "synth-store.example.com"]),
    ("etsy", ("openapi.etsy.com",), ["https://openapi.etsy.com/v3", "openapi.etsy.com"]),
    ("ebay", ("api.ebay.com",), ["https://api.ebay.com", "api.ebay.com"]),
    ("walmart", ("marketplace.walmartapis.com",), ["https://marketplace.walmartapis.com", "marketplace.walmartapis.com"]),
    ("tiktok", ("open-api.tiktokglobalshop.com",), ["https://open-api.tiktokglobalshop.com", "open-api.tiktokglobalshop.com"]),
    # Amazon: the REGIONAL SP-API allowlist — every region host is allowlisted,
    # and nothing else (the region config only picks between these entries).
    (
        "amazon",
        (
            "sellingpartnerapi-na.amazon.com",
            "sellingpartnerapi-eu.amazon.com",
            "sellingpartnerapi-fe.amazon.com",
        ),
        [
            "https://sellingpartnerapi-na.amazon.com",
            "sellingpartnerapi-na.amazon.com",
            "https://sellingpartnerapi-eu.amazon.com",
            "https://sellingpartnerapi-fe.amazon.com",
        ],
    ),
]


@pytest.mark.parametrize(
    "family,allowlist,good_values",
    SSRF_CASES,
    ids=[case[0] for case in SSRF_CASES],
)
def test_ssrf_rejects_host_tricks_per_base_url(family, allowlist, good_values):
    """Every bad host/spelling is rejected fail-closed; allowlisted bases pass."""
    for bad in SSRF_BAD_VALUES:
        assert validated_https_host(bad, allow_suffixes=allowlist) is None, (
            f"{family}: SSRF gate must reject {bad!r}"
        )
    for good in good_values:
        assert validated_https_host(good, allow_suffixes=allowlist) is not None, (
            f"{family}: allowlisted base {good!r} must pass"
        )


def _context(*, config: dict | None = None, credential: dict | None = None) -> AcquisitionContext:
    return AcquisitionContext.model_construct(
        tenant_id="tenant-synth-1",
        provider_identity="probe",
        config=config or {},
        credential=credential,
    )


def test_woocommerce_site_host_is_the_ssrf_chokepoint():
    """WooCommerce's tenant-supplied site_url resolves to the public FQDN or bails."""
    from services.providers.woocommerce.auth import _site_host

    good = _context(config={"site_url": "https://synth-store.example.com"})
    assert _site_host(good) == "synth-store.example.com"
    for bad in SSRF_BAD_VALUES:
        assert _site_host(_context(config={"site_url": bad})) == ""


@pytest.mark.parametrize(
    "family,expected_base",
    [
        ("etsy", "https://openapi.etsy.com/v3"),
        ("ebay", "https://api.ebay.com"),
        ("walmart", "https://marketplace.walmartapis.com"),
        ("tiktok", "https://open-api.tiktokglobalshop.com"),
    ],
    ids=["etsy", "ebay", "walmart", "tiktok"],
)
def test_fixed_host_families_never_take_tenant_input(family, expected_base):
    """The four fixed-host families resolve a FIXED base — tenant input is inert."""
    mods = {
        "etsy": "services.providers.etsy.auth",
        "ebay": "services.providers.ebay.auth",
        "walmart": "services.providers.walmart.auth",
        "tiktok": "services.providers.tiktok.auth",
    }
    import importlib

    auth = importlib.import_module(mods[family])
    # A hostile config value must NOT change the resolved base.
    ctx = _context(config={"region": "na", "site_url": "https://127.0.0.1"})
    assert auth._base_url(ctx) == expected_base
    assert validated_https_host(expected_base, allow_suffixes=auth.API_HOST_ALLOWLIST) is not None


def test_amazon_region_only_selects_between_allowlisted_hosts():
    """Amazon's region config picks between allowlisted regional hosts — never beyond."""
    from services.providers.amazon.auth import (
        API_HOST_ALLOWLIST,
        _REGION_TO_HOST,
        _base_url,
    )

    # Every documented region resolves to an allowlisted host.
    for region in _REGION_TO_HOST:
        ctx = _context(config={"region": region})
        base = _base_url(ctx)
        assert validated_https_host(base, allow_suffixes=API_HOST_ALLOWLIST) is not None, (
            f"region {region!r} must resolve inside the allowlist, got {base!r}"
        )
    # Unknown/hostile region values fall back to the allowlisted default.
    for hostile in ("127.0.0.1", "amazon.com.evil.example", "", "production"):
        base = _base_url(_context(config={"region": hostile}))
        assert base == "https://sellingpartnerapi-na.amazon.com", (
            f"hostile region {hostile!r} must fall back, got {base!r}"
        )
    # A hostile host in the allowlist position is still rejected by the gate.
    assert validated_https_host(
        "https://sellingpartnerapi-na.amazon.com.evil.example",
        allow_suffixes=API_HOST_ALLOWLIST,
    ) is None


# ── Fixture-replay determinism ─────────────────────────────────────────────

# family -> (plugin identity, payload, provider_record_id, expected event_type,
#            expected total Decimal as string)
DETERMINISM_CASES = [
    ("woocommerce.admin.orders_read", WOO_ORDER, "9000200001", "commerce.order.fulfilled", "102.98"),
    ("etsy.api.orders_read", ETSY_RECEIPT, "5001", "commerce.order.fulfilled", "12.5"),
    ("ebay.fulfillment.orders_read", EBAY_ORDER, "EB-SYNTH-1", "commerce.order.paid", "110.95"),
    ("walmart.marketplace.orders_read", WALMART_ORDER, "WMT-SYNTH-1", "commerce.order.fulfilled", "55.00"),
    ("tiktok.shop.orders_read", TIKTOK_ORDER, "TT-SYNTH-1", "commerce.order.fulfilled", "59.00"),
    ("amazon.merchant.orders_read", AMAZON_ORDER, "AMZ-SYNTH-1", "commerce.order.fulfilled", "49.99"),
]


@pytest.mark.parametrize(
    "provider_identity,payload,provider_record_id,event_type,total",
    DETERMINISM_CASES,
    ids=[case[0].split(".")[0] for case in DETERMINISM_CASES],
)
def test_normalizer_replay_determinism(
    provider_identity, payload, provider_record_id, event_type, total
):
    """Same raw record => byte-identical events with exact event_id + Money Decimal."""
    from services.providers.woocommerce.normalizer import WooCommerceOrderNormalizer
    from services.providers.etsy.normalizer import EtsyOrderNormalizer
    from services.providers.ebay.normalizer import EbayOrderNormalizer
    from services.providers.walmart.normalizer import WalmartOrderNormalizer
    from services.providers.tiktok.normalizer import TikTokOrderNormalizer
    from services.providers.amazon.normalizer import AmazonOrderNormalizer

    normalizers = {
        "woocommerce.admin.orders_read": WooCommerceOrderNormalizer(),
        "etsy.api.orders_read": EtsyOrderNormalizer(),
        "ebay.fulfillment.orders_read": EbayOrderNormalizer(),
        "walmart.marketplace.orders_read": WalmartOrderNormalizer(),
        "tiktok.shop.orders_read": TikTokOrderNormalizer(),
        "amazon.merchant.orders_read": AmazonOrderNormalizer(),
    }
    raw = _raw_for(provider_identity, f"raw-{provider_identity.split('.')[0]}-1", payload, provider_record_id)
    normalizer = normalizers[provider_identity]

    first = normalizer.normalize(raw)
    second = normalizer.normalize(raw)
    # Byte-identical replay (deterministic — no wall-clock / randomness).
    assert first.model_dump_json() == second.model_dump_json()

    assert first.dropped == []
    assert len(first.events) == 1
    event = first.events[0]
    # Deterministic event_id: "<record_id>:<event_type>".
    assert event.event_id == f"{raw.record_id}:{event_type}"
    assert event.event_type == event_type
    assert event.provider_identity == provider_identity
    assert event.data["status"].value == event_type.split(".")[-1]
    # Exact Money Decimal, never a binary float.
    assert event.data["total"]["amount"] == Decimal(total)
    assert event.data["total"]["currency"] == "USD"


def test_unmappable_status_is_a_visible_drop_never_silent():
    """An unmappable status is a visible drop for ALL six families (never silent)."""
    from services.providers.woocommerce.normalizer import WooCommerceOrderNormalizer
    from services.providers.etsy.normalizer import EtsyOrderNormalizer
    from services.providers.ebay.normalizer import EbayOrderNormalizer
    from services.providers.walmart.normalizer import WalmartOrderNormalizer
    from services.providers.tiktok.normalizer import TikTokOrderNormalizer
    from services.providers.amazon.normalizer import AmazonOrderNormalizer

    woo_bad = {**WOO_ORDER, "status": "synth-custom-state"}
    etsy_bad = {**ETSY_RECEIPT, "status": "synth-custom"}
    ebay_bad = {**EBAY_ORDER, "orderPaymentStatus": "SYNTH-CUSTOM"}
    wmt_bad = {**WALMART_ORDER, "orderStatus": "SYNTH-CUSTOM"}
    tt_bad = {**TIKTOK_ORDER, "order_status": "SYNTH-CUSTOM"}
    amz_bad = {**AMAZON_ORDER, "OrderStatus": "SYNTH-CUSTOM"}

    cases = [
        (WooCommerceOrderNormalizer(), woo_bad, "9000200005"),
        (EtsyOrderNormalizer(), etsy_bad, "5005"),
        (EbayOrderNormalizer(), ebay_bad, "EB-SYNTH-2"),
        (WalmartOrderNormalizer(), wmt_bad, "WMT-SYNTH-2"),
        (TikTokOrderNormalizer(), tt_bad, "TT-SYNTH-2"),
        (AmazonOrderNormalizer(), amz_bad, "AMZ-SYNTH-2"),
    ]
    for normalizer, payload, record_id in cases:
        raw = _raw_for(
            "probe", f"raw-drop-{record_id}", payload, record_id
        )
        result = normalizer.normalize(raw)
        assert result.events == []
        assert any("known_unsupported_behavior" in drop for drop in result.dropped)


# ── Webhook + signing determinism ──────────────────────────────────────────


def test_wc_hmac_webhook_verify_is_constant_time():
    """WooCommerce's claimed wc_hmac scheme verifies the raw-body HMAC."""
    from services.providers.woocommerce.webhook import WooCommerceWebhookAdapter

    secret = "synth-wc-secret"
    body = b'{"id": 9000200001, "status": "completed"}'
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    adapter = WooCommerceWebhookAdapter(provider_identity="woocommerce.admin.orders_read")
    assert adapter.verify(body, {"X-WC-Webhook-Signature": signature}, secret) is True
    assert adapter.verify(body, {"X-WC-Webhook-Signature": "sha256=deadbeef"}, secret) is False
    assert adapter.verify(body, {"X-WC-Webhook-Signature": signature}, None) is False
    assert adapter.verify(body, {}, secret) is False
    # parse emits exactly one webhook-sourced order record.
    records = adapter.parse(dict(WOO_ORDER), headers={})
    assert len(records) == 1
    assert records[0].provider_record_type == "order"
    assert records[0].acquisition_mode == "webhook"


def test_tiktok_hmac_webhook_verify_is_constant_time():
    """TikTok's claimed tiktok_hmac scheme verifies the raw-body HMAC."""
    from services.providers.tiktok.webhook import TikTokWebhookAdapter

    secret = "synth-tt-secret"
    body = b'{"data": {"order_id": "TT-SYNTH-1", "order_status": "COMPLETED"}}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    adapter = TikTokWebhookAdapter(provider_identity="tiktok.shop.orders_read")
    assert adapter.verify(body, {"X-Tiktok-Shop-Sign": signature}, secret) is True
    assert adapter.verify(body, {"X-Tiktok-Shop-Sign": "deadbeef"}, secret) is False
    assert adapter.verify(body, {"X-Tiktok-Shop-Sign": signature}, None) is False
    records = adapter.parse({"data": {"order_id": "TT-SYNTH-1", "order_status": "COMPLETED"}}, headers={})
    assert len(records) == 1
    assert records[0].provider_record_id == "TT-SYNTH-1"


def test_tiktok_request_signing_is_deterministic():
    """TikTok request signing is byte-identical for identical inputs."""
    from services.providers.tiktok.auth import sign_request

    params = {"shop_id": "S1", "path": "/order/search"}
    one = sign_request(app_secret="synth-secret", params=params, timestamp=1783468800, nonce="n1")
    two = sign_request(app_secret="synth-secret", params=params, timestamp=1783468800, nonce="n1")
    three = sign_request(app_secret="synth-secret", params=params, timestamp=1783468800, nonce="n2")
    assert one == two
    assert len(one) == 64  # hex HMAC-SHA256
    assert one != three  # the nonce is part of the signed material


# ── Pull adapter fetch / cursor-build / error classification ──────────────


class _FakeResponse:
    """Minimal httpx-like response for structural pull-adapter replay."""

    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json = json_body if json_body is not None else {}
        self.headers = headers or {}
        self.content = b"{}" if status_code == 200 else b""

    def json(self):
        return self._json


class _FakeClient:
    """Async httpx-like client: captures calls, returns a fixed response."""

    def __init__(self, response, *, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, headers=None, **kwargs):
        self.calls.append(("get", url, headers, kwargs))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response

    async def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append(("post", url, json, headers, kwargs))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


def _pull_context(*, config=None, credential=None) -> AcquisitionContext:
    """An AcquisitionContext carrying account/connection ids for pull adapters."""
    return AcquisitionContext.model_construct(
        tenant_id="tenant-synth-1",
        provider_identity="probe",
        connection_id="conn-synth-1",
        account_id="acct-synth-1",
        config=config or {},
        credential=credential,
    )


@pytest.mark.parametrize(
    "family,cursor,expected",
    [
        (
            "etsy",
            "update_ts:1783044000:offset:50",
            {"limit": "25", "offset": "50", "last_updated": "1783044000"},
        ),
        ("tiktok", "update_time:1783044000:token:TOK", {"page_size": 10, "page_token": "TOK", "update_time_ge": 1783044000}),
        (
            "ebay",
            "after:2026-08-01T10:00:00Z:token:CONT",
            {"limit": "200", "filter": "lastmodifieddate:[2026-08-01T10:00:00Z..]", "continuationToken": "CONT"},
        ),
        (
            "walmart",
            "createdStartDate:2026-08-01T10:00:00Z:cursor:NEXT",
            {"limit": "5", "createdStartDate": "2026-08-01T10:00:00Z", "nextCursor": "NEXT"},
        ),
        (
            "amazon",
            "created:2026-08-01T10:00:00Z:token:NEXT",
            {"MaxResultsPerPage": "100", "CreatedAfter": "2026-08-01T10:00:00Z", "NextToken": "NEXT"},
        ),
    ],
    ids=["etsy", "tiktok", "ebay", "walmart", "amazon"],
)
def test_pull_cursor_builds(family, cursor, expected):
    """Each family's cursor -> request mapping matches its documented scheme."""
    import importlib

    mod = importlib.import_module(f"services.providers.{family}.pull")
    if family == "etsy":
        built = mod._build_params(cursor, limit=25, shop_id="S1")
    elif family == "tiktok":
        built = mod._build_body(cursor, limit=10)
    elif family in ("ebay", "amazon"):
        built = mod._build_query(cursor)
    else:  # walmart
        built = mod._build_params(cursor, limit=5)
    assert built == expected


def test_composite_cursors_keep_the_incremental_window_mid_pagination():
    """ebay/walmart/amazon _next_cursor emit the COMPOSITE form keeping the window."""
    from services.providers.ebay.pull import _next_cursor as ebay_next
    from services.providers.walmart.pull import _next_cursor as walmart_next
    from services.providers.amazon.pull import _next_cursor as amazon_next

    iso = "2026-08-01T10:00:00Z"
    assert ebay_next({"continuationToken": "C1"}, window=iso) == f"after:{iso}:token:C1"
    assert ebay_next({"continuationToken": "C1"}, window=None) == "token:C1"
    assert walmart_next({"list": {"nextCursor": "C1", "elements": [WALMART_ORDER]}}, window=iso) == (
        f"createdStartDate:{iso}:cursor:C1"
    )
    assert amazon_next({"payload": {"NextToken": "N1", "Orders": [AMAZON_ORDER]}}, window=iso) == (
        f"created:{iso}:token:N1"
    )


def test_non_numeric_window_falls_back_never_raises():
    """G-1/G-2: etsy/tiktok _next_cursor degrade non-numeric windows, never raise."""
    from services.providers.etsy.pull import _next_cursor as etsy_next
    from services.providers.tiktok.pull import _next_cursor as tiktok_next

    orders_bad = [{"receipt_id": 1, "update_ts": "abc"}, {"receipt_id": 2, "update_ts": None}]
    # No parseable window value: falls back to the previous window, not a raise.
    assert etsy_next({"next_offset": None}, orders_bad, window="1783044000", offset=0) == "update_ts:1783044000"
    assert etsy_next({"next_offset": None}, orders_bad, window=None, offset=0) is None
    # A parseable max still advances the window.
    assert etsy_next({}, [{"update_ts": 10}, {"update_ts": 20}], window=None, offset=0) == "update_ts:20"

    tt_bad = [{"order_id": 1, "update_time": "abc"}]
    assert tiktok_next({"data": {}}, tt_bad, window="1783044000") == "update_time:1783044000"
    assert tiktok_next({"data": {}}, tt_bad, window=None) is None


@pytest.mark.asyncio
async def test_etsy_fetch_records_iso_occurred_at_and_composite_cursor(monkeypatch):
    """Etsy fetch replays a page: ISO occurred_at, next_offset paging, window kept."""
    from datetime import datetime, timezone

    import services.providers.etsy.pull as etsy_pull
    from services.providers.etsy.pull import EtsyPullAdapter

    client = _FakeClient(_FakeResponse(200, json_body={"results": [ETSY_RECEIPT], "next_offset": 50}))
    monkeypatch.setattr(etsy_pull, "_http_client", lambda: client)
    adapter = EtsyPullAdapter(provider_identity="etsy.api.orders_read")
    result = await adapter.fetch(
        _pull_context(credential={"shop_id": "S1", "client_id": "C1", "access_token": "TOK"}),
        cursor="update_ts:1783044000",
    )
    assert result.success is True
    records = result.data.records
    assert len(records) == 1
    assert records[0].provider_record_id == "5001"
    # G-10: provider_occurred_at is ISO-8601, never an epoch-seconds string.
    assert records[0].provider_occurred_at == datetime.fromtimestamp(1783044000, tz=timezone.utc).isoformat()
    # G-7-family: the composite cursor keeps the update_ts window mid-pagination.
    assert result.data.next_cursor == "update_ts:1783044000:offset:50"
    assert result.data.has_more is True


@pytest.mark.asyncio
async def test_tiktok_fetch_signs_exactly_the_transmitted_request(monkeypatch):
    """TikTok fetch transmits app_key/shop_id/path/timestamp/nonce so HMAC recomputes."""
    from urllib.parse import parse_qs, urlparse

    import services.providers.tiktok.pull as tiktok_pull
    from services.providers.tiktok.pull import TikTokPullAdapter

    client = _FakeClient(
        _FakeResponse(200, json_body={"data": {"orders": [TIKTOK_ORDER], "next_page_token": "TOK"}})
    )
    monkeypatch.setattr(tiktok_pull, "_http_client", lambda: client)
    adapter = TikTokPullAdapter(provider_identity="tiktok.shop.orders_read")
    result = await adapter.fetch(
        _pull_context(credential={"app_key": "AK", "app_secret": "SK", "shop_id": "S1"}),
        cursor="update_time:1783044000",
    )
    assert result.success is True
    records = result.data.records
    assert len(records) == 1
    assert records[0].provider_record_id == "TT-SYNTH-1"
    # G-11: provider_occurred_at is ISO-8601, never an epoch-seconds string.
    assert records[0].provider_occurred_at.startswith("2026-")
    # G-3: the signed material is transmitted — server can recompute the HMAC.
    assert client.calls[0][0] == "post"
    qs = parse_qs(urlparse(client.calls[0][1]).query)
    assert qs["app_key"] == ["AK"]
    assert qs["shop_id"] == ["S1"]
    assert qs["path"] == ["/order/search"]
    assert "timestamp" in qs and qs["timestamp"][0].isdigit()
    assert "nonce" in qs and qs["nonce"][0]  # a real per-request nonce, never a constant
    assert qs["sign"] and len(qs["sign"][0]) == 64
    # G-2: the composite cursor keeps the update_time window.
    assert result.data.next_cursor == "update_time:1783044000:token:TOK"


@pytest.mark.asyncio
async def test_amazon_fetch_records_and_composite_cursor(monkeypatch):
    """Amazon fetch replays a page: records enriched, composite cursor keeps window."""
    import services.providers.amazon.pull as amazon_pull
    from services.providers.amazon.pull import AmazonPullAdapter

    client = _FakeClient(
        _FakeResponse(200, json_body={"payload": {"Orders": [AMAZON_ORDER], "NextToken": "NEXT"}})
    )
    monkeypatch.setattr(amazon_pull, "_http_client", lambda: client)
    adapter = AmazonPullAdapter(provider_identity="amazon.merchant.orders_read")
    result = await adapter.fetch(
        _pull_context(config={"region": "na"}, credential={"access_token": "LWA-TOK"}),
        cursor="created:2026-08-01T10:00:00Z",
    )
    assert result.success is True
    records = result.data.records
    assert len(records) == 1
    assert records[0].provider_record_id == "AMZ-SYNTH-1"
    assert records[0].provider_occurred_at == "2026-08-02T11:00:00Z"
    # G-9: the composite cursor keeps the created window.
    assert result.data.next_cursor == "created:2026-08-01T10:00:00Z:token:NEXT"


ERROR_FAMILIES = [
    ("etsy", {"shop_id": "S1", "client_id": "C1", "access_token": "TOK"}, {}),
    ("tiktok", {"app_key": "AK", "app_secret": "SK", "shop_id": "S1"}, {}),
    ("amazon", {"access_token": "LWA-TOK"}, {"region": "na"}),
]


@pytest.mark.parametrize(
    "family,credential,config",
    ERROR_FAMILIES,
    ids=[case[0] for case in ERROR_FAMILIES],
)
@pytest.mark.asyncio
async def test_pull_error_classification(family, credential, config, monkeypatch):
    """HTTP 401/429/5xx/4xx and network failures classify to the documented status."""
    import importlib

    from shared.integration_contracts.results import AdapterStatus

    mod = importlib.import_module(f"services.providers.{family}.pull")
    adapter_cls_name = {
        "etsy": "EtsyPullAdapter",
        "tiktok": "TikTokPullAdapter",
        "amazon": "AmazonPullAdapter",
    }[family]
    adapter = getattr(mod, adapter_cls_name)(provider_identity=f"{family}.x.orders_read")

    ctx = _pull_context(config=config, credential=credential)

    async def classify(status, *, raise_exc=None):
        client = _FakeClient(_FakeResponse(status_code=status), raise_exc=raise_exc)
        monkeypatch.setattr(mod, "_http_client", lambda: client)
        return await adapter.fetch(ctx, cursor=None)

    result = await classify(401)
    assert result.status == AdapterStatus.UNAUTHORIZED and result.retryable is False
    result = await classify(429)
    assert result.status == AdapterStatus.RATE_LIMITED and result.retryable is True
    result = await classify(500)
    assert result.status == AdapterStatus.RETRYABLE_ERROR and result.retryable is True
    result = await classify(404)
    assert result.status == AdapterStatus.PERMANENT_ERROR and result.retryable is False
    result = await classify(200, raise_exc=TimeoutError("boom"))
    assert result.status == AdapterStatus.RETRYABLE_ERROR
    assert result.error_code == "connection_failed"


# ── Registry smoke ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "install_fn,identity_key,source",
    [
        ("install_woocommerce_providers", "woocommerce.admin.orders_read", "woocommerce"),
        ("install_etsy_providers", "etsy.api.orders_read", "etsy"),
        ("install_ebay_providers", "ebay.fulfillment.orders_read", "ebay"),
        ("install_walmart_providers", "walmart.marketplace.orders_read", "walmart"),
        ("install_tiktok_providers", "tiktok.shop.orders_read", "tiktok"),
        ("install_amazon_providers", "amazon.merchant.orders_read", "amazon"),
    ],
    ids=lambda value: value if isinstance(value, str) else value,
)
def test_install_family_providers_registers(install_fn, identity_key, source):
    """Each install_<family>_providers self-registration path installs its plugin."""
    import importlib

    from services.provider_runtime.registry import ProviderRegistry

    family = identity_key.split(".")[0]
    mod = importlib.import_module(f"services.providers.{family}")
    registry = ProviderRegistry(auto_install_legacy=False)
    getattr(mod, install_fn)(registry)
    assert identity_key in registry
    assert registry.sources()[identity_key] == source


def test_registry_load_all_installs_all_native_and_legacy():
    """load_all() installs the six native plugins + the legacy corpus.

    The six UPR follow-on providers (woocommerce, etsy, amazon, ebay, walmart,
    tiktok) are ``LOCAL_PLUGIN_MODULES`` entries and register on import; the
    legacy connector corpus installs through the legacy bridge.
    """
    from services.provider_runtime.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.load_all()
    keys = set(registry.sources())
    for native in (
        "shopify.admin.orders_read",
        "woocommerce.admin.orders_read",
        "etsy.api.orders_read",
        "amazon.merchant.orders_read",
        "ebay.fulfillment.orders_read",
        "walmart.marketplace.orders_read",
        "tiktok.shop.orders_read",
    ):
        assert native in keys, f"load_all() must register {native}"
    assert "legacy" in set(registry.sources().values())
