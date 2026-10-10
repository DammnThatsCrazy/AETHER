"""Unit tests: BYOK key vault — no raw keys in responses, masked identifiers."""
from __future__ import annotations

import pytest

from shared.providers.key_vault import BYOKKeyVault


@pytest.fixture
def vault():
    return BYOKKeyVault()


@pytest.mark.asyncio
async def test_list_keys_no_raw_key(vault):
    """list_keys must never return the raw api_key value."""
    await vault.store_key(
        tenant_id="t1",
        provider_name="coingecko",
        category="price",
        api_key="sk-live-super-secret-key",
    )
    keys = await vault.list_keys("t1")
    assert len(keys) == 1
    key_record = keys[0]

    assert "api_key" not in key_record
    assert "encrypted_key" not in key_record
    assert key_record.get("has_key") is True
    assert key_record["provider_name"] == "coingecko"


@pytest.mark.asyncio
async def test_get_key_returns_decrypted_value(vault):
    """get_key returns the raw key internally — must only be used server-side."""
    await vault.store_key(
        tenant_id="t1",
        provider_name="binance_public",
        category="cex",
        api_key="sk-test-key-123",
    )
    key = await vault.get_key("t1", "binance_public")
    assert key == "sk-test-key-123"


@pytest.mark.asyncio
async def test_verify_key_no_secret_exposure(vault):
    """verify_key must not expose any key bytes."""
    await vault.store_key(
        tenant_id="t2",
        provider_name="defi_llama",
        category="defi",
        api_key="top-secret-key",
    )
    result = await vault.verify_key("t2", "defi_llama")
    assert result["exists"] is True
    assert result["active"] is True
    assert "api_key" not in str(result)
    assert "top-secret-key" not in str(result)


@pytest.mark.asyncio
async def test_masked_identifier_format(vault):
    await vault.store_key(
        tenant_id="t3",
        provider_name="kalshi",
        category="prediction",
        api_key="my-secret-api-key",
    )
    masked = vault.masked_identifier("t3", "kalshi")
    assert masked.startswith("****")
    assert len(masked) == 8  # "****" + 4 hex chars
    assert "my-secret-api-key" not in masked


@pytest.mark.asyncio
async def test_rotate_key(vault):
    await vault.store_key("t4", "provider_a", "cat", "old-key")
    rotated = await vault.rotate_key("t4", "provider_a", "new-key")
    assert rotated is not None
    # Old key no longer retrievable
    new_val = await vault.get_key("t4", "provider_a")
    assert new_val == "new-key"


@pytest.mark.asyncio
async def test_revoke_key_blocks_get(vault):
    await vault.store_key("t5", "provider_b", "cat", "my-key")
    revoked = await vault.revoke_key("t5", "provider_b")
    assert revoked is True
    # Revoked key returns None from get_key
    key = await vault.get_key("t5", "provider_b")
    assert key is None


@pytest.mark.asyncio
async def test_cross_tenant_isolation(vault):
    """Tenant A's keys must not be accessible to Tenant B."""
    await vault.store_key("tenant_A", "dune_api", "onchain", "key-for-A")
    key_b = await vault.get_key("tenant_B", "dune_api")
    assert key_b is None


@pytest.mark.asyncio
async def test_verify_nonexistent_key(vault):
    result = await vault.verify_key("t_none", "nonexistent")
    assert result["exists"] is False
    assert result["active"] is False
