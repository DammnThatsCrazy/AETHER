"""Tests for NoesisStartupValidator (P0.7)."""

from __future__ import annotations

import pytest

from services.noesis.startup import NoesisStartupValidator


def test_valid_config_no_llm(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "false")
    monkeypatch.setenv("NOESIS_RATE_LIMIT_QPM", "60")
    monkeypatch.setenv("NOESIS_DAILY_QUOTA", "1000")
    monkeypatch.setenv("NOESIS_PROVIDER_TOKEN_BUDGET", "100000")

    errors = NoesisStartupValidator().validate()
    assert errors == []


def test_missing_anthropic_key_when_llm_enabled(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    errors = NoesisStartupValidator().validate()
    assert any("ANTHROPIC_API_KEY" in e for e in errors)


def test_missing_openai_key_when_llm_enabled(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    errors = NoesisStartupValidator().validate()
    assert any("OPENAI_API_KEY" in e for e in errors)


def test_anthropic_key_present_clears_error(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")

    errors = NoesisStartupValidator().validate()
    assert errors == []


def test_invalid_qpm_is_caught(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "false")
    monkeypatch.setenv("NOESIS_RATE_LIMIT_QPM", "not-a-number")

    errors = NoesisStartupValidator().validate()
    assert any("NOESIS_RATE_LIMIT_QPM" in e for e in errors)


def test_zero_qpm_is_caught(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "false")
    monkeypatch.setenv("NOESIS_RATE_LIMIT_QPM", "0")

    errors = NoesisStartupValidator().validate()
    assert any("NOESIS_RATE_LIMIT_QPM" in e for e in errors)


def test_noesis_disabled_skips_all_validation(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "false")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NOESIS_RATE_LIMIT_QPM", "0")

    errors = NoesisStartupValidator().validate()
    assert errors == []


def test_unknown_provider_is_caught(monkeypatch):
    monkeypatch.setenv("NOESIS_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_ENABLED", "true")
    monkeypatch.setenv("NOESIS_LLM_PROVIDER", "gemini")

    errors = NoesisStartupValidator().validate()
    assert any("gemini" in e for e in errors)
