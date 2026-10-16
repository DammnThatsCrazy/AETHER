"""CI V2 control gates and selected-build wrapper."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import ci_build_selected, ci_control_gates
from scripts.lib.verification_router import load_router_registry

ROOT = Path(__file__).resolve().parents[2]


def test_control_gates_cover_the_legacy_universal_fast_set() -> None:
    registry = load_router_registry(ROOT / "config/verification_router.yaml")
    ids = ci_control_gates.gate_ids(registry)
    assert set(registry.lanes["fast"]) <= set(ids)
    assert "contracts" in ids
    assert len(ids) == len(set(ids))


def test_control_gates_fail_closed_on_an_unknown_gate() -> None:
    registry = load_router_registry(ROOT / "config/verification_router.yaml")

    class Stub:
        lanes = {"fast": ["not_a_registered_check"]}
        checks = registry.checks

    with pytest.raises(ValueError, match="not_a_registered_check"):
        ci_control_gates.gate_ids(Stub())


def test_build_selection_is_empty_for_a_docs_only_diff(tmp_path: Path) -> None:
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    sel = ci_build_selected.selection(out.stdout.strip())  # no diff against HEAD
    assert not sel.get("workspaces") and not sel.get("backend_image")


def test_build_selected_dry_run_prints_the_selection(capsys: pytest.CaptureFixture[str]) -> None:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert ci_build_selected.main(["--base", head.stdout.strip(), "--dry-run"]) == 0
    assert "backend_image: False" in capsys.readouterr().out


def test_build_selected_blocks_when_the_plan_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        stderr = "boom"

    def fake_run(cmd, **kw):  # writes a BLOCKED plan
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps({"status": "BLOCKED", "reason": "x"}))
        return Proc()

    monkeypatch.setattr(ci_build_selected.subprocess, "run", fake_run)
    with pytest.raises(SystemExit, match="BLOCKED"):
        ci_build_selected.selection("HEAD")
