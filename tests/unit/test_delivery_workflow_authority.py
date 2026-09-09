from pathlib import Path

from scripts.release.check_delivery_workflow_authority import validate


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
