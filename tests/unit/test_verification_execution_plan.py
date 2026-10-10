from __future__ import annotations

from scripts.verification_execution_plan import build_execution_plan


def test_frontend_plan_uses_node_profile_without_backend_image() -> None:
    plan = build_execution_plan(["apps/aether-web/src/pages/profile.tsx"])

    assert plan["status"] == "READY"
    assert plan["build"]["node_required"] is True
    assert plan["build"]["backend_image"] is False
    assert plan["build"]["python_profiles"] == ["ci-control"]
    frontend_jobs = [job for job in plan["jobs"] if "frontend-aether" in job["checks"]]
    assert frontend_jobs and frontend_jobs[0]["dependency_profile"] == "node-frontend"


def test_control_plane_plan_is_typed_and_does_not_fan_out_builds() -> None:
    plan = build_execution_plan([".github/workflows/repo-consistency.yml"])

    assert plan["status"] == "READY"
    assert plan["global_scopes"] == ["verification_control_plane"]
    assert plan["build"]["node_required"] is False
    assert plan["build"]["backend_image"] is False
    assert plan["build"]["workspaces"] == []
    profiles = {job["dependency_profile"] for job in plan["jobs"]}
    # The control-plane change escalates to the typed toolchain and durable
    # integration suites, but it must not fan out to an application build.
    assert {"ci-control", "python-all", "docker-backend"} <= profiles
    assert all(not job.get("suite_ids") or job["dependency_profile"] != "node-frontend" for job in plan["jobs"])


def test_environment_authority_templates_are_classified() -> None:
    plan = build_execution_plan(["config/environments/.env.production.example", "config/environments/.env.staging.example"])

    assert plan["status"] == "READY"
    assert plan["domains"] == ["delivery"]
    # config/** also owns the templates now that they live under config/environments;
    # the delivery domain and the (no-node) build plan are unchanged.
    assert plan["selected_components"] == ["verification-and-documentation", "workspace-root"]
    assert plan["build"]["node_required"] is False


def test_unknown_path_is_blocked_instead_of_emitting_zero_work() -> None:
    plan = build_execution_plan(["new-runtime-surface/worker.py"])

    assert plan["status"] == "BLOCKED"
    assert plan["jobs"] == []
    assert plan["unresolved_paths"] == ["new-runtime-surface/worker.py"]


def _suite_ids(plan: dict) -> set[str]:
    return {sid for job in plan["jobs"] for sid in job.get("suite_ids", [])}


def test_functionality_proof_suite_is_selected_only_by_the_paths_it_imports() -> None:
    # The suite imports packages/{shared,web,react-native,proof-*}, its own
    # test directories, the mocks and fixtures they load, and its vitest config.
    for path in (
        "packages/shared/consent-receipt.ts",
        "packages/sdk/web/src/index.ts",
        "packages/sdk/react-native/src/index.ts",
        "tests/e2e/proof/packages/contracts/index.ts",
        "tests/e2e/proof/packages/fixtures/index.json",
        "tests/sdk/web/web-offline.test.ts",
        "tests/mocks/react-native.ts",
        "tests/fixtures/sdk/canonical-first-value-journey.json",
        "vitest.config.fps.ts",
    ):
        plan = build_execution_plan([path])
        assert plan["status"] == "READY", path
        assert "functionality-proof-ts" in _suite_ids(plan), path


def test_functionality_proof_suite_is_not_a_domain_wide_default() -> None:
    # A path with no specific rule falls back to its domain's `checks`; the proof
    # suite must not be in those defaults or unrelated SDK, mobile and backend
    # changes would pay for a Node install and an 84-file run.
    for path in (
        "packages/sdk/ios/Sources/AetherSDK/Aether.swift",
        "packages/sdk/mobile-core/src/index.ts",
        "packages/ui/brand/src/index.ts",
        "services/backend/config/settings.py",
    ):
        plan = build_execution_plan([path])
        assert plan["status"] == "READY", path
        assert "functionality-proof-ts" not in _suite_ids(plan), path
