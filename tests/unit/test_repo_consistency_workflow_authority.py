"""The PR workflow exposes distinct, fail-closed delivery authorities."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "repo-consistency.yml"
REPO_HEALTH_WORKFLOW = ROOT / ".github" / "workflows" / "repo-health.yml"
PRODUCTION_EQUIVALENT_WORKFLOW = ROOT / ".github" / "workflows" / "production-equivalent-ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _repo_health_workflow() -> dict:
    return yaml.safe_load(REPO_HEALTH_WORKFLOW.read_text(encoding="utf-8"))


def _production_equivalent_workflow() -> dict:
    return yaml.safe_load(PRODUCTION_EQUIVALENT_WORKFLOW.read_text(encoding="utf-8"))


def test_pr_workflow_has_explicit_delivery_stages() -> None:
    jobs = _workflow()["jobs"]
    assert {
        "classify-change",
        "build-artifact",
        "selected-verification",
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
    assert jobs["publish-evidence"]["name"] == "verification / disposition"
    assert jobs["selected-verification"]["name"] != jobs["publish-evidence"]["name"]
    disposition_script = "\n".join(
        step.get("run", "") for step in jobs["selected-verification"]["steps"]
    )
    assert "scripts/verification_disposition.py" in disposition_script
    assert "--execute" in disposition_script
    assert '"authority":"verification"' in disposition_script
    assert '"blocking":true' in disposition_script

    assert "repo-consistency" not in jobs


def test_build_artifact_excludes_dependency_dist_directories() -> None:
    jobs = _workflow()["jobs"]
    script = "\n".join(step.get("run", "") for step in jobs["build-artifact"]["steps"])
    assert "build-selection.json" in script
    assert "Build only selected workspaces" in script or "npm run build --workspace" in script
    assert "npm run build --workspace=\"$workspace\"" in script
    assert "find packages frontend apps" not in script
    assert 'selection.get("workspaces")' in script
    assert "dependency order" in str(jobs["build-artifact"]["steps"])
    assert jobs["build-artifact"]["env"]["VITE_AETHER_ENV"] == "production"


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


def test_backend_image_is_bound_to_candidate_and_loaded_by_consumer() -> None:
    jobs = _workflow()["jobs"]
    build = "\n".join(step.get("run", "") for step in jobs["build-artifact"]["steps"])
    selected = "\n".join(step.get("run", "") for step in jobs["selected-verification"]["steps"])
    assert "docker save" in build
    assert "--component backend-image=release-evidence/backend-image.tar.gz" in build
    assert "docker load" in selected
    assert "--component backend-image=release-evidence/backend-image.tar.gz" in selected


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


def test_full_ci_is_not_a_blocking_pr_dependency() -> None:
    jobs = _workflow()["jobs"]
    assert "repo-consistency" not in jobs
    assert "make ci-check" not in "\n".join(
        step.get("run", "") for step in jobs["publish-evidence"]["steps"]
    )


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


def test_production_equivalent_ci_filters_real_stack_with_impact_authority() -> None:
    jobs = _production_equivalent_workflow()["jobs"]
    classifier = jobs["classify-impact"]
    assert classifier["outputs"]["run_real_stack"] == "${{ steps.selection.outputs.run_real_stack }}"
    classifier_script = "\n".join(step.get("run", "") for step in classifier["steps"])
    assert "scripts/impact_graph.py" in classifier_script
    assert '"no-production-equivalent-impact"' in classifier_script
    assert "production-equivalent-selection" in "\n".join(
        str(step) for step in classifier["steps"]
    )

    real_stack = jobs["real-stack-ingestion-smoke"]
    assert real_stack["needs"] == "classify-impact"
    assert str(real_stack["if"]) == "needs.classify-impact.outputs.run_real_stack == 'true'"
