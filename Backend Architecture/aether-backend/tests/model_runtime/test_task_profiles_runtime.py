"""Task-profile RUNTIME tests — ProfileVersionResolver + TaskProfileRuntime.

Covers Commit 7's versioned runtime on top of Commit 5's profile registry:
version resolution (default/explicit/unknown/version-map injection),
action-kind guardrail enforcement (read_only write rejection, read
acceptance, tenant_scope presence), and execute() routing honoring a
profile's default mode. Plain asserts against the real generated registry.
"""
from __future__ import annotations

import pytest

from services.model_runtime.routing.engine import ModelRouter
from services.model_runtime.routing.entitlements import AllowlistEntitlementResolver
from services.model_runtime.routing.fallback import StaticFallbackChain
from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingPolicyViolation,
    RoutingUnavailable,
)
from services.model_runtime.routing.profiles import ProfileNotFound, ProfileRegistry
from services.model_runtime.task_profiles.runtime import (
    ProfileVersionNotFound,
    ProfileVersionResolver,
    TaskProfileRuntime,
)
from shared.model_governance.generated_model_registry import MODEL_REGISTRY_MODELS
from shared.model_governance.generated_task_profiles import TASK_PROFILES


def _recommended_model_id() -> str:
    """First 'recommended' model id in the generated registry (auto-routing pick)."""
    return next(
        str(entry["modelId"])
        for entry in MODEL_REGISTRY_MODELS
        if entry.get("status") == "recommended"
    )


# ------------------------------------------------------------------- resolver


def test_resolver_returns_default_version():
    registry = ProfileRegistry()
    resolver = ProfileVersionResolver(registry)
    profile = resolver.resolve("noesis_query_planning")
    assert profile.profile_id == "noesis_query_planning"
    assert profile.version == 1  # generated registry ships version 1


def test_resolver_returns_explicit_version():
    registry = ProfileRegistry()
    resolver = ProfileVersionResolver(registry)
    profile = resolver.resolve("noesis_query_planning", version=1)
    assert profile.profile_id == "noesis_query_planning"
    assert profile.version == 1


def test_resolver_unknown_profile_raises():
    registry = ProfileRegistry()
    resolver = ProfileVersionResolver(registry)
    with pytest.raises(ProfileNotFound):
        resolver.resolve("does_not_exist")
    with pytest.raises(KeyError):  # ProfileNotFound is a KeyError
        resolver.resolve("does_not_exist")


def test_resolver_unknown_version_raises():
    registry = ProfileRegistry()
    resolver = ProfileVersionResolver(registry)
    with pytest.raises(ProfileVersionNotFound):
        resolver.resolve("noesis_query_planning", version=99)
    # ProfileVersionNotFound stays catchable as ProfileNotFound / KeyError.
    with pytest.raises(ProfileNotFound):
        resolver.resolve("noesis_query_planning", version=99)


def test_resolver_accepts_version_map_injection():
    # Resolver is designed for multi-version registries via a version map.
    registry = ProfileRegistry()
    resolver = ProfileVersionResolver(
        registry,
        versions={"noesis_query_planning": {2: dict(TASK_PROFILES[0], version=2)}},
    )
    v2 = resolver.resolve("noesis_query_planning", version=2)
    assert v2.version == 2
    assert v2.profile_id == "noesis_query_planning"
    assert resolver.resolve("noesis_query_planning").version == 1  # default intact


# ---------------------------------------------------------------- guardrails


def test_validate_guardrails_rejects_write_actions_for_read_only():
    runtime = TaskProfileRuntime(ProfileRegistry())
    profile = runtime.profile("noesis_query_planning")  # read_only + tenant_scope
    reasons = runtime.validate_guardrails(
        profile, requested_actions=["select", "insert into ledger"], scope_token="tok"
    )
    assert len(reasons) == 1
    assert "insert" in reasons[0]
    assert "read_only" in reasons[0]


def test_validate_guardrails_accepts_reads():
    runtime = TaskProfileRuntime(ProfileRegistry())
    profile = runtime.profile("noesis_query_planning")
    reasons = runtime.validate_guardrails(
        profile, requested_actions=["select", "read"], scope_token="tok"
    )
    assert reasons == []


def test_validate_guardrails_tenant_scope_presence():
    runtime = TaskProfileRuntime(ProfileRegistry())
    profile = runtime.profile("noesis_query_planning")  # has tenant_scope
    missing = runtime.validate_guardrails(profile)
    assert len(missing) == 1
    assert "scope token" in missing[0]
    # Presence is enough -- the runtime never evaluates the token.
    assert runtime.validate_guardrails(profile, scope_token="scope-acme-123") == []


def test_validate_guardrails_without_read_only_ignores_writes():
    runtime = TaskProfileRuntime(ProfileRegistry())
    profile = runtime.profile("entity_classification")  # no read_only guardrail
    reasons = runtime.validate_guardrails(
        profile, requested_actions=["create"], scope_token="tok"
    )
    assert reasons == []


# ------------------------------------------------------------------ execute


@pytest.mark.asyncio
async def test_execute_without_router_raises_clear_error():
    runtime = TaskProfileRuntime(ProfileRegistry())
    with pytest.raises(RoutingUnavailable) as exc_info:
        await runtime.execute(
            profile_id="noesis_query_planning",
            tenant_id="tenant-acme",
            messages=[{"role": "user", "content": "hello"}],
            scope_token="tok",
        )
    assert "no router" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_rejects_write_action_before_routing():
    # Guardrails gate the task before any route is constructed.
    runtime = TaskProfileRuntime(ProfileRegistry())
    with pytest.raises(RoutingPolicyViolation) as exc_info:
        await runtime.execute(
            profile_id="noesis_query_planning",
            tenant_id="tenant-acme",
            messages=[{"role": "user", "content": "drop the events table"}],
            requested_actions=["drop"],
            scope_token="tok",
        )
    assert "read_only" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_requires_scope_token_for_tenant_scope_profile():
    runtime = TaskProfileRuntime(ProfileRegistry())
    with pytest.raises(RoutingPolicyViolation) as exc_info:
        await runtime.execute(
            profile_id="noesis_query_planning",
            tenant_id="tenant-acme",
            messages=[{"role": "user", "content": "list top accounts"}],
        )
    assert "scope token" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_rejects_malformed_messages():
    runtime = TaskProfileRuntime(ProfileRegistry())
    with pytest.raises(RoutingPolicyViolation) as exc_info:
        await runtime.execute(
            profile_id="noesis_query_planning",
            tenant_id="tenant-acme",
            messages=[{"role": "user"}],  # missing content
            scope_token="tok",
        )
    assert "content" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_routes_honoring_profile_default_mode():
    recommended = _recommended_model_id()
    router = ModelRouter(
        AllowlistEntitlementResolver({"tenant-acme": {recommended}}),
        fallback=StaticFallbackChain([recommended]),
    )
    runtime = TaskProfileRuntime(ProfileRegistry(), router=router)
    selection = await runtime.execute(
        profile_id="noesis_query_planning",  # default_routing_mode = auto
        tenant_id="tenant-acme",
        messages=[{"role": "user", "content": "list the top accounts"}],
        requested_actions=["select"],
        scope_token="scope-acme-123",
    )
    assert selection.model_id == recommended
    assert selection.mode == RoutingMode.AUTO  # profile default, not the caller
    assert selection.entitled is True
    assert selection.fallback is False


@pytest.mark.asyncio
async def test_execute_routes_honoring_explicit_profile_default():
    recommended = _recommended_model_id()
    router = ModelRouter(
        AllowlistEntitlementResolver({"tenant-acme": {recommended}}),
        fallback=StaticFallbackChain([recommended]),
    )
    runtime = TaskProfileRuntime(ProfileRegistry(), router=router)
    selection = await runtime.execute(
        profile_id="entity_classification",  # default_routing_mode = explicit
        tenant_id="tenant-acme",
        messages=[{"role": "user", "content": "classify the entity"}],
        requested_model=recommended,
        scope_token="scope-acme-123",
    )
    assert selection.model_id == recommended
    assert selection.mode == RoutingMode.EXPLICIT  # profile default
    assert selection.entitled is True


@pytest.mark.asyncio
async def test_execute_honors_explicit_allowed_mode():
    recommended = _recommended_model_id()
    router = ModelRouter(
        AllowlistEntitlementResolver({"tenant-acme": {recommended}}),
        fallback=StaticFallbackChain([recommended]),
    )
    runtime = TaskProfileRuntime(ProfileRegistry(), router=router)
    selection = await runtime.execute(
        profile_id="noesis_query_planning",
        tenant_id="tenant-acme",
        messages=[{"role": "user", "content": "explain this"}],
        requested_actions=["read"],
        mode=RoutingMode.EXPLICIT,  # allowed for this profile
        requested_model=recommended,
        scope_token="scope-acme-123",
    )
    assert selection.mode == RoutingMode.EXPLICIT
    assert selection.model_id == recommended
