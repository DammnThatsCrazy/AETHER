"""Rights Authority rollout guard — mode parse/default + helper semantics.

Blueprint §16: rollout modes per gate OFF | SHADOW | WARN | ENFORCE, no global
hard flip. An unset/invalid value is always ``off`` (fail closed). Enforcement
only ever binds in ``enforce``; recording is true except in ``off``.
"""
from __future__ import annotations

import pytest

from services.rights_authority import rollout as rollout_mod
from services.rights_authority.rollout import (
    ROLLOUT_ENV_VAR,
    RolloutMode,
    configure_rollout,
    current_mode,
    describe,
    enforce_denials,
    is_active,
    parse_rollout_mode,
    record_decisions,
    reset_rollout,
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_rollout()
    monkeypatch.delenv(ROLLOUT_ENV_VAR, raising=False)
    yield
    reset_rollout()
    monkeypatch.delenv(ROLLOUT_ENV_VAR, raising=False)


# ═══════════════════════════════════════════════════════════════════════════
# Parse + default (fail closed)
# ═══════════════════════════════════════════════════════════════════════════

def test_default_mode_is_off():
    assert current_mode() is RolloutMode.OFF
    assert rollout_mod.mode_label() == "off"


@pytest.mark.parametrize("raw,expected", [
    ("off", RolloutMode.OFF),
    ("OFF", RolloutMode.OFF),
    ("shadow", RolloutMode.SHADOW),
    (" SHADOW ", RolloutMode.SHADOW),
    ("warn", RolloutMode.WARN),
    ("WARN", RolloutMode.WARN),
    ("enforce", RolloutMode.ENFORCE),
    ("Enforce", RolloutMode.ENFORCE),
])
def test_parse_rollout_mode_normalizes(raw, expected):
    assert parse_rollout_mode(raw) is expected


@pytest.mark.parametrize("raw", [None, "", "  ", "enforce-now", "enfrce", "on", 7])
def test_parse_rollout_mode_invalid_fails_closed_to_off(raw):
    assert parse_rollout_mode(raw) is RolloutMode.OFF


def test_parse_rollout_mode_invalid_respects_explicit_default():
    assert parse_rollout_mode("bogus", default=RolloutMode.ENFORCE) is RolloutMode.ENFORCE


# ═══════════════════════════════════════════════════════════════════════════
# Helper semantics across modes
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,active,record,enforce", [
    ("off", False, False, False),
    ("shadow", True, True, False),
    ("warn", True, True, False),
    ("enforce", True, True, True),
])
def test_helper_matrix(monkeypatch, raw, active, record, enforce):
    monkeypatch.setenv(ROLLOUT_ENV_VAR, raw)
    assert is_active() is active
    assert record_decisions() is record
    assert enforce_denials() is enforce


def test_configure_override_precedes_env(monkeypatch):
    monkeypatch.setenv(ROLLOUT_ENV_VAR, "off")
    assert current_mode() is RolloutMode.OFF
    configure_rollout("ENFORCE")
    assert current_mode() is RolloutMode.ENFORCE
    assert enforce_denials() is True
    reset_rollout()
    assert current_mode() is RolloutMode.OFF


def test_describe_snapshot():
    snap = describe()
    assert snap["mode"] == "off"
    assert snap["active"] is False
    assert snap["record_decisions"] is False
    assert snap["enforce_denials"] is False
    assert snap["source"] == "default"
