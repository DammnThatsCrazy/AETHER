"""Credential-authority-backed webhook-secret resolution (FIN-CRED-1-VAULT-RETIRE).

Default OFF: adapters read the legacy BYOKKeyVault secret, byte-for-byte as
before. When AETHER_PAYMENT_CREDENTIAL_AUTHORITY_ENABLED is set, an adapter
resolves its webhook_signing_secret ONLY from the durable CredentialAuthority
(active + rotation-overlap previous) with NO vault fallback — so verification
fails closed when the authority slot is unconfigured, and a rotation accepts a
signature from either the new active or the still-valid previous secret.

All in-memory (AETHER_ENV=local → sandbox); no live network, no new deps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.integrations.providers.payment_rails import ADAPTERS  # noqa: E402
from services.integrations.providers.payment_rails.base import get_payment_rails_vault  # noqa: E402
from services.providers.credentials.authority import credential_authority  # noqa: E402

pytestmark = pytest.mark.asyncio

_BODY = b'{"event":"x"}'
_SLOT = "webhook_signing_secret"
_ENV = "sandbox"


def _tenant():
    return f"t-{uuid.uuid4().hex[:8]}"


def _patch_authority(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        settings, "payment_rails",
        dataclasses.replace(settings.payment_rails, credential_authority_enabled=enabled),
    )


def _sig(secret: str) -> str:
    return hmac.new(secret.encode(), _BODY, hashlib.sha256).hexdigest()


async def _authority_activate(tenant: str, provider: str, secret: str):
    await credential_authority.create_pending(tenant, provider, _ENV, _SLOT, secret, created_by="admin")
    await credential_authority.activate(tenant, provider, _ENV, _SLOT, credential_version=1, actor="admin")


# ── flag OFF: legacy vault parity ─────────────────────────────────────────────

async def test_flag_off_verifies_with_vault_secret(monkeypatch):
    reset_in_memory_stores()
    _patch_authority(monkeypatch, False)  # default
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    await get_payment_rails_vault().store_key(tenant, adapter.vault_provider_name, "payment", "whsec_off")

    assert await adapter.verify_webhook(tenant, _BODY, _sig("whsec_off")) is True
    assert await adapter.verify_webhook(tenant, _BODY, "deadbeef") is False


# ── flag ON: authority-only, no vault fallback ────────────────────────────────

async def test_flag_on_verifies_with_authority_secret(monkeypatch):
    reset_in_memory_stores()
    _patch_authority(monkeypatch, True)
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    await _authority_activate(tenant, adapter.provider_name, "whsec_authority")

    assert await adapter.verify_webhook(tenant, _BODY, _sig("whsec_authority")) is True


async def test_flag_on_no_authority_version_fails_closed_despite_vault_key(monkeypatch):
    reset_in_memory_stores()
    _patch_authority(monkeypatch, True)
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    # a vault key exists, but flag-ON must NOT fall back to it (retirement invariant)
    await get_payment_rails_vault().store_key(tenant, adapter.vault_provider_name, "payment", "whsec_vaultonly")

    assert await adapter._resolve_signing_secrets(tenant) == []
    assert await adapter.verify_webhook(tenant, _BODY, _sig("whsec_vaultonly")) is False


async def test_flag_on_rotation_overlap_accepts_active_or_previous(monkeypatch):
    reset_in_memory_stores()
    _patch_authority(monkeypatch, True)
    adapter = ADAPTERS["coinbase"]
    tenant = _tenant()
    await _authority_activate(tenant, adapter.provider_name, "alpha")
    await credential_authority.rotate(
        tenant, adapter.provider_name, _ENV, _SLOT, "beta",
        actor="admin", expected_active_version=1,
    )

    # the new active (beta) AND the rotation-overlap previous (alpha) both verify
    assert await adapter.verify_webhook(tenant, _BODY, _sig("beta")) is True
    assert await adapter.verify_webhook(tenant, _BODY, _sig("alpha")) is True
