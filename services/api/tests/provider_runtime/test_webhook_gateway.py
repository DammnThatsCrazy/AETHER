"""Tests for the inbound provider webhook gateway.

Covers the full ingest contract: WebhookInbox best-effort after ownership
verification, signature verification, endpoint-ownership trust, metadata-only
denial records (never the unverified payload), and parse → raw store → normalize
→ bridge.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Mapping, Optional

import pytest
from pydantic import SecretStr

import repositories.repos as repos
from repositories.delivery_repos import WebhookInboxRepository
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from connectors.provider_runtime.connection import (
    ProviderConnection,
    ProviderConnectionRepository,
)
from connectors.provider_runtime.acquisition import (
    ProviderAccountRecord,
    ProviderAccountRepository,
)
from connectors.provider_runtime.errors import ProviderNotInstalled
from connectors.provider_runtime.raw_store import RawProviderRecordStore
from connectors.provider_runtime.webhook import WebhookGateway, _extract_webhook_secret
from shared.credentials.types import (
    ApiKeyCredential,
    ApiKeyWebhookSecretCredential,
)
from shared.integration_contracts.events import make_aether_event, make_raw_record
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import (
    Authentication,
    Availability,
    ManifestReadiness,
    ProviderManifest,
    Webhooks,
)
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification

IDENTITY = "shopify.orders.catalog"
SHOPIFY_IDENTITY = "shopify.admin.orders_read"


# ── Protocol-conforming fakes ───────────────────────────────────────────────


class FakeRegistry:
    def __init__(self, plugins: dict[str, Any]) -> None:
        self._plugins = dict(plugins)

    def get(self, identity_key: str) -> Any:
        return self._plugins.get(identity_key)


class FakeBroker:
    def __init__(self, credential: Any = None) -> None:
        self.credential = credential

    async def reveal(self, tenant_id: str, ref: str) -> Any:
        return self.credential


class RefBroker:
    def __init__(self, secrets: dict[str, str]) -> None:
        self.secrets = secrets
        self.revealed: list[str] = []

    async def reveal(self, tenant_id: str, ref: str) -> Any:
        self.revealed.append(ref)
        return {"webhook_secret": self.secrets[ref]}


class FakeRawStore:
    def __init__(self) -> None:
        self.records: list[Any] = []

    async def ingest(self, records, *, tenant_id=None) -> list[tuple[Any, bool]]:
        for record in records:
            self.records.append(record)
        return [(record, True) for record in records]

    async def count(self, *, tenant_id, provider_identity, provider_record_type=None) -> int:
        return sum(
            1
            for r in self.records
            if r.tenant_id == tenant_id
            and r.provider_identity == provider_identity
            and (provider_record_type is None or r.provider_record_type == provider_record_type)
        )


class FakeBridge:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def ingest_events(self, tenant_id: str, events) -> int:
        self.events.extend(events)
        return len(events)


class FakeNormalizer:
    def normalize(self, record):
        return NormalizationResult(
            events=[
                make_aether_event(
                    provider_identity=record.provider_identity,
                    event_type="commerce.order.created",
                    event_family="commerce",
                    tenant_id=record.tenant_id,
                    source_record_id=record.record_id,
                    data={"record_id": record.provider_record_id},
                )
            ],
            skipped=0,
            dropped=[],
            normalizer_version="1",
        )


class FakeWebhookAdapter:
    def __init__(self, *, verify_result: bool = True, records: Optional[list[Any]] = None) -> None:
        self._verify_result = verify_result
        self._records = list(records or [])
        self.verify_calls: list[tuple[bytes, Mapping[str, str], Optional[str]]] = []
        self.parse_calls: list[tuple[dict[str, Any], Mapping[str, str] | None]] = []

    def verify(self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]) -> bool:
        self.verify_calls.append((raw_body, headers, secret))
        return self._verify_result

    def parse(self, payload: dict[str, Any], headers: Mapping[str, str] | None = None) -> list[Any]:
        self.parse_calls.append((payload, headers))
        return list(self._records)


class FakePlugin:
    def __init__(
        self,
        *,
        manifest: Any,
        webhook: Any = None,
        normalizer: Any = None,
    ) -> None:
        self._manifest = manifest
        self._webhook = webhook
        self._normalizer = normalizer

    def manifest(self) -> Any:
        return self._manifest

    def webhook(self) -> Any:
        return self._webhook

    def normalizer(self) -> Any:
        return self._normalizer


# ── Builders ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def make_manifest(
    *,
    verification_scheme: Optional[str] = None,
    streams: Optional[list[StreamDescriptor]] = None,
) -> ProviderManifest:
    return ProviderManifest(
        provider_family="shopify",
        product_id="orders",
        capability_id="catalog",
        display_name="Shopify Orders",
        category="commerce",
        readiness=ManifestReadiness(state="sandbox_validated", level=3),
        availability=Availability(),
        authentication=Authentication(type="api_key"),
        webhooks=Webhooks(supported=True, verification_scheme=verification_scheme),
        streams=streams or [],
        data_outputs=["commerce.order.created"],
        product_destinations=["silver"],
    )


def make_connection(
    *,
    tenant_id: str = "tenant-1",
    credential_ref: str = "provider:tenant-1:shopify.orders.catalog",
) -> ProviderConnection:
    return ProviderConnection(
        connection_id="conn_1",
        tenant_id=tenant_id,
        provider_identity=IDENTITY,
        state=ConnectionState.CONNECTED,
        credential_ref=credential_ref,
        selected_accounts=["acc_1"],
        config={"shop": "myshop.myshopify.com"},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def make_record(
    *,
    record_id: str,
    provider_record_type: str = "order",
    stream_id: Optional[str] = None,
) -> Any:
    return make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id=record_id,
        provider_record_type=provider_record_type,
        payload={"id": record_id},
        tenant_id="tenant-1",
        connection_id="conn_1",
        account_id="acc_1",
        acquisition_mode="webhook",
        stream_id=stream_id,
    )


def make_stream_descriptor(
    *,
    stream_id: str = "orders",
    acquisition_modes: tuple[str, ...] = ("webhook",),
    activation_config_field: str | None = None,
    activation_config_value: str | None = None,
) -> StreamDescriptor:
    supports_webhook = "webhook" in acquisition_modes
    supports_pull = "pull" in acquisition_modes
    return StreamDescriptor(
        stream_id=stream_id,
        object_kind="order",
        domain_pack="commerce",
        acquisition_modes=acquisition_modes,
        output_contract="bronze.provider_events",
        source_authority_class="commerce.order",
        data_classification=DataClassification.SENSITIVE_PII,
        cursor_scheme="updated_at" if supports_pull else None,
        webhook_topics=("orders/create",) if supports_webhook else (),
        initial_backfill=supports_pull,
        incremental=supports_pull,
        activation_config_field=activation_config_field,
        activation_config_value=activation_config_value,
    )


async def _persist_connection(connections: ProviderConnectionRepository) -> ProviderConnection:
    connection = make_connection()
    await connections.upsert(connection)
    return connection


def _gateway(
    *,
    plugin: Any,
    identity_key: str = IDENTITY,
    raw_store: Any = None,
    bridge: Any = None,
    broker: Any = None,
    connections: Any = None,
    accounts: Any = None,
    registry: Any = None,
) -> WebhookGateway:
    return WebhookGateway(
        registry=registry if registry is not None else FakeRegistry({identity_key: plugin}),
        raw_store=raw_store or FakeRawStore(),
        bridge=bridge or FakeBridge(),
        broker=broker or FakeBroker(),
        connections=connections or ProviderConnectionRepository(),
        accounts=accounts or ProviderAccountRepository(),
    )


def _shopify_plugin() -> FakePlugin:
    from connectors.providers.shopify.plugin import ShopifyOrdersPlugin

    plugin = ShopifyOrdersPlugin()
    return FakePlugin(
        manifest=plugin.manifest(),
        webhook=plugin.webhook(),
        normalizer=FakeNormalizer(),
    )


def _shopify_connection(
    connection_id: str, domain: str, *, mode: str = "rest_webhook", selected: bool = True
) -> ProviderConnection:
    account_id = f"shop:{domain}"
    return ProviderConnection(
        connection_id=connection_id,
        tenant_id="tenant-1",
        provider_identity=SHOPIFY_IDENTITY,
        state=ConnectionState.CONNECTED,
        credential_ref=f"credential:{connection_id}",
        selected_accounts=[account_id] if selected else [],
        config={"shop_domain": domain, "orders_api": mode},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


async def _persist_shopify_account(
    accounts: ProviderAccountRepository, connection: ProviderConnection, domain: str
) -> None:
    account_id = f"shop:{domain}"
    await accounts.upsert(
        ProviderAccountRecord(
            account_id=f"{connection.connection_id}:{account_id}",
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            provider_identity=connection.provider_identity,
            display_name=domain,
            external_id="gid://shopify/Shop/123",
            metadata={"shop_domain": domain},
        )
    )


def _shopify_delivery_body(
    domain: str, *, order_id: int = 9001, updated_at: str = "2026-10-03T10:00:00Z"
) -> bytes:
    return json.dumps(
        {
            "id": 7001,
            "domain": domain,
            "topic": "orders/update",
            "body": {
                "id": order_id,
                "updated_at": updated_at,
                "created_at": "2026-10-01T10:00:00Z",
                "currency": "USD",
                "total_price": "25.00",
                "line_items": [],
            },
        },
        separators=(",", ":"),
    ).encode()


def _shopify_headers(
    raw_body: bytes, secret: str, *, delivery_id: str, domain: str
) -> dict[str, str]:
    signature = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()
    return {
        "X-Shopify-Hmac-SHA256": signature,
        "X-Shopify-Webhook-Id": delivery_id,
        "X-Shopify-Shop-Domain": domain,
        "X-Shopify-Topic": "orders/update",
    }


# ── Signature-verified success ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_success_signature_verified():
    secret_cred = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("sk_live_abc"),
        webhook_secret=SecretStr("whsec_123"),
    )
    webhook = FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)

    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        bridge=bridge,
        broker=FakeBroker(credential=secret_cred),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={"x-shopify-hmac-sha256": "abc"},
        signature="sig123",
        tenant_id="tenant-1",
    )

    assert result["accepted"] is True
    assert result["verified"] is True
    assert result["record_count"] == 1
    assert result["event_count"] == 1
    # verify() received the revealed plaintext webhook secret
    assert webhook.verify_calls[0][2] == "whsec_123"
    # raw store got the record, bridge got the normalized event
    assert await raw_store.count(tenant_id="tenant-1", provider_identity=IDENTITY) == 1
    assert len(bridge.events) == 1
    # A verified delivery is retained and marked processed on success.
    rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"},
        limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["processed"] is True
    assert rows[0]["verified"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "identity", "adapter", "payload", "expected_namespace"),
    [
        (
            "shopify", "shopify.admin.orders_read",
            "connectors.providers.shopify.webhook.ShopifyWebhookAdapter",
            {"id": 81, "customer": {"id": 7001, "email": "buyer@example.com", "phone": "+14155550101"}},
            "shopify:shop:evidence.myshopify.com:conn_1",
        ),
        (
            "woocommerce", "woocommerce.admin.orders_read",
            "connectors.providers.woocommerce.webhook.WooCommerceWebhookAdapter",
            {"id": 82, "customer_id": 7002, "billing": {"email": "buyer@example.com", "phone": "+14155550101"}},
            "woocommerce:acc_1:conn_1",
        ),
    ],
)
async def test_real_provider_webhook_parse_captures_only_durable_hashed_identity_evidence(
    provider, identity, adapter, payload, expected_namespace,
):
    import hashlib
    import hmac
    import json
    from importlib import import_module

    from identity.identity.hashing import hash_value
    from identity.identity.repository import IdentityResolutionRepository
    from identity.identity.source_identity_registry import SourceIdentityRegistry

    adapter_cls = getattr(import_module(adapter.rsplit(".", 1)[0]), adapter.rsplit(".", 1)[1])
    webhook = adapter_cls(provider_identity=identity)

    class DedupeRawStore(FakeRawStore):
        """Mirror Bronze: duplicate keys return the retained raw payload."""

        def __init__(self):
            super().__init__()
            self._by_key = {}

        async def ingest(self, records, *, tenant_id=None):
            outcomes = []
            for record in records:
                key = (tenant_id or record.tenant_id, record.provider_identity,
                       record.provider_record_id, record.schema_version)
                if key in self._by_key:
                    outcomes.append((self._by_key[key], False))
                else:
                    self._by_key[key] = record
                    self.records.append(record)
                    outcomes.append((record, True))
            return outcomes

    raw_store = DedupeRawStore()
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    domain = "evidence.myshopify.com"
    if provider == "shopify":
        connection = _shopify_connection("conn_1", domain)
        await _persist_shopify_account(accounts, connection, domain)
        webhook_payload = {
            "id": 7001,
            "domain": domain,
            "topic": "orders/update",
            "body": payload,
        }
    else:
        connection = ProviderConnection(
            connection_id="conn_1", tenant_id="tenant-1", provider_identity=identity,
            state=ConnectionState.CONNECTED, credential_ref="provider:tenant-1:test",
            selected_accounts=["acc_1"], created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        webhook_payload = payload
    await connections.upsert(connection)
    secret = "webhook-secret"
    if provider == "shopify":
        body = json.dumps(webhook_payload).encode()
        headers = _shopify_headers(
            body, secret, delivery_id="evidence-delivery-1", domain=domain,
        )
        signature = headers["X-Shopify-Hmac-SHA256"]
    else:
        body = json.dumps(webhook_payload).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers = {"X-WC-Webhook-Signature": signature}
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="signature"),
        webhook=webhook,
        normalizer=FakeNormalizer(),
    )
    gateway = _gateway(
        plugin=plugin, raw_store=raw_store,
        broker=FakeBroker(credential={"webhook_secret": SecretStr(secret)}),
        connections=connections, accounts=accounts, registry=FakeRegistry({identity: plugin}),
    )

    result = await gateway.ingest(
        identity, raw_body=body, headers=headers, signature=signature, tenant_id="tenant-1",
    )
    assert result["accepted"] is True, result
    assert len(raw_store.records) == 1
    stored_raw = raw_store.records[0]
    expected_account_id = f"shop:{domain}" if provider == "shopify" else "acc_1"
    assert (stored_raw.tenant_id, stored_raw.connection_id, stored_raw.account_id) == (
        "tenant-1", "conn_1", expected_account_id,
    )

    source = await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        "tenant-1", expected_namespace, external_id="7001" if provider == "shopify" else "7002",
    )
    assert source is not None
    assert source.external_id in {"7001", "7002"}
    assert source.status == "unresolved"
    claims = await IdentityResolutionRepository().get_claims_for_source(source.id)
    by_type = {claim["claim_type"]: claim for claim in claims}
    assert by_type["email"]["normalized_value"] == hash_value(
        "buyer@example.com", scope="email:tenant-1",
    )
    assert by_type["phone"]["normalized_value"] == hash_value(
        "+14155550101", scope="phone:tenant-1",
    )
    assert by_type["email"]["raw_value"] is None
    assert by_type["phone"]["raw_value"] is None
    assert "buyer@example.com" not in repr(claims)
    assert "+14155550101" not in repr(claims)
    from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter

    candidate = await ImportIdentityCandidateAdapter(IdentityResolutionRepository()).evaluate(
        tenant_id="tenant-1", claims={"email": "buyer@example.com", "phone": "+14155550101"},
    )
    assert candidate.outcome == "candidate"
    assert candidate.candidate_source_identity_ids == [source.id]

    # A duplicate key with a conflicting payload is ignored by Bronze. The
    # incoming data must not alter claims when it was not the persisted row.
    conflicting_payload = json.loads(json.dumps(payload))
    if provider != "shopify":
        conflicting_payload["billing"]["email"] = "changed@example.com"
    conflicting_webhook_payload = (
        {
            "id": 7001,
            "domain": domain,
            "topic": "orders/update",
            "body": conflicting_payload,
        }
        if provider == "shopify"
        else conflicting_payload
    )
    conflicting_body = json.dumps(conflicting_webhook_payload).encode()
    if provider == "shopify":
        conflicting_headers = _shopify_headers(
            conflicting_body,
            secret,
            delivery_id="evidence-delivery-1",
            domain=domain,
        )
        conflicting_signature = conflicting_headers["X-Shopify-Hmac-SHA256"]
    else:
        conflicting_signature = "sha256=" + hmac.new(
            secret.encode(), conflicting_body, hashlib.sha256,
        ).hexdigest()
        conflicting_headers = {"X-WC-Webhook-Signature": conflicting_signature}
    await gateway.ingest(
        identity, raw_body=conflicting_body,
        headers=conflicting_headers,
        signature=conflicting_signature, tenant_id="tenant-1",
    )
    replay_claims = await IdentityResolutionRepository().get_claims_for_source(source.id)
    assert len(replay_claims) == 3
    assert by_type["email"]["normalized_value"] == hash_value(
        "buyer@example.com", scope="email:tenant-1",
    )
    assert "changed@example.com" not in repr(replay_claims)
    assert len(raw_store.records) == 1

    # An unaccepted/failed raw-store result is not evidence of durable receipt.
    from identity.identity.provider_evidence import capture_durable_provider_customer_evidence
    from shared.integration_contracts.events import make_raw_record

    unaccepted = make_raw_record(
        provider_identity=identity, provider_record_id="unaccepted-order",
        provider_record_type="order", payload=payload, tenant_id="tenant-1",
    )
    assert await capture_durable_provider_customer_evidence(
        [unaccepted], [], tenant_id="tenant-1", connection_id="conn_1", account_id="acc_1",
        lifecycle_type="provider_webhook_inbox", lifecycle_id="inbox-unaccepted",
    ) == 0


# ── Verification failure → auditable metadata-only denial ──────────────────
@pytest.mark.asyncio
async def test_quarantined_bronze_record_is_not_normalized_bridged_or_acknowledged(
    monkeypatch,
):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)

    class CountingNormalizer(FakeNormalizer):
        def __init__(self):
            self.calls = 0

        def normalize(self, record):
            self.calls += 1
            return super().normalize(record)

    normalizer = CountingNormalizer()
    webhook = FakeWebhookAdapter(
        verify_result=True,
        records=[make_record(record_id="quarantined-order")],
    )
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=normalizer)
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=RawProviderRecordStore(),
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"quarantined-order"}',
        headers={"x-shopify-hmac-sha256": "verified"},
        signature="sig123",
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == "raw_persist_failed"
    assert normalizer.calls == 0
    assert bridge.events == []
    inbox_rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"}, limit=10
    )
    # The rights gate denied raw storage, so this delivery body is not retained.
    assert inbox_rows == []
    bronze_rows = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-1", "source": IDENTITY}, limit=10
    )
    assert bronze_rows == []


# ── Verification failure → tenantless denial telemetry ────────────────────


@pytest.mark.asyncio
async def test_ingest_verification_failure_does_not_write_tenant_denial():
    webhook = FakeWebhookAdapter(verify_result=False, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    connection = make_connection().model_copy(update={"tenant_id": "tenant-victim"})
    await connections.upsert(connection)

    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={},
        signature="bad",
        tenant_id="tenant-victim",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert result["inbox_id"] is None
    # The supplied tenant hint is not authority to create a tenant Bronze row.
    assert raw_store.records == []
    assert len(bridge.events) == 0
    # Failed verification does not persist a raw-body inbox row.
    rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-victim"},
        limit=10,
    )
    assert rows == []


@pytest.mark.asyncio
async def test_declared_webhook_stream_accepts_matching_record_stream():
    webhook = FakeWebhookAdapter(
        verify_result=True,
        records=[make_record(record_id="o1", stream_id="orders")],
    )
    plugin = FakePlugin(
        manifest=make_manifest(streams=[make_stream_descriptor()]),
        webhook=webhook,
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"o1"}',
        headers={},
        tenant_id="tenant-1",
    )

    assert result["accepted"] is True
    assert raw_store.records[0].provider_record_type == "order"
    assert raw_store.records[0].stream_id == "orders"


@pytest.mark.parametrize(
    ("stream_id", "declared_stream_id", "acquisition_modes", "expected_error"),
    [
        (None, "orders", ("webhook",), "provider_stream_id_missing"),
        ("customers", "orders", ("webhook",), "provider_stream_not_found"),
        ("orders_pull", "orders_pull", ("pull",), "provider_stream_not_webhook"),
    ],
)
@pytest.mark.asyncio
async def test_declared_stream_mismatch_is_denied_before_raw_record_persistence(
    stream_id: Optional[str],
    declared_stream_id: str,
    acquisition_modes: tuple[str, ...],
    expected_error: str,
):
    webhook = FakeWebhookAdapter(
        verify_result=True,
        records=[make_record(record_id="o1", stream_id=stream_id)],
    )
    plugin = FakePlugin(
        manifest=make_manifest(
            streams=[
                make_stream_descriptor(
                    stream_id=declared_stream_id,
                    acquisition_modes=acquisition_modes,
                )
            ]
        ),
        webhook=webhook,
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"o1"}',
        headers={},
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == result["error_code"] == expected_error
    assert webhook.parse_calls
    # The only raw record is the typed metadata-only denial. The adapter's
    # provider record never reaches the raw store or normalizer.
    assert len(raw_store.records) == 1
    denial = raw_store.records[0]
    assert denial.provider_record_type == "webhook_denial"
    assert denial.payload == {}
    assert denial.metadata["error_code"] == expected_error
    assert bridge.events == []
    inbox_rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"},
        limit=10,
    )
    assert inbox_rows == []


@pytest.mark.asyncio
async def test_shopify_domain_routes_to_exact_persisted_connection_with_two_connections():
    domain_a = "shop-a.myshopify.com"
    domain_b = "shop-b.myshopify.com"
    connection_a = _shopify_connection("conn_shop_a", domain_a)
    connection_b = _shopify_connection("conn_shop_b", domain_b)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection_a)
    await connections.upsert(connection_b)
    await _persist_shopify_account(accounts, connection_a, domain_a)
    await _persist_shopify_account(accounts, connection_b, domain_b)
    raw_store = FakeRawStore()
    broker = RefBroker(
        {
            connection_a.credential_ref: "secret-a",
            connection_b.credential_ref: "secret-b",
        }
    )
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain_a)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-a", delivery_id="delivery-a", domain=domain_a),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is True
    assert broker.revealed == [connection_a.credential_ref]
    assert len(raw_store.records) == 1
    assert (
        raw_store.records[0].connection_id,
        raw_store.records[0].account_id,
        raw_store.records[0].metadata["shopify_shop_domain"],
    ) == (connection_a.connection_id, f"shop:{domain_a}", domain_a)


@pytest.mark.asyncio
async def test_shopify_valid_hmac_for_wrong_domain_is_rejected():
    domain_a = "shop-a.myshopify.com"
    domain_b = "shop-b.myshopify.com"
    connection_a = _shopify_connection("conn_shop_a", domain_a)
    connection_b = _shopify_connection("conn_shop_b", domain_b)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection_a)
    await connections.upsert(connection_b)
    await _persist_shopify_account(accounts, connection_a, domain_a)
    await _persist_shopify_account(accounts, connection_b, domain_b)
    raw_store = FakeRawStore()
    broker = RefBroker(
        {
            connection_a.credential_ref: "secret-a",
            connection_b.credential_ref: "secret-b",
        }
    )
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain_b)
    headers = _shopify_headers(body, "secret-a", delivery_id="delivery-bad", domain=domain_b)
    from connectors.providers.shopify.webhook import ShopifyWebhookAdapter

    assert ShopifyWebhookAdapter(provider_identity=SHOPIFY_IDENTITY).verify(
        body, headers, "secret-a"
    )

    result = await gateway.ingest(
        SHOPIFY_IDENTITY, raw_body=body, headers=headers, tenant_id="tenant-1"
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == [connection_b.credential_ref]
    assert raw_store.records == []
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"}) == []


@pytest.mark.asyncio
async def test_shopify_bad_candidate_domain_does_not_write_to_caller_selected_tenant():
    domain = "shop-a.myshopify.com"
    connection = _shopify_connection("conn_shop_a", domain)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker({connection.credential_ref: "secret-a"})
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body("shop-attacker.example")

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(
            body, "secret-a", delivery_id="delivery-bad-domain", domain="shop-attacker.example"
        ),
        tenant_id="tenant-victim",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_shopify_invalid_json_does_not_write_to_caller_selected_tenant():
    raw_store = FakeRawStore()
    broker = RefBroker({})
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=ProviderConnectionRepository(),
        accounts=ProviderAccountRepository(),
    )

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=b"{malformed-json",
        headers={},
        tenant_id="tenant-victim",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-victim"}) == []


@pytest.mark.asyncio
async def test_shopify_unmatched_account_does_not_write_to_caller_selected_tenant():
    persisted_domain = "shop-a.myshopify.com"
    body_domain = "shop-b.myshopify.com"
    connection = _shopify_connection("conn_shop_a", persisted_domain)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, persisted_domain)
    broker = RefBroker({connection.credential_ref: "secret-a"})
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(body_domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-a", delivery_id="no-account", domain=body_domain),
        tenant_id="tenant-victim",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_shopify_duplicate_persisted_domain_is_rejected_as_ambiguous():
    domain = "shop-a.myshopify.com"
    connection_a = _shopify_connection("conn_shop_a", domain)
    connection_b = _shopify_connection("conn_shop_b", domain)
    connection_a = connection_a.model_copy(update={"tenant_id": "tenant-victim"})
    connection_b = connection_b.model_copy(update={"tenant_id": "tenant-victim"})
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    for connection in (connection_a, connection_b):
        await connections.upsert(connection)
        await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker(
        {
            connection_a.credential_ref: "secret-a",
            connection_b.credential_ref: "secret-b",
        }
    )
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-a", delivery_id="ambiguous", domain=domain),
        tenant_id="tenant-victim",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_shopify_unselected_persisted_account_is_rejected():
    domain = "shop-a.myshopify.com"
    connection = _shopify_connection("conn_shop_a", domain, selected=False)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker({connection.credential_ref: "secret-a"})
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-a", delivery_id="unselected", domain=domain),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_shopify_poll_only_mode_denies_before_secret_or_inbox():
    domain = "shop-a.myshopify.com"
    connection = _shopify_connection("conn_shop_a", domain, mode="rest")
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker({connection.credential_ref: "secret-a"})
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-a", delivery_id="poll-only", domain=domain),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == result["error_code"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"}) == []


@pytest.mark.asyncio
async def test_shopify_missing_delivery_id_header_fails_closed_before_inbox_or_raw_order():
    domain = "shop-a.myshopify.com"
    connection = _shopify_connection("conn_shop_a", domain)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    raw_store = FakeRawStore()
    secret = "secret-a"
    broker = RefBroker({connection.credential_ref: secret})
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)
    headers = _shopify_headers(body, secret, delivery_id="to-be-removed", domain=domain)
    del headers["X-Shopify-Webhook-Id"]

    result = await gateway.ingest(
        SHOPIFY_IDENTITY, raw_body=body, headers=headers, tenant_id="tenant-1"
    )

    assert result["accepted"] is False
    assert result["reason"] == "parse_failed"
    assert broker.revealed == [connection.credential_ref]
    assert len(raw_store.records) == 1
    assert raw_store.records[0].provider_record_type == "webhook_denial"
    assert raw_store.records[0].payload == {}
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"}) == []


@pytest.mark.asyncio
async def test_webhook_stream_activation_config_is_enforced_before_raw_persistence():
    webhook = FakeWebhookAdapter(records=[make_record(record_id="o1", stream_id="orders")])
    plugin = FakePlugin(
        manifest=make_manifest(
            streams=[
                make_stream_descriptor(
                    activation_config_field="orders_api",
                    activation_config_value="rest_webhook",
                )
            ]
        ),
        webhook=webhook,
        normalizer=FakeNormalizer(),
    )
    connections = ProviderConnectionRepository()
    connection = make_connection().model_copy(update={"config": {"orders_api": "rest"}})
    await connections.upsert(connection)
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id":"o1"}', headers={}, tenant_id="tenant-1"
    )

    assert result["accepted"] is False
    assert result["reason"] == result["error_code"] == "provider_stream_inactive"
    assert len(raw_store.records) == 1
    assert raw_store.records[0].provider_record_type == "webhook_denial"
    assert webhook.parse_calls


@pytest.mark.asyncio
async def test_webhook_parser_exception_does_not_log_or_return_exception_text(caplog):
    canary = "parser-secret-canary"

    class RaisingWebhook(FakeWebhookAdapter):
        def parse(self, payload, headers=None):
            raise RuntimeError(canary)

    plugin = FakePlugin(
        manifest=make_manifest(), webhook=RaisingWebhook(), normalizer=FakeNormalizer()
    )
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id":"o1"}', headers={}, tenant_id="tenant-1"
    )

    assert result["accepted"] is False
    assert result["reason"] == "parse_failed"
    assert canary not in caplog.text
    assert canary not in result["detail"]
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"}) == []


# ── Endpoint-ownership trust (endpoint_secret scheme) ──────────────────────


@pytest.mark.asyncio
async def test_ingest_endpoint_secret_scheme_verifies_via_endpoint_token():
    """endpoint_secret scheme: a caller-presented token constant-time-matching the
    connection's secret proves ownership; no signature is ever demanded."""
    webhook = FakeWebhookAdapter(verify_result=False, records=[make_record(record_id="o1")])
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="endpoint_secret"),
        webhook=webhook,
        normalizer=FakeNormalizer(),
    )
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"),
                webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={"X-Aether-Webhook-Endpoint-Token": "ep_12345"},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is True
    assert result["verified"] is True
    assert webhook.verify_calls == []  # endpoint-ownership, not signature
    assert result["detail"] == "verified via per-connection endpoint token"


@pytest.mark.asyncio
async def test_ingest_endpoint_secret_scheme_wrong_token_does_not_write_denial():
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="endpoint_secret"),
        webhook=FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")]),
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"),
                webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={"X-Aether-Webhook-Endpoint-Token": "wrong_token"},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert raw_store.records == []
    assert (
        await WebhookInboxRepository().find_many(
            filters={"tenant_id": "tenant-1"},
            limit=10,
        )
        == []
    )


@pytest.mark.asyncio
async def test_ingest_endpoint_secret_scheme_missing_token_denied():
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="endpoint_secret"),
        webhook=FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")]),
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"),
                webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert "detail" not in result
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_ingest_no_secret_configured_does_not_write_tenant_denial():
    """A signature scheme with no configured secret is denied, never trusted."""
    webhook = FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(credential=None),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert "detail" not in result
    assert raw_store.records == []


# ── Resolver / payload / capability failures ────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_missing_plugin_raises():
    gateway = _gateway(plugin=None, registry=FakeRegistry({}))
    with pytest.raises(ProviderNotInstalled):
        await gateway.ingest(
            IDENTITY,
            raw_body=b"{}",
            headers={},
            tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_ingest_missing_connection_uses_generic_public_rejection():
    plugin = FakePlugin(manifest=make_manifest(), webhook=FakeWebhookAdapter())
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        connections=ProviderConnectionRepository(),
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b"{}",
        headers={},
        tenant_id="tenant-victim",
    )
    assert result["reason"] == result["error_code"] == "webhook_rejected"
    assert result["inbox_id"] is None
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_ingest_cross_tenant_hint_does_not_resolve_connection():
    """The X-Aether-Tenant-ID hint is routing only. A connection stored under
    tenant-1 is never resolved for a tenant-2 hint — tenant isolation holds even
    though the public webhook route is unauthenticated by API key."""
    plugin = FakePlugin(
        manifest=make_manifest(),
        webhook=FakeWebhookAdapter(),
        normalizer=FakeNormalizer(),
    )
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)  # stored under tenant-1
    raw_store = FakeRawStore()
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={},
        tenant_id="tenant-2",
    )
    assert result["reason"] == result["error_code"] == "webhook_rejected"
    assert result["inbox_id"] is None
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_ingest_invalid_json_leaves_denial():
    """Passes verification first, then a malformed body is denied as invalid_payload."""
    plugin = FakePlugin(
        manifest=make_manifest(), webhook=FakeWebhookAdapter(), normalizer=FakeNormalizer()
    )
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b"not json at all",
        headers={},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "invalid_payload"
    assert raw_store.records[0].provider_record_type == "webhook_denial"


@pytest.mark.asyncio
async def test_ingest_provider_without_webhook_capability_does_not_write_denial():
    plugin = FakePlugin(manifest=make_manifest(), webhook=None, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(plugin=plugin, raw_store=raw_store, connections=connections)
    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id": "o1"}',
        headers={},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "webhook_rejected"
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_shopify_graphql_mode_denies_webhook_before_inbox_or_hmac():
    domain = "shop-graphql.myshopify.com"
    connection = _shopify_connection("conn_shop_graphql", domain, mode="graphql")
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker({connection.credential_ref: "secret-graphql"})
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        bridge=bridge,
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-graphql", delivery_id="graphql", domain=domain),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == result["error_code"] == "webhook_rejected"
    assert result["inbox_id"] is None
    assert broker.revealed == []
    assert raw_store.records == []
    assert bridge.events == []
    rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"},
        limit=10,
    )
    assert rows == []  # no unauthenticated body is retained for a poll-only mode


@pytest.mark.asyncio
async def test_shopify_rest_poll_mode_is_webhook_disabled_before_hmac():
    domain = "shop-rest.myshopify.com"
    connection = _shopify_connection("conn_shop_rest", domain, mode="rest")
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    broker = RefBroker({connection.credential_ref: "secret-rest"})
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        bridge=FakeBridge(),
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-rest", delivery_id="rest-poll", domain=domain),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == result["error_code"] == "webhook_rejected"
    assert broker.revealed == []
    assert raw_store.records == []
    assert await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"}) == []


@pytest.mark.asyncio
async def test_shopify_rest_webhook_mode_reaches_hmac_and_parser():
    domain = "shop-hook.myshopify.com"
    connection = _shopify_connection("conn_shop_hook", domain)
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    await connections.upsert(connection)
    await _persist_shopify_account(accounts, connection, domain)
    raw_store = FakeRawStore()
    broker = RefBroker({connection.credential_ref: "secret-hook"})
    gateway = _gateway(
        plugin=_shopify_plugin(),
        identity_key=SHOPIFY_IDENTITY,
        raw_store=raw_store,
        bridge=FakeBridge(),
        broker=broker,
        connections=connections,
        accounts=accounts,
    )
    body = _shopify_delivery_body(domain)

    result = await gateway.ingest(
        SHOPIFY_IDENTITY,
        raw_body=body,
        headers=_shopify_headers(body, "secret-hook", delivery_id="delivery-hook", domain=domain),
        tenant_id="tenant-1",
    )

    assert result["accepted"] is True
    assert broker.revealed == [connection.credential_ref]
    assert raw_store.records[0].connection_id == connection.connection_id
    assert raw_store.records[0].account_id == f"shop:{domain}"


# ── Webhook secret extraction shapes ────────────────────────────────────────


def test_extract_webhook_secret_shapes():
    assert _extract_webhook_secret(None) is None
    assert _extract_webhook_secret("plain") == "plain"
    assert _extract_webhook_secret("") is None
    assert _extract_webhook_secret({"webhook_secret": "dict_secret"}) == "dict_secret"
    assert _extract_webhook_secret({"secret": "alt_secret"}) == "alt_secret"
    assert (
        _extract_webhook_secret(
            ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"), webhook_secret=SecretStr("whsec_abc")
            )
        )
        == "whsec_abc"
    )
    # A credential without a webhook secret yields None (endpoint-ownership fallback).
    assert _extract_webhook_secret(ApiKeyCredential(api_key=SecretStr("k"))) is None


@pytest.mark.asyncio
async def test_verified_unscoped_webhook_is_bound_to_selected_connection_account():
    unscoped = make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id="o1",
        provider_record_type="order",
        payload={"id": "o1"},
        acquisition_mode="webhook",
    )
    plugin = FakePlugin(
        manifest=make_manifest(),
        webhook=FakeWebhookAdapter(records=[unscoped]),
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("secret"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"o1"}',
        headers={},
        tenant_id="tenant-1",
    )

    assert result["accepted"] is True
    persisted = raw_store.records[0]
    assert (persisted.tenant_id, persisted.connection_id, persisted.account_id) == (
        "tenant-1",
        "conn_1",
        "acc_1",
    )
    assert bridge.events[0].tenant_id == "tenant-1"
    assert bridge.events[0].source_record_id == persisted.record_id


@pytest.mark.asyncio
async def test_webhook_cross_tenant_record_claim_is_denied_before_normalization():
    claimed_other_tenant = make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id="o1",
        provider_record_type="order",
        payload={"id": "o1"},
        tenant_id="tenant-2",
        acquisition_mode="webhook",
    )
    plugin = FakePlugin(
        manifest=make_manifest(),
        webhook=FakeWebhookAdapter(records=[claimed_other_tenant]),
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=raw_store,
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("secret"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"o1"}',
        headers={},
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == "scope_mismatch"
    assert len(raw_store.records) == 1
    assert raw_store.records[0].provider_record_type == "webhook_denial"
    assert bridge.events == []


@pytest.mark.asyncio
async def test_webhook_raw_persist_failure_leaves_inbox_unprocessed():
    class FailingRawStore(FakeRawStore):
        async def ingest(self, records, *, tenant_id=None):
            raise RuntimeError("database unavailable")

    plugin = FakePlugin(
        manifest=make_manifest(),
        webhook=FakeWebhookAdapter(records=[make_record(record_id="o1")]),
        normalizer=FakeNormalizer(),
    )
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        raw_store=FailingRawStore(),
        bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"),
                webhook_secret=SecretStr("secret"),
            )
        ),
        connections=connections,
    )

    result = await gateway.ingest(
        IDENTITY,
        raw_body=b'{"id":"o1"}',
        headers={},
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == "raw_persist_failed"
    assert bridge.events == []
    rows = await WebhookInboxRepository().find_many(filters={"tenant_id": "tenant-1"})
    assert rows == []
