"""Root ``model_runtime`` barrel surface tests (Commit 16 final integration).

Verifies the package root now re-exports the full provider-neutral harness
surface: every name in ``services.model_runtime.__all__`` is importable and
identity-equal to its canonical source module's export, the previously-existing
Commit-5 routing names are still exported (no regression), and ``__all__`` is
deduplicated with no ``object`` artifacts.
"""

from __future__ import annotations

import importlib

import services.model_runtime as model_runtime

# Canonical source module for every name re-exported from the root barrel.
# New subpackage surfaces resolve against their public barrels; the Commit-5
# routing/base surfaces resolve against their defining modules.
_SOURCE_EXPORTS: dict[str, list[str]] = {
    # config (ADR-008 D5/D8/D9)
    "services.model_runtime.config": [
        "ConfigError",
        "ModelRuntimeSettings",
        "get_settings",
        "required_env_vars",
    ],
    # base contracts
    "services.model_runtime.models": [
        "ModelBudgetExceeded",
        "ModelInvocationError",
        "ModelNotConfigured",
        "ModelProvider",
        "ModelProviderError",
        "ModelRequest",
        "ModelResponse",
        "ModelTimeoutError",
        "TokenUsage",
    ],
    "services.model_runtime.provider": [
        "AsyncModelProvider",
        "BaseModelProvider",
    ],
    "services.model_runtime.deterministic": ["DeterministicModelProvider"],
    "services.model_runtime.service": [
        "ModelRuntimeService",
        "TokenBudget",
    ],
    # routing/policy (ADR-008 D4, Commit 5)
    "services.model_runtime.routing.entitlements": [
        "AllowlistEntitlementResolver",
    ],
    "services.model_runtime.routing.fallback": ["StaticFallbackChain"],
    "services.model_runtime.routing.models": [
        "RouteAuditEntry",
        "RouteSelection",
        "RoutingMode",
        "RoutingNotEntitled",
        "RoutingPolicyViolation",
        "RoutingRequest",
        "RoutingResolutionError",
        "RoutingUnavailable",
    ],
    "services.model_runtime.routing.engine": ["ModelRouter"],
    "services.model_runtime.routing.profiles": ["ProfileRegistry"],
    # grounded context / evidence (ADR-008 D6)
    "services.model_runtime.context": [
        "ContextBuilder",
        "ContextScopeViolation",
        "ContextService",
        "GroundedPromptBuilder",
        "InjectionGuardError",
        "PromptSizeError",
    ],
    # grounded synthesis (ADR-008 D6)
    "services.model_runtime.synthesis": [
        "GroundedSynthesisEngine",
        "GroundingViolation",
        "InsufficientEvidence",
        "PlanNotAllowlisted",
        "PlanUnsafe",
        "StaleEvidence",
        "SynthesisRenderError",
        "SynthesisRenderer",
        "SynthesisRequest",
        "SynthesisResult",
        "SynthesisService",
        "SynthesisServiceError",
        "SynthesisUnsafe",
        "UnsupportedSynthesis",
    ],
    # verification/faithfulness (ADR-008 D7)
    "services.model_runtime.verification": [
        "LEAK_MARKERS",
        "SecretLeakDetector",
        "VerificationEngine",
        "VerificationFailure",
        "VerificationResult",
        "VerificationService",
        "VerificationServiceError",
        "VerificationUnsafe",
    ],
    # evaluation plane (ADR-008 D7/D8)
    "services.model_runtime.evaluation": [
        "EvaluationCase",
        "EvaluationReport",
        "EvaluationRunner",
        "EvaluationService",
        "EvaluationServiceError",
        "GateResult",
        "RegressionGate",
    ],
    # credentials (ADR-008 D5)
    "services.model_runtime.credentials": [
        "AwsSecretsCredentialResolver",
        "ByokCredentialResolver",
        "CredentialCache",
        "CredentialResolution",
        "CredentialResolverError",
        "CredentialService",
        "CredentialSource",
        "NoopCredentialSource",
        "ProviderCredentialResolver",
    ],
    # task profiles (ADR-008 D3/D4/D7)
    "services.model_runtime.task_profiles": [
        "OutputValidator",
        "ProfileVersionResolver",
        "TaskProfileRuntime",
        "TaskProfileService",
    ],
    # observability (ADR-008 D8)
    "services.model_runtime.observability": [
        "CircuitBreaker",
        "CircuitRegistry",
        "IncidentClassifier",
        "RuntimeHealth",
        "RuntimeMetricsRecorder",
    ],
}

# Commit-5 routing/base surface that must not regress.
_LEGACY_EXPORTS = (
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
    "ModelRouter",
    "ModelTimeoutError",
    "ProfileRegistry",
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
)


def test_root_package_imports_cleanly() -> None:
    assert model_runtime.__all__


def test_every_root_export_maps_to_a_source_module() -> None:
    """Every name in the root ``__all__`` is accounted for by exactly one
    source module (no orphans, no gaps)."""
    source_names = {
        name for names in _SOURCE_EXPORTS.values() for name in names
    }
    assert len(source_names) == len(model_runtime.__all__)
    assert source_names == set(model_runtime.__all__)


def test_every_root_export_is_importable() -> None:
    for name in model_runtime.__all__:
        assert getattr(model_runtime, name) is not None, name


def test_root_exports_are_identity_equal_to_source() -> None:
    """Each root export is the same object as its canonical source export."""
    for module_name, names in _SOURCE_EXPORTS.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert getattr(model_runtime, name) is getattr(module, name), (
                f"root {name!r} is not identity-equal to "
                f"{module_name}.{name}"
            )


def test_legacy_routing_surface_still_exported() -> None:
    """The Commit-5 names remain exported with no regression."""
    for name in _LEGACY_EXPORTS:
        assert name in model_runtime.__all__, name
        assert getattr(model_runtime, name) is not None, name


def test_all_is_deduplicated_without_object_artifacts() -> None:
    assert len(model_runtime.__all__) == len(set(model_runtime.__all__))
    assert "object" not in model_runtime.__all__
    assert all(isinstance(name, str) for name in model_runtime.__all__)
