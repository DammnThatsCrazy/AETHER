"""Model runtime settings — single configuration source (ADR-008 D5/D8/D9).

The multi-model harness FAILS CLOSED in staging/production when a
production-required variable is absent or empty.  This module is the one place
that decides which ``MODEL_RUNTIME_*`` variables are REQUIRED per environment.

It never reads or stores credentials itself — adapters read their own
environment variables — it only validates which variables are required and
refuses to construct a settings object when a production-required value is
missing.

Rules implemented by :meth:`ModelRuntimeSettings._fail_closed`:

* ``MODEL_RUNTIME_ENABLED=true`` in a non-local environment (``AETHER_ENV`` in
  ``{staging, production, test}``) requires a production-safe credential
  backend (``env`` or ``aws_secrets``) — never ``in_memory``/``disabled``.
* ``MODEL_RUNTIME_ENABLED=true`` in a non-local environment requires a real
  default provider — ``deterministic`` is test-only.
* ``credential_backend=aws_secrets`` requires a non-empty
  ``MODEL_RUNTIME_CREDENTIAL_AWS_REGION`` in every environment.
* Circuit-breaker settings are wired into :class:`~services.model_runtime.service.ModelRuntimeService`
  dispatch (ADR-008 D8): ``circuit_failure_threshold`` must be ``>= 1`` and
  ``circuit_recovery_timeout_s`` non-negative, or the settings fail closed.

Deployment tuning controls are CONSUMED, not inert: the settings-backed factory
:meth:`ModelRuntimeService.from_settings
<services.model_runtime.service.ModelRuntimeService.from_settings>` feeds
``adapters_dir`` into :func:`services.model_runtime.service.load_provider_adapters`
(provider adapters are actually loaded), ``estimated_request_tokens`` into the
budget reservation size, and ``max_providers`` into the provider-registry
bound. Each is validated fail-closed here so a misconfigured deployment fails
at startup instead of silently ignoring the control: ``estimated_request_tokens``
and ``max_providers`` must be ``>= 1`` and ``adapters_dir`` must be a non-empty
path.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Environments where the harness must fail closed.  ``test`` is included so a
# test run that flips the feature gate on behaves like a real deployment.
_NON_LOCAL_ENVS = frozenset({"staging", "production", "test"})

# Credential backends allowed in non-local environments (D5).  ``in_memory``
# and ``disabled`` are local/test-only and never satisfy production fail-closed.
_PROD_SAFE_CREDENTIAL_BACKENDS = frozenset({"env", "aws_secrets"})

# The deterministic provider is a test/local fixture; a real provider must be
# named in a non-local environment.
_TEST_ONLY_DEFAULT_PROVIDER = "deterministic"


class ConfigError(Exception):
    """Raised when model-runtime settings are invalid for the environment.

    Extends :class:`Exception` (not ``ValueError``) so pydantic propagates it
    verbatim instead of wrapping it in a ``ValidationError`` — callers can rely
    on catching :class:`ConfigError` directly.
    """


class ModelRuntimeSettings(BaseSettings):
    """Environment-driven settings for the multi-model harness.

    Reads ``MODEL_RUNTIME_*`` variables (prefix ``MODEL_RUNTIME_``); unknown
    variables are ignored and the optional ``.env`` file is merged in when
    present.  Missing or empty production-required values raise
    :class:`ConfigError` via the ``_fail_closed`` validator.
    """

    model_config = SettingsConfigDict(
        env_prefix="MODEL_RUNTIME_",
        extra="ignore",
        env_file=".env",
    )

    enabled: bool = False                 # MODEL_RUNTIME_ENABLED — feature gate, default OFF (D9)
    adapters_dir: str = "services/model_runtime/adapters"
    default_provider: str = "deterministic"
    estimated_request_tokens: int = 800
    max_providers: int = 16
    # Credential backend (D5) — env-gated, fail-closed below
    credential_backend: str = "in_memory"   # in_memory | env | aws_secrets | disabled
    credential_aws_region: str | None = None
    credential_aws_prefix: str = "aether/credentials"
    credential_cache_ttl_seconds: int = 60
    # Observability (D8)
    observability_enabled: bool = False
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout_s: float = 60.0

    @model_validator(mode="after")
    def _fail_closed(self) -> ModelRuntimeSettings:
        """Enforce the per-environment fail-closed rules (D5/D8/D9)."""
        env = _current_env()
        if self.enabled and env in _NON_LOCAL_ENVS:
            if self.credential_backend not in _PROD_SAFE_CREDENTIAL_BACKENDS:
                raise ConfigError(
                    "credential_backend="
                    f"{self.credential_backend!r} is not allowed when "
                    f"MODEL_RUNTIME_ENABLED=true in {env!r}; must be one of "
                    f"{sorted(_PROD_SAFE_CREDENTIAL_BACKENDS)}"
                )
            if self.default_provider == _TEST_ONLY_DEFAULT_PROVIDER:
                raise ConfigError(
                    "default_provider="
                    f"{self.default_provider!r} is test-only and not allowed when "
                    f"MODEL_RUNTIME_ENABLED=true in {env!r}; name a real provider"
                )
        if self.credential_backend == "aws_secrets":
            if not self.credential_aws_region:
                raise ConfigError(
                    "credential_aws_region is required (non-empty) when "
                    "credential_backend='aws_secrets'"
                )
        # Circuit-breaker settings (D8) are wired into ModelRuntimeService
        # dispatch; reject unusable thresholds at configuration time so a
        # misconfigured deployment fails closed before any provider call.
        if self.circuit_failure_threshold < 1:
            raise ConfigError(
                "circuit_failure_threshold must be >= 1, got "
                f"{self.circuit_failure_threshold}"
            )
        if self.circuit_recovery_timeout_s < 0:
            raise ConfigError(
                "circuit_recovery_timeout_s must be >= 0, got "
                f"{self.circuit_recovery_timeout_s}"
            )
        # Deployment tuning controls are consumed by
        # ModelRuntimeService.from_settings (adapters_dir -> adapter loading,
        # estimated_request_tokens -> budget reservation size, max_providers ->
        # provider-registry bound). Reject unusable values fail-closed here so
        # a misconfigured control can never be silently ignored at runtime.
        if self.estimated_request_tokens < 1:
            raise ConfigError(
                "estimated_request_tokens must be >= 1, got "
                f"{self.estimated_request_tokens}"
            )
        if self.max_providers < 1:
            raise ConfigError(
                "max_providers must be >= 1, got " f"{self.max_providers}"
            )
        if not self.adapters_dir.strip():
            raise ConfigError("adapters_dir must be a non-empty path")
        return self


@lru_cache(maxsize=None)
def get_settings() -> ModelRuntimeSettings:
    """Return the process-wide, cached model-runtime settings singleton."""
    return ModelRuntimeSettings()


def required_env_vars(settings: ModelRuntimeSettings) -> tuple[str, ...]:
    """Return the ``MODEL_RUNTIME_*`` names a valid deployment must set.

    Derived from the current environment and the fail-closed rules: a non-local
    deployment must name a production-safe credential backend and a real
    default provider, and an ``aws_secrets`` backend must pin a region.  The
    feature gate is always listed so deployment templates opt in explicitly.
    """
    names: list[str] = ["MODEL_RUNTIME_ENABLED"]
    if _current_env() in _NON_LOCAL_ENVS:
        names.extend(
            [
                "MODEL_RUNTIME_CREDENTIAL_BACKEND",
                "MODEL_RUNTIME_DEFAULT_PROVIDER",
            ]
        )
    if settings.credential_backend == "aws_secrets":
        names.append("MODEL_RUNTIME_CREDENTIAL_AWS_REGION")
    # De-duplicate while preserving order.
    return tuple(dict.fromkeys(names))


def _current_env() -> str:
    """Return the current deployment environment, defaulting to ``local``."""
    return os.environ.get("AETHER_ENV", "local") or "local"


__all__ = [
    "ConfigError",
    "ModelRuntimeSettings",
    "get_settings",
    "required_env_vars",
]
