"""Unit tests for scripts/validate_contracts.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_contracts.py"


@pytest.fixture(scope="module")
def vc():
    spec = importlib.util.spec_from_file_location("validate_contracts", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_contracts"] = module
    spec.loader.exec_module(module)
    return module


def _events(events, families=None, consent_purposes=None):
    return {
        "events": events,
        "families": families if families is not None else ["core"],
        "consent_purposes": consent_purposes if consent_purposes is not None else [],
    }


def _consent(*purposes):
    return {"purposes": [{"name": p, "description": "x"} for p in purposes]}


# --- check_event_consent_purposes -----------------------------------------


def test_consent_purpose_match_passes(vc):
    events = _events([{"name": "track", "family": "core", "consent_purpose": "analytics"}])
    consent = _consent("analytics")
    assert vc.check_event_consent_purposes(events, consent) == []


def test_consent_purpose_mismatch_fails(vc):
    events = _events([{"name": "track", "family": "core", "consent_purpose": "telepathy"}])
    consent = _consent("analytics")
    errors = vc.check_event_consent_purposes(events, consent)
    assert len(errors) == 1
    assert "telepathy" in errors[0]
    assert "track" in errors[0]


# --- check_event_families --------------------------------------------------


def test_event_family_match_passes(vc):
    events = _events(
        [{"name": "track", "family": "core", "consent_purpose": "analytics"}],
        families=["core", "identity"],
    )
    assert vc.check_event_families(events) == []


def test_event_family_mismatch_fails(vc):
    events = _events(
        [{"name": "track", "family": "phantom", "consent_purpose": "analytics"}],
        families=["core"],
    )
    errors = vc.check_event_families(events)
    assert len(errors) == 1
    assert "phantom" in errors[0]


# --- check_consent_purposes_self_consistent --------------------------------


def test_advertised_purpose_match_passes(vc):
    events = _events([], consent_purposes=["analytics", "web3"])
    consent = _consent("analytics", "web3", "agent")
    assert vc.check_consent_purposes_self_consistent(events, consent) == []


def test_advertised_purpose_mismatch_fails(vc):
    events = _events([], consent_purposes=["analytics", "ghost"])
    consent = _consent("analytics")
    errors = vc.check_consent_purposes_self_consistent(events, consent)
    assert len(errors) == 1
    assert "ghost" in errors[0]


# --- end-to-end against the real generated artifacts ----------------------


def test_real_artifacts_are_consistent(vc):
    """The committed docs/_generated artifacts must cross-validate."""
    events = vc._load("events.json")
    consent = vc._load("consent.json")
    if events is None or consent is None:
        pytest.skip("generated artifacts not present — run run_all.py")
    assert vc.check_event_consent_purposes(events, consent) == []
    assert vc.check_event_families(events) == []
    assert vc.check_consent_purposes_self_consistent(events, consent) == []
