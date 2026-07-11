"""PR3 — the signal-use policy matrix enforces exact-purpose, no broad fallback."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = json.loads((ROOT / "packages/shared/contracts/signal-use-matrix.json").read_text())
CONSENT = json.loads((ROOT / "packages/shared/contracts/consent-registry.json").read_text())

_BY_TYPE = {s["signal_type"]: s for s in MATRIX["signals"]}
_PURPOSES = {p["key"] for p in CONSENT["purposes"]}
_EXPLICIT = {p["key"] for p in CONSENT["purposes"] if p.get("explicitOptInRequired")}


def test_validator_passes():
    from scripts import validate_signal_use_matrix as v

    assert v.main() == 0


def test_every_required_purpose_is_registry_valid():
    for sig in MATRIX["signals"]:
        assert sig["required_purposes"]
        for p in sig["required_purposes"]:
            assert p in _PURPOSES, f"{sig['signal_type']} -> unknown purpose {p}"


def test_fingerprint_only_never_links():
    assert _BY_TYPE["device_fingerprint"]["allow_identity_linking"] is False


def test_sensitive_signals_require_exact_explicit_purpose():
    for sig in MATRIX["signals"]:
        if sig.get("explicit_opt_in_required"):
            req = sig["required_purposes"]
            assert len(req) == 1 and req[0] in _EXPLICIT, sig["signal_type"]


def test_every_explicit_optin_purpose_has_a_signal():
    covered = {p for s in MATRIX["signals"] for p in s["required_purposes"]}
    for purpose in _EXPLICIT:
        assert purpose in covered, f"explicit opt-in purpose {purpose} has no signal-use entry"
