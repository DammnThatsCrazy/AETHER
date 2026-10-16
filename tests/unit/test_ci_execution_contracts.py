from __future__ import annotations

from pathlib import Path

from scripts.validate_ci_execution_contracts import validate_workflow_cadence

ROOT = Path(__file__).resolve().parents[2]

AUTHORITY = (
    "name: ci\non:\n  pull_request:\n    types: [opened, synchronize, reopened, ready_for_review]\n"
    "jobs:\n  verdict:\n    name: verdict\n"
)


def test_repository_pr_workflow_cadence_matches_the_authority_contract() -> None:
    assert validate_workflow_cadence(ROOT) == []


def _fixture(tmp_path: Path, files: dict[str, str]) -> list[str]:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config/verification_policy.yaml").write_text(
        "normal_pr:\n  finalization_event: ready_for_review\n", encoding="utf-8"
    )
    wf = tmp_path / ".github/workflows"
    wf.mkdir(parents=True)
    for name, text in files.items():
        (wf / name).write_text(text, encoding="utf-8")
    return validate_workflow_cadence(tmp_path)


def _other(types: str) -> str:
    return f"name: x\non:\n  pull_request:\n    types: {types}\njobs: {{}}\n"


def test_workflow_cadence_rejects_untyped_pull_request_trigger(tmp_path: Path) -> None:
    errors = _fixture(tmp_path, {"ci.yml": AUTHORITY, "other.yml": "name: x\non:\n  pull_request:\njobs: {}\n"})
    assert any("pull_request must declare types" in error for error in errors)


def test_authority_may_run_on_every_pr_head(tmp_path: Path) -> None:
    assert _fixture(tmp_path, {"ci.yml": AUTHORITY}) == []


def test_other_workflows_are_finalization_only(tmp_path: Path) -> None:
    ok = _fixture(tmp_path, {"ci.yml": AUTHORITY, "other.yml": _other("[ready_for_review]")})
    assert ok == []


def test_only_the_authority_may_run_on_every_pr_head(tmp_path: Path) -> None:
    errors = _fixture(
        tmp_path,
        {"ci.yml": AUTHORITY, "other.yml": _other("[opened, synchronize, reopened, ready_for_review]")},
    )
    assert any("other.yml" in e for e in errors)


def test_authority_types_are_pinned(tmp_path: Path) -> None:
    errors = _fixture(tmp_path, {"ci.yml": AUTHORITY.replace("[opened, synchronize, reopened, ready_for_review]", "[synchronize]")})
    assert any("ci.yml" in e for e in errors)


def test_authority_check_name_is_pinned(tmp_path: Path) -> None:
    errors = _fixture(tmp_path, {"ci.yml": AUTHORITY.replace("name: verdict", "name: summary")})
    assert any("ci / verdict" in e for e in errors)


def test_missing_authority_is_an_error(tmp_path: Path) -> None:
    errors = _fixture(tmp_path, {"other.yml": _other("[ready_for_review]")})
    assert any("ci.yml" in e for e in errors)
