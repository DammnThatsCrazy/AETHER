"""Supplementary PR workflows stay bounded; the authority itself is covered in test_ci_workflow_authority."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
REPO_HEALTH_WORKFLOW = ROOT / ".github" / "workflows" / "repo-health.yml"
PRODUCTION_EQUIVALENT_WORKFLOW = ROOT / ".github" / "workflows" / "production-equivalent-ci.yml"


def _repo_health_workflow() -> dict:
    return yaml.safe_load(REPO_HEALTH_WORKFLOW.read_text(encoding="utf-8"))


def _production_equivalent_workflow() -> dict:
    return yaml.safe_load(PRODUCTION_EQUIVALENT_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    value = document.get("on") if "on" in document else document.get(True)
    return value if isinstance(value, dict) else {}


def test_supplementary_pr_workflows_start_only_at_finalization() -> None:
    assert _triggers(_production_equivalent_workflow())["pull_request"]["types"] == ["ready_for_review"]


def test_repo_health_has_no_pull_request_trigger() -> None:
    # Pull requests are verified by ci.yml; repo-health keeps trusted-branch, nightly and dispatch signals.
    assert "pull_request" not in _triggers(_repo_health_workflow())
    assert "pr-size" not in _repo_health_workflow()["jobs"]


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
    assert "github.event_name == 'pull_request'" not in str(jobs["lint-docs"].get("if", ""))

    validate = jobs["validate"]
    assert "main-integration" not in validate["needs"]
    assert "github.event_name == 'schedule'" in str(validate["if"])
    assert "github.event_name == 'workflow_dispatch'" in str(validate["if"])


def test_repo_health_main_integration_is_bounded_and_fail_closed() -> None:
    jobs = _repo_health_workflow()["jobs"]
    main = jobs["main-integration"]
    assert str(main["if"]) == (
        "github.event_name == 'push' && "
        "(github.ref == 'refs/heads/main' || github.ref == 'refs/heads/staging')"
    )
    script = "\n".join(step.get("run", "") for step in main["steps"])
    assert "scripts/validate_contracts.py" in script
    assert "make generate-contracts-check" in script
    assert "make validate-impact-graph" in script
    assert "make integration-durable" in script
    assert "services/api/Dockerfile" in script
    assert '"SELECTED"' in script
    assert '"NOT_APPLICABLE"' in script
    assert "Impact Graph did not select backend_image" in script
    assert "docker build" in script
    assert "docker push" not in script
    assert "deploy" not in script.lower()


def test_repo_health_builds_cross_workspace_dependencies_before_lint() -> None:
    jobs = _repo_health_workflow()["jobs"]
    typescript = jobs["typescript"]
    steps = typescript["steps"]
    names = [step.get("name", "") for step in steps]
    dependency_step = names.index("Build proof and mobile dependency packages before workspace lint")
    lint_step = names.index("TypeScript lint/static checks")
    assert dependency_step < lint_step
    dependency_run = steps[dependency_step]["run"]
    for workspace in (
        "tests/e2e/proof/packages/contracts",
        "tests/e2e/proof/packages/fixtures",
        "tests/e2e/proof/packages/runner",
        "tests/e2e/proof/packages/reporting",
        "packages/sdk/react-native",
        "packages/sdk/mobile-core",
    ):
        assert workspace in dependency_run


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
