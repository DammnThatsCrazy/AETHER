"""Per-PR frontend previews: fork safety, teardown, and a least-privilege role.

The repository is public, so the preview workflow must never give a fork's
code AWS credentials, must remove each preview when its pull request closes,
and must only use Amplify operations its role manifest grants, on the preview
app's pr-* branches.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/frontend-preview.yml"
MANIFEST = ROOT / "config/staging_frontend_preview_iam_policy.yaml"
MAIN_TF = ROOT / "deploy/aws/terraform/main.tf"
STAGING_TFVARS = ROOT / "deploy/aws/terraform/profiles/staging.tfvars"

def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML reads the bare `on:` key as True.
    return workflow.get("on", workflow.get(True))


def test_pull_requests_trigger_only_at_finalization():
    triggers = _triggers(_workflow())
    assert "pull_request_target" not in triggers
    assert triggers["pull_request"] == {"types": ["ready_for_review"]}
    assert set(triggers) == {"pull_request", "workflow_dispatch", "push", "schedule"}
    assert triggers["push"] == {"branches": ["main"]}


def test_deploy_refuses_fork_and_closed_pull_requests():
    deploy = _workflow()["jobs"]["deploy"]
    resolve = deploy["steps"][0]["run"]
    assert '"$head_repo" != "$GITHUB_REPOSITORY"' in resolve
    assert 'test "$state" = open' in resolve
    assert "^[0-9]{1,7}$" in resolve
    assert deploy["if"] == "github.event_name == 'pull_request' || github.event_name == 'workflow_dispatch'"


def test_merged_or_closed_pull_requests_lose_their_preview():
    cleanup = _workflow()["jobs"]["cleanup"]
    assert cleanup["if"] == "github.event_name == 'push' || github.event_name == 'schedule'"
    script = "\n".join(step.get("run", "") for step in cleanup["steps"])
    assert "aws amplify list-branches" in script
    assert 'if [ "$state" = closed ]' in script
    assert 'aws amplify delete-branch --app-id "$PREVIEW_APP_ID" --branch-name "$branch"' in script


def test_workflow_token_is_least_privilege():
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {
        "contents": "read", "id-token": "write", "pull-requests": "write",
    }
    assert workflow["jobs"]["cleanup"]["permissions"] == {
        "contents": "read", "id-token": "write", "pull-requests": "read",
    }


def test_every_amplify_call_is_granted_on_the_preview_app_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    used = {f"amplify:{''.join(p.capitalize() for p in cmd.split('-'))}"
            for cmd in re.findall(r"aws amplify ([a-z-]+)", text)}
    statements = _manifest()["statements"]
    granted = {action for s in statements for action in s["actions"]}
    assert used and used <= granted, used - granted
    assert granted == used, f"manifest grants unused actions: {granted - used}"

    for statement in statements:
        resources = statement["resource"]
        resources = resources if isinstance(resources, list) else [resources]
        if statement["actions"] == ["amplify:ListApps"]:
            assert resources == ["*"] and statement["scope"] == "global-read-required-by-api"
            continue
        for resource in resources:
            assert "*" not in resource.split("apps/")[1].split("/")[0], resource
            if statement["actions"] not in (["amplify:GetApp"], ["amplify:ListBranches"]):
                assert resource.startswith(
                    "arn:aws:amplify:us-east-1:${account_id}:apps/${frontend_preview_app_id}/branches/pr-*"
                ), resource


def test_role_trusts_only_this_repositorys_pull_requests_and_main():
    trust = _manifest()["trust"]
    assert trust == {
        "provider": "token.actions.githubusercontent.com",
        "audience": "sts.amazonaws.com",
        "subjects": [
            "repo:DammnThatsCrazy/AETHER:pull_request",
            "repo:DammnThatsCrazy/AETHER:ref:refs/heads/main",
        ],
    }


def test_previews_are_staging_only_in_terraform():
    text = MAIN_TF.read_text(encoding="utf-8")
    assert 'var.enable_frontend_previews && local.enable_static_frontends && var.environment == "staging"' in text
    preview = text[text.index('resource "aws_amplify_app" "frontend_preview"'):]
    preview = preview[:preview.index("\n}\n")]
    assert "repository" not in preview, "the preview app must not be connected to the repository"
    assert 'status = "404-200"' in preview
    # Staging declares the toggle explicitly (currently off pending the
    # account's Amplify app limit; see profiles/staging.tfvars).
    assert re.search(r"^enable_frontend_previews\s*=\s*(true|false)$", STAGING_TFVARS.read_text(), re.M)
