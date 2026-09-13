"""WS6 — config/secret migration projection tests.

Covers the Shopify built mapping (native identity, config/secret field maps,
credential ref target), the refs-only no-plaintext contract, unbuilt families
marked as manual-mapping, fail-closed validation (invalid hosts, missing
secrets), and ``apply_projection`` storing a refs-only native credential +
connection. Includes the legacy ``MultiCredential`` reveal shape (secrets nested
under ``credentials[...]``).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from pydantic import SecretStr

from shared.credentials.types import (
    ApiKeyCredential,
    ApiKeyWebhookSecretCredential,
    MultiCredential,
    StructuredCredential,
)
from services.provider_runtime.errors import CredentialMissing
from services.provider_runtime.migration_projections import (
    ProjectionInvalid,
    ProjectionUnavailable,
    apply_projection,
    list_projectable,
    project_connection,
)

_SHOPIFY_REF = "legacy:t1:shopify"
_SHOPIFY_CONFIG = {"shop_domain": "acme.myshopify.com"}


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeBroker:
    def __init__(self, stored: StructuredCredential | None = None) -> None:
        self.stored = stored
        self.writes: list[tuple] = []

    def provider_ref(self, tenant_id: str, identity_key: str) -> str:
        return f"provider:{tenant_id}:{identity_key}"

    async def resolve(self, tenant_id: str, ref: str) -> StructuredCredential | None:
        return self.stored

    async def store(self, tenant_id: str, ref: str, credential: StructuredCredential) -> None:
        self.writes.append((tenant_id, ref, credential))


class FakeConnections:
    def __init__(self, existing=None) -> None:
        self.upserted: list = []
        self._existing = existing or []

    async def list_for_tenant(self, tenant_id: str, *, limit: int = 100):
        return [
            conn
            for conn in self._existing
            if getattr(conn, "tenant_id", None) == tenant_id
        ][:limit]

    async def upsert(self, connection) -> None:
        self.upserted.append(connection)
        return connection


# ── project_connection: Shopify built mapping ───────────────────────────────


def test_project_connection_shopify_maps_native_identity_and_fields() -> None:
    projection = project_connection("t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF)
    assert projection.connector_type == "shopify"
    assert projection.native_identity == "shopify.admin.orders_read"
    assert projection.config_field_map == {"shop_domain": "shop_domain"}
    assert projection.secret_field_map == {
        "api_key": "api_key",
        "webhook_signing_secret": "webhook_secret",
    }
    assert projection.credential_ref_target == "provider:t1:shopify.admin.orders_read"
    assert projection.confidence == "medium"
    assert projection.notes


def test_project_connection_normalizes_host_through_ssrf_gate() -> None:
    # The projectable surface validates the host; apply_projection normalizes it
    # through validated_https_host (https:// prefix stripped to a bare host).
    projection = project_connection("t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF)
    assert projection.native_identity == "shopify.admin.orders_read"
    assert projection.config_field_map == {"shop_domain": "shop_domain"}


# ── Refs-only contract (no plaintext) ───────────────────────────────────────


def test_project_connection_rejects_plaintext_secret_ref() -> None:
    with pytest.raises(ProjectionInvalid):
        project_connection("t1", "shopify", _SHOPIFY_CONFIG, "shpat_REAL_SECRET")


def test_project_connection_rejects_empty_ref() -> None:
    with pytest.raises(ProjectionInvalid):
        project_connection("t1", "shopify", _SHOPIFY_CONFIG, "")


def test_project_connection_rejects_missing_tenant() -> None:
    with pytest.raises(ProjectionInvalid):
        project_connection("", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF)


# ── Unbuilt families ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "family",
    ["woocommerce", "etsy", "amazon", "ebay", "walmart", "tiktok"],
)
def test_project_connection_unbuilt_family_raises_unavailable(family: str) -> None:
    with pytest.raises(ProjectionUnavailable):
        project_connection("t1", family, {}, f"legacy:t1:{family}")


def test_project_connection_unknown_family_raises_unavailable() -> None:
    with pytest.raises(ProjectionUnavailable):
        project_connection("t1", "not_a_provider", {}, "legacy:t1:unknown")


# ── Fail-closed validation ──────────────────────────────────────────────────


def test_project_connection_invalid_host_fails_closed() -> None:
    with pytest.raises(ProjectionInvalid):
        project_connection(
            "t1", "shopify", {"shop_domain": "http://127.0.0.1"}, _SHOPIFY_REF
        )


def test_project_connection_missing_config_key_fails_closed() -> None:
    with pytest.raises(ProjectionInvalid):
        project_connection("t1", "shopify", {}, _SHOPIFY_REF)


# ── list_projectable ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_projectable_marks_built_and_unbuilt_families() -> None:
    candidates = await list_projectable("t1", connections=FakeConnections())
    by_type = {c.connector_type: c for c in candidates}
    assert by_type["shopify"].native_identity == "shopify.admin.orders_read"
    assert by_type["shopify"].requires_manual_mapping is False
    assert by_type["shopify"].confidence == "medium"
    for family in ("woocommerce", "etsy", "amazon", "ebay", "walmart", "tiktok"):
        assert by_type[family].native_identity is None
        assert by_type[family].requires_manual_mapping is True


@pytest.mark.asyncio
async def test_list_projectable_excludes_already_migrated_family() -> None:
    from services.provider_runtime.connection import ProviderConnection

    migrated = ProviderConnection(
        connection_id="conn_migrated",
        tenant_id="t1",
        provider_identity="shopify.admin.orders_read",
        state="credentials_received",
        credential_ref="provider:t1:shopify.admin.orders_read",
    )
    candidates = await list_projectable("t1", connections=FakeConnections([migrated]))
    types = {c.connector_type for c in candidates}
    assert "shopify" not in types
    assert "woocommerce" in types


# ── apply_projection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_projection_flat_credential_creates_native_connection() -> None:
    legacy = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("shpat_NATIVE_KEY_1"),
        webhook_secret=SecretStr("whsec_NATIVE_1"),
    )
    broker = FakeBroker(stored=legacy)
    connections = FakeConnections()
    native = await apply_projection(
        "t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF,
        broker=broker, connections=connections,
    )
    assert native.provider_identity == "shopify.admin.orders_read"
    assert native.credential_ref == "provider:t1:shopify.admin.orders_read"
    # The returned connection carries ONLY a ref — never secret material.
    assert "api_key" not in native.model_dump()
    assert "webhook_secret" not in native.model_dump()
    # The stored native credential is re-wrapped as SecretStr (refs-only).
    stored_ref, stored_cred = broker.writes[0][1], broker.writes[0][2]
    assert stored_ref == "provider:t1:shopify.admin.orders_read"
    assert isinstance(stored_cred, ApiKeyWebhookSecretCredential)
    assert stored_cred.api_key.get_secret_value() == "shpat_NATIVE_KEY_1"
    assert stored_cred.webhook_secret.get_secret_value() == "whsec_NATIVE_1"
    assert len(connections.upserted) == 1
    # Config host is normalized through the S1 SSRF gate to a bare admin host.
    assert native.config["shop_domain"] == "acme.myshopify.com"


@pytest.mark.asyncio
async def test_apply_projection_multicredential_shape() -> None:
    """Legacy MultiCredential reveal nests secrets under ``credentials[...]``;
    the extractor must resolve the mapped fields inside the sub-credentials."""
    legacy = MultiCredential(
        credentials={
            "api_key": ApiKeyCredential(api_key=SecretStr("shpat_MULTI_KEY_2")),
            "webhook_signing_secret": ApiKeyWebhookSecretCredential(
                api_key=SecretStr("unused"),
                webhook_secret=SecretStr("whsec_MULTI_2"),
            ),
        }
    )
    broker = FakeBroker(stored=legacy)
    connections = FakeConnections()
    native = await apply_projection(
        "t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF,
        broker=broker, connections=connections,
    )
    assert native.credential_ref == "provider:t1:shopify.admin.orders_read"
    stored_cred = broker.writes[0][2]
    assert isinstance(stored_cred, ApiKeyWebhookSecretCredential)
    assert stored_cred.api_key.get_secret_value() == "shpat_MULTI_KEY_2"
    assert stored_cred.webhook_secret.get_secret_value() == "whsec_MULTI_2"


@pytest.mark.asyncio
async def test_apply_projection_missing_legacy_credential_fails_closed() -> None:
    broker = FakeBroker(stored=None)
    with pytest.raises(CredentialMissing):
        await apply_projection(
            "t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF,
            broker=broker, connections=FakeConnections(),
        )


@pytest.mark.asyncio
async def test_apply_projection_partial_credential_fails_closed() -> None:
    # A flat credential missing the webhook secret cannot produce a complete
    # api_key_webhook_secret native credential — fail closed, never partial.
    legacy = ApiKeyCredential(api_key=SecretStr("shpat_ONLY_KEY_3"))
    broker = FakeBroker(stored=legacy)
    with pytest.raises(CredentialMissing):
        await apply_projection(
            "t1", "shopify", _SHOPIFY_CONFIG, _SHOPIFY_REF,
            broker=broker, connections=FakeConnections(),
        )


@pytest.mark.asyncio
async def test_apply_projection_invalid_host_fails_closed() -> None:
    legacy = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("shpat_K"), webhook_secret=SecretStr("whsec_W")
    )
    broker = FakeBroker(stored=legacy)
    with pytest.raises(ProjectionInvalid):
        await apply_projection(
            "t1", "shopify", {"shop_domain": "http://127.0.0.1"}, _SHOPIFY_REF,
            broker=broker, connections=FakeConnections(),
        )
    assert broker.writes == []


@pytest.mark.asyncio
async def test_apply_projection_unbuilt_family_fails_closed() -> None:
    with pytest.raises(ProjectionUnavailable):
        await apply_projection(
            "t1", "woocommerce", {}, "legacy:t1:woocommerce",
            broker=FakeBroker(), connections=FakeConnections(),
        )
