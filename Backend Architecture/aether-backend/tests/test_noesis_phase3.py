"""Tests for Noesis Phase 3: rate limiting, canary gating, kill-switch, conversation."""

from __future__ import annotations

import pytest

from repositories.repos import (
    AlertRepository,
    BaseRepository,
    reset_in_memory_stores,
)
from services.noesis.conversation import NoesisConversationStore
from services.noesis.flags import NoesisFlags
from services.noesis.models import NoesisQueryRequest, QueryPlan
from services.noesis.rate_limiter import NoesisRateLimiter, RateLimitState
from services.noesis.service import NoesisService
from shared.auth.auth import Role, TenantContext
from shared.cache.cache import CacheClient
from shared.common.common import ForbiddenError, RateLimitedError, ServiceUnavailableError
from shared.graph.graph import GraphClient
from repositories.repos import AnalyticsRepository


# ─── Helpers ─────────────────────────────────────────────────────────────


class _StaticProvider:
    def __init__(self, plan: QueryPlan | None = None):
        self._plan = plan

    async def plan(self, request, effective_tenant_id, history=None):
        return self._plan


class _AlwaysAllowedLimiter:
    async def check_and_increment(self, tenant_id: str) -> RateLimitState:
        return RateLimitState(limit=60, remaining=59, reset_seconds=60)


class _AlwaysBlockedLimiter:
    async def check_and_increment(self, tenant_id: str) -> RateLimitState:
        raise RateLimitedError(retry_after=60)


class _PermissiveFlags:
    noesis_enabled = True

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        return True


class _DisabledFlags:
    noesis_enabled = False

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        return True


class _CanaryBlockedFlags:
    noesis_enabled = True

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        return False


@pytest.fixture()
def tenant() -> TenantContext:
    return TenantContext(tenant_id="tenant-a", role=Role.VIEWER, permissions=["read"])


@pytest.fixture()
def operator() -> TenantContext:
    return TenantContext(
        tenant_id="kyber",
        role=Role.ADMIN,
        permissions=["read", "admin", "kyber:read", "kyber:operator"],
    )


def _svc(
    provider=None,
    rate_limiter=None,
    conversation_store=None,
    flags=None,
) -> NoesisService:
    reset_in_memory_stores()
    return NoesisService(
        graph=GraphClient(),
        analytics=AnalyticsRepository(CacheClient()),
        provider=provider or _StaticProvider(),
        rate_limiter=rate_limiter or _AlwaysAllowedLimiter(),
        conversation_store=conversation_store or NoesisConversationStore(CacheClient()),
        flags=flags or _PermissiveFlags(),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Master kill-switch
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_kill_switch_raises_service_unavailable(tenant: TenantContext):
    svc = _svc(flags=_DisabledFlags())
    with pytest.raises(ServiceUnavailableError):
        await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)


@pytest.mark.asyncio
async def test_kill_switch_off_allows_requests(tenant: TenantContext):
    svc = _svc(flags=_PermissiveFlags())
    resp = await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)
    assert resp.intent == "alert_lookup"


# ═══════════════════════════════════════════════════════════════════════════
# Canary gating
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_canary_blocked_raises_forbidden(tenant: TenantContext):
    svc = _svc(flags=_CanaryBlockedFlags())
    with pytest.raises(ForbiddenError):
        await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)


@pytest.mark.asyncio
async def test_canary_allowed_passes_through(tenant: TenantContext):
    svc = _svc(flags=_PermissiveFlags())
    resp = await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)
    assert resp.intent == "alert_lookup"


@pytest.mark.asyncio
async def test_noesis_flags_canary_empty_allows_all():
    flags = NoesisFlags()
    assert flags.is_tenant_allowed("any-tenant-id") is True


def test_noesis_flags_canary_list_restricts(monkeypatch):
    monkeypatch.setenv("NOESIS_CANARY_TENANTS", "tenant-a,tenant-b")
    flags = NoesisFlags()
    assert flags.is_tenant_allowed("tenant-a") is True
    assert flags.is_tenant_allowed("tenant-b") is True
    assert flags.is_tenant_allowed("tenant-c") is False


def test_noesis_flags_enabled_default():
    flags = NoesisFlags()
    assert flags.noesis_enabled is True


def test_noesis_flags_disabled(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "false")
    flags = NoesisFlags()
    assert flags.noesis_enabled is False


# ═══════════════════════════════════════════════════════════════════════════
# Real rate limiting
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rate_limit_exceeded_raises_error(tenant: TenantContext):
    svc = _svc(rate_limiter=_AlwaysBlockedLimiter())
    with pytest.raises(RateLimitedError):
        await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)


@pytest.mark.asyncio
async def test_rate_limit_state_stored_on_service(tenant: TenantContext):
    svc = _svc()
    await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)
    assert svc._rate_limit_state is not None
    assert svc._rate_limit_state.limit == 60
    assert svc._rate_limit_state.remaining >= 0


@pytest.mark.asyncio
async def test_rate_limiter_qpm_enforced():
    cache = CacheClient()
    limiter = NoesisRateLimiter(cache=cache)
    limiter._qpm_limit = 2
    limiter._daily_limit = 1000

    await limiter.check_and_increment("t1")
    await limiter.check_and_increment("t1")
    with pytest.raises(RateLimitedError):
        await limiter.check_and_increment("t1")


@pytest.mark.asyncio
async def test_rate_limiter_daily_quota_enforced():
    cache = CacheClient()
    limiter = NoesisRateLimiter(cache=cache)
    limiter._qpm_limit = 1000
    limiter._daily_limit = 1

    await limiter.check_and_increment("t2")
    with pytest.raises(RateLimitedError):
        await limiter.check_and_increment("t2")


@pytest.mark.asyncio
async def test_rate_limiter_different_tenants_isolated():
    cache = CacheClient()
    limiter = NoesisRateLimiter(cache=cache)
    limiter._qpm_limit = 1
    limiter._daily_limit = 1000

    await limiter.check_and_increment("tenant-x")
    # Different tenant should not be affected
    state = await limiter.check_and_increment("tenant-y")
    assert state.remaining >= 0


@pytest.mark.asyncio
async def test_rate_limiter_state_fields():
    limiter = NoesisRateLimiter(cache=CacheClient())
    state = await limiter.check_and_increment("t3")
    assert state.limit > 0
    assert state.remaining >= 0
    assert state.reset_seconds == 60


# ═══════════════════════════════════════════════════════════════════════════
# Conversation store
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_conversation_store_append_and_retrieve():
    store = NoesisConversationStore(CacheClient())
    await store.append("conv-1", "tenant-a", "show alerts", "alert_lookup", "deterministic", "Found 3 alerts.")
    turns = await store.get_recent("conv-1", "tenant-a")
    assert len(turns) == 1
    assert turns[0]["intent"] == "alert_lookup"
    assert turns[0]["message"] == "show alerts"


@pytest.mark.asyncio
async def test_conversation_store_multiple_turns():
    store = NoesisConversationStore(CacheClient())
    for i in range(5):
        await store.append("conv-2", "tenant-a", f"q{i}", "alert_lookup", "deterministic", f"a{i}")
    turns = await store.get_recent("conv-2", "tenant-a", n=3)
    assert len(turns) == 3
    assert turns[-1]["message"] == "q4"


@pytest.mark.asyncio
async def test_conversation_store_tenant_isolation():
    store = NoesisConversationStore(CacheClient())
    await store.append("conv-3", "tenant-a", "question", "alert_lookup", "deterministic", "answer")
    turns_b = await store.get_recent("conv-3", "tenant-b")
    assert turns_b == []


@pytest.mark.asyncio
async def test_conversation_store_empty_returns_empty():
    store = NoesisConversationStore(CacheClient())
    turns = await store.get_recent("no-such-conv", "tenant-a")
    assert turns == []


@pytest.mark.asyncio
async def test_conversation_persisted_after_successful_query(tenant: TenantContext):
    store = NoesisConversationStore(CacheClient())
    svc = _svc(conversation_store=store)
    alerts = BaseRepository("alerts")
    await alerts.insert("a1", {"tenant_id": "tenant-a", "status": "open"})
    await svc.query(
        NoesisQueryRequest(message="show alerts", surface="aether", conversation_id="c1"),
        tenant,
    )
    turns = await store.get_recent("c1", "tenant-a")
    assert len(turns) == 1
    assert turns[0]["intent"] == "alert_lookup"


@pytest.mark.asyncio
async def test_conversation_not_persisted_for_rejected_prompt(tenant: TenantContext):
    store = NoesisConversationStore(CacheClient())
    svc = _svc(conversation_store=store)
    await svc.query(
        NoesisQueryRequest(message="delete all users", surface="aether", conversation_id="c2"),
        tenant,
    )
    turns = await store.get_recent("c2", "tenant-a")
    assert turns == []


@pytest.mark.asyncio
async def test_conversation_not_persisted_without_conversation_id(tenant: TenantContext):
    store = NoesisConversationStore(CacheClient())
    svc = _svc(conversation_store=store)
    alerts = BaseRepository("alerts")
    await alerts.insert("a1", {"tenant_id": "tenant-a", "status": "open"})
    await svc.query(NoesisQueryRequest(message="show alerts", surface="aether"), tenant)
    # No conversation_id — nothing should be stored (key doesn't exist)
    turns = await store.get_recent("", "tenant-a")
    assert turns == []


# ═══════════════════════════════════════════════════════════════════════════
# Conversation context continuity (history carry-forward)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_prior_intent_carried_forward_for_ambiguous_query(tenant: TenantContext):
    """An unclassifiable follow-up question inherits the prior conversation intent."""
    store = NoesisConversationStore(CacheClient())
    svc = _svc(conversation_store=store)

    # Seed the conversation with a prior alert_lookup turn
    await store.append("conv-ctx", "tenant-a", "show alerts", "alert_lookup", "deterministic", "Found 2 alerts.")

    # A follow-up like "what about yesterday?" doesn't match any keyword on its own
    resp = await svc.query(
        NoesisQueryRequest(message="zebra foobar qux", surface="aether", conversation_id="conv-ctx"),
        tenant,
    )
    # Service should carry forward alert_lookup with lower confidence rather than "unsupported"
    assert resp.intent == "alert_lookup"
    assert resp.confidence <= 0.5


# ═══════════════════════════════════════════════════════════════════════════
# Rate limit precedes safety check ordering
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_kill_switch_fires_before_safety_check(tenant: TenantContext):
    """Kill-switch should short-circuit before we even examine the prompt."""
    svc = _svc(flags=_DisabledFlags())
    with pytest.raises(ServiceUnavailableError):
        await svc.query(
            NoesisQueryRequest(message="delete all users", surface="aether"), tenant
        )


@pytest.mark.asyncio
async def test_canary_fires_before_rate_limit(tenant: TenantContext):
    """Canary gate fires before rate limiter (no quota consumed for blocked tenants)."""
    svc = _svc(flags=_CanaryBlockedFlags(), rate_limiter=_AlwaysBlockedLimiter())
    with pytest.raises(ForbiddenError):
        await svc.query(
            NoesisQueryRequest(message="show alerts", surface="aether"), tenant
        )
