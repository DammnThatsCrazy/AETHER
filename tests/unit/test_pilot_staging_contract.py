"""Focused offline checks for the additive lean AWS staging lane."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT = ROOT / "scripts" / "release" / "check_pilot_staging_contract.py"


@pytest.fixture
def contract_module():
    spec = importlib.util.spec_from_file_location("pilot_staging_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow(name: str) -> dict:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")) or {}
    return document


def _on(document: dict):
    return document.get("on", document.get(True))


def test_pilot_entrypoint_is_dispatch_only_and_uses_the_shared_lane_token():
    document = _workflow("pilot-staging.yml")
    triggers = _on(document)
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["deployment_lane"]["options"] == ["full", "pilot"]
    assert inputs["deployment_lane"]["default"] == "pilot"
    assert inputs["action"]["default"] == "full-rehearsal"
    assert inputs["staging_secrets_kms_key_arn"]["default"] == "alias/aether-staging-secrets"

    text = (WORKFLOWS / "pilot-staging.yml").read_text(encoding="utf-8")
    for authority in (
        ".github/workflows/terraform-promote.yml",
        ".github/workflows/deploy.yml",
        ".github/workflows/staging-lifecycle.yml",
        ".github/workflows/staging-smoke.yml",
    ):
        assert authority in text
    assert "PILOT_DEFERRED_GATES" in text
    assert "check_staging_lane_contract.py" in text
    assert "check_pilot_staging_contract.py" in text
    assert "Require merged-main authority" in text
    assert 'GITHUB_REF_NAME" = main' in text
    assert "staging-state-reconcile.yml" in text
    assert "reconcile_pilot_price_secret_state" in text
    assert "IMPORT-STAGING" in text
    assert "gh run download" in text
    assert "delivery_mode=build-only" in text
    for forbidden in (
        "check_kyber_staging_contract.py",
        "probe_kyber_staging_identity.py",
        "KYBER_GOOGLE_CLIENT_ID",
        "KYBER_GOOGLE_CLIENT_SECRET",
    ):
        assert forbidden not in text


def test_pilot_credential_preflight_matches_each_action_to_its_real_inputs():
    pilot = _workflow("pilot-staging.yml")
    credential_step = next(
        step
        for step in pilot["jobs"]["credential-preflight"]["steps"]
        if step.get("name") == "Validate all staging credential metadata"
    )
    script = credential_step["run"]
    env = credential_step["env"]
    assert "plan|apply|validate) credential_purpose=infrastructure" in script
    assert "redeploy) credential_purpose=delivery" in script
    assert "smoke) credential_purpose=smoke" in script
    assert "full-rehearsal) credential_purpose=rehearsal" in script
    assert "STAGING_ADMIN_API_KEY" not in env
    assert 'inputs.action) && secrets.SMOKE_API_KEY ||' in env["SMOKE_API_KEY"]
    assert '["redeploy","smoke"]' in env["SMOKE_API_KEY"]

    dispatch = pilot["jobs"]["dispatch-authority"]
    assert dispatch["env"]["GH_TOKEN"] == (
        "${{ secrets.WORKFLOW_DISPATCH_TOKEN || secrets.TF_AMPLIFY_GITHUB_ACCESS_TOKEN }}"
    )
    assert "github.token" not in dispatch["env"]["GH_TOKEN"]
    assert "configure WORKFLOW_DISPATCH_TOKEN or TF_AMPLIFY_GITHUB_ACCESS_TOKEN" in dispatch["steps"][0]["run"]

    terraform = _workflow("terraform-promote.yml")
    plan_credential_check = next(
        step for step in terraform["jobs"]["plan"]["steps"]
        if step.get("name") == "Validate staging credential shape before planning"
    )
    assert "--purpose terraform-plan" in plan_credential_check["run"]
    assert plan_credential_check["env"]["STAGING_ADMIN_API_KEY"] == (
        "${{ secrets.STAGING_ADMIN_API_KEY }}"
    )

    infrastructure = _workflow("infrastructure.yml")
    remote_plan_credential_check = next(
        step for step in infrastructure["jobs"]["remote-plan"]["steps"]
        if step.get("name") == "Validate staging credential shape before remote planning"
    )
    assert "--purpose terraform-plan" in remote_plan_credential_check["run"]
    assert remote_plan_credential_check["env"]["STAGING_ADMIN_API_KEY"] == (
        "${{ secrets.STAGING_ADMIN_API_KEY }}"
    )
    assert "SMOKE_API_KEY" not in remote_plan_credential_check["env"]
    assert "Prove GitHub repository-secret access before pilot apply" not in (
        WORKFLOWS / "pilot-staging.yml"
    ).read_text(encoding="utf-8")

    deploy_text = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert "--purpose delivery" in deploy_text
    assert "STAGING_ADMIN_API_KEY: ${{ secrets.STAGING_ADMIN_API_KEY }}" not in deploy_text


@pytest.mark.parametrize(
    "name",
    ("terraform-promote.yml", "deploy.yml", "staging-lifecycle.yml", "staging-smoke.yml"),
)
def test_canonical_staging_authorities_accept_full_and_pilot(name):
    document = _workflow(name)
    inputs = (_on(document) or {}).get("workflow_dispatch", {}).get("inputs", {})
    assert inputs["deployment_lane"]["options"] == ["full", "pilot"]
    expected_default = "pilot" if name == "staging-lifecycle.yml" else "full"
    assert inputs["deployment_lane"]["default"] == expected_default


def test_main_push_uses_pilot_lane_and_profile_choices_do_not_fork():
    deploy = (WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert deploy.count("github.event_name == 'push' && 'pilot'") == 8
    assert "github.event_name == 'push' && 'full'" not in deploy
    assert "KYBER_GOOGLE_CLIENT_ID: ${{ (github.event_name != 'push'" in deploy
    assert "KYBER_GOOGLE_CLIENT_SECRET: ${{ (github.event_name != 'push'" in deploy
    deploy_inputs = _on(_workflow("deploy.yml"))["workflow_dispatch"]["inputs"]
    assert deploy_inputs["delivery_mode"]["options"] == ["deploy", "build-only"]
    assert deploy_inputs["delivery_mode"]["default"] == "deploy"
    assert "inputs.delivery_mode == 'deploy'" in deploy

    terraform = _workflow("terraform-promote.yml")
    profile_options = (
        (_on(terraform) or {})["workflow_dispatch"]["inputs"]["profile"]["options"]
    )
    assert "staging" in profile_options
    assert "pilot" not in profile_options
    assert "staging-pilot" not in profile_options


def test_pilot_sleep_apply_uses_the_canonical_regenerated_sleep_plan():
    text = (WORKFLOWS / "pilot-staging.yml").read_text(encoding="utf-8")
    branch = text.split("            apply-sleep)", 1)[1].split("            *)", 1)[0]
    assert "backend_image_digest is required for pilot apply-sleep" in branch
    assert '-f backend_image_digest="$BACKEND_IMAGE_DIGEST"' in branch
    assert '-f intended_release_sha="$INTENDED_RELEASE_SHA"' in branch


def test_pilot_planning_paths_reconcile_price_secret_state_before_planning():
    pilot = (WORKFLOWS / "pilot-staging.yml").read_text(encoding="utf-8")
    lifecycle = (WORKFLOWS / "staging-lifecycle.yml").read_text(encoding="utf-8")
    promote = (WORKFLOWS / "terraform-promote.yml").read_text(encoding="utf-8")
    for workflow in (pilot, lifecycle):
        assert "staging-state-reconcile.yml" in workflow
        assert "staging_secret_names=" in workflow
        assert "staging_secrets_kms_key_arn" in workflow
        assert "IMPORT-STAGING" in workflow
        assert "verify_effective_staging_apply_policy.py" in workflow
        assert "config/staging_plan_iam_policy.yaml" in workflow
        assert "config/terraform_plan_state_access_policy.yaml" in workflow
        assert "AetherStagingPlanContract" in workflow
        assert "Require merged-main authority" in workflow
    assert "--require-aws-staging-secrets" in promote
    assert "required_staging_secret_names" in promote
    assert "module.secrets.aws_kms_key.secrets" in promote
    assert "module.secrets.aws_kms_alias.secrets" in promote


def test_current_tree_has_lane_and_static_stripe_wiring(contract_module):
    errors = contract_module.find_errors()
    joined = "\n".join(errors)
    # The main integration owns the lane token, secret resources, and ECS
    # runtime names. Static completeness is not live Stripe readiness: the
    # workflow still performs the read-only AWS price-secret preflight.
    assert joined == ""


def test_lane_contract_rejects_full_for_the_pilot_entrypoint(contract_module):
    errors = contract_module.find_errors(lane="full")
    assert "only accepts deployment_lane=pilot" in "\n".join(errors)


def test_pilot_contract_does_not_accept_secret_values_as_arguments(contract_module):
    # The production parser is intentionally limited to lane/workflow/evidence
    # selectors. A price ID supplied on the command line is not a valid input.
    with pytest.raises(SystemExit):
        contract_module.main(["--stripe-price-alpha", "price_real_but_not_an_input"])
