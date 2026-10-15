"""Stripe key mode must match the deployment environment (sandbox vs live)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import Environment, stripe_key_mode_error  # noqa: E402


@pytest.mark.parametrize("key", ["sk_test_abc123", "rk_test_abc123"])
def test_staging_accepts_sandbox_keys(key: str) -> None:
    assert stripe_key_mode_error(Environment.STAGING, key) is None


@pytest.mark.parametrize("key", ["sk_live_abc123", "rk_live_abc123"])
def test_staging_rejects_live_keys_without_echoing_them(key: str) -> None:
    error = stripe_key_mode_error(Environment.STAGING, key)
    assert error and "staging" in error and key not in error


@pytest.mark.parametrize("key", ["sk_live_abc123", "rk_live_abc123"])
def test_production_accepts_live_keys(key: str) -> None:
    assert stripe_key_mode_error(Environment.PRODUCTION, key) is None


@pytest.mark.parametrize("key", ["sk_test_abc123", "rk_test_abc123"])
def test_production_rejects_sandbox_keys_without_echoing_them(key: str) -> None:
    error = stripe_key_mode_error(Environment.PRODUCTION, key)
    assert error and "production" in error and key not in error


def test_empty_or_unrecognised_keys_and_other_environments_are_not_judged() -> None:
    assert stripe_key_mode_error(Environment.STAGING, "") is None
    assert stripe_key_mode_error(Environment.PRODUCTION, "whatever") is None
    assert stripe_key_mode_error(Environment.LOCAL, "sk_live_abc123") is None
