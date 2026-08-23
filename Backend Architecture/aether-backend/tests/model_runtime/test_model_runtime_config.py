"""Tests for the model-runtime settings fail-closed config (ADR-008 D5/D8/D9)."""

from __future__ import annotations

from services.model_runtime.config import (
    ConfigError,
    ModelRuntimeSettings,
    get_settings,
    required_env_vars,
)

# Env vars that could leak between tests; the defaults tests pin them explicitly.
_MODEL_RUNTIME_VARS = (
    "MODEL_RUNTIME_ENABLED",
    "MODEL_RUNTIME_ADAPTERS_DIR",
    "MODEL_RUNTIME_DEFAULT_PROVIDER",
    "MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS",
    "MODEL_RUNTIME_MAX_PROVIDERS",
    "MODEL_RUNTIME_CREDENTIAL_BACKEND",
    "MODEL_RUNTIME_CREDENTIAL_AWS_REGION",
    "MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX",
    "MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS",
    "MODEL_RUNTIME_OBSERVABILITY_ENABLED",
    "MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD",
    "MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S",
)


def _raises(exc_type, fn, *args, **kwargs):
    """Run ``fn`` returning the raised exception, or fail if none is raised."""
    try:
        fn(*args, **kwargs)
    except exc_type as err:
        return err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _clear_model_runtime_env(monkeypatch):
    """Clear ambient MODEL_RUNTIME_* and AETHER_ENV so defaults hold."""
    monkeypatch.delenv("AETHER_ENV", raising=False)
    for var in _MODEL_RUNTIME_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Defaults / construction
# ---------------------------------------------------------------------------


def test_defaults(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    s = ModelRuntimeSettings()
    assert s.enabled is False
    assert s.adapters_dir == "services/model_runtime/adapters"
    assert s.default_provider == "deterministic"
    assert s.estimated_request_tokens == 800
    assert s.max_providers == 16
    assert s.credential_backend == "in_memory"
    assert s.credential_aws_region is None
    assert s.credential_aws_prefix == "aether/credentials"
    assert s.credential_cache_ttl_seconds == 60
    assert s.observability_enabled is False
    assert s.circuit_failure_threshold == 5
    assert s.circuit_recovery_timeout_s == 60.0


def test_get_settings_returns_same_cached_instance():
    first = get_settings()
    second = get_settings()
    assert first is second
    assert isinstance(first, ModelRuntimeSettings)


def test_extra_ignore_tolerates_unrelated_env(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("MODEL_RUNTIME_UNKNOWN_FIELD", "bogus")
    monkeypatch.setenv("UNRELATED_VAR", "also-ignored")
    s = ModelRuntimeSettings()
    assert s.enabled is False
    assert s.credential_backend == "in_memory"


# ---------------------------------------------------------------------------
# Fail-closed: production + enabled=True (D5/D8/D9)
# ---------------------------------------------------------------------------


def test_prod_fail_closed_in_memory_backend_raises(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    err = _raises(ConfigError, ModelRuntimeSettings)
    assert "credential_backend" in str(err)


def test_prod_fail_closed_disabled_backend_raises(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "disabled")
    err = _raises(ConfigError, ModelRuntimeSettings)
    assert "credential_backend" in str(err)


def test_prod_fail_closed_aws_secrets_missing_region_raises(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "aws_secrets")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    err = _raises(ConfigError, ModelRuntimeSettings)
    assert "credential_aws_region" in str(err)


def test_prod_fail_closed_aws_secrets_empty_region_raises(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "aws_secrets")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_AWS_REGION", "")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    err = _raises(ConfigError, ModelRuntimeSettings)
    assert "credential_aws_region" in str(err)


def test_prod_fail_closed_aws_secrets_with_region_valid(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "aws_secrets")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_AWS_REGION", "us-east-1")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    s = ModelRuntimeSettings()
    assert s.enabled is True
    assert s.credential_backend == "aws_secrets"
    assert s.credential_aws_region == "us-east-1"
    assert s.default_provider == "anthropic"


def test_prod_fail_closed_deterministic_default_provider_raises(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "env")
    # MODEL_RUNTIME_DEFAULT_PROVIDER left unset -> "deterministic" (test-only).
    err = _raises(ConfigError, ModelRuntimeSettings)
    assert "default_provider" in str(err)


def test_prod_fail_closed_env_backend_real_provider_valid(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "env")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    s = ModelRuntimeSettings()
    assert s.enabled is True
    assert s.credential_backend == "env"
    assert s.default_provider == "anthropic"


# ---------------------------------------------------------------------------
# required_env_vars (deployment templates)
# ---------------------------------------------------------------------------


def test_required_env_vars_includes_credential_backend_names(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "aws_secrets")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_AWS_REGION", "us-east-1")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    s = ModelRuntimeSettings()
    names = required_env_vars(s)
    assert isinstance(names, tuple)
    assert "MODEL_RUNTIME_ENABLED" in names
    assert "MODEL_RUNTIME_CREDENTIAL_BACKEND" in names
    assert "MODEL_RUNTIME_CREDENTIAL_AWS_REGION" in names
    assert "MODEL_RUNTIME_DEFAULT_PROVIDER" in names


def test_required_env_vars_env_backend_does_not_require_region(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "env")
    monkeypatch.setenv("MODEL_RUNTIME_DEFAULT_PROVIDER", "anthropic")
    s = ModelRuntimeSettings()
    names = required_env_vars(s)
    assert "MODEL_RUNTIME_CREDENTIAL_BACKEND" in names
    assert "MODEL_RUNTIME_CREDENTIAL_AWS_REGION" not in names


# ---------------------------------------------------------------------------
# Local / dev must stay permissive (D9)
# ---------------------------------------------------------------------------


def test_local_env_in_memory_enabled_is_valid(monkeypatch):
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    s = ModelRuntimeSettings()
    assert s.enabled is True
    assert s.credential_backend == "in_memory"
    assert s.default_provider == "deterministic"
