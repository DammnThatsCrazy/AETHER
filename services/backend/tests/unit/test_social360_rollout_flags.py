"""Social360 + Relationship Fidelity product-surface rollout flags (M10).

Covers the six rollout_controls flags added to ``Social360Config``
(config/settings.py), mirroring docs/blueprints/social360.md §121-122:

* AETHER_SOCIAL360_ENABLED            → False
* AETHER_SOCIAL_UPR_ENABLED           → False
* AETHER_RELATIONSHIP_MOTIFS_ENABLED  → False
* AETHER_RELATIONSHIP_FIDELITY_MODE   → "off"
* AETHER_PATH_FIDELITY_ENABLED        → False
* AETHER_SOCIAL_LENSES_ENABLED        → False

Every control is fail-closed: defaults OFF / "off", settable via env or
dataclass kwargs, and wired through the ``settings`` singleton runtime code
reads. ``Social360Config`` field defaults are evaluated at module import time,
so a plain re-instantiation never observes a post-import env change; the tests
reload ``config.settings`` to prove the env → config wiring (the pattern used
by test_runtime_flags.py).
"""
from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

import config.settings as settings_module  # noqa: E402

FLAG_ENV = (
    "AETHER_SOCIAL360_ENABLED",
    "AETHER_SOCIAL_UPR_ENABLED",
    "AETHER_RELATIONSHIP_MOTIFS_ENABLED",
    "AETHER_RELATIONSHIP_FIDELITY_MODE",
    "AETHER_PATH_FIDELITY_ENABLED",
    "AETHER_SOCIAL_LENSES_ENABLED",
)


def _reload_with_env(monkeypatch: pytest.MonkeyPatch, **setvars: str) -> None:
    """Clear the six Social360 flags (fail-closed), apply ``setvars``, reload.

    Reloading re-evaluates the dataclass field defaults against the current env,
    and rebuilds the ``settings`` singleton (which runs Settings.__post_init__).
    """
    for key in FLAG_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in setvars.items():
        monkeypatch.setenv(key, value)
    importlib.reload(settings_module)


@pytest.fixture(autouse=True)
def _reset_social360_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore default (fail-closed) flags around every test."""
    _reload_with_env(monkeypatch)


# ── Defaults (fail-closed) ──────────────────────────────────────────────────


def test_six_social360_flags_default_off() -> None:
    cfg = settings_module.Social360Config()
    assert cfg.social360_enabled is False
    assert cfg.social_upr_enabled is False
    assert cfg.relationship_motifs_enabled is False
    assert cfg.relationship_fidelity_mode == "off"
    assert cfg.path_fidelity_enabled is False
    assert cfg.social_lenses_enabled is False


def test_fidelity_mode_ladder_allows_off_shadow_warn_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    for mode in ("off", "shadow", "warn", "enforce"):
        _reload_with_env(monkeypatch, AETHER_RELATIONSHIP_FIDELITY_MODE=mode)
        cfg = settings_module.Social360Config()
        assert cfg.relationship_fidelity_mode == mode
        # The master Settings must boot in every valid mode (local defaults).
        settings_module.Settings()


def test_fidelity_mode_outside_ladder_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="AETHER_RELATIONSHIP_FIDELITY_MODE"):
        _reload_with_env(monkeypatch, AETHER_RELATIONSHIP_FIDELITY_MODE="banana")


# ── Env → config wiring ─────────────────────────────────────────────────────


def test_flags_wire_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_with_env(
        monkeypatch,
        AETHER_SOCIAL360_ENABLED="true",
        AETHER_SOCIAL_UPR_ENABLED="1",
        AETHER_RELATIONSHIP_MOTIFS_ENABLED="yes",
        AETHER_RELATIONSHIP_FIDELITY_MODE="enforce",
        AETHER_PATH_FIDELITY_ENABLED="true",
        AETHER_SOCIAL_LENSES_ENABLED="true",
    )
    cfg = settings_module.Social360Config()
    assert cfg.social360_enabled is True
    assert cfg.social_upr_enabled is True
    assert cfg.relationship_motifs_enabled is True
    assert cfg.relationship_fidelity_mode == "enforce"
    assert cfg.path_fidelity_enabled is True
    assert cfg.social_lenses_enabled is True


def test_master_settings_exposes_social360_config() -> None:
    s = settings_module.Settings()
    assert s.social360.social360_enabled is False
    assert s.social360.social_upr_enabled is False
    assert s.social360.relationship_motifs_enabled is False
    assert s.social360.relationship_fidelity_mode == "off"
    assert s.social360.path_fidelity_enabled is False
    assert s.social360.social_lenses_enabled is False
