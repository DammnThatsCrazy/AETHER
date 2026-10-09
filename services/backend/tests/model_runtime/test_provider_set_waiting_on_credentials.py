"""Every adapter-backed provider is wired and, without credentials, simply waiting."""
from __future__ import annotations

import pytest

from services.model_runtime import providers as provider_set
from services.model_runtime.routes import _health_reason, _provider_set, _sanitize_reason, _GENERIC_REASON

ALL_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "MODEL_RUNTIME_COMPAT_API_KEY", "MODEL_RUNTIME_COMPAT_BASE_URL", "MODEL_RUNTIME_COMPAT_PROVIDER_NAME",
    "MODEL_RUNTIME_KIMI_API_KEY", "MODEL_RUNTIME_KIMI_BASE_URL",
    "MODEL_RUNTIME_DEEPSEEK_API_KEY", "MODEL_RUNTIME_DEEPSEEK_BASE_URL",
    "MODEL_RUNTIME_QWEN_API_KEY", "MODEL_RUNTIME_QWEN_BASE_URL",
)


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    provider_set.reset_runtime()
    yield
    provider_set.reset_runtime()


def test_every_adapter_backed_provider_is_registered_and_waiting():
    providers = provider_set.build_providers()
    assert set(providers) == {
        "deterministic", "anthropic", "openai", "openai_compatible", "kimi", "deepseek", "qwen",
    }
    assert providers["deterministic"].is_configured() is True
    for name in set(providers) - {"deterministic"}:
        assert providers[name].is_configured() is False, name
        assert provider_set.missing_credentials(name), name


def test_the_health_reason_names_the_variables_that_unlock_each_provider():
    reason = provider_set.credential_reason("anthropic", configured=False)
    assert reason == "waiting on credentials: set ANTHROPIC_API_KEY"
    assert "MODEL_RUNTIME_KIMI_API_KEY" in provider_set.credential_reason("kimi", configured=False)
    assert provider_set.credential_reason("anthropic", configured=True) == "configured"
    assert provider_set.credential_reason("nope", configured=False) == "no adapter for this provider"
    # The wording survives the response sanitizer (it carries no secret-shaped marker).
    for name in provider_set.REQUIREMENTS:
        text = provider_set.credential_reason(name, configured=False)
        assert _sanitize_reason(text) == text, name


def test_supplying_the_variables_is_the_only_step_left(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-value")
    monkeypatch.setenv("MODEL_RUNTIME_KIMI_API_KEY", "test-value")
    monkeypatch.setenv("MODEL_RUNTIME_KIMI_BASE_URL", "https://kimi.invalid/v1")
    providers = provider_set.build_providers()
    assert providers["anthropic"].is_configured() is True
    assert providers["kimi"].is_configured() is True
    assert providers["openai"].is_configured() is False
    assert provider_set.missing_credentials("kimi") == ()


def test_a_key_without_its_endpoint_is_still_waiting(monkeypatch):
    monkeypatch.setenv("MODEL_RUNTIME_DEEPSEEK_API_KEY", "test-value")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_API_KEY", "test-value")
    providers = provider_set.build_providers()
    assert providers["deepseek"].is_configured() is False
    assert providers["openai_compatible"].is_configured() is False
    assert provider_set.missing_credentials("deepseek") == ("MODEL_RUNTIME_DEEPSEEK_BASE_URL",)


def test_named_endpoints_do_not_borrow_the_generic_compat_credentials(monkeypatch):
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_API_KEY", "test-value")
    monkeypatch.setenv("MODEL_RUNTIME_COMPAT_BASE_URL", "https://compat.invalid/v1")
    providers = provider_set.build_providers()
    assert providers["openai_compatible"].is_configured() is True
    for name in ("kimi", "deepseek", "qwen"):
        assert providers[name].is_configured() is False, name


def test_the_runtime_is_built_over_the_real_set_without_credentials():
    runtime = provider_set.get_runtime()
    assert {"anthropic", "openai", "kimi", "deepseek", "qwen", "openai_compatible"} <= set(runtime.provider_names())
    assert provider_set.get_runtime() is runtime  # built once


def test_the_health_surface_reports_the_real_set_including_registry_providers():
    names = set(_provider_set())
    assert {"deterministic", "anthropic", "openai", "kimi", "deepseek", "qwen", "openai_compatible"} <= names


def test_health_reason_passes_unknown_probe_reasons_through_for_sanitizing():
    class _H:
        provider = "anthropic"
        configured = False
        reason = "something else"

    assert _health_reason(_H()) == "something else"
    _H.reason = "not configured"
    assert _health_reason(_H()).startswith("waiting on credentials")
    assert _sanitize_reason("Bearer abc") == _GENERIC_REASON
