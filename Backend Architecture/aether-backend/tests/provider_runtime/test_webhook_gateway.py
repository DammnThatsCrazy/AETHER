"""Tests for the inbound provider webhook gateway.

Covers the full ingest contract: WebhookInbox best-effort BEFORE verification,
signature verification, endpoint-ownership trust, metadata-only denial records
(never the unverified payload), and parse → raw store → normalize → bridge.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import pytest
from pydantic import SecretStr

from repositories.delivery_repos import WebhookInboxRepository
from repositories.repos import reset_in_memory_stores
from services.provider_runtime.connection import (
    ProviderConnection,
    ProviderConnectionRepository,
)
from services.provider_runtime.errors import CredentialMissing, ProviderNotInstalled
from services.provider_runtime.webhook import WebhookGateway, _extract_webhook_secret
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

IDENTITY = "shopify.orders.catalog"


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

    def verify(self, raw_body: bytes, headers: Mapping[str, str], secret: Optional[str]) -> bool:
        self.verify_calls.append((raw_body, headers, secret))
        return self._verify_result

    def parse(self, payload: dict[str, Any], headers: Mapping[str, str] | None = None) -> list[Any]:
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


def make_manifest(*, verification_scheme: Optional[str] = None) -> ProviderManifest:
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
        data_outputs=["commerce.order.created"],
        product_destinations=["silver"],
    )


def make_connection(
    *, tenant_id: str = "tenant-1", credential_ref: str = "provider:tenant-1:shopify.orders.catalog",
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


def make_record(*, record_id: str, provider_record_type: str = "order") -> Any:
    return make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id=record_id,
        provider_record_type=provider_record_type,
        payload={"id": record_id},
        tenant_id="tenant-1",
        connection_id="conn_1",
        account_id="acc_1",
        acquisition_mode="webhook",
    )


async def _persist_connection(connections: ProviderConnectionRepository) -> ProviderConnection:
    connection = make_connection()
    await connections.upsert(connection)
    return connection


def _gateway(
    *,
    plugin: Any,
    raw_store: Any = None,
    bridge: Any = None,
    broker: Any = None,
    connections: Any = None,
    registry: Any = None,
) -> WebhookGateway:
    return WebhookGateway(
        registry=registry if registry is not None else FakeRegistry({IDENTITY: plugin}),
        raw_store=raw_store or FakeRawStore(),
        bridge=bridge or FakeBridge(),
        broker=broker or FakeBroker(),
        connections=connections or ProviderConnectionRepository(),
    )


# ── Signature-verified success ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_success_signature_verified():
    secret_cred = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("sk_live_abc"), webhook_secret=SecretStr("whsec_123"),
    )
    webhook = FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)

    gateway = _gateway(
        plugin=plugin, raw_store=raw_store, bridge=bridge,
        broker=FakeBroker(credential=secret_cred), connections=connections,
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
    # inbox row was written before verification and marked processed on success
    rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"}, limit=10,
    )
    assert len(rows) == 1
    assert rows[0]["processed"] is True
    assert rows[0]["verified"] is True


# ── Verification failure → auditable metadata-only denial ──────────────────


@pytest.mark.asyncio
async def test_ingest_verification_failure_leaves_denial_without_payload():
    webhook = FakeWebhookAdapter(verify_result=False, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)

    gateway = _gateway(
        plugin=plugin, raw_store=raw_store, bridge=bridge,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"), webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}', headers={}, signature="bad",
        tenant_id="tenant-1",
    )

    assert result["accepted"] is False
    assert result["reason"] == "verification_failed"
    # exactly ONE denial record — never the unverified payload, never a real event
    assert len(raw_store.records) == 1
    denial = raw_store.records[0]
    assert denial.provider_record_type == "webhook_denial"
    assert denial.payload == {}
    assert denial.metadata["denial"] is True
    assert denial.metadata["reason"] == "verification_failed"
    assert len(bridge.events) == 0
    # inbox retained, marked unprocessed
    rows = await WebhookInboxRepository().find_many(
        filters={"tenant_id": "tenant-1"}, limit=10,
    )
    assert rows[0]["processed"] is False


# ── Endpoint-ownership trust (endpoint_secret scheme) ──────────────────────


@pytest.mark.asyncio
async def test_ingest_endpoint_secret_scheme_verifies_via_endpoint_token():
    """endpoint_secret scheme: a caller-presented token constant-time-matching the
    connection's secret proves ownership; no signature is ever demanded."""
    webhook = FakeWebhookAdapter(verify_result=False, records=[make_record(record_id="o1")])
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="endpoint_secret"),
        webhook=webhook, normalizer=FakeNormalizer(),
    )
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"), webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}',
        headers={"X-Aether-Webhook-Endpoint-Token": "ep_12345"},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is True
    assert result["verified"] is True
    assert webhook.verify_calls == []  # endpoint-ownership, not signature
    assert result["detail"] == "verified via per-connection endpoint token"


@pytest.mark.asyncio
async def test_ingest_endpoint_secret_scheme_wrong_token_denied():
    plugin = FakePlugin(
        manifest=make_manifest(verification_scheme="endpoint_secret"),
        webhook=FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")]),
        normalizer=FakeNormalizer(),
    )
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin, raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"), webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}',
        headers={"X-Aether-Webhook-Endpoint-Token": "wrong_token"},
        tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "verification_failed"
    assert raw_store.records[0].provider_record_type == "webhook_denial"
    assert len(raw_store.records) == 1


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
        plugin=plugin, raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("sk"), webhook_secret=SecretStr("ep_12345"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}', headers={}, tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "verification_failed"
    assert "requires a caller-presented endpoint token" in result["detail"]
    assert raw_store.records[0].provider_record_type == "webhook_denial"


@pytest.mark.asyncio
async def test_ingest_no_secret_configured_is_denied():
    """A signature scheme with no configured secret is a misconfiguration —
    DENIED with an auditable denial record, never auto-accepted."""
    webhook = FakeWebhookAdapter(verify_result=True, records=[make_record(record_id="o1")])
    plugin = FakePlugin(manifest=make_manifest(), webhook=webhook, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin, raw_store=raw_store,
        broker=FakeBroker(credential=None), connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}', headers={}, tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "verification_failed"
    assert "no webhook secret configured" in result["detail"]
    assert raw_store.records[0].provider_record_type == "webhook_denial"
    assert len(raw_store.records) == 1


# ── Resolver / payload / capability failures ────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_missing_plugin_raises():
    gateway = _gateway(plugin=None, registry=FakeRegistry({}))
    with pytest.raises(ProviderNotInstalled):
        await gateway.ingest(
            IDENTITY, raw_body=b"{}", headers={}, tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_ingest_missing_connection_raises():
    plugin = FakePlugin(manifest=make_manifest(), webhook=FakeWebhookAdapter())
    gateway = _gateway(plugin=plugin, connections=ProviderConnectionRepository())
    with pytest.raises(CredentialMissing):
        await gateway.ingest(
            IDENTITY, raw_body=b"{}", headers={}, tenant_id="tenant-1",
        )


@pytest.mark.asyncio
async def test_ingest_cross_tenant_hint_does_not_resolve_connection():
    """The X-Aether-Tenant-ID hint is routing only. A connection stored under
    tenant-1 is never resolved for a tenant-2 hint — tenant isolation holds even
    though the public webhook route is unauthenticated by API key."""
    plugin = FakePlugin(
        manifest=make_manifest(), webhook=FakeWebhookAdapter(), normalizer=FakeNormalizer(),
    )
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)  # stored under tenant-1
    gateway = _gateway(
        plugin=plugin,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"), webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    with pytest.raises(CredentialMissing):
        await gateway.ingest(
            IDENTITY, raw_body=b'{"id": "o1"}', headers={}, tenant_id="tenant-2",
        )


@pytest.mark.asyncio
async def test_ingest_invalid_json_leaves_denial():
    """Passes verification first, then a malformed body is denied as invalid_payload."""
    plugin = FakePlugin(manifest=make_manifest(), webhook=FakeWebhookAdapter(), normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(
        plugin=plugin, raw_store=raw_store,
        broker=FakeBroker(
            credential=ApiKeyWebhookSecretCredential(
                api_key=SecretStr("k"), webhook_secret=SecretStr("whsec_123"),
            )
        ),
        connections=connections,
    )
    result = await gateway.ingest(
        IDENTITY, raw_body=b"not json at all", headers={}, tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "invalid_payload"
    assert raw_store.records[0].provider_record_type == "webhook_denial"


@pytest.mark.asyncio
async def test_ingest_provider_without_webhook_capability():
    plugin = FakePlugin(manifest=make_manifest(), webhook=None, normalizer=FakeNormalizer())
    raw_store = FakeRawStore()
    connections = ProviderConnectionRepository()
    await _persist_connection(connections)
    gateway = _gateway(plugin=plugin, raw_store=raw_store, connections=connections)
    result = await gateway.ingest(
        IDENTITY, raw_body=b'{"id": "o1"}', headers={}, tenant_id="tenant-1",
    )
    assert result["accepted"] is False
    assert result["reason"] == "webhook_not_supported"
    assert raw_store.records[0].provider_record_type == "webhook_denial"


# ── Webhook secret extraction shapes ────────────────────────────────────────


def test_extract_webhook_secret_shapes():
    assert _extract_webhook_secret(None) is None
    assert _extract_webhook_secret("plain") == "plain"
    assert _extract_webhook_secret("") is None
    assert _extract_webhook_secret({"webhook_secret": "dict_secret"}) == "dict_secret"
    assert _extract_webhook_secret({"secret": "alt_secret"}) == "alt_secret"
    assert _extract_webhook_secret(
        ApiKeyWebhookSecretCredential(api_key=SecretStr("k"), webhook_secret=SecretStr("whsec_abc"))
    ) == "whsec_abc"
    # A credential without a webhook secret yields None (endpoint-ownership fallback).
    assert _extract_webhook_secret(ApiKeyCredential(api_key=SecretStr("k"))) is None
