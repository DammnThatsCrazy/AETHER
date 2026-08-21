"""Tests for the DSR mobile-coverage gate (scripts/release/check_dsr_coverage.py).

Verifies the gate passes on the real tree and, critically, that it FAILS closed when
a principal-scoped mobile table is dropped from DSR_COMPONENTS or left unwired in the
consent.erasure handler — the guard that keeps mobile data reachable by a DSR erasure.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_dsr_coverage", ROOT / "scripts" / "release" / "check_dsr_coverage.py"
)
gate = importlib.util.module_from_spec(_spec)
sys.modules["check_dsr_coverage"] = gate
_spec.loader.exec_module(gate)


def test_gate_passes_on_the_real_tree():
    assert gate.run(ROOT) == 0


def test_all_mobile_components_are_registered():
    components = gate._dsr_components(ROOT)
    assert {"continuation_records", "mobile_installations", "client_sync_records"} <= components


def test_kyber_device_components_are_registered_and_hook_named():
    """The operator-keyed kyber device stores are gated with the right hook
    name (M8-E1): each entry must expose delete_by_operator on its repo file."""
    components = gate._dsr_components(ROOT)
    kyber = {
        "kyber_trusted_devices",
        "kyber_webauthn_credentials",
        "kyber_device_proof_keys",
    }
    assert kyber <= components
    for component in kyber:
        spec = gate.MOBILE_DSR_COVERAGE[component]
        assert spec["hook"] == "delete_by_operator", component
        assert gate._repo_defines_hook(ROOT, str(spec["repo"]), "delete_by_operator")


def test_missing_kyber_component_fails(monkeypatch):
    # Drop a kyber device component from DSR_COMPONENTS → the gate must fail
    # (the device store would silently skip erasure).
    original = gate._dsr_components
    monkeypatch.setattr(
        gate, "_dsr_components", lambda root: original(root) - {"kyber_trusted_devices"}
    )
    assert gate.run(ROOT) != 0


def test_missing_component_fails(monkeypatch):
    # Drop one mobile component from the parsed DSR_COMPONENTS → the gate must fail.
    original = gate._dsr_components
    monkeypatch.setattr(
        gate, "_dsr_components", lambda root: original(root) - {"continuation_records"}
    )
    assert gate.run(ROOT) != 0


def test_unwired_handler_fails(monkeypatch):
    # A component present in DSR_COMPONENTS but not marked by the erasure handler
    # (seeded-but-never-marked → DSR never completes) must fail the gate.
    original = gate._handler_marked_components
    monkeypatch.setattr(
        gate, "_handler_marked_components", lambda root: original(root) - {"mobile_installations"}
    )
    assert gate.run(ROOT) != 0
