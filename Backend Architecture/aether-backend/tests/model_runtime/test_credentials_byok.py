"""BYOK credential resolver tests (Commit 6 / ADR-008 D5).

Covers the four resolution paths (cache / secret backend / env / none), the
fail-closed backend-error path, and the no-leak invariant. Plain asserts only.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from services.model_runtime.credentials.byok import (
    ByokCredentialResolver,
    CredentialCache,
    NoopCredentialSource,
)
from shared.credentials.interface import CredentialMetadata

#: Fallback env var the resolver reads by name (never the key value).
ENV_REF = "AETHER_LLM_API_KEY"


def _meta(
    tenant_id: str = "tenant-a",
    ref: str = "llm/openai",
    masked: str = "****abcd",
) -> CredentialMetadata:
    """Build a secret-free masked metadata to seed a source or cache."""
    now = datetime.now(timezone.utc)
    return CredentialMetadata(
        tenant_id=tenant_id,
        ref=ref,
        credential_type="api_key",
        version=1,
        status="partner_live",
        masked_identifier=masked,
        created_at=now,
        updated_at=now,
    )


class _CountingSource(NoopCredentialSource):
    """Noop source that counts ``load`` calls (seeded via ``put``)."""

    def __init__(self) -> None:
        super().__init__()
        self.load_calls = 0

    async def load(self, tenant_id: str, ref: str) -> CredentialMetadata:
        self.load_calls += 1
        return await super().load(tenant_id, ref)


class _FailingSource(NoopCredentialSource):
    """Source whose backend is unreachable (fail-closed path)."""

    async def load(self, tenant_id: str, ref: str) -> CredentialMetadata:
        raise RuntimeError("backend boom")


@pytest.mark.asyncio
async def test_backend_path_resolves_configured_with_masked_id():
    source = NoopCredentialSource()
    source.put("tenant-a", "llm/openai", _meta())
    resolver = ByokCredentialResolver(source)

    res = await resolver.resolve("tenant-a", "openai")

    assert res.resolved is True
    assert res.configured is True
    assert res.source == "secret_backend"
    assert res.ref == "llm/openai"
    assert res.masked_identifier == "****abcd"
    assert res.reason == "resolved from secret backend"


@pytest.mark.asyncio
async def test_env_fallback_resolves_configured_when_env_set(monkeypatch):
    raw = "sk-live-secret-abc123"
    monkeypatch.setenv(ENV_REF, raw)
    resolver = ByokCredentialResolver(NoopCredentialSource())

    res = await resolver.resolve("tenant-a", "openai")

    assert res.resolved is True
    assert res.configured is True
    assert res.source == "env"
    assert res.ref == ENV_REF
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[-4:]
    assert res.masked_identifier == "****" + suffix
    assert raw not in res.masked_identifier


@pytest.mark.asyncio
async def test_no_credential_resolves_not_configured(monkeypatch):
    monkeypatch.delenv(ENV_REF, raising=False)
    resolver = ByokCredentialResolver(NoopCredentialSource())

    res = await resolver.resolve("tenant-a", "openai")

    assert res.resolved is True
    assert res.configured is False
    assert res.source == "none"
    assert res.reason == "no credential configured for provider"
    assert res.masked_identifier is None


@pytest.mark.asyncio
async def test_cache_hit_skips_source():
    source = _CountingSource()
    source.put("tenant-a", "llm/openai", _meta())
    resolver = ByokCredentialResolver(source, CredentialCache())

    first = await resolver.resolve("tenant-a", "openai")
    assert first.configured is True
    assert source.load_calls == 1  # first resolve populated the cache

    second = await resolver.resolve("tenant-a", "openai")
    assert second.configured is True
    assert second.source == "secret_backend"
    assert second.masked_identifier == "****abcd"
    assert source.load_calls == 1  # cache hit skipped the source


@pytest.mark.asyncio
async def test_cache_hit_serves_without_touching_a_failing_source():
    # A pre-seeded cache must satisfy the resolve even though the source itself
    # would fail closed — proving the cache path never queries the source.
    cache = CredentialCache()
    await cache.put(_meta())
    resolver = ByokCredentialResolver(_FailingSource(), cache)

    res = await resolver.resolve("tenant-a", "openai")

    assert res.configured is True
    assert res.source == "secret_backend"
    assert res.masked_identifier == "****abcd"
    assert res.reason == "cached credential"


@pytest.mark.asyncio
async def test_source_failure_fails_closed():
    resolver = ByokCredentialResolver(_FailingSource())

    res = await resolver.resolve("tenant-a", "openai")

    assert res.resolved is True
    assert res.configured is False
    assert res.reason == "backend unavailable"
    assert res.masked_identifier is None


@pytest.mark.asyncio
async def test_resolve_never_leaks_raw_key(monkeypatch):
    raw = "sk-super-secret-raw-key-material"
    monkeypatch.setenv(ENV_REF, raw)
    resolver = ByokCredentialResolver(NoopCredentialSource())

    res = await resolver.resolve("tenant-a", "openai")

    dumped = str(res.model_dump())
    assert res.configured is True
    assert raw not in dumped
    assert raw not in (res.masked_identifier or "")
    assert raw not in res.reason
    assert raw not in res.ref


@pytest.mark.asyncio
async def test_backend_resolution_never_leaks_plaintext():
    source = NoopCredentialSource()
    source.put("tenant-a", "llm/openai", _meta(masked="****zz99"))
    resolver = ByokCredentialResolver(source)

    res = await resolver.resolve("tenant-a", "openai")

    dumped = str(res.model_dump())
    assert "sk-" not in dumped  # no raw-secret-looking material anywhere
    assert res.masked_identifier == "****zz99"
    assert "zz99" in dumped  # only the masked tag surfaces


def test_is_configured_tracks_env_ref_presence(monkeypatch):
    monkeypatch.delenv(ENV_REF, raising=False)
    resolver = ByokCredentialResolver(NoopCredentialSource())
    assert resolver.is_configured("openai") is False

    monkeypatch.setenv(ENV_REF, "present")
    assert resolver.is_configured("openai") is True


@pytest.mark.asyncio
async def test_health_delegates_to_source():
    resolver = ByokCredentialResolver(NoopCredentialSource())
    assert await resolver.health() is True


def test_byok_resolver_satisfies_provider_credential_resolver_protocol():
    from services.model_runtime.credentials.interface import (
        ProviderCredentialResolver,
    )

    resolver = ByokCredentialResolver(NoopCredentialSource())
    assert isinstance(resolver, ProviderCredentialResolver)
