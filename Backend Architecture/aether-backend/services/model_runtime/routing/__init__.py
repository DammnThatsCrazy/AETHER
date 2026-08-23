"""AETHER model-runtime routing/policy — routing modes, entitlements, fallbacks.

Public API surface for the routing package (ADR-008 D4): routing data models,
entitlement resolvers, fallback chains, the model router, and the task-profile
registry bridge that binds routing policy to named harness tasks.
"""

from services.model_runtime.routing.engine import ModelRouter
from services.model_runtime.routing.entitlements import (
    AllowlistEntitlementResolver,
    CompositeEntitlementResolver,
    EntitlementResolver,
)
from services.model_runtime.routing.fallback import (
    FallbackChain,
    RegistryFallbackChain,
    StaticFallbackChain,
    select_fallback,
)
from services.model_runtime.routing.models import (
    EntitlementDecision,
    RouteAuditEntry,
    RouteSelection,
    RoutingMode,
    RoutingNotEntitled,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingResolutionError,
    RoutingUnavailable,
)
from services.model_runtime.routing.profiles import (
    ProfileNotFound,
    ProfileRegistry,
    TaskProfileView,
    apply_profile,
    routing_request_from_profile,
)

__all__ = [
    # routing/models.py — data models and errors
    "EntitlementDecision",
    "RouteAuditEntry",
    "RouteSelection",
    "RoutingMode",
    "RoutingNotEntitled",
    "RoutingPolicyViolation",
    "RoutingRequest",
    "RoutingResolutionError",
    "RoutingUnavailable",
    # routing/entitlements.py — server-authoritative entitlement resolvers
    "AllowlistEntitlementResolver",
    "CompositeEntitlementResolver",
    "EntitlementResolver",
    # routing/fallback.py — fallback chains and fallback selection
    "FallbackChain",
    "RegistryFallbackChain",
    "StaticFallbackChain",
    "select_fallback",
    # routing/engine.py — the router
    "ModelRouter",
    # routing/profiles.py — task-profile registry bridge
    "ProfileNotFound",
    "ProfileRegistry",
    "TaskProfileView",
    "apply_profile",
    "routing_request_from_profile",
]
