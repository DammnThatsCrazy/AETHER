"""Credential rotation/revocation orchestration tests — ADR-008 D5.

Covers :class:`ExpiryBasedRotationPolicy` (deterministic, with an injected
clock) and :class:`RotationOrchestrator` (rotate invalidates the cache, revoke
fails closed, ``evaluate_all`` only decides and never rotates). Built on the
credential contracts from the credentials team: ``models.py`` rotation decision
record + ``interface.py`` ``CredentialSource`` / ``CredentialCache`` and the
``NoopCredentialSource`` test double. Plain ``assert`` only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.model_runtime.credentials.interface import (
    CredentialCache,
    NoopCredentialSource,
)
from services.model_runtime.credentials.models import CredentialBackendUnavailable
from services.model_runtime.credentials.rotation import (
    ExpiryBasedRotationPolicy,
    RotationOrchestrator,
)
from shared.credentials.interface import STATUS_ACTIVE, make_metadata

# Fixed clock so the expiry policy is fully deterministic.
NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=timezone.utc)
ONE_DAY = timedelta(days=1)


def _meta(
    *,
    ref: str = "llm-default",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    expires_at: datetime | None = None,
    version: int = 1,
):
    created = created_at if created_at is not None else NOW - ONE_DAY
    updated = updated_at if updated_at is not None else created
    return make_metadata(
        tenant_id="tenant-1",
        ref=ref,
        credential_type="provider_api_key",
        version=version,
        lifecycle_status=STATUS_ACTIVE,
        masked_identifier="****abcd",
        created_at=created,
        updated_at=updated,
        expires_at=expires_at,
    )


class RecordingCache(CredentialCache):
    """CredentialCache spy that records every invalidation."""

    def __init__(self) -> None:
        super().__init__()
        self.invalidated: list[tuple[str, str]] = []

    async def invalidate(self, tenant_id: str, ref: str) -> None:
        self.invalidated.append((tenant_id, ref))
        await super().invalidate(tenant_id, ref)


class FailingRotateSource(NoopCredentialSource):
    """Source whose rotation always fails at the backend."""

    async def rotate(self, tenant_id: str, ref: str):
        raise RuntimeError("secret backend unreachable")


class RevokeFalseSource(NoopCredentialSource):
    """Source that reports a failed revocation (returns False)."""

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        return False


class RevokeErrorSource(NoopCredentialSource):
    """Source whose revocation raises at the backend."""

    async def revoke(self, tenant_id: str, ref: str) -> bool:
        raise RuntimeError("secret backend unreachable")


# ---------------------------------------------------------------------- policy


async def test_policy_young_credential_no_rotate():
    policy = ExpiryBasedRotationPolicy(max_age_seconds=86400)
    meta = _meta(created_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(days=30))

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.ref == "llm-default"
    assert decision.should_rotate is False
    assert decision.reason == "not due for rotation"
    assert decision.expires_at == meta.expires_at


async def test_policy_past_max_age_rotates():
    policy = ExpiryBasedRotationPolicy(max_age_seconds=86400)
    meta = _meta(created_at=NOW - timedelta(days=2), expires_at=NOW + timedelta(days=30))

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.should_rotate is True
    assert "max age" in decision.reason


async def test_policy_recent_update_resets_staleness():
    # Created long ago but rotated/updated recently -> not stale by max age.
    policy = ExpiryBasedRotationPolicy(max_age_seconds=86400)
    meta = _meta(
        created_at=NOW - timedelta(days=5),
        updated_at=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=30),
    )

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.should_rotate is False


async def test_policy_within_grace_of_expiry_rotates():
    policy = ExpiryBasedRotationPolicy(grace_seconds=300)
    meta = _meta(created_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(minutes=2))

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.should_rotate is True
    assert "grace" in decision.reason


async def test_policy_expired_rotates():
    policy = ExpiryBasedRotationPolicy(grace_seconds=300)
    meta = _meta(created_at=NOW - timedelta(hours=1), expires_at=NOW - timedelta(minutes=5))

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.should_rotate is True


async def test_policy_no_expiry_no_max_age_no_rotate():
    policy = ExpiryBasedRotationPolicy()
    meta = _meta(created_at=NOW - timedelta(days=30), expires_at=None)

    decision = await policy.evaluate(meta, now=NOW)

    assert decision.should_rotate is False


# --------------------------------------------------------------- orchestrator


async def test_orchestrator_rotate_calls_source_and_invalidates_cache():
    source = NoopCredentialSource()
    source.put("tenant-1", "llm-default", _meta(version=1))
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(source, cache, policy=ExpiryBasedRotationPolicy())

    rotated = await orchestrator.rotate("tenant-1", "llm-default")

    assert rotated.ref == "llm-default"
    assert rotated.version == 2
    assert cache.invalidated == [("tenant-1", "llm-default")]
    loaded = await source.load("tenant-1", "llm-default")
    assert loaded.version == 2


async def test_orchestrator_rotate_failure_raises_and_keeps_cache():
    source = FailingRotateSource()
    source.put("tenant-1", "llm-default", _meta())
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(source, cache, policy=ExpiryBasedRotationPolicy())

    raised = False
    try:
        await orchestrator.rotate("tenant-1", "llm-default")
    except CredentialBackendUnavailable:
        raised = True
    assert raised is True
    assert cache.invalidated == []


async def test_orchestrator_rotate_without_cache_succeeds():
    # CredentialService forwards cache=None (ByokCredentialResolver permits an
    # absent cache); invalidation must be a no-op, never an AttributeError that
    # fails a rotation after the source already changed the credential.
    source = NoopCredentialSource()
    source.put("tenant-1", "llm-default", _meta(version=1))
    orchestrator = RotationOrchestrator(source, None, policy=ExpiryBasedRotationPolicy())

    rotated = await orchestrator.rotate("tenant-1", "llm-default")

    assert rotated.ref == "llm-default"
    assert rotated.version == 2
    loaded = await source.load("tenant-1", "llm-default")
    assert loaded.version == 2  # source rotation actually happened


async def test_orchestrator_revoke_without_cache_succeeds():
    # Same absent-cache configuration on the revoke path.
    source = NoopCredentialSource()
    source.put("tenant-1", "llm-default", _meta())
    orchestrator = RotationOrchestrator(source, None, policy=ExpiryBasedRotationPolicy())

    result = await orchestrator.revoke("tenant-1", "llm-default")

    assert result is True
    loaded = await source.load("tenant-1", "llm-default")
    assert loaded.version == 1  # revoked, not rotated


async def test_orchestrator_revoke_success_invalidates_cache():
    source = NoopCredentialSource()
    source.put("tenant-1", "llm-default", _meta())
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(source, cache, policy=ExpiryBasedRotationPolicy())

    result = await orchestrator.revoke("tenant-1", "llm-default")

    assert result is True
    assert cache.invalidated == [("tenant-1", "llm-default")]


async def test_orchestrator_revoke_failure_returns_false_keeps_cache():
    source = RevokeFalseSource()
    source.put("tenant-1", "llm-default", _meta())
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(source, cache, policy=ExpiryBasedRotationPolicy())

    result = await orchestrator.revoke("tenant-1", "llm-default")

    assert result is False
    assert cache.invalidated == []


async def test_orchestrator_revoke_error_returns_false_keeps_cache():
    source = RevokeErrorSource()
    source.put("tenant-1", "llm-default", _meta())
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(source, cache, policy=ExpiryBasedRotationPolicy())

    result = await orchestrator.revoke("tenant-1", "llm-default")

    assert result is False
    assert cache.invalidated == []


async def test_evaluate_all_returns_decisions_without_rotating():
    source = NoopCredentialSource()
    source.put(
        "tenant-1",
        "ref-a",
        _meta(ref="ref-a", created_at=NOW - timedelta(hours=1), expires_at=NOW + timedelta(days=30)),
    )
    source.put(
        "tenant-1",
        "ref-b",
        _meta(ref="ref-b", created_at=NOW - timedelta(days=2), expires_at=NOW + timedelta(days=30)),
    )
    cache = RecordingCache()
    orchestrator = RotationOrchestrator(
        source,
        cache,
        policy=ExpiryBasedRotationPolicy(max_age_seconds=86400),
    )

    decisions = await orchestrator.evaluate_all("tenant-1", ["ref-a", "ref-b"], now=NOW)

    assert [d.ref for d in decisions] == ["ref-a", "ref-b"]
    assert decisions[0].should_rotate is False
    assert decisions[1].should_rotate is True
    # decision-only: nothing rotated, cache untouched
    assert cache.invalidated == []
    assert (await source.load("tenant-1", "ref-a")).version == 1
    assert (await source.load("tenant-1", "ref-b")).version == 1
