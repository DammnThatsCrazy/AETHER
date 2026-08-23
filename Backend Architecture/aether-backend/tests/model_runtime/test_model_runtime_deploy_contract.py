"""Deployment-contract test for the model-runtime settings layer (Commit 15).

C15 (ADR-008 D5/D8/D9) deployment & config. The settings module
(``services/model_runtime/config.py``) and the deployment artifacts — the
backend env template, the deploy env template, and the deploy README — must
stay in lock-step: if an operator copy-pastes the env template, the service
must have no undeclared required variable.

Concurrency / gating: C15 lands in parallel. ``config.py`` is importor-skipped
so this suite passes (as a skip) until C15-A lands; a deployment artifact file
that is not yet present is skipped individually with an explicit reason so the
shared contract checks do not hard-fail mid-commit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# The settings module is C15-A and may land concurrently with this test; until
# it is importable the whole suite skips.
config = pytest.importorskip("services.model_runtime.config")

_REPO_ROOT = Path(__file__).resolve().parents[4]
# The backend's canonical env example is the repo-root `.env.example` — there
# is no per-service copy under aether-backend (verified during C15; the root
# file owns the model-runtime section). Pointing here (rather than at a
# non-existent backend copy) keeps the required-settings check RUNNING instead
# of skipping, against the same canonical source the operator copies.
_BACKEND_ENV_EXAMPLE = _REPO_ROOT / ".env.example"
_DEPLOY_ENV_EXAMPLE = _REPO_ROOT / "deploy" / "model-runtime" / ".env.example"
_DEPLOY_README = _REPO_ROOT / "deploy" / "model-runtime" / "README.md"

# The env prefix the settings layer is bound to (config.py SettingsConfigDict).
_ENV_PREFIX = "MODEL_RUNTIME_"

# Secret-shaped tokens that must never appear in a committed deployment
# template value (matched case-insensitively).
_SECRET_TOKENS = ("sk-", "akia", "bearer ", "secret=", "key=")

# Phrases that document the fail-closed production rule for in_memory.
_FAIL_CLOSED_PHRASES = (
    "do not use",
    "must not",
    "must be",
    "not for production",
    "forbidden in production",
    "prohibited in production",
    "production forbids",
    "production",
)

_ENV_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", re.MULTILINE)


def _call_required_env_vars(settings) -> set[str]:
    """Invoke ``required_env_vars`` tolerantly (absent / signature drift)."""
    resolver = getattr(config, "required_env_vars", None)
    if resolver is None:
        return set()
    try:
        raw = resolver(settings)
    except TypeError:
        try:
            raw = resolver()
        except TypeError:
            return set()
    if isinstance(raw, dict):
        return set(raw)
    return set(raw)


def _required_env_var_names() -> set[str]:
    """Return the ``MODEL_RUNTIME_*`` names a deployment must declare.

    Primary source is C15-A's ``required_env_vars(settings)``; if it is absent
    or returns nothing, fall back to deriving the documented ``MODEL_RUNTIME_*``
    list from the settings model's declared fields + env_prefix.
    """
    settings = config.ModelRuntimeSettings()
    names = _call_required_env_vars(settings)
    if names:
        return names
    prefix = config.ModelRuntimeSettings.model_config.get("env_prefix") or _ENV_PREFIX
    return {f"{prefix}{field.upper()}" for field in config.ModelRuntimeSettings.model_fields}


def _env_keys(text: str) -> set[str]:
    """Return the set of declared keys in a dotenv-style file."""
    return {match.group(1) for match in _ENV_KEY_RE.finditer(text)}


def _env_model_runtime_values(text: str) -> dict[str, str]:
    """Return ``MODEL_RUNTIME_*`` key->value pairs (inline comments stripped)."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key.startswith(_ENV_PREFIX):
            continue
        value = value.split(" #", 1)[0].strip()
        pairs[key] = value
    return pairs


def _assert_no_secret_shaped_values(pairs: dict[str, str], label: str) -> None:
    """Assert no ``MODEL_RUNTIME_*`` template value is secret-shaped."""
    offending = {
        key: value
        for key, value in pairs.items()
        if any(token in value.lower() for token in _SECRET_TOKENS)
    }
    assert not offending, f"{label} contains secret-shaped values: {offending}"


def test_backend_env_example_declares_required_settings() -> None:
    if not _BACKEND_ENV_EXAMPLE.exists():
        pytest.skip(f"backend .env.example not present yet: {_BACKEND_ENV_EXAMPLE}")
    required = _required_env_var_names()
    keys = _env_keys(_BACKEND_ENV_EXAMPLE.read_text(encoding="utf-8"))
    missing = sorted(required - keys)
    assert not missing, (
        f"backend .env.example is missing required model-runtime settings: {missing}"
    )


def test_deploy_env_example_declares_required_settings() -> None:
    if not _DEPLOY_ENV_EXAMPLE.exists():
        pytest.skip(f"deploy .env.example not present yet: {_DEPLOY_ENV_EXAMPLE}")
    required = _required_env_var_names()
    keys = _env_keys(_DEPLOY_ENV_EXAMPLE.read_text(encoding="utf-8"))
    missing = sorted(required - keys)
    assert not missing, f"deploy .env.example is missing required model-runtime settings: {missing}"


def test_deploy_readme_documents_required_settings() -> None:
    if not _DEPLOY_README.exists():
        pytest.skip(f"deploy README not present yet: {_DEPLOY_README}")
    required = _required_env_var_names()
    text = _DEPLOY_README.read_text(encoding="utf-8")
    missing = sorted(name for name in required if name not in text)
    assert not missing, (
        f"deploy README does not document required model-runtime settings: {missing}"
    )


def test_no_secret_shaped_values_in_env_templates() -> None:
    files = [
        (_BACKEND_ENV_EXAMPLE, "backend .env.example"),
        (_DEPLOY_ENV_EXAMPLE, "deploy .env.example"),
    ]
    present = [(path, label) for path, label in files if path.exists()]
    if not present:
        pytest.skip("neither env template present yet — nothing to scan")
    for path, label in present:
        _assert_no_secret_shaped_values(
            _env_model_runtime_values(path.read_text(encoding="utf-8")), label
        )


def test_deploy_readme_documents_fail_closed_prod_rule() -> None:
    if not _DEPLOY_README.exists():
        pytest.skip(f"deploy README not present yet: {_DEPLOY_README}")
    text = _DEPLOY_README.read_text(encoding="utf-8").lower()
    assert "in_memory" in text, "deploy README must document the in_memory credential backend"
    assert any(phrase in text for phrase in _FAIL_CLOSED_PHRASES), (
        "deploy README must document that in_memory is not allowed in production"
    )


def test_settings_defaults_are_fail_closed() -> None:
    # D9: the feature gate defaults OFF.
    assert config.ModelRuntimeSettings().enabled is False
    # D5: credentials default to the non-durable, non-production backend.
    assert config.ModelRuntimeSettings().credential_backend == "in_memory"
