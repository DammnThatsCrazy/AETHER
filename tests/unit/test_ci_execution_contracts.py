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
