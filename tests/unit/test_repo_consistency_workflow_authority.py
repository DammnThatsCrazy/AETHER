"""The PR workflow exposes distinct, fail-closed delivery authorities."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-consistency.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_pr_workflow_has_explicit_delivery_stages() -> None:
    jobs = _workflow()["jobs"]
    assert {
        "classify-change",
        "build-artifact",
        "selected-verification",
        "repo-consistency",
        "publish-evidence",
    }.issubset(jobs)
    assert jobs["build-artifact"]["needs"] == "classify-change"
    assert set(jobs["selected-verification"]["needs"]) == {"classify-change", "build-artifact"}
    assert set(jobs["publish-evidence"]["needs"]) == {
        "classify-change",
        "build-artifact",
        "selected-verification",
        "repo-consistency",
    }


def test_canonical_gate_remains_pr_completion_authority() -> None:
    jobs = _workflow()["jobs"]
    canonical_script = "\n".join(
        step.get("run", "") for step in jobs["repo-consistency"]["steps"]
    )
    assert "make ci-check" in canonical_script
    assert '"authority":"pr-completion"' in canonical_script
    assert '"blocking":true' in canonical_script


def test_build_artifact_excludes_dependency_dist_directories() -> None:
    jobs = _workflow()["jobs"]
    script = "\n".join(step.get("run", "") for step in jobs["build-artifact"]["steps"])
    assert "-name node_modules -prune" in script


def test_built_candidate_is_verified_without_rebuilding_in_consumers() -> None:
    jobs = _workflow()["jobs"]
    build = "\n".join(step.get("run", "") for step in jobs["build-artifact"]["steps"])
    selected = "\n".join(step.get("run", "") for step in jobs["selected-verification"]["steps"])
    assert "scripts/artifact_builder.py" in build
    assert "release-candidate.json" in build
    assert "--verify" in selected
    assert "tar --extract --gzip --file release-evidence/repository-build.tar.gz" in selected
    assert "npm run build" not in selected
    assert "build-artifact" in jobs["selected-verification"]["needs"]


def test_publication_fails_when_any_required_stage_did_not_pass() -> None:
    publication = _workflow()["jobs"]["publish-evidence"]
    assert str(publication["if"]) == "always()"
    script = "\n".join(step.get("run", "") for step in publication["steps"])
    assert 'value != "success"' in script
    assert "raise SystemExit" in script
    uploads = [
        step for step in publication["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads and uploads[0]["if"] == "always()"
