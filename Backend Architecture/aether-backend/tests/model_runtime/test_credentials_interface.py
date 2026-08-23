"""Tests for the credential resolution seam (ADR-008 D5) — interface layer."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.credentials.interface import (
    STATUS_ACTIVE,
    CredentialMetadata,
    make_metadata,
)
from services.model_runtime.credentials.interface import (
    CredentialCache,
    CredentialSource,
    NoopCredentialSource,
    ProviderCredentialResolver,
)
from services.model_runtime.credentials.models import (
    CredentialNotResolved,
    CredentialResolution,
)


def _make_meta(
    *,
    tenant_id: str = "tenant-1",
    ref: str = "ref-1",
    version: int = 1,
) -> CredentialMetadata:
    """Build a masked, secret-free credential metadata for seeding tests."""
    now = datetime.now(timezone.utc)
    return make_metadata(
        tenant_id=tenant_id,
        ref=ref,
        credential_type="api_key",
        version=version,
        lifecycle_status=STATUS_ACTIVE,
        masked_identifier="****abcd",
        created_at=now,
        updated_at=now,
    )


class _EnvGatedResolver:
    """Structural implementation of ProviderCredentialResolver.

    ``is_configured`` is the sync, env-gated fast path the contract requires:
    a provider is configured when ``<PROVIDER>_API_KEY`` is present in the
    process environment. ``resolve`` always returns a masked, secret-free
    :class:`CredentialResolution`.
    """

    def is_configured(self, provider: str) -> bool:
        return bool(os.environ.get(f"{provider.upper()}_API_KEY"))

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        return CredentialResolution(
            provider=provider,
            tenant_id=tenant_id,
            ref=f"{provider}:{tenant_id}:default",
            resolved=True,
            configured=True,
            masked_identifier="****abcd",
            source="env",
            rotated_at=None,
            expires_at=None,
            reason="resolved via env credential",
        )

    async def health(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# NoopCredentialSource
# ---------------------------------------------------------------------------


async def test_noop_source_load_happy_path():
    src = NoopCredentialSource()
    meta = _make_meta()
    src.put("tenant-1", "ref-1", meta)

    loaded = await src.load("tenant-1", "ref-1")
    assert loaded is meta
    assert isinstance(loaded, CredentialMetadata)
    # Only masked, secret-free metadata is ever exposed.
    assert loaded.masked_identifier == "****abcd"
    for field in ("api_key", "token", "secret", "client_secret"):
        assert field not in loaded.model_dump()


async def test_noop_source_rotate_happy_path():
    src = NoopCredentialSource()
    src.put("tenant-1", "ref-1", _make_meta(version=3))

    rotated = await src.rotate("tenant-1", "ref-1")
    assert rotated.version == 4
    assert rotated.rotated_at is not None
    assert rotated.revoked_at is None
    assert rotated.status == CredentialReadiness.PARTNER_LIVE
    # Rotation is durable in the in-memory store.
    assert (await src.load("tenant-1", "ref-1")).version == 4


async def test_noop_source_revoke_happy_path():
    src = NoopCredentialSource()
    src.put("tenant-1", "ref-1", _make_meta())

    assert await src.revoke("tenant-1", "ref-1") is True
    after = await src.load("tenant-1", "ref-1")
    assert after.status == CredentialReadiness.DISABLED
    assert after.revoked_at is not None


async def test_noop_source_unknown_ref_raises():
    src = NoopCredentialSource()
    with pytest.raises(CredentialNotResolved):
        await src.load("tenant-1", "missing")
    with pytest.raises(CredentialNotResolved):
        await src.rotate("tenant-1", "missing")
    with pytest.raises(CredentialNotResolved):
        await src.revoke("tenant-1", "missing")


async def test_noop_source_health_true():
    assert await NoopCredentialSource().health() is True


async def test_noop_source_conforms_to_credential_source_protocol():
    assert isinstance(NoopCredentialSource(), CredentialSource)


# ---------------------------------------------------------------------------
# CredentialCache
# ---------------------------------------------------------------------------


async def test_cache_miss_then_put_then_get():
    cache = CredentialCache()
    meta = _make_meta()
    assert await cache.get("tenant-1", "ref-1") is None

    await cache.put(meta)
    got = await cache.get("tenant-1", "ref-1")
    assert got is meta
    # Different tenant / ref keys do not collide.
    assert await cache.get("tenant-2", "ref-1") is None
    assert await cache.get("tenant-1", "ref-2") is None


async def test_cache_invalidate():
    cache = CredentialCache()
    await cache.put(_make_meta())
    assert await cache.get("tenant-1", "ref-1") is not None

    await cache.invalidate("tenant-1", "ref-1")
    assert await cache.get("tenant-1", "ref-1") is None
    # Invalidating an unknown key is a no-op.
    await cache.invalidate("tenant-1", "never-stored")


async def test_cache_ttl_expiry_deterministic():
    # ttl_seconds=0 expires every entry immediately — a deterministic TTL check.
    cache = CredentialCache(ttl_seconds=0)
    await cache.put(_make_meta())
    assert await cache.get("tenant-1", "ref-1") is None


async def test_cache_ttl_expiry_with_sleep():
    cache = CredentialCache(ttl_seconds=0.02)
    meta = _make_meta()
    await cache.put(meta)
    assert await cache.get("tenant-1", "ref-1") is meta

    await asyncio.sleep(0.03)
    assert await cache.get("tenant-1", "ref-1") is None


# ---------------------------------------------------------------------------
# ProviderCredentialResolver protocol
# ---------------------------------------------------------------------------


def test_resolver_protocol_accepts_structural_impl():
    # A class with the right method shape satisfies the protocol structurally.
    assert isinstance(_EnvGatedResolver(), ProviderCredentialResolver)
    assert isinstance(ProviderCredentialResolver, type)


async def test_resolver_returns_masked_resolution():
    res = await _EnvGatedResolver().resolve("tenant-1", "openai")
    assert res.provider == "openai"
    assert res.tenant_id == "tenant-1"
    assert res.resolved is True
    assert res.configured is True
    assert res.masked_identifier == "****abcd"
    assert res.source == "env"
    assert res.reason
    # Masked identifier is secret-free by construction (no redact patterns).
    assert res.masked_identifier.startswith("****")


async def test_resolver_health():
    assert await _EnvGatedResolver().health() is True


def test_is_configured_env_gated(monkeypatch):
    resolver = _EnvGatedResolver()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolver.is_configured("openai") is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert resolver.is_configured("openai") is True
    # Other providers are not configured by the openai key alone.
    assert resolver.is_configured("anthropic") is False
