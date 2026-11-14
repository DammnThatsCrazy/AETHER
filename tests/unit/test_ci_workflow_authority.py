"""`ci.yml` is the single, fail-closed pull-request authority (`ci / verdict`)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _ci() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    value = document.get("on") if "on" in document else document.get(True)
    return value if isinstance(value, dict) else {}


def _script(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_authority_runs_for_non_draft_pull_requests_and_trusted_pushes() -> None:
    triggers = _triggers(_ci())
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert triggers["push"]["branches"] == ["development", "staging", "main"]
    assert "merge_group" in triggers
    assert "workflow_dispatch" in triggers


def test_drafts_run_nothing() -> None:
    classify = _ci()["jobs"]["classify"]
    assert "draft == false" in str(classify["if"])


def test_verdict_aggregates_every_stage_and_always_runs() -> None:
    jobs = _ci()["jobs"]
    verdict = jobs["verdict"]
    assert set(verdict["needs"]) == {"classify", "suites", "checks"}
    assert str(verdict["if"]) == "always()"
    script = _script(verdict)
    for stage in ("classification did not succeed", "selected checks", "selected suites"):
        assert stage in script
    # A legitimate no-op is only an empty selection with suites skipped.
    assert '"$MODE" = empty' in script


def test_verdict_context_is_the_job_name_and_manual_replays_cannot_claim_it() -> None:
    name = str(_ci()["jobs"]["verdict"]["name"])
    assert "'ci / verdict'" in name
    assert "workflow_dispatch" in name and "manual replay" in name


def test_evidence_is_published_only_by_verified_non_draft_non_manual_runs() -> None:
    steps = _ci()["jobs"]["verdict"]["steps"]
    evaluate = next(i for i, s in enumerate(steps) if s.get("name") == "Evaluate the planned job set")
    for step in steps[evaluate + 1:]:
        condition = str(step.get("if", ""))
        assert "workflow_dispatch" in condition and "draft == false" in condition
    upload = next(s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact"))
    assert upload["with"]["name"] == "ci-verdict-evidence"
    assert upload["with"]["retention-days"] == 7


def test_full_ci_is_not_a_blocking_pr_dependency() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "make ci-check" not in text and "make release-gate" not in text


def test_selection_uses_the_registry_selector() -> None:
    assert "scripts/ci_select.py" in _script(_ci()["jobs"]["classify"])
    assert "scripts/suite_worker.py" in _script(_ci()["jobs"]["suites"])


def test_control_gates_and_selected_builds_are_checks() -> None:
    rules = yaml.safe_load((ROOT / "config/ci/ownership.yaml").read_text(encoding="utf-8"))
    checks = {c["id"]: c for c in rules["checks"]}
    assert checks["control-gates"]["always"] is True
    assert checks["control-gates"]["run"] == ["python scripts/ci_control_gates.py"]
    assert checks["build-selected"]["base"] is True
    assert checks["build-selected"]["run"] == ["python scripts/ci_build_selected.py"]
