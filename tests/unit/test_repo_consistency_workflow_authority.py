"""The PR workflow exposes distinct, fail-closed delivery authorities."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-consistency.yml"
REPO_HEALTH_WORKFLOW = ROOT / ".github" / "workflows" / "repo-health.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _repo_health_workflow() -> dict:
    return yaml.safe_load(REPO_HEALTH_WORKFLOW.read_text(encoding="utf-8"))


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
    }


def test_adaptive_disposition_is_pr_completion_authority() -> None:
    jobs = _workflow()["jobs"]
    disposition_script = "\n".join(
        step.get("run", "") for step in jobs["selected-verification"]["steps"]
    )
    assert "scripts/verification_disposition.py" in disposition_script
    assert "--execute" in disposition_script
    assert '"authority":"verification"' in disposition_script
    assert '"blocking":true' in disposition_script

    shadow = jobs["repo-consistency"]
    shadow_script = "\n".join(step.get("run", "") for step in shadow["steps"])
    assert str(shadow["if"]) == "github.event_name == 'pull_request'"
    assert shadow["continue-on-error"] is True
    assert "make ci-check" in shadow_script
    assert '"authority":"regression-shadow"' in shadow_script
    assert '"blocking":false' in shadow_script


def test_build_artifact_excludes_dependency_dist_directories() -> None:
    jobs = _workflow()["jobs"]
    script = "\n".join(step.get("run", "") for step in jobs["build-artifact"]["steps"])
    assert "build-selection.json" in script
    assert "Build only selected workspaces" in script or "npm run build --workspace" in script
    assert "npm run build --workspace=\"$workspace\"" in script
    assert "find packages frontend apps" not in script


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


def test_repo_health_reserves_broad_regression_for_schedule_or_dispatch() -> None:
    jobs = _repo_health_workflow()["jobs"]
    regression_condition = "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    for job_name in (
        "detect-changes",
        "python-tests",
        "backend-tests",
        "typescript",
        "e2e-tenant",
        "staging-preflight-dry-run",
    ):
        assert str(jobs[job_name]["if"]) == regression_condition
    assert "github.event_name == 'schedule'" in str(jobs["ml-tests"]["if"])
    assert "github.event_name == 'workflow_dispatch'" in str(jobs["ml-tests"]["if"])
    assert "needs.detect-changes.outputs.ml" not in str(jobs["ml-tests"]["if"])
    assert "github.event_name == 'pull_request'" in str(jobs["pr-size"]["if"])
    assert jobs["pr-size"]["continue-on-error"] in {
        True,
        "${{ github.event_name == 'pull_request' }}",
    }
    assert "github.event_name == 'pull_request'" not in str(jobs["lint-docs"].get("if", ""))
    assert jobs["lint-docs"]["continue-on-error"] in {
        True,
        "${{ github.event_name == 'pull_request' }}",
    }

    validate = jobs["validate"]
    assert "main-integration" not in validate["needs"]
    assert "github.event_name == 'schedule'" in str(validate["if"])
    assert "github.event_name == 'workflow_dispatch'" in str(validate["if"])


def test_repo_health_main_integration_is_bounded_and_fail_closed() -> None:
    jobs = _repo_health_workflow()["jobs"]
    main = jobs["main-integration"]
    assert str(main["if"]) == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    script = "\n".join(step.get("run", "") for step in main["steps"])
    assert "scripts/validate_contracts.py" in script
    assert "make generate-contracts-check" in script
    assert "make validate-impact-graph" in script
    assert "make integration-durable" in script
    assert "Backend Architecture/aether-backend/Dockerfile" in script
    assert '"SELECTED"' in script
    assert '"NOT_APPLICABLE"' in script
    assert "Impact Graph did not select backend_image" in script
    assert "docker build" in script
    assert "docker push" not in script
    assert "deploy" not in script.lower()
