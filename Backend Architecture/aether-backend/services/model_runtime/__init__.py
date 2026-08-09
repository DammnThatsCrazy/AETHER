"""AETHER Multi-Model Intelligence Harness — provider-neutral model runtime."""

from services.model_runtime.deterministic import DeterministicModelProvider
from services.model_runtime.models import (
    ModelBudgetExceeded,
    ModelInvocationError,
    ModelNotConfigured,
    ModelProvider,
    ModelProviderError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    TokenUsage,
)
from services.model_runtime.provider import AsyncModelProvider, BaseModelProvider
from services.model_runtime.service import ModelRuntimeService, TokenBudget

# ADR-008 D4 routing/policy (Commit 5): the routing subpackage is owned by the
# routing team and lands in the same commit; imported guardedly so the
# model_runtime package loads cleanly during concurrent development.
from services.model_runtime.routing.entitlements import AllowlistEntitlementResolver
from services.model_runtime.routing.fallback import StaticFallbackChain
from services.model_runtime.routing.models import (
    RouteAuditEntry,
    RouteSelection,
    RoutingMode,
    RoutingNotEntitled,
    RoutingPolicyViolation,
    RoutingRequest,
    RoutingResolutionError,
    RoutingUnavailable,
)

__all__ = [
    "AllowlistEntitlementResolver",
    "AsyncModelProvider",
    "BaseModelProvider",
    "DeterministicModelProvider",
    "ModelBudgetExceeded",
    "ModelInvocationError",
    "ModelNotConfigured",
    "ModelProvider",
    "ModelProviderError",
    "ModelRequest",
    "ModelResponse",
    "ModelRuntimeService",
    "ModelTimeoutError",
    "RouteAuditEntry",
    "RouteSelection",
    "RoutingMode",
    "RoutingNotEntitled",
    "RoutingPolicyViolation",
    "RoutingRequest",
    "RoutingResolutionError",
    "RoutingUnavailable",
    "StaticFallbackChain",
    "TokenBudget",
    "TokenUsage",
]

try:  # engine/profiles land with the routing team; keep exports complete only
    # when the modules are present.
    from services.model_runtime.routing.engine import ModelRouter
    from services.model_runtime.routing.profiles import ProfileRegistry
except ImportError:  # pragma: no cover - not landed yet
    pass
else:
    __all__ += ["ModelRouter", "ProfileRegistry"]
