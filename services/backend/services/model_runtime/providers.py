"""The real provider set for the model runtime — present, wired, and waiting on credentials.

Every registry provider with a transport adapter is constructed here and handed to
:class:`~services.model_runtime.service.ModelRuntimeService` and the health surface.
A provider with no credential reports ``is_configured() == False`` and a controlled
"waiting on credentials" reason naming the environment variables that unlock it; it
never serves a request and never fails startup. Supplying the variables (through the
deployment secret store, never a ``.env`` file) is the only step left to turn one on.

Providers:

* ``anthropic``  - ``ANTHROPIC_API_KEY``
* ``openai``     - ``OPENAI_API_KEY``
* ``kimi`` / ``deepseek`` / ``qwen`` - OpenAI-compatible endpoints, each with its own
  ``MODEL_RUNTIME_<NAME>_API_KEY`` and ``MODEL_RUNTIME_<NAME>_BASE_URL``
* ``openai_compatible`` - a single generic endpoint from the
  ``MODEL_RUNTIME_COMPAT_*`` surface (see ``adapters/compatible.py``)

The deterministic local provider is always configured. Registry providers that have no
adapter at all are reported as such, not as waiting on a credential.

A tenant-facing completion route is intentionally not built on top of this yet: it
needs a durable entitlement store and a per-tenant token budget, otherwise any
entitled tenant would spend the platform key without a limit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from services.model_runtime.adapters.anthropic import AnthropicModelProvider
from services.model_runtime.adapters.compatible import OpenAICompatibleModelProvider
from services.model_runtime.adapters.openai import OpenAIModelProvider
from services.model_runtime.deterministic import DeterministicModelProvider
from services.model_runtime.provider import AsyncModelProvider
from services.model_runtime.service import ModelRuntimeService
from shared.model_governance.generated_model_registry import MODEL_REGISTRY_PROVIDERS


@dataclass(frozen=True)
class ProviderRequirement:
    """What a provider needs before it can serve a request."""

    name: str
    #: Environment variables that must all be non-empty for the provider to be configured.
    env_vars: tuple[str, ...]


#: OpenAI-compatible registry providers, each with its own credential surface.
_NAMED_COMPATIBLE: tuple[str, ...] = ("kimi", "deepseek", "qwen")

REQUIREMENTS: dict[str, ProviderRequirement] = {
    "anthropic": ProviderRequirement("anthropic", ("ANTHROPIC_API_KEY",)),
    "openai": ProviderRequirement("openai", ("OPENAI_API_KEY",)),
    "openai_compatible": ProviderRequirement(
        "openai_compatible", ("MODEL_RUNTIME_COMPAT_API_KEY", "MODEL_RUNTIME_COMPAT_BASE_URL")
    ),
    **{
        name: ProviderRequirement(
            name, (f"MODEL_RUNTIME_{name.upper()}_API_KEY", f"MODEL_RUNTIME_{name.upper()}_BASE_URL")
        )
        for name in _NAMED_COMPATIBLE
    },
}


def _named_compatible(name: str) -> OpenAICompatibleModelProvider:
    """A compatible-endpoint provider for ``name`` that reads only its own variables.

    The generic adapter falls back to the shared ``MODEL_RUNTIME_COMPAT_*`` surface when
    no key is passed, which would make every named provider appear configured as soon as
    the generic one is. Overwrite the resolved values so each reads its own credential.
    """
    prefix = f"MODEL_RUNTIME_{name.upper()}"
    provider = OpenAICompatibleModelProvider(provider_name=name)
    base_url = os.getenv(f"{prefix}_BASE_URL", "")
    provider.base_url = base_url
    # An endpoint is unusable without both halves, so a key alone stays "waiting".
    provider.api_key = os.getenv(f"{prefix}_API_KEY", "") if base_url else ""
    model = os.getenv(f"{prefix}_MODEL")
    if model:
        provider.model = model
    return provider


def build_providers() -> dict[str, AsyncModelProvider]:
    """Construct every adapter-backed provider from the current environment.

    Never raises for a missing credential: that provider is simply unconfigured.
    """
    generic = OpenAICompatibleModelProvider()
    if not os.getenv("MODEL_RUNTIME_COMPAT_BASE_URL"):
        # Without its own base URL the generic endpoint would fall back to OpenAI's.
        generic.api_key = ""
    providers: dict[str, AsyncModelProvider] = {
        "deterministic": DeterministicModelProvider(),
        "anthropic": AnthropicModelProvider(),
        "openai": OpenAIModelProvider(),
        "openai_compatible": generic,
    }
    for name in _NAMED_COMPATIBLE:
        providers[name] = _named_compatible(name)
    return providers


def missing_credentials(name: str) -> tuple[str, ...]:
    """Environment variables still unset for ``name`` (empty when it can be configured)."""
    requirement = REQUIREMENTS.get(name)
    if requirement is None:
        return ()
    return tuple(var for var in requirement.env_vars if not os.getenv(var))


def has_adapter(name: str) -> bool:
    """True when a transport adapter exists for ``name`` (so it can only be waiting, not absent)."""
    return name in REQUIREMENTS or name == "deterministic"


def credential_reason(name: str, configured: bool) -> str:
    """Controlled, secret-free health reason for ``name``."""
    if configured:
        return "configured"
    if name not in REQUIREMENTS:
        return "no adapter for this provider"
    return "waiting on credentials: set " + ", ".join(REQUIREMENTS[name].env_vars)


def registry_providers_without_adapter() -> tuple[str, ...]:
    """Registry providers that still have no transport adapter."""
    return tuple(p for p in MODEL_REGISTRY_PROVIDERS if p not in REQUIREMENTS)


_RUNTIME: ModelRuntimeService | None = None


def get_runtime() -> ModelRuntimeService:
    """The process-wide runtime over the real provider set (built lazily, once)."""
    global _RUNTIME
    if _RUNTIME is None:
        from services.model_runtime.config import get_settings
        from services.model_runtime.credentials.byok import ByokCredentialResolver
        from services.model_runtime.credentials.interface import CredentialCache, NoopCredentialSource
        from services.model_runtime.credentials.models import ResolverConfig
        from services.model_runtime.credentials.service import CredentialService

        settings = get_settings()
        if settings.credential_backend == "aws_secrets":
            from services.model_runtime.credentials.aws_secrets import AwsSecretsCredentialResolver
            from shared.credentials.aws_secrets_manager import AwsSecretsManagerCredentialBackend

            backend = AwsSecretsManagerCredentialBackend(
                secret_prefix=settings.credential_aws_prefix,
                region=settings.credential_aws_region,
            )
            resolver = AwsSecretsCredentialResolver(backend, aws_region=settings.credential_aws_region)
        else:
            # Env resolution is explicitly tenant-scoped by ByokCredentialResolver;
            # no process-wide provider key can satisfy a tenant request.
            resolver = ByokCredentialResolver(
                NoopCredentialSource(), CredentialCache(settings.credential_cache_ttl_seconds)
            )
        credential_service = CredentialService(
            resolver,
            config=ResolverConfig(
                enabled=settings.enabled,
                backend=settings.credential_backend,
                aws_region=settings.credential_aws_region,
                aws_secrets_prefix=settings.credential_aws_prefix,
                cache_ttl_seconds=settings.credential_cache_ttl_seconds,
            ),
        )
        _RUNTIME = ModelRuntimeService.from_settings(
            settings, providers=build_providers(), credential_service=credential_service
        )
    return _RUNTIME


def reset_runtime() -> None:
    """Drop the cached runtime so the next call re-reads the environment (tests, rotation)."""
    global _RUNTIME
    _RUNTIME = None


__all__ = [
    "ProviderRequirement",
    "REQUIREMENTS",
    "build_providers",
    "credential_reason",
    "get_runtime",
    "has_adapter",
    "missing_credentials",
    "registry_providers_without_adapter",
    "reset_runtime",
]
