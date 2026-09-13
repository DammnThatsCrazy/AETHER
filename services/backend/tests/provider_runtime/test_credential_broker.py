"""Tests for the credential broker (refs never plaintext)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from shared.credentials.in_memory import InMemoryCredentialBackend
from shared.credentials.service import CredentialService
from shared.credentials.types import ApiKeyCredential

from services.provider_runtime.credential_broker import CredentialBroker


@pytest.fixture
def backend() -> InMemoryCredentialBackend:
    return InMemoryCredentialBackend(store={})


@pytest.fixture
def broker(backend: InMemoryCredentialBackend) -> CredentialBroker:
    return CredentialBroker(service=CredentialService(backend=backend))


def test_provider_ref_format(broker: CredentialBroker):
    ref = broker.provider_ref("tenant-1", "shopify.orders.catalog")
    assert ref == "provider:tenant-1:shopify.orders.catalog"
    # A ref never contains secret material by construction.
    assert "sk_" not in ref


@pytest.mark.asyncio
async def test_store_and_resolve_round_trip(broker: CredentialBroker):
    ref = broker.provider_ref("tenant-1", "shopify.orders.catalog")
    credential = ApiKeyCredential(api_key=SecretStr("sk_live_abc"))
    await broker.store("tenant-1", ref, credential)

    resolved = await broker.resolve("tenant-1", ref)
    assert resolved is not None
    assert resolved.type == "api_key"
    assert resolved.api_key.get_secret_value() == "sk_live_abc"


@pytest.mark.asyncio
async def test_resolve_missing_returns_none(broker: CredentialBroker):
    ref = broker.provider_ref("tenant-1", "shopify.orders.catalog")
    assert await broker.resolve("tenant-1", ref) is None


@pytest.mark.asyncio
async def test_reveal_returns_structured_credential(broker: CredentialBroker):
    ref = broker.provider_ref("tenant-1", "stripe.billing.catalog")
    await broker.store("tenant-1", ref, ApiKeyCredential(api_key=SecretStr("sk_test_xyz")))

    revealed = await broker.reveal("tenant-1", ref)
    assert revealed is not None
    assert revealed.type == "api_key"
    # Secret is reachable only through the explicit SecretStr unwrap.
    assert revealed.api_key.get_secret_value() == "sk_test_xyz"


@pytest.mark.asyncio
async def test_revoked_credential_resolves_to_none(broker: CredentialBroker):
    ref = broker.provider_ref("tenant-1", "stripe.billing.catalog")
    await broker.store("tenant-1", ref, ApiKeyCredential(api_key=SecretStr("sk_test_xyz")))

    await broker.revoke("tenant-1", ref)
    assert await broker.resolve("tenant-1", ref) is None


@pytest.mark.asyncio
async def test_refs_are_tenant_scoped(broker: CredentialBroker):
    ref_a = broker.provider_ref("tenant-1", "shopify.orders.catalog")
    ref_b = broker.provider_ref("tenant-2", "shopify.orders.catalog")
    assert ref_a != ref_b

    await broker.store("tenant-1", ref_a, ApiKeyCredential(api_key=SecretStr("sk_1")))
    # A different tenant must not resolve the same identity key.
    assert await broker.resolve("tenant-2", ref_b) is None
