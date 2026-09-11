from __future__ import annotations

import scripts.verification_disposition as disposition_module
from scripts.verification_disposition import CommandResult, build_disposition


def _ids(result: dict) -> set[str]:
    return {check["check_id"] for check in result["checks"]}


def test_frontend_change_has_one_planned_disposition_and_scoped_builds() -> None:
    result = build_disposition(["frontend/aether/src/pages/profile.tsx"])

    assert result["authority"] == "verification"
    assert result["blocking"] is True
    assert result["status"] == "PLANNED"
    assert {"toolchain", "repository_metadata", "test_inventory", "delivery_metadata"} <= _ids(result)
    assert "frontend-aether" in _ids(result)
    assert "backend" not in _ids(result)
    assert result["build_selection"]["packages"] == ["shared"]
    assert result["build_selection"]["applications"] == ["aether"]
    assert result["build_selection"]["workspaces"] == [
        "packages/brand",
        "packages/shared",
        "frontend/shared",
        "packages/web",
        "frontend/aether",
    ]
    assert result["build_selection"]["backend_image"] is False
    assert result["build_selection"]["sdk"] == {
        "ios": False,
        "android": False,
        "js": False,
    }


def test_package_workspace_change_selects_its_build_and_dependencies() -> None:
    result = build_disposition(["packages/server/src/index.ts"])

    assert result["build_selection"]["workspaces"] == [
        "packages/shared",
        "packages/server",
    ]


def test_global_node_dependency_change_selects_every_buildable_workspace() -> None:
    result = build_disposition(["package-lock.json"])

    buildable = {
        "packages/shared",
        "packages/web",
        "packages/server",
        "packages/react-native",
        "packages/mobile-core",
        "frontend/aether",
        "frontend/kyber",
        "frontend/docs",
        "frontend/demo",
        "frontend/olympus-marketing",
        "frontend/aether-marketing",
    }
    assert buildable <= set(result["build_selection"]["workspaces"])


def test_registry_change_skips_release_only_quarantined_suite() -> None:
    result = build_disposition(["config/test_suites.yaml"])

    assert "datalake-backend" not in result["suites"]["planned_ids"]
    assert {
        row["suite"] for row in result["suites"]["skipped"]
    } >= {"datalake-backend"}


def test_advisory_suite_is_non_blocking_in_disposition() -> None:
    result = build_disposition(["frontend/docs/src/main.tsx"])

    advisory = [check for check in result["checks"] if check["check_id"] == "frontend-docs"]
    assert advisory and advisory[0]["blocking"] is False
    assert result["status"] == "PLANNED"


def test_advisory_failure_does_not_fail_blocking_disposition(monkeypatch) -> None:
    def advisory_failure(checks, *, execute):
        return [
            CommandResult(
                check_id="frontend-docs",
                lane="pr",
                command=("advisory-doc-check",),
                status="FAILED",
                returncode=1,
                duration_seconds=0.1,
                output="informational failure",
                blocking=False,
                release_class="advisory",
            )
        ]

    monkeypatch.setattr(disposition_module, "_run_parallel", advisory_failure)
    result = build_disposition(["frontend/docs/src/main.tsx"], execute=True)

    assert result["status"] == "PASS"
    assert result["advisory_failures"][0]["check_id"] == "frontend-docs"


def test_backend_change_selects_backend_build_without_unrelated_apps() -> None:
    result = build_disposition(["Backend Architecture/aether-backend/services/profile/routes.py"])

    assert result["impact"]["selected_lane"] == "pr"
    assert "backend" in _ids(result)
    assert result["build_selection"]["backend_image"] is True
    assert result["build_selection"]["applications"] == []
    assert result["build_selection"]["sdk"] == {
        "ios": False,
        "android": False,
        "js": False,
    }


def test_unresolved_executable_change_blocks_pr_only_disposition() -> None:
    result = build_disposition(["new-runtime-surface/worker.py"])

    assert result["status"] == "BLOCKED"
    assert result["unresolved_paths"] == ["new-runtime-surface/worker.py"]
    assert result["impact"]["risk"] == "R3"


def test_ci_architecture_change_runs_universal_controls_and_escalates() -> None:
    result = build_disposition([".github/workflows/repo-consistency.yml"])

    assert result["status"] == "PLANNED"
    assert result["impact"]["risk"] == "R3"
    assert result["impact"]["selected_lane"] == "integration"
    assert "workflow_authority" in _ids(result)


def test_risk_comes_from_selected_lane_policy() -> None:
    result = build_disposition([".github/workflows/repo-consistency.yml"])
    assert result["impact"]["selected_lane"] == "integration"
    assert result["impact"]["risk"] == "R3"
