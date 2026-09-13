"""Task-profile registry bridge tests — TaskProfileView, ProfileRegistry, apply_profile.

Covers the profile -> routing bridge for the Aether model-runtime router
(ADR-008 D3/D4): validated views over the generated task-profile registry,
read-only registry access, profile-mode application, and the convenience
request constructor.
"""
from __future__ import annotations

import pytest

from services.model_runtime.routing.models import (
    RoutingMode,
    RoutingPolicyViolation,
    RoutingRequest,
)
from services.model_runtime.routing.profiles import (
    ProfileNotFound,
    ProfileRegistry,
    TaskProfileView,
    apply_profile,
    routing_request_from_profile,
)
from shared.model_governance.generated_task_profiles import TASK_PROFILES


def test_task_profile_view_validates_against_registry_contract():
    # Build one profile from the raw registry dict and check every field.
    view = TaskProfileView(TASK_PROFILES[0])
    assert view.profile_id == "noesis_query_planning"
    assert view.version == 1
    assert view.model_role == "planning"
    assert view.default_routing_mode == RoutingMode.AUTO
    assert view.allowed_routing_modes == (
        RoutingMode.AUTO,
        RoutingMode.TENANT_DEFAULT,
        RoutingMode.EXPLICIT,
    )
    assert view.output_kind == "query_plan"
    assert view.guardrails == (
        "read_only",
        "tenant_scope",
        "allowlist_plan",
        "no_write_keywords",
        "no_injection",
    )
    assert view.evidence_required is False
    assert view.max_tokens == 512
    assert view.timeout_ms == 5000
    assert view.max_retries == 1


def test_task_profile_view_accepts_every_generated_profile():
    # Every entry of the generated registry must construct cleanly (the view is
    # a projection over the whole contract, not just one hand-picked profile).
    for raw in TASK_PROFILES:
        view = TaskProfileView(raw)
        assert view.profile_id == raw["profileId"]
        assert view.default_routing_mode.value == raw["defaultRoutingMode"]
        assert tuple(m.value for m in view.allowed_routing_modes) == tuple(
            raw["allowedRoutingModes"]
        )
        assert view.guardrails == tuple(raw["guardrails"])


def test_task_profile_view_drops_descriptive_metadata():
    # ``purpose`` is registry metadata the view does not surface, so the view
    # still constructs from the real registry dict.
    assert "purpose" in TASK_PROFILES[0]
    view = TaskProfileView(TASK_PROFILES[0])
    assert not hasattr(view, "purpose")


def test_task_profile_view_rejects_unknown_field():
    raw = dict(TASK_PROFILES[0])
    raw["bogusField"] = 123
    with pytest.raises(ValueError):
        TaskProfileView(raw)


def test_profile_registry_defaults_to_generated_registry():
    registry = ProfileRegistry()
    assert registry.ids() == tuple(p["profileId"] for p in TASK_PROFILES)
    assert len(registry.all()) == len(TASK_PROFILES)
    for profile in registry.all():
        assert isinstance(profile, TaskProfileView)
        assert profile.profile_id in registry.ids()


def test_profile_registry_get_all_ids():
    registry = ProfileRegistry()
    profile = registry.get("entity_classification")
    assert profile.profile_id == "entity_classification"
    assert profile.default_routing_mode == RoutingMode.EXPLICIT
    # all() returns profiles in the same order ids() does.
    assert registry.all() == tuple(registry.get(pid) for pid in registry.ids())


def test_profile_registry_unknown_profile_raises():
    registry = ProfileRegistry()
    with pytest.raises(ProfileNotFound):
        registry.get("does_not_exist")
    # ProfileNotFound is a KeyError, so dict-style callers keep working.
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_apply_profile_defaults_mode_from_profile():
    registry = ProfileRegistry()
    request = routing_request_from_profile(
        registry, "noesis_query_planning", tenant_id="tenant-acme"
    )
    assert request.mode is None
    bound = apply_profile(registry, request)
    assert bound is not request  # new object, input untouched
    assert bound.profile_id == "noesis_query_planning"
    assert bound.mode == RoutingMode.AUTO  # profile default_routing_mode
    assert bound.tenant_id == "tenant-acme"
    assert request.mode is None  # input never mutated


def test_apply_profile_keeps_explicit_allowed_mode():
    registry = ProfileRegistry()
    request = RoutingRequest(
        tenant_id="tenant-acme",
        profile_id="noesis_query_planning",
        mode=RoutingMode.EXPLICIT,  # allowed by the profile
    )
    bound = apply_profile(registry, request)
    assert bound.mode == RoutingMode.EXPLICIT


def test_apply_profile_rejects_disallowed_mode():
    registry = ProfileRegistry()
    request = RoutingRequest(
        tenant_id="tenant-acme",
        profile_id="noesis_query_planning",
        mode=RoutingMode.POLICY_REQUIRED,  # never in a profile's allowed set
    )
    with pytest.raises(RoutingPolicyViolation):
        apply_profile(registry, request)


def test_apply_profile_requires_profile_id():
    registry = ProfileRegistry()
    request = RoutingRequest(tenant_id="tenant-acme")
    with pytest.raises(RoutingPolicyViolation):
        apply_profile(registry, request)


def test_routing_request_from_profile_builds_correct_request():
    registry = ProfileRegistry()
    request = routing_request_from_profile(
        registry,
        "grounded_answer_synthesis",
        tenant_id="tenant-acme",
        requested_model="claude-sonnet-4-5",
        tenant_default_model="claude-haiku-4-5-20251001",
        entitled_model_ids={"claude-sonnet-4-5", "claude-haiku-4-5-20251001"},
    )
    assert request.tenant_id == "tenant-acme"
    assert request.profile_id == "grounded_answer_synthesis"
    assert request.mode is None  # apply_profile resolves the default
    assert request.requested_model == "claude-sonnet-4-5"
    assert request.tenant_default_model == "claude-haiku-4-5-20251001"
    assert request.entitled_model_ids == {
        "claude-sonnet-4-5",
        "claude-haiku-4-5-20251001",
    }


def test_routing_request_from_profile_unknown_profile_raises():
    registry = ProfileRegistry()
    with pytest.raises(ProfileNotFound):
        routing_request_from_profile(registry, "does_not_exist", tenant_id="t1")


def test_routing_package_init_exports():
    # The routing package re-exports the whole routing public API.
    import services.model_runtime.routing as routing

    for name in (
        "RoutingMode",
        "RoutingRequest",
        "RouteSelection",
        "EntitlementDecision",
        "RouteAuditEntry",
        "RoutingNotEntitled",
        "RoutingUnavailable",
        "RoutingPolicyViolation",
        "RoutingResolutionError",
        "EntitlementResolver",
        "AllowlistEntitlementResolver",
        "CompositeEntitlementResolver",
        "FallbackChain",
        "StaticFallbackChain",
        "RegistryFallbackChain",
        "select_fallback",
        "ModelRouter",
        "TaskProfileView",
        "ProfileRegistry",
        "ProfileNotFound",
        "apply_profile",
        "routing_request_from_profile",
    ):
        assert hasattr(routing, name), f"routing package missing export {name!r}"
