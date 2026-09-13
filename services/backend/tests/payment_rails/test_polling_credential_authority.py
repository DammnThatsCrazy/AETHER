"""Polling-credential cutover to the durable CredentialAuthority (CS1).

Coinbase / MoonPay / Bridge resolve their read-only polling API key
(``onramp_api_key`` / ``server_api_key`` / ``api_key``) from the durable
CredentialAuthority when the authority is enabled — never the retired in-memory
vault outside local development. The credential *environment* (sandbox|live) is
threaded explicitly, so a sandbox connection can never pull with a live secret
and vice-versa. Webhook-only providers (Privy, Stripe) declare no polling slot.

All in-memory (AETHER_ENV=local); no live network, no new deps.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails import base as pr_base  # noqa: E402
from services.integrations.providers.payment_rails.base import (  # noqa: E402
    get_payment_rails_vault,
)
from services.providers.credentials.authority import credential_authority  # noqa: E402

pytestmark = pytest.mark.asyncio

_POLLING_SLOTS = {"coinbase": "onramp_api_key", "moonpay": "server_api_key", "bridge": "api_key"}


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


def _patch(monkeypatch, **fields) -> None:
    monkeypatch.setattr(
        settings, "payment_rails", dataclasses.replace(settings.payment_rails, **fields)
    )


async def _activate(tenant: str, provider: str, env: str, slot: str, secret: str) -> None:
    await credential_authority.create_pending(tenant, provider, env, slot, secret, created_by="admin")
    await credential_authority.activate(tenant, provider, env, slot, credential_version=1, actor="admin")


# ── polling-slot declaration ──────────────────────────────────────────────────

def test_polling_slot_derivation():
    for provider, slot in _POLLING_SLOTS.items():
        assert ADAPTERS[provider].polling_slot() == slot
    # webhook-only providers declare no polling slot
    assert ADAPTERS["privy"].polling_slot() is None
    assert ADAPTERS["stripe"].polling_slot() is None


# ── flag ON: polling secret resolves from the authority, per environment ──────

@pytest.mark.parametrize("provider", list(_POLLING_SLOTS))
async def test_flag_on_polling_secret_from_authority(monkeypatch, provider):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=True)
    adapter = ADAPTERS[provider]
    tenant = _tenant()
    await _activate(tenant, provider, "sandbox", _POLLING_SLOTS[provider], "poll_sbx")

    assert await adapter._require_secret(tenant, "sandbox") == "poll_sbx"
    # wrong environment: the live slot is unprovisioned → fail closed (None)
    assert await adapter._require_secret(tenant, "live") is None


async def test_flag_on_sandbox_and_live_isolated(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=True)
    adapter = ADAPTERS["moonpay"]
    tenant = _tenant()
    await _activate(tenant, "moonpay", "sandbox", "server_api_key", "sbx_key")
    await _activate(tenant, "moonpay", "live", "server_api_key", "live_key")

    assert await adapter._require_secret(tenant, "sandbox") == "sbx_key"
    assert await adapter._require_secret(tenant, "live") == "live_key"


async def test_flag_on_outside_local_no_vault_fallback(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=True)
    # Simulate a non-local deployment: the vault must NEVER be consulted.
    monkeypatch.setattr(pr_base, "_is_local_env", lambda: False)
    adapter = ADAPTERS["bridge"]
    tenant = _tenant()
    await get_payment_rails_vault().store_key(tenant, adapter.vault_provider_name, "payment", "vault_key")

    # authority has no active polling slot → fail closed, never the vault
    assert await adapter._require_secret(tenant, "sandbox") is None


async def test_flag_off_polling_secret_from_vault(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=False)
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    await get_payment_rails_vault().store_key(tenant, adapter.vault_provider_name, "payment", "vault_key")

    assert await adapter._require_secret(tenant) == "vault_key"


# ── is_configured computed from the authority ─────────────────────────────────

async def test_is_configured_from_authority_requires_all_slots(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=True)
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    # only the webhook slot present → a polling provider is not fully configured
    await _activate(tenant, "coinbase", "sandbox", "webhook_signing_secret", "whsec")
    assert await adapter.is_configured(tenant, "sandbox") is False
    # add the polling slot → configured
    await _activate(tenant, "coinbase", "sandbox", "onramp_api_key", "apikey")
    assert await adapter.is_configured(tenant, "sandbox") is True
    # a different environment remains unconfigured
    assert await adapter.is_configured(tenant, "live") is False


# ── environment-threaded webhook secret resolution ────────────────────────────

async def test_webhook_secret_environment_threaded(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, credential_authority_enabled=True)
    adapter = ADAPTERS["bridge"]
    tenant = _tenant()
    await _activate(tenant, "bridge", "live", "webhook_signing_secret", "live_whsec")

    assert await adapter._resolve_signing_secrets(tenant, "live") == ["live_whsec"]
    # sandbox slot unprovisioned → empty (fail closed), never the live secret
    assert await adapter._resolve_signing_secrets(tenant, "sandbox") == []


# ── live-probe test_slot ──────────────────────────────────────────────────────

async def test_live_probe_test_slot_local_credential_present(monkeypatch):
    reset_in_memory_stores()
    tenant = _tenant()
    await credential_authority.create_pending(
        tenant, "coinbase", "sandbox", "onramp_api_key", "apikey", created_by="admin"
    )
    # local mode performs no network IO; a decryptable polling key → credential_present
    view = await credential_authority.test_slot(
        tenant, "coinbase", "sandbox", "onramp_api_key", actor="admin"
    )
    assert view["last_test_result"] == "credential_present"


async def test_signature_selfcheck_test_slot_valid(monkeypatch):
    reset_in_memory_stores()
    tenant = _tenant()
    await credential_authority.create_pending(
        tenant, "coinbase", "sandbox", "webhook_signing_secret", "whsec", created_by="admin"
    )
    view = await credential_authority.test_slot(
        tenant, "coinbase", "sandbox", "webhook_signing_secret", actor="admin"
    )
    assert view["last_test_result"] == "valid"
