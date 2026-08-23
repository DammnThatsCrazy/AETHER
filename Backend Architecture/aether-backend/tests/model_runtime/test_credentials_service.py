"""Tests for the ``CredentialService`` facade (ADR-008 D5, Agent F).

Exercises the fail-closed D9 feature gate, resolver delegation, masked-only
metadata listing, rotation/revocation delegation, health, audit-safe
``describe()``, and a clean package-root import of the public API. BYOK over
the no-op source is used throughout (plus a small number of stub sources to
exercise delegation edges that Noop cannot reach).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.certification.readiness import CredentialReadiness
from shared.credentials.interface import STATUS_ACTIVE, CredentialMetadata, make_metadata
from services.model_runtime.credentials.aws_source import AwsCredentialSource
from services.model_runtime.credentials import (
    AwsSecretsCredentialResolver,
    ByokCredentialResolver,
    CredentialBackendUnavailable,
    CredentialCache,
    CredentialNotResolved,
    CredentialResolution,
    CredentialResolverError,
    CredentialService,
    CredentialSource,
    CredentialUnsafe,
    ExpiryBasedRotationPolicy,
    NoopCredentialSource,
    ProviderCredentialResolver,
    REDACT_PATTERNS,
    ResolverConfig,
    RotationDecision,
    RotationOrchestrator,
    RotationPolicy,
    assert_no_raw_secrets,
    mask_identifier,
)

_ENV_REF = "AETHER_LLM_API_KEY"


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


def _resolver(source: CredentialSource | None = None) -> ByokCredentialResolver:
    """BYOK resolver over the given (default no-op) source + a real cache."""
    return ByokCredentialResolver(
        source if source is not None else NoopCredentialSource(),
        CredentialCache(),
        env_credential_ref=_ENV_REF,
    )


class _MinimalAwsBackend:
    """Minimal ``CredentialBackendLike`` stub for the AWS resolver (no AWS).

    Exposes just enough for the service facade seam: metadata/list/revoke plus
    the sync readiness signal the resolver's ``is_configured`` uses. Rotate is
    not exercised by the seam test below.
    """

    def __init__(self, stored: dict[str, str] | None = None) -> None:
        self._stored = dict(stored or {})
        self.revoke_calls: list[tuple[str, str]] = []

    def is_ready(self) -> bool:
        return True

    async def get(self, tenant_id: str, ref: str):
        return None

    async def metadata(self, tenant_id: str, ref: str):
        masked = self._stored.get(ref)
        if masked is None:
            return None
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

    async def list(self, tenant_id: str):
        now = datetime.now(timezone.utc)
        return [
            make_metadata(
                tenant_id=tenant_id,
                ref=ref,
                credential_type="api_key",
                version=1,
                lifecycle_status=STATUS_ACTIVE,
                masked_identifier=masked,
                created_at=now,
                updated_at=now,
            )
            for ref, masked in self._stored.items()
        ]

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        self.revoke_calls.append((tenant_id, ref))
        return ref in self._stored

    async def rotate(self, tenant_id: str, ref: str, credential):
        raise AssertionError("not exercised by the service-seam test")

    async def health_check(self):
        from shared.credentials.interface import CredentialBackendHealth

        return CredentialBackendHealth(backend="minimal", durable=True, healthy=True)


# ---------------------------------------------------------------------------
# Resolve: D9 fail-closed feature gate
# ---------------------------------------------------------------------------


async def test_resolve_disabled_by_default():
    # No config passed -> ResolverConfig() -> enabled=False (D9, default OFF).
    service = CredentialService(_resolver())
    res = await service.resolve("tenant-1", "anthropic")
    assert isinstance(res, CredentialResolution)
    assert res.configured is False
    assert res.resolved is False
    assert res.reason == "credential resolution disabled"
    assert res.provider == "anthropic"
    assert res.tenant_id == "tenant-1"
    assert res.masked_identifier is None
    assert res.source == "none"


class _ExplodingResolver:
    """Resolver that raises if it is ever reached (gate-priority probe)."""

    def is_configured(self, provider: str) -> bool:
        return True

    async def resolve(self, tenant_id: str, provider: str) -> CredentialResolution:
        raise AssertionError("resolver must not be called while the gate is disabled")

    async def health(self) -> bool:
        return True


async def test_disabled_gate_does_not_touch_resolver():
    service = CredentialService(_ExplodingResolver())
    res = await service.resolve("tenant-1", "openai")
    assert res.configured is False
    assert res.reason == "credential resolution disabled"
    # A configured credential exists via env, yet the gate still wins.
    assert res.ref == "disabled:openai:tenant-1"


async def test_resolve_enabled_delegates_to_resolver(monkeypatch):
    # With a resolvable tenant-scoped env key present, enabled=True must
    # delegate rather than short-circuit on the (disabled) marker.
    monkeypatch.setenv("TENANT-1_ANTHROPIC_API_KEY", "sk-credential-integration-test-0000")
    service = CredentialService(_resolver(), config=ResolverConfig(enabled=True))
    res = await service.resolve("tenant-1", "anthropic")
    assert res.reason != "credential resolution disabled"
    assert res.provider == "anthropic"
    assert res.tenant_id == "tenant-1"
    assert isinstance(res.configured, bool)
    # Fail-closed: the raw key never surfaces in any serialized field.
    assert "sk-credential-integration-test" not in res.model_dump_json()


# ---------------------------------------------------------------------------
# List metadata: masked-only
# ---------------------------------------------------------------------------


async def test_list_metadata_noop_source_returns_empty():
    # Noop exposes no list surface -> the facade returns [] (trivially masked).
    service = CredentialService(_resolver())
    assert await service.list_metadata("tenant-1") == []


class _ListingSource(NoopCredentialSource):
    """Noop source that additionally exposes a ``list`` surface."""

    def __init__(self, items: list[CredentialMetadata] | None = None) -> None:
        super().__init__()
        self._items = list(items or [])
        self.list_calls = 0

    def list(self, tenant_id: str) -> list[CredentialMetadata]:
        self.list_calls += 1
        return list(self._items)


async def test_list_metadata_delegates_to_source_list_surface():
    src = _ListingSource([_make_meta()])
    service = CredentialService(_resolver(src))
    items = await service.list_metadata("tenant-1")
    assert src.list_calls == 1
    assert len(items) == 1
    item = items[0]
    assert item.ref == "ref-1"
    assert item.tenant_id == "tenant-1"
    assert item.masked_identifier == "****abcd"
    # Masked-only: no raw secret material anywhere in the serialized view.
    text = item.model_dump_json()
    for token in ("sk-", "AKIA", "Bearer ", "api_key=", "secret="):
        assert token not in text


# ---------------------------------------------------------------------------
# Rotate
# ---------------------------------------------------------------------------


async def test_rotate_without_policy_returns_none():
    service = CredentialService(_resolver())
    assert await service.rotate("tenant-1", "ref-1") is None


async def test_rotate_with_policy_returns_new_metadata():
    src = NoopCredentialSource()
    src.put("tenant-1", "ref-1", _make_meta(version=3))
    service = CredentialService(
        _resolver(src),
        rotation_policy=ExpiryBasedRotationPolicy(max_age_seconds=1),
    )
    result = await service.rotate("tenant-1", "ref-1")
    assert result is not None
    assert result.ref == "ref-1"
    assert result.version == 4
    assert result.rotated_at is not None
    assert result.revoked_at is None
    # The rotation is durable on the source (no stale version served).
    assert (await src.load("tenant-1", "ref-1")).version == 4


async def test_rotate_unknown_ref_fails_closed():
    service = CredentialService(
        _resolver(),
        rotation_policy=ExpiryBasedRotationPolicy(),
    )
    with pytest.raises(CredentialBackendUnavailable):
        await service.rotate("tenant-1", "ref-1")


# ---------------------------------------------------------------------------
# Revoke
# ---------------------------------------------------------------------------


async def test_revoke_seeded_credential_returns_true():
    src = NoopCredentialSource()
    src.put("tenant-1", "ref-1", _make_meta())
    service = CredentialService(_resolver(src))
    assert await service.revoke("tenant-1", "ref-1") is True
    after = await src.load("tenant-1", "ref-1")
    assert after.status == CredentialReadiness.DISABLED
    assert after.revoked_at is not None


async def test_revoke_unknown_ref_returns_false():
    # Empty Noop source -> source.revoke raises CredentialNotResolved, which the
    # facade swallows (fail closed) instead of surfacing backend noise.
    service = CredentialService(_resolver())
    assert await service.revoke("tenant-1", "ref-1") is False


class _NoRevokeSource(NoopCredentialSource):
    """Noop source without a revoke surface."""

    revoke = None  # type: ignore[assignment]


async def test_revoke_without_source_revoke_surface_returns_false():
    service = CredentialService(_resolver(_NoRevokeSource()))
    assert await service.revoke("tenant-1", "ref-1") is False


# ---------------------------------------------------------------------------
# Health + audit-safe describe
# ---------------------------------------------------------------------------


async def test_health_delegates_to_resolver():
    service = CredentialService(_resolver())
    result = await service.health()
    assert isinstance(result, bool)
    assert result is True


def test_describe_is_audit_safe_no_secrets():
    service = CredentialService(_resolver(), config=ResolverConfig(enabled=True))
    line = service.describe()
    assert isinstance(line, str)
    assert line
    assert "ByokCredentialResolver" in line
    assert "enabled=True" in line
    for token in ("sk-", "AKIA", "Bearer", "-----BEGIN", "key=", "secret="):
        assert token not in line


def test_describe_reports_disabled_gate():
    line = CredentialService(_resolver()).describe()
    assert "enabled=False" in line


# ---------------------------------------------------------------------------
# Redaction guard + package surface
# ---------------------------------------------------------------------------


def test_redact_guard_rejects_raw_secrets():
    for sample in ("sk-abc123def456", "AKIAIOSFODNN7EXAMPLE", "Bearer eyJhbGciOiJIUzI1NiJ9"):
        with pytest.raises(CredentialUnsafe):
            assert_no_raw_secrets(sample)
    # Benign masked/operational strings pass.
    assert assert_no_raw_secrets("provider-anthropic", "****1a2b") is None
    assert mask_identifier("sk-secret").startswith("****")


def test_package_imports_cleanly():
    import services.model_runtime.credentials as credentials_pkg

    for name in (
        "AwsSecretsCredentialResolver",
        "ByokCredentialResolver",
        "CredentialBackendUnavailable",
        "CredentialCache",
        "CredentialNotResolved",
        "CredentialResolution",
        "CredentialResolverError",
        "CredentialService",
        "CredentialSource",
        "CredentialUnsafe",
        "ExpiryBasedRotationPolicy",
        "NoopCredentialSource",
        "ProviderCredentialResolver",
        "REDACT_PATTERNS",
        "ResolverConfig",
        "RotationDecision",
        "RotationOrchestrator",
        "RotationPolicy",
        "assert_no_raw_secrets",
        "mask_identifier",
    ):
        assert getattr(credentials_pkg, name) is not None, name
    assert set(("sk-", "AKIA", "Bearer ", "-----BEGIN", "key=", "secret=")).issubset(
        set(REDACT_PATTERNS)
    )
    assert CredentialService is credentials_pkg.CredentialService


# ---------------------------------------------------------------------------
# AWS resolver: lifecycle source seam (regression for the _source() None bug)
# ---------------------------------------------------------------------------


async def test_aws_resolver_service_source_seam_is_not_none():
    # Regression: AwsSecretsCredentialResolver stores its backend as ``_backend``,
    # so the source seam used to return None — making list_metadata always empty,
    # revoke always False, and rotation build an orchestrator with a None source.
    backend = _MinimalAwsBackend(stored={"llm/anthropic": "****a1b2"})
    resolver = AwsSecretsCredentialResolver(backend, aws_region="us-east-1")
    service = CredentialService(resolver)

    # The seam that feeds list/revoke/rotation adapts the AWS resolver to a real
    # CredentialSource — never None.
    source = service._source()
    assert isinstance(source, AwsCredentialSource)

    # The facade's AWS-backed controls operate: non-empty real metadata list and
    # a revoke that actually calls through to the backend.
    items = await service.list_metadata("t1")
    assert len(items) == 1
    assert items[0].ref == "llm/anthropic"
    assert items[0].masked_identifier == "****a1b2"
    assert await service.revoke("t1", "llm/anthropic") is True
    assert backend.revoke_calls == [("t1", "llm/anthropic")]
