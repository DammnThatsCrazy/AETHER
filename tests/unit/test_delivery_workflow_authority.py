from pathlib import Path

from scripts.release.check_delivery_workflow_authority import _executable_run_text, validate


ROOT = Path(__file__).resolve().parents[2]


def test_enforced_delivery_authority_has_one_owner_per_blueprint_authority():
    assert validate(root=ROOT) == []


def test_delivery_authority_rejects_non_github_workflow_path(tmp_path: Path):
    source = (ROOT / "config/delivery_workflow_authority.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "authority.yaml"
    bad.write_text(
        source.replace(".github/workflows/repo-consistency.yml", "scripts/not-a-workflow.py", 1),
        encoding="utf-8",
    )
    errors = validate(config_path=bad, root=ROOT)
    assert any("non-GitHub workflow path" in error for error in errors)


def test_required_command_must_be_in_executable_run_not_step_name_or_comment():
    workflow = {
        "jobs": {
            "plan": {
                "steps": [
                    {"name": "terraform plan", "run": "# terraform plan\necho plan omitted"},
                    {"name": "log", "run": "echo terraform apply"},
                ]
            }
        }
    }
    assert "terraform plan" not in _executable_run_text(workflow)
    workflow["jobs"]["plan"]["steps"].append({"run": "terraform plan -input=false"})
    assert "terraform plan" in _executable_run_text(workflow)
