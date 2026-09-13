"""AETHER Multi-Model Intelligence Harness — provider-neutral model runtime.

Final integration barrel (Commit 16): the full provider-neutral harness surface
is now exported from the package root.  Alongside the base model-runtime
contracts and the ADR-008 D4 routing/policy layer (Commit 5), the root
re-exports the public surface of every landed subpackage:

* D5 credentials — per-tenant LLM credential/secret integration
  (:class:`CredentialService`, :class:`ProviderCredentialResolver`, the BYOK and
  AWS Secrets Manager resolvers);
* D3/D4/D7 task profiles — versioned task-profile runtime
  (:class:`TaskProfileService`, :class:`TaskProfileRuntime`,
  :class:`ProfileVersionResolver`, :class:`OutputValidator`);
* D6 grounded context — retrieval-before-synthesis evidence layer
  (:class:`ContextService`, :class:`ContextBuilder`,
  :class:`GroundedPromptBuilder`, :class:`ContextScopeViolation`);
* D6 grounded synthesis — the answering path (:class:`SynthesisService`,
  :class:`GroundedSynthesisEngine`, :class:`SynthesisRenderer`);
* D7 verification/faithfulness — the fail-closed D7 gate
  (:class:`VerificationService`, :class:`VerificationEngine`,
  :class:`SecretLeakDetector`);
* D7/D8 evaluation — the regression-gated evaluation plane
  (:class:`EvaluationService`, :class:`EvaluationRunner`,
  :class:`RegressionGate`);
* D8 observability — metrics/health/readiness/circuit-breaking/runbooks
  (:class:`RuntimeHealth`, :class:`RuntimeMetricsRecorder`,
  :class:`CircuitBreaker`, :class:`CircuitRegistry`,
  :class:`IncidentClassifier`);
* D5/D8/D9 configuration — the single settings source
  (:class:`ModelRuntimeSettings`, :class:`ConfigError`).

Every re-exported subpackage landed by Commit 16 and each name is verified to
resolve; imports are unguarded and the barrel imports cleanly on its own.
"""

from services.model_runtime.config import (
    ConfigError,
    ModelRuntimeSettings,
    get_settings,
    required_env_vars,
)
from services.model_runtime.context import (
    ContextBuilder,
    ContextScopeViolation,
    ContextService,
    GroundedPromptBuilder,
    InjectionGuardError,
    PromptSizeError,
)
from services.model_runtime.credentials import (
    AwsSecretsCredentialResolver,
    ByokCredentialResolver,
    CredentialCache,
    CredentialResolution,
    CredentialResolverError,
    CredentialService,
    CredentialSource,
    NoopCredentialSource,
    ProviderCredentialResolver,
)
from services.model_runtime.deterministic import DeterministicModelProvider
from services.model_runtime.evaluation import (
    EvaluationCase,
    EvaluationReport,
    EvaluationRunner,
    EvaluationService,
    EvaluationServiceError,
    GateResult,
    RegressionGate,
)
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
from services.model_runtime.observability import (
    CircuitBreaker,
    CircuitRegistry,
    IncidentClassifier,
    RuntimeHealth,
    RuntimeMetricsRecorder,
)
from services.model_runtime.provider import AsyncModelProvider, BaseModelProvider
from services.model_runtime.routing.engine import ModelRouter
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
from services.model_runtime.routing.profiles import ProfileRegistry
from services.model_runtime.service import ModelRuntimeService, TokenBudget
from services.model_runtime.synthesis import (
    GroundedSynthesisEngine,
    GroundingViolation,
    InsufficientEvidence,
    PlanNotAllowlisted,
    PlanUnsafe,
    StaleEvidence,
    SynthesisRenderError,
    SynthesisRenderer,
    SynthesisRequest,
    SynthesisResult,
    SynthesisService,
    SynthesisServiceError,
    SynthesisUnsafe,
    UnsupportedSynthesis,
)
from services.model_runtime.task_profiles import (
    OutputValidator,
    ProfileVersionResolver,
    TaskProfileRuntime,
    TaskProfileService,
)
from services.model_runtime.verification import (
    LEAK_MARKERS,
    SecretLeakDetector,
    VerificationEngine,
    VerificationFailure,
    VerificationResult,
    VerificationService,
    VerificationServiceError,
    VerificationUnsafe,
)

__all__ = [
    # --- config (ADR-008 D5/D8/D9) ---
    "ConfigError",
    "ModelRuntimeSettings",
    "get_settings",
    "required_env_vars",
    # --- base contracts (models.py / provider.py / deterministic.py) ---
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
    "ModelTimeoutError",
    "TokenUsage",
    # --- routing/policy (ADR-008 D4, Commit 5) ---
    "AllowlistEntitlementResolver",
    "ModelRouter",
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
    # --- service facade ---
    "ModelRuntimeService",
    "TokenBudget",
    # --- grounded context / evidence (ADR-008 D6) ---
    "ContextBuilder",
    "ContextScopeViolation",
    "ContextService",
    "GroundedPromptBuilder",
    "InjectionGuardError",
    "PromptSizeError",
    # --- grounded synthesis (ADR-008 D6) ---
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
    # --- verification/faithfulness (ADR-008 D7) ---
    "LEAK_MARKERS",
    "SecretLeakDetector",
    "VerificationEngine",
    "VerificationFailure",
    "VerificationResult",
    "VerificationService",
    "VerificationServiceError",
    "VerificationUnsafe",
    # --- evaluation plane (ADR-008 D7/D8) ---
    "EvaluationCase",
    "EvaluationReport",
    "EvaluationRunner",
    "EvaluationService",
    "EvaluationServiceError",
    "GateResult",
    "RegressionGate",
    # --- credentials (ADR-008 D5) ---
    "AwsSecretsCredentialResolver",
    "ByokCredentialResolver",
    "CredentialCache",
    "CredentialResolution",
    "CredentialResolverError",
    "CredentialService",
    "CredentialSource",
    "NoopCredentialSource",
    "ProviderCredentialResolver",
    # --- task profiles (ADR-008 D3/D4/D7) ---
    "OutputValidator",
    "ProfileVersionResolver",
    "TaskProfileRuntime",
    "TaskProfileService",
    # --- observability (ADR-008 D8) ---
    "CircuitBreaker",
    "CircuitRegistry",
    "IncidentClassifier",
    "RuntimeHealth",
    "RuntimeMetricsRecorder",
]
