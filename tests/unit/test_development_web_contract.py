"""The persistent Development build of the Aether app (development-web.yml).

It deploys only from the Development branch, through the same least-privilege
role as the PR previews, and only to the `development` branch of the
AETHER-development-web Amplify app.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/development-web.yml"
MANIFEST = ROOT / "config/staging_frontend_preview_iam_policy.yaml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_it_runs_only_for_pushes_to_development() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))  # PyYAML reads bare `on:` as True
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["development"]
    assert "pull_request" not in triggers and "pull_request_target" not in triggers
    assert workflow["jobs"]["deploy"]["if"] == "github.ref == 'refs/heads/development'"


def test_workflow_token_and_concurrency_are_minimal() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {"contents": "read", "id-token": "write"}
    assert workflow["concurrency"] == {"group": "development-web", "cancel-in-progress": True}
    assert workflow["env"]["DEVELOPMENT_BRANCH"] == "development"


def test_it_skips_until_the_role_is_configured() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "vars.FRONTEND_PREVIEW_ROLE_ARN" in text
    assert text.count("steps.armed.outputs.armed == 'true'") >= 7


def test_every_amplify_call_is_granted_on_the_development_app_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    used = {
        f"amplify:{''.join(part.capitalize() for part in cmd.split('-'))}"
        for cmd in re.findall(r"aws amplify ([a-z-]+)", text)
    }
    granted = {action for statement in _manifest()["statements"] for action in statement["actions"]}
    assert used and used <= granted, used - granted
    # Never touches the staging or production apps' branches or domains.
    assert not re.search(r"aws amplify (update|delete|start-job|create-domain)", text)
    # The branch it manages is the one the manifest allows.
    resources = [
        resource
        for statement in _manifest()["statements"]
        if "amplify:CreateBranch" in statement["actions"]
        for resource in statement["resource"]
    ]
    assert any(resource.endswith("/branches/development") for resource in resources)


def test_it_resolves_the_development_app_by_its_name_and_reads_staging_settings() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'select(.name == "AETHER-development-web")' in text
    assert 'select(.name == "AETHER-staging-web")' in text
    assert "VITE_AUTH0_(REDIRECT|LOGOUT)_URI" in text
