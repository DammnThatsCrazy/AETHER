"""Tests for the AWS Secrets Manager credential resolver (ADR-008 D5).

All tests use a fake :class:`CredentialBackendLike` stub — no real AWS or
boto3 is ever touched. Coverage: happy path, missing secret, backend failure,
region unset, scope/prefix enforcement, ``is_configured`` gating, cache-hit
short-circuit, and the invariant that a resolution never contains raw secret
strings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import SecretStr

from services.model_runtime.credentials.aws_secrets import (
    AwsSecretsCredentialResolver,
)
from services.model_runtime.credentials.interface import CredentialCache
from services.model_runtime.credentials.models import assert_no_raw_secrets
from shared.certification.readiness import CredentialReadiness
from shared.credentials.interface import (
    STATUS_ACTIVE,
    STATUS_REVOKED,
    CredentialBackendHealth,
    CredentialMetadata,
    make_metadata,
)
from shared.credentials.types import ApiKeyCredential


class FakeBackend:
    """In-memory ``CredentialBackendLike`` stub (no AWS).

    Stores ``ref -> (masked_identifier, raw_secret)`` exactly like the real
    backend stores plaintext at rest; ``metadata()`` reveals only the masked
    identifier while ``get()`` is the plaintext seam the resolver must never
    touch.
    """

    def __init__(
        self,
        *,
        ready: bool = True,
        stored: dict[str, tuple[str, str]] | None = None,
        metadata_overrides: dict[str, CredentialMetadata] | None = None,
    ):
        self._ready = ready
        self._stored = dict(stored or {})
        # ref -> pre-built CredentialMetadata returned verbatim by metadata()
        # (lets tests simulate revoked / expired / degraded records directly).
        self._metadata_overrides = dict(metadata_overrides or {})
        self.metadata_calls: list[tuple[str, str]] = []
        self.get_calls: list[tuple[str, str]] = []
        self.health_calls = 0

    def is_ready(self) -> bool:
        return self._ready

    def _meta(self, tenant_id: str, ref: str, masked: str) -> CredentialMetadata:
        now = datetime.now(timezone.utc)
        return make_metadata(
            tenant_id=tenant_id,
            ref=ref,
            credential_type="api_key",
            version=1,
            lifecycle_status=STATUS_ACTIVE,
            masked_identifier=masked,
            created_at=now,
            updated_at=now,
        )

    async def get(self, tenant_id: str, ref: str):
        self.get_calls.append((tenant_id, ref))
        entry = self._stored.get(ref)
        if entry is None:
            return None
        # Plaintext seam: the resolver must never call this.
        return ApiKeyCredential(api_key=SecretStr(entry[1]))

    async def rotate(self, tenant_id: str, ref: str, credential):
        raise AssertionError("resolver must never rotate")

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        raise AssertionError("resolver must never revoke")

    async def metadata(self, tenant_id: str, ref: str):
        self.metadata_calls.append((tenant_id, ref))
        override = self._metadata_overrides.get(ref)
        if override is not None:
            return override
        entry = self._stored.get(ref)
        if entry is None:
            return None
        return self._meta(tenant_id, ref, entry[0])

    async def list(self, tenant_id: str):
        items = [self._meta(tenant_id, ref, entry[0]) for ref, entry in self._stored.items()]
        items.extend(self._metadata_overrides.values())
        return items

    async def health_check(self) -> CredentialBackendHealth:
        self.health_calls += 1
        return CredentialBackendHealth(backend="fake", durable=True, healthy=self._ready)


class RaisingBackend(FakeBackend):
    """A backend whose ``metadata`` surface raises (AWS unavailable)."""

    async def metadata(self, tenant_id: str, ref: str):
        raise RuntimeError("simulated AWS failure")


async def test_happy_path_resolves_from_secret_backend():
    fake = FakeBackend(stored={"llm/anthropic": ("****a1b2", "sk-ant-raw-00000000")})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is True
    assert resolution.resolved is True
    assert resolution.source == "secret_backend"
    assert resolution.provider == "anthropic"
    assert resolution.tenant_id == "t1"
    assert resolution.ref == "llm/anthropic"
    assert resolution.reason == "resolved from aws secrets manager"
    assert resolution.masked_identifier == "****a1b2"
    assert fake.metadata_calls == [("t1", "llm/anthropic")]
    assert fake.get_calls == []


async def test_missing_secret_fails_closed():
    fake = FakeBackend()  # nothing stored
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is False
    assert resolution.resolved is False
    assert resolution.source == "none"
    assert resolution.reason == "no aws secret"
    assert resolution.masked_identifier is None


async def test_backend_error_fails_closed():
    resolver = AwsSecretsCredentialResolver(RaisingBackend(), aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is False
    assert resolution.resolved is False
    assert resolution.source == "none"
    assert resolution.reason == "aws backend unavailable"


async def test_resolve_without_region_fails_closed(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    fake = FakeBackend(stored={"llm/anthropic": ("****a1b2", "sk-ant-raw-00000000")})
    resolver = AwsSecretsCredentialResolver(fake)

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is False
    assert resolution.reason == "aws backend unavailable"
    assert fake.metadata_calls == []  # backend never touched without a region


async def test_unsafe_provider_fails_closed_without_backend_call():
    fake = FakeBackend(stored={"llm/anthropic": ("****a1b2", "sk-ant-raw-00000000")})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "victim/../../evil")

    assert resolution.configured is False
    assert resolution.resolved is False
    assert resolution.source == "none"
    assert resolution.reason == "invalid provider ref"
    assert fake.metadata_calls == []


def test_secret_arn_path_is_scoped():
    resolver = AwsSecretsCredentialResolver(FakeBackend(), aws_region="us-east-1")

    assert resolver.secret_arn_path("t1", "anthropic") == "aether/credentials/t1/llm/anthropic"
    assert resolver.secret_arn_path("t1", "openai") == "aether/credentials/t1/llm/openai"


def test_secret_arn_path_rejects_escaping_provider():
    resolver = AwsSecretsCredentialResolver(FakeBackend(), aws_region="us-east-1")

    for bad in ("../other", "llm/../x", "a/b", "..", ".hidden"):
        try:
            resolver.secret_arn_path("t1", bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"escaped scope accepted for provider {bad!r}")


def test_is_configured_false_without_aws_env(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    resolver = AwsSecretsCredentialResolver(FakeBackend(ready=True))

    assert resolver.is_configured("anthropic") is False


def test_is_configured_true_with_region_and_ready_backend(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    resolver = AwsSecretsCredentialResolver(FakeBackend(ready=True))

    assert resolver.is_configured("anthropic") is True


def test_is_configured_true_with_aws_region_kwarg():
    resolver = AwsSecretsCredentialResolver(FakeBackend(ready=True), aws_region="eu-west-1")

    assert resolver.is_configured("anthropic") is True


def test_is_configured_false_when_backend_not_ready(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    resolver = AwsSecretsCredentialResolver(FakeBackend(ready=False))

    assert resolver.is_configured("anthropic") is False


async def test_cache_hit_skips_backend():
    fake = FakeBackend(stored={"llm/openai": ("****1111", "sk-openai-raw-11111111")})
    cache = CredentialCache()
    resolver = AwsSecretsCredentialResolver(fake, cache=cache, aws_region="us-east-1")
    now = datetime.now(timezone.utc)
    await cache.put(
        make_metadata(
            tenant_id="t1",
            ref="llm/openai",
            credential_type="api_key",
            version=1,
            lifecycle_status=STATUS_ACTIVE,
            masked_identifier="****1111",
            created_at=now,
            updated_at=now,
        )
    )

    resolution = await resolver.resolve("t1", "openai")

    assert resolution.configured is True
    assert resolution.resolved is True
    assert resolution.source == "secret_backend"
    assert resolution.masked_identifier == "****1111"
    assert fake.metadata_calls == []  # backend never consulted


async def test_second_resolve_hits_cache():
    fake = FakeBackend(stored={"llm/openai": ("****1111", "sk-openai-raw-11111111")})
    resolver = AwsSecretsCredentialResolver(fake, cache=CredentialCache(), aws_region="us-east-1")

    await resolver.resolve("t1", "openai")
    await resolver.resolve("t1", "openai")

    assert fake.metadata_calls == [("t1", "llm/openai")]  # backend consulted once


async def test_resolution_never_contains_raw_secret():
    raw = "sk-ant-raw-secret-0123456789abcdef"
    fake = FakeBackend(stored={"llm/anthropic": ("****a1b2", raw)})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is True
    assert fake.get_calls == []  # plaintext seam never touched
    assert raw not in str(resolution)
    assert raw not in resolution.reason
    assert raw not in (resolution.masked_identifier or "")
    # A's contract helper agrees: the resolution carries no raw secret strings.
    assert_no_raw_secrets(resolution.reason, resolution.masked_identifier or "")


async def test_health_delegates_to_backend():
    healthy = AwsSecretsCredentialResolver(FakeBackend(ready=True))
    assert await healthy.health() is True
    assert healthy._backend.health_calls == 1

    unhealthy = AwsSecretsCredentialResolver(FakeBackend(ready=False))
    assert await unhealthy.health() is False


# ---------------------------------------------- revoked / expired rejection


def _revoked_meta(ref: str, masked: str = "****a1b2") -> CredentialMetadata:
    """Metadata carrying a revoked lifecycle status (readiness=DISABLED)."""
    now = datetime.now(timezone.utc)
    return make_metadata(
        tenant_id="t1",
        ref=ref,
        credential_type="api_key",
        version=1,
        lifecycle_status=STATUS_REVOKED,
        masked_identifier=masked,
        created_at=now,
        updated_at=now,
        revoked_at=now,
    )


def _degraded_meta(ref: str, masked: str = "****1111") -> CredentialMetadata:
    """Metadata whose past expiry projects to readiness=DEGRADED."""
    now = datetime.now(timezone.utc)
    return make_metadata(
        tenant_id="t1",
        ref=ref,
        credential_type="api_key",
        version=1,
        lifecycle_status=STATUS_ACTIVE,
        masked_identifier=masked,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )


def _expired_live_meta(ref: str, masked: str = "****2222") -> CredentialMetadata:
    """A status snapshot that predates expiry: status still live, but the aware
    ``expires_at`` has already passed (rejected on the expiry check alone)."""
    now = datetime.now(timezone.utc)
    return CredentialMetadata(
        tenant_id="t1",
        ref=ref,
        credential_type="api_key",
        version=1,
        status=CredentialReadiness.PARTNER_LIVE,
        masked_identifier=masked,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )


async def test_revoked_metadata_is_not_serviceable():
    fake = FakeBackend(metadata_overrides={"llm/anthropic": _revoked_meta("llm/anthropic")})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is False
    assert resolution.resolved is True
    assert resolution.source == "none"
    assert resolution.reason == "aws secret revoked"
    assert resolution.masked_identifier is None


async def test_degraded_metadata_is_not_serviceable():
    fake = FakeBackend(metadata_overrides={"llm/openai": _degraded_meta("llm/openai")})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "openai")

    assert resolution.configured is False
    assert resolution.resolved is True
    assert resolution.reason == "aws secret degraded"


async def test_expired_metadata_is_not_serviceable():
    # status is live (PARTNER_LIVE) but the aware expires_at has passed.
    fake = FakeBackend(metadata_overrides={"llm/openai": _expired_live_meta("llm/openai")})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "openai")

    assert resolution.configured is False
    assert resolution.resolved is True
    assert resolution.reason == "aws secret expired"


async def test_live_metadata_with_future_expiry_is_serviceable():
    now = datetime.now(timezone.utc)
    live = make_metadata(
        tenant_id="t1",
        ref="llm/openai",
        credential_type="api_key",
        version=1,
        lifecycle_status=STATUS_ACTIVE,
        masked_identifier="****1111",
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        expires_at=now + timedelta(days=30),
    )
    fake = FakeBackend(metadata_overrides={"llm/openai": live})
    resolver = AwsSecretsCredentialResolver(fake, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "openai")

    assert resolution.configured is True
    assert resolution.resolved is True
    assert resolution.source == "secret_backend"
    assert resolution.reason == "resolved from aws secrets manager"


async def test_unusable_metadata_is_not_cached():
    cache = CredentialCache()
    fake = FakeBackend(metadata_overrides={"llm/anthropic": _revoked_meta("llm/anthropic")})
    resolver = AwsSecretsCredentialResolver(fake, cache=cache, aws_region="us-east-1")

    r1 = await resolver.resolve("t1", "anthropic")
    r2 = await resolver.resolve("t1", "anthropic")

    assert r1.configured is False
    assert r2.configured is False
    # The unusable metadata was never cached, so the second resolve re-hit the
    # backend instead of being served from a stale cache.
    assert fake.metadata_calls == [("t1", "llm/anthropic"), ("t1", "llm/anthropic")]


async def test_cached_revoked_metadata_is_not_serviceable():
    cache = CredentialCache()
    await cache.put(_revoked_meta("llm/anthropic"))
    fake = FakeBackend()  # nothing stored; the (revoked) cache must not serve
    resolver = AwsSecretsCredentialResolver(fake, cache=cache, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "anthropic")

    assert resolution.configured is False
    assert resolution.resolved is True
    assert resolution.reason == "aws secret revoked"
    assert fake.metadata_calls == []  # cache short-circuited, but rejected


async def test_cached_expired_metadata_is_not_serviceable():
    cache = CredentialCache()
    await cache.put(_expired_live_meta("llm/openai"))
    fake = FakeBackend()
    resolver = AwsSecretsCredentialResolver(fake, cache=cache, aws_region="us-east-1")

    resolution = await resolver.resolve("t1", "openai")

    assert resolution.configured is False
    assert resolution.resolved is True
    assert resolution.reason == "aws secret expired"
    assert fake.metadata_calls == []  # cache short-circuited, but rejected
