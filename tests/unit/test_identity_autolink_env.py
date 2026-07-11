"""PR3 — strong (probabilistic) identity auto-linking is OFF by default in
staging/production; deterministic auto-linking is unaffected; an explicit env
opt-in re-enables strong auto-link.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

for _mod in ("jwt", "cryptography", "cryptography.hazmat"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.identity.resolver import _strong_autolink_enabled  # noqa: E402


@pytest.mark.parametrize("env", ["local", "dev", "test", ""])
def test_strong_autolink_enabled_in_non_prod(monkeypatch, env):
    monkeypatch.setenv("AETHER_ENV", env)
    monkeypatch.delenv("AETHER_IDENTITY_STRONG_AUTOLINK", raising=False)
    assert _strong_autolink_enabled() is True


@pytest.mark.parametrize("env", ["staging", "production", "prod", "PRODUCTION"])
def test_strong_autolink_disabled_by_default_in_prod(monkeypatch, env):
    monkeypatch.setenv("AETHER_ENV", env)
    monkeypatch.delenv("AETHER_IDENTITY_STRONG_AUTOLINK", raising=False)
    assert _strong_autolink_enabled() is False


@pytest.mark.parametrize("flag", ["1", "true", "yes", "on"])
def test_explicit_opt_in_reenables_strong_autolink_in_prod(monkeypatch, flag):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_IDENTITY_STRONG_AUTOLINK", flag)
    assert _strong_autolink_enabled() is True


def test_non_truthy_flag_does_not_reenable(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("AETHER_IDENTITY_STRONG_AUTOLINK", "maybe")
    assert _strong_autolink_enabled() is False
