"""Model-runtime credential resolution models — secret-free contract tests."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError

from services.model_runtime.credentials.models import (
    REDACT_PATTERNS,
    CredentialBackendUnavailable,
    CredentialNotResolved,
    CredentialResolution,
    CredentialResolverError,
    CredentialUnsafe,
    ResolverConfig,
    RotationDecision,
    assert_no_raw_secrets,
    mask_identifier,
)

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _raises(exc_type, call):
    """Assert that ``call()`` raises ``exc_type``, using only plain asserts."""
    try:
        call()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def test_credential_resolution_round_trip():
    res = CredentialResolution(
        provider="anthropic",
        tenant_id="tenant-1",
        ref="llm/anthropic-primary",
        resolved=True,
        configured=True,
        masked_identifier="****1a2b",
        source="secret_backend",
        rotated_at=_EPOCH,
        expires_at=None,
        reason="primary key",
    )
    assert res.provider == "anthropic"
    assert res.tenant_id == "tenant-1"
    assert res.ref == "llm/anthropic-primary"
    assert res.resolved is True
    assert res.configured is True
    assert res.masked_identifier == "****1a2b"
    assert res.source == "secret_backend"
    assert res.rotated_at == _EPOCH
    assert res.expires_at is None
    assert res.reason == "primary key"


def test_credential_resolution_defaults():
    res = CredentialResolution(
        provider="openai",
        tenant_id="t1",
        ref="r1",
        resolved=False,
        configured=False,
    )
    assert res.masked_identifier is None
    assert res.source == "none"
    assert res.rotated_at is None
    assert res.expires_at is None
    assert res.reason == ""


def test_credential_resolution_frozen():
    res = CredentialResolution(
        provider="a", tenant_id="t", ref="r", resolved=True, configured=True
    )
    _raises(ValidationError, lambda: setattr(res, "resolved", False))
    _raises(ValidationError, lambda: setattr(res, "reason", "x"))


def test_credential_resolution_forbids_extra():
    _raises(
        ValidationError,
        lambda: CredentialResolution(
            provider="a",
            tenant_id="t",
            ref="r",
            resolved=True,
            configured=True,
            bogus=1,
        ),
    )


def test_credential_resolution_source_literal():
    _raises(
        ValidationError,
        lambda: CredentialResolution(
            provider="a",
            tenant_id="t",
            ref="r",
            resolved=True,
            configured=True,
            source="vault",
        ),
    )


def test_masked_identifier_rejects_raw_secret():
    _raises(
        CredentialUnsafe,
        lambda: CredentialResolution(
            provider="a",
            tenant_id="t",
            ref="r",
            resolved=True,
            configured=True,
            masked_identifier="sk-abc123",
        ),
    )
    # A benign masked form is accepted.
    res = CredentialResolution(
        provider="a",
        tenant_id="t",
        ref="r",
        resolved=True,
        configured=True,
        masked_identifier="****a1b2",
    )
    assert res.masked_identifier == "****a1b2"


def test_resolver_config_fail_closed_default():
    cfg = ResolverConfig()
    assert cfg.enabled is False  # fail-closed: off by default
    assert cfg.backend == "in_memory"
    assert cfg.aws_region is None
    assert cfg.aws_secrets_prefix == "aether/credentials"
    assert cfg.rotation_grace_seconds == 300
    assert cfg.cache_ttl_seconds == 60


def test_resolver_config_round_trip():
    cfg = ResolverConfig(
        enabled=True,
        backend="aws_secrets_manager",
        aws_region="us-east-1",
        aws_secrets_prefix="aether/credentials",
        rotation_grace_seconds=900,
        cache_ttl_seconds=120,
    )
    assert cfg.enabled is True
    assert cfg.backend == "aws_secrets_manager"
    assert cfg.aws_region == "us-east-1"
    assert cfg.aws_secrets_prefix == "aether/credentials"
    assert cfg.rotation_grace_seconds == 900
    assert cfg.cache_ttl_seconds == 120


def test_resolver_config_rejects_non_positive_cache_ttl():
    _raises(ValidationError, lambda: ResolverConfig(cache_ttl_seconds=0))
    _raises(ValidationError, lambda: ResolverConfig(cache_ttl_seconds=-1))


def test_resolver_config_forbids_extra():
    _raises(ValidationError, lambda: ResolverConfig(enabled=True, bogus=True))


def test_rotation_decision_round_trip():
    dec = RotationDecision(
        ref="llm/anthropic-primary",
        should_rotate=True,
        reason="within grace window",
        expires_at=_EPOCH,
    )
    assert dec.ref == "llm/anthropic-primary"
    assert dec.should_rotate is True
    assert dec.reason == "within grace window"
    assert dec.expires_at == _EPOCH
    noop = RotationDecision(ref="r", should_rotate=False)
    assert noop.reason == ""
    assert noop.expires_at is None


def test_error_hierarchy():
    assert issubclass(CredentialNotResolved, CredentialResolverError)
    assert issubclass(CredentialBackendUnavailable, CredentialResolverError)
    assert issubclass(CredentialUnsafe, CredentialResolverError)
    assert issubclass(CredentialResolverError, Exception)
    # Siblings are distinct classes.
    assert CredentialNotResolved is not CredentialBackendUnavailable
    assert CredentialNotResolved is not CredentialUnsafe


def test_assert_no_raw_secrets_rejects_each_pattern():
    samples = {
        "sk-": "sk-abc123def456",
        "AKIA": "AKIAIOSFODNN7EXAMPLE",
        "Bearer ": "Bearer eyJhbGciOiJIUzI1NiJ9",
        "-----BEGIN": "-----BEGIN PRIVATE KEY-----\nMII",
        "key=": "api_key=sk-abc",
        "secret=": "client_secret=hunter2",
    }
    assert set(samples) == set(REDACT_PATTERNS)
    for value in samples.values():
        _raises(CredentialUnsafe, lambda v=value: assert_no_raw_secrets(v))


def test_assert_no_raw_secrets_passes_benign():
    assert assert_no_raw_secrets() is None
    assert assert_no_raw_secrets("") is None
    for benign in (
        "provider-anthropic",
        "resolved via secret backend",
        "rotation in progress",
        "00000000-0000-0000-0000-000000000000",
        "****1a2b",
        "anthropic:claude-3-5",
    ):
        assert assert_no_raw_secrets(benign) is None


def test_mask_identifier_format_and_safety():
    mid = mask_identifier("sk-secret-value")
    assert mid.startswith("****")
    assert len(mid) == 8
    assert mid[4:] == mid[4:].lower()
    assert mid.isalnum() is False  # starts with the "****" literal prefix
    # The masked output never matches a redact pattern, so it can never be
    # mistaken for (or re-derived into) raw secret material.
    assert_no_raw_secrets(mid)
