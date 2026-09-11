from __future__ import annotations

from scripts.verification_disposition import build_disposition


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
    assert result["build_selection"] == {
        "packages": ["shared"],
        "applications": ["aether"],
        "backend_image": False,
        "sdk": {"ios": False, "android": False, "js": False},
    }


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
    assert result["impact"]["risk"] == "R5"
    assert result["impact"]["selected_lane"] == "integration"
    assert "workflow_authority" in _ids(result)
