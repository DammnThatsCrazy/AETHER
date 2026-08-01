"""Tests for the credential registry status reporter (scripts/credentials_status.py).

Verifies the honest provisioning-state logic: env-var derivation, missing/invalid/
configured determination, that a configured slot never reads as ready, that --strict
blocks only credentials required for the active profile, and that no secret value is
ever emitted.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "credentials_status", ROOT / "scripts" / "credentials_status.py"
)
cs = importlib.util.module_from_spec(_spec)
sys.modules["credentials_status"] = cs
_spec.loader.exec_module(cs)


def test_env_var_derivation():
    assert cs._env_var_for("byok:notification:apns") == "AETHER_BYOK_NOTIFICATION_APNS"
    assert cs._env_var_for("byok:distribution:google_play_signing") == (
        "AETHER_BYOK_DISTRIBUTION_GOOGLE_PLAY_SIGNING"
    )


def test_state_missing_when_absent(monkeypatch):
    monkeypatch.delenv("AETHER_BYOK_NOTIFICATION_APNS", raising=False)
    state, name = cs._provisioning_state("byok:notification:apns")
    assert state == cs.MISSING
    assert name == "AETHER_BYOK_NOTIFICATION_APNS"


def test_state_invalid_when_empty(monkeypatch):
    monkeypatch.setenv("AETHER_BYOK_NOTIFICATION_APNS", "   ")
    state, _ = cs._provisioning_state("byok:notification:apns")
    assert state == cs.INVALID


def test_state_configured_when_present(monkeypatch):
    monkeypatch.setenv("AETHER_BYOK_NOTIFICATION_APNS", "opaque-present")
    state, _ = cs._provisioning_state("byok:notification:apns")
    assert state == cs.CONFIGURED


def test_registry_rows_are_all_missing_by_default(monkeypatch):
    for var in list(sys.modules):  # no-op guard; keep import side effects clean
        break
    # Clear all mobile slots so the baseline is deterministic.
    for name in (
        "AETHER_BYOK_NOTIFICATION_APNS", "AETHER_BYOK_NOTIFICATION_FCM",
        "AETHER_BYOK_NOTIFICATION_WEB_PUSH_VAPID", "AETHER_BYOK_NOTIFICATION_EMAIL",
        "AETHER_BYOK_DISTRIBUTION_APPLE_SIGNING", "AETHER_BYOK_DISTRIBUTION_GOOGLE_PLAY_SIGNING",
    ):
        monkeypatch.delenv(name, raising=False)
    rows = cs._rows(cs._load_registry())
    ids = {r["id"] for r in rows}
    assert {"apns", "fcm", "web_push_vapid", "email_ses"}.issubset(ids)
    assert all(r["state"] == cs.MISSING for r in rows)


def test_preflight_strict_blocks_required_profile(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "staging")
    for name in (
        "AETHER_BYOK_NOTIFICATION_APNS", "AETHER_BYOK_NOTIFICATION_FCM",
        "AETHER_BYOK_NOTIFICATION_WEB_PUSH_VAPID", "AETHER_BYOK_NOTIFICATION_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    rows = cs._rows(cs._load_registry())
    assert cs._preflight(rows, strict=True) == 1  # required creds missing → not ready


def test_preflight_local_profile_not_blocked(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local-live")
    rows = cs._rows(cs._load_registry())
    # None of these are required for local-live → strict still passes.
    assert cs._preflight(rows, strict=True) == 0


def test_activation_smoke_never_ready(monkeypatch, capsys):
    rows = cs._rows(cs._load_registry())
    assert cs._activation_smoke(rows) == 0
    out = capsys.readouterr().out.lower()
    assert "ready" not in out.replace("never reported 'ready'", "")


def test_inventory_never_prints_secret_value(monkeypatch, capsys):
    monkeypatch.setenv("AETHER_BYOK_NOTIFICATION_APNS", "SUPER-SECRET-VALUE")
    rows = cs._rows(cs._load_registry())
    cs._inventory(rows)
    out = capsys.readouterr().out
    assert "SUPER-SECRET-VALUE" not in out
