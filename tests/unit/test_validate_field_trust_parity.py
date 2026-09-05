"""Unit tests for scripts/validate_field_trust_parity.py.

Exercises the core diff function (`drift_messages`) with stubbed generator
helpers so drift detection is covered without coupling to the full live
generator's input requirements, plus a live-tree smoke test of `main()`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_field_trust_parity.py"


@pytest.fixture(scope="module")
def vftp():
    spec = importlib.util.spec_from_file_location("validate_field_trust_parity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_field_trust_parity"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stub_gen(vftp, monkeypatch):
    """No-op structural validation; generator helpers echo inputs back."""
    monkeypatch.setattr(vftp.gen, "validate_field_trust", lambda reg: None)
    monkeypatch.setattr(
        vftp.gen, "update_events_ts", lambda reg, current: current
    )
    monkeypatch.setattr(
        vftp.gen, "gen_python_registry", lambda reg, consent: "PY_SAME"
    )
    return vftp.gen


# --- drift_messages (core diff function) -----------------------------------


def test_clean_inputs_produce_no_messages(vftp, stub_gen):
    msgs = vftp.drift_messages({}, {}, "TS", "PY_SAME")
    assert msgs == []


def test_ts_drift_reports_events_ts(vftp, stub_gen, monkeypatch):
    def _updated(reg, current):
        return "TS_REWRITTEN"

    monkeypatch.setattr(vftp.gen, "update_events_ts", _updated)
    msgs = vftp.drift_messages({}, {}, "TS_CURRENT", "PY_SAME")
    assert len(msgs) == 1
    assert "packages/shared/events.ts" in msgs[0]
    assert "drifted" in msgs[0]


def test_python_drift_reports_generated_registry(vftp, stub_gen, monkeypatch):
    def _py(reg, consent):
        return "PY_REWRITTEN"

    monkeypatch.setattr(vftp.gen, "gen_python_registry", _py)
    msgs = vftp.drift_messages({}, {}, "TS", "PY_CURRENT")
    assert len(msgs) == 1
    assert "generated_registry.py" in msgs[0]
    assert "drifted" in msgs[0]


def test_both_drift_reports_both(vftp, stub_gen, monkeypatch):
    monkeypatch.setattr(
        vftp.gen, "update_events_ts", lambda reg, current: "TS_REWRITTEN"
    )
    monkeypatch.setattr(
        vftp.gen, "gen_python_registry", lambda reg, consent: "PY_REWRITTEN"
    )
    msgs = vftp.drift_messages({}, {}, "TS_CURRENT", "PY_CURRENT")
    assert len(msgs) == 2
    joined = "\n".join(msgs)
    assert "packages/shared/events.ts" in joined
    assert "generated_registry.py" in joined


def test_structural_failure_propagates_system_exit(vftp, stub_gen, monkeypatch):
    """A registry that fails validate_field_trust must fail the gate via
    SystemExit even when the twins otherwise match."""

    def _validate(reg):
        raise SystemExit(1)

    monkeypatch.setattr(vftp.gen, "validate_field_trust", _validate)
    with pytest.raises(SystemExit) as exc_info:
        vftp.drift_messages({}, {}, "TS", "PY_SAME")
    assert exc_info.value.code == 1


# --- main() over the live tree ----------------------------------------------


def test_main_passes_on_live_tree(vftp):
    """Live-tree smoke: the committed registry + generated twins must be in
    parity (this is what the repo_doctor-wired gate enforces)."""
    assert vftp.main() == 0
