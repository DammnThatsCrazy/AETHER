"""Per-tenant LLM credential/secret integration for the model runtime (ADR-008 D5).

Public package surface:

* the fail-closed :class:`CredentialService` facade,
* the resolver seam (:class:`ProviderCredentialResolver`, :class:`CredentialSource`,
  :class:`CredentialCache`, :class:`NoopCredentialSource`),
* the BYOK and AWS Secrets Manager resolvers,
* rotation/revocation orchestration + policies,
* the secret-free resolution models and the redaction guard.

Only masked, secret-free metadata ever leaves this package (see
``shared.credentials.interface``); raw keys never appear in any public model.
"""

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
from services.model_runtime.credentials.interface import (
    CredentialCache,
    CredentialSource,
    NoopCredentialSource,
    ProviderCredentialResolver,
)
from services.model_runtime.credentials.rotation import (
    ExpiryBasedRotationPolicy,
    RotationOrchestrator,
    RotationPolicy,
)
from services.model_runtime.credentials.service import CredentialService

__all__ = [
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
]

try:  # BYOK / AWS Secrets Manager resolvers land with the resolver teams; keep
    # the package importable during concurrent development (ADR-008 D5).
    from services.model_runtime.credentials.aws_secrets import (
        AwsSecretsCredentialResolver,
    )
    from services.model_runtime.credentials.byok import ByokCredentialResolver
except ImportError:  # pragma: no cover - not landed yet
    pass
else:
    __all__ += ["AwsSecretsCredentialResolver", "ByokCredentialResolver"]
