from __future__ import annotations

from pathlib import Path

from scripts.validate_ci_execution_contracts import validate_workflow_cadence


ROOT = Path(__file__).resolve().parents[2]


def test_repository_pr_workflow_cadence_is_finalization_only() -> None:
    assert validate_workflow_cadence(ROOT) == []


def test_workflow_cadence_rejects_untyped_pull_request_trigger(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config/verification_policy.yaml").write_text(
        "normal_pr:\n  finalization_event: ready_for_review\n",
        encoding="utf-8",
    )
    workflow_dir = tmp_path / ".github/workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "repo-consistency.yml").write_text(
        "name: Repo Consistency\non:\n  pull_request:\njobs:\n"
        "  publish-evidence:\n    name: verification / disposition\n",
        encoding="utf-8",
    )

    errors = validate_workflow_cadence(tmp_path)
    assert any("pull_request must declare types" in error for error in errors)


def _cadence_fixture(tmp_path: Path, extra_name: str, types: str) -> list[str]:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config/verification_policy.yaml").write_text(
        "normal_pr:\n  finalization_event: ready_for_review\n", encoding="utf-8"
    )
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True)
    (wf / "repo-consistency.yml").write_text(
        "name: Repo Consistency\non:\n  pull_request:\n    types: [ready_for_review]\njobs:\n"
        "  publish-evidence:\n    name: verification / disposition\n",
        encoding="utf-8",
    )
    (wf / extra_name).write_text(
        f"name: x\non:\n  pull_request:\n    types: {types}\njobs: {{}}\n", encoding="utf-8"
    )
    return validate_workflow_cadence(tmp_path)


def test_ci_v2_workflow_may_run_on_every_pr_head(tmp_path: Path) -> None:
    assert _cadence_fixture(
        tmp_path, "ci.yml", "[opened, synchronize, reopened, ready_for_review]"
    ) == []


def test_ci_v2_exemption_is_limited_to_ci_yml(tmp_path: Path) -> None:
    errors = _cadence_fixture(
        tmp_path, "other.yml", "[opened, synchronize, reopened, ready_for_review]"
    )
    assert any("other.yml" in e for e in errors)


def test_ci_v2_types_are_pinned(tmp_path: Path) -> None:
    errors = _cadence_fixture(tmp_path, "ci.yml", "[synchronize]")
    assert any("ci.yml" in e for e in errors)
