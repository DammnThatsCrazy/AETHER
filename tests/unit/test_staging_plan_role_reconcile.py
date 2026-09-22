"""Contract tests for the confirmation-gated staging plan-role reconciler."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/reconcile_staging_plan_role.py"
WORKFLOW = ROOT / ".github/workflows/reconcile-staging-plan-role.yml"
TRUST_POLICY = ROOT / "config/staging_plan_reconcile_trust_policy.json"
CALLER_POLICY = ROOT / "config/staging_plan_reconcile_iam_policy.json"


def _module():
    spec = importlib.util.spec_from_file_location("reconcile_staging_plan_role", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _workflow_document() -> dict:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_reviewed_plan_manifest_renders_account_bound_read_only_policy() -> None:
    module = _module()
    manifest = yaml.safe_load(
        (ROOT / "config/staging_plan_iam_policy.yaml").read_text(encoding="utf-8")
    )
    rendered = module.render_policy_document(manifest, account_id="544471417928")

    assert rendered["Version"] == "2012-10-17"
    statements = {statement["Sid"]: statement for statement in rendered["Statement"]}
    rds = statements["ReadStagingRdsResources"]
    assert "rds:DescribeGlobalClusters" in rds["Action"]
    assert rds["Resource"] == ["*"]
    assert "${account_id}" not in repr(rendered)
    assert all(statement["Effect"] == "Allow" for statement in rendered["Statement"])
    assert all(
        not any(action.endswith(":*") or action == "*" for action in statement["Action"])
        for statement in rendered["Statement"]
    )


def test_flat_conditions_are_rendered_as_string_equals() -> None:
    module = _module()
    manifest = {
        "version": 1,
        "profile": "staging",
        "role": "AetherStagingPlan",
        "statements": [
            {
                "sid": "ReadTaggedKey",
                "actions": ["kms:DescribeKey"],
                "resource": "arn:aws:kms:us-east-1:${account_id}:key/*",
                "conditions": {"aws:ResourceTag/Environment": "staging"},
            }
        ],
    }

    rendered = module.render_policy_document(manifest, account_id="123456789012")

    assert rendered["Statement"][0]["Condition"] == {
        "StringEquals": {"aws:ResourceTag/Environment": ["staging"]}
    }


def test_condition_operator_override_and_nested_conditions_are_preserved() -> None:
    module = _module()
    base = {
        "version": 1,
        "profile": "staging",
        "role": "AetherStagingPlan",
        "statements": [
            {
                "sid": "ListAliases",
                "actions": ["kms:ListAliases"],
                "resource": "*",
                "conditions": {"kms:RequestAlias": "alias/aether-staging-*"},
                "condition_operators": {"kms:RequestAlias": "StringLike"},
            }
        ],
    }
    assert module.render_policy_document(base, account_id="123456789012")["Statement"][0][
        "Condition"
    ] == {"StringLike": {"kms:RequestAlias": ["alias/aether-staging-*"]}}

    nested = {
        **base,
        "statements": [
            {
                "sid": "TaggedRead",
                "actions": ["kms:DescribeKey"],
                "resource": "arn:aws:kms:us-east-1:${account_id}:key/*",
                "conditions": {
                    "StringEquals": {"aws:ResourceTag/Environment": "staging"}
                },
            }
        ],
    }
    assert module.render_policy_document(nested, account_id="123456789012")["Statement"][0][
        "Condition"
    ] == {"StringEquals": {"aws:ResourceTag/Environment": ["staging"]}}


def test_renderer_rejects_mutating_plan_actions() -> None:
    module = _module()
    manifest = {
        "version": 1,
        "profile": "staging",
        "role": "AetherStagingPlan",
        "statements": [
            {
                "sid": "UnexpectedMutation",
                "actions": ["rds:ModifyDBCluster"],
                "resource": "*",
            }
        ],
    }
    with pytest.raises(SystemExit):
        module.render_policy_document(manifest, account_id="123456789012")


def test_target_role_and_confirmation_are_exact() -> None:
    module = _module()
    assert module.target_role_parts("arn:aws:iam::123456789012:role/AetherStagingPlan") == (
        "123456789012",
        "AetherStagingPlan",
    )
    with pytest.raises(SystemExit):
        module.target_role_parts("arn:aws:iam::123456789012:role/path/AetherStagingPlan")


def test_reconciliation_workflow_is_dispatch_only_and_non_terraform() -> None:
    document = _workflow_document()
    triggers = document.get("on", document.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["expected_commit_sha"]["required"] is True
    assert inputs["confirmation"]["required"] is True

    job = document["jobs"]["reconcile"]
    assert job["environment"] == "staging-terraform"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "RECONCILE-STAGING-PLAN-IAM" in text
    assert "reconcile_staging_plan_role.py" in text
    assert "AWS_STAGING_PLAN_RECONCILE_ROLE_ARN" in text
    assert "AetherStagingPlanReconcile" in text
    assert "--skip-verification" in text
    assert "Switch to the read-only plan role" in text
    assert "AWS_INFRA_ROLE_ARN" not in text
    assert 'GITHUB_REF_NAME" = main' in text
    assert "terraform apply" not in text
    assert "get-secret-value" not in text
    assert "batch-get-secret-value" not in text


def test_reconciliation_caller_contract_is_exact_and_narrow() -> None:
    trust = json.loads(TRUST_POLICY.read_text(encoding="utf-8"))
    caller = json.loads(CALLER_POLICY.read_text(encoding="utf-8"))

    statement = trust["Statement"][0]
    assert statement["Principal"]["Federated"].endswith(
        "/token.actions.githubusercontent.com"
    )
    assert statement["Condition"]["StringLike"][
        "token.actions.githubusercontent.com:sub"
    ] == "repo:DammnThatsCrazy/AETHER:environment:staging-terraform"

    statements = {item["Sid"]: item for item in caller["Statement"]}
    assert set(statements) == {
        "ReadTargetPlanRoleMetadata",
        "ReconcileTargetPlanContract",
    }
    assert statements["ReconcileTargetPlanContract"]["Action"] == "iam:PutRolePolicy"
    assert statements["ReconcileTargetPlanContract"]["Resource"].endswith(
        ":role/AetherStagingPlan"
    )


def test_lifecycle_entrypoints_verify_live_plan_role_before_dispatch() -> None:
    pilot = (ROOT / ".github/workflows/pilot-staging.yml").read_text(encoding="utf-8")
    lifecycle = (ROOT / ".github/workflows/staging-lifecycle.yml").read_text(encoding="utf-8")
    for workflow in (pilot, lifecycle):
        assert "verify_effective_staging_apply_policy.py" in workflow
        assert "config/staging_plan_iam_policy.yaml" in workflow
        assert "config/terraform_plan_state_access_policy.yaml" in workflow
        assert "AetherStagingPlanContract" in workflow


def test_authority_registry_owns_the_reconciliation_workflow() -> None:
    registry = yaml.safe_load(
        (ROOT / "config/delivery_workflow_authority.yaml").read_text(encoding="utf-8")
    )
    infrastructure = next(item for item in registry["authorities"] if item["id"] == "infrastructure")
    assert ".github/workflows/reconcile-staging-plan-role.yml" in infrastructure["workflows"]
    assert "scripts/release/reconcile_staging_plan_role.py" in infrastructure["required_commands"]
