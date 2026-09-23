from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from scripts.release.check_staging_lifecycle_policy import EXPECTED, main, render_policy_document
from scripts.release.verify_effective_staging_lifecycle_policy import (
    compare_documents,
    inline_policy_name_errors,
)
import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/staging_lifecycle_iam_policy.yaml"


def test_lifecycle_manifest_covers_every_workflow_action() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    actions = {action for statement in doc["statements"] for action in statement["actions"]}
    assert EXPECTED <= actions


def test_lifecycle_manifest_is_static_checker_clean() -> None:
    assert main(["--manifest", str(MANIFEST)]) == 0


def test_lifecycle_workflows_run_contract_check() -> None:
    for name in ("staging-lifecycle.yml", "staging-ttl-guard.yml"):
        text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "check_staging_lifecycle_policy.py" in text
        assert "verify_effective_staging_lifecycle_policy.py" in text


def test_lifecycle_manifest_uses_task_specific_scopes() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    assert by_sid["RunStagingMigrationTasks"]["resource"] == [
        "arn:aws:ecs:us-east-1:${account_id}:task-definition/AETHER-staging-*",
        "arn:aws:ecs:us-east-1:${account_id}:cluster/AETHER-staging",
    ]
    assert by_sid["RunStagingMigrationTasks"]["conditions"] == {
        "ArnEquals": {
            "ecs:cluster": "arn:aws:ecs:us-east-1:${account_id}:cluster/AETHER-staging",
        }
    }
    assert by_sid["ReadStagingLogEvents"]["resource"] == (
        "arn:aws:logs:us-east-1:${account_id}:log-group:/ecs/AETHER-staging/*:log-stream:*"
    )


def test_lifecycle_manifest_uses_aws_global_api_scopes() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    assert by_sid["ListStagingServices"]["resource"] == "*"
    assert by_sid["InspectStagingTaskDefinitions"]["resource"] == "*"
    assert by_sid["InspectStagingLogs"]["resource"] == "*"
    assert by_sid["ReadStagingLogEvents"]["resource"] != "*"
    assert by_sid["InspectStagingAutoscalingTargets"]["resource"] == "*"
    target_arn = "arn:aws:application-autoscaling:us-east-1:${account_id}:scalable-target/*"
    assert by_sid["ReadStagingAutoscalingTargetTags"]["resource"] == target_arn
    assert by_sid["PreventAutoscalingRevival"]["resource"] == target_arn
    assert by_sid["PreventAutoscalingRevival"]["conditions"] == {
        "StringEquals": {
            "application-autoscaling:service-namespace": ["ecs"],
            "application-autoscaling:scalable-dimension": ["ecs:service:DesiredCount"],
            "aws:ResourceTag/Environment": ["staging"],
            "aws:ResourceTag/Project": ["AETHER"],
        }
    }


def test_first_admin_bootstrap_secret_exception_is_exact_and_conditioned() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    secret_pattern = (
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:"
        "aether/first-admin-bootstrap-token-*"
    )
    actual_secret_arn = (
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:"
        "aether/first-admin-bootstrap-token-FZ5SRb"
    )
    secret_statement = by_sid["ReadFirstAdminBootstrapToken"]
    assert secret_statement["actions"] == ["secretsmanager:GetSecretValue"]
    assert secret_statement["resource"] == secret_pattern
    assert fnmatchcase(actual_secret_arn, secret_statement["resource"])
    for other_secret_arn in (
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/stripe-secret-key-AbCdEf",
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/jwt-secret-AbCdEf",
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/kyber-google-client-secret-AbCdEf",
        "arn:aws:secretsmanager:us-west-2:544471417928:secret:aether/first-admin-bootstrap-token-FZ5SRb",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:aether/first-admin-bootstrap-token-FZ5SRb",
    ):
        assert not fnmatchcase(other_secret_arn, secret_statement["resource"])

    decrypt_statement = by_sid["DecryptFirstAdminBootstrapToken"]
    assert decrypt_statement["actions"] == ["kms:Decrypt"]
    assert decrypt_statement["resource"] == (
        "arn:aws:kms:us-east-1:544471417928:key/"
        "91753780-d694-4e5a-9e80-7123af974554"
    )
    assert decrypt_statement["conditions"] == {
        "StringEquals": {"kms:ViaService": "secretsmanager.us-east-1.amazonaws.com"},
        "StringLike": {"kms:EncryptionContext:SecretARN": secret_pattern},
    }
    assert fnmatchcase(
        actual_secret_arn,
        decrypt_statement["conditions"]["StringLike"][
            "kms:EncryptionContext:SecretARN"
        ],
    )
    assert not fnmatchcase(
        "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/stripe-secret-key-AbCdEf",
        decrypt_statement["conditions"]["StringLike"][
            "kms:EncryptionContext:SecretARN"
        ],
    )
    assert decrypt_statement["conditions"]["StringEquals"]["kms:ViaService"] != (
        "kms.us-east-1.amazonaws.com"
    )
    assert {"secretsmanager:*", "kms:*"} <= set(doc["forbidden_actions"])
    assert set(doc["allowed_action_exceptions"]) == {
        "ReadFirstAdminBootstrapToken",
        "DecryptFirstAdminBootstrapToken",
    }
    rendered = render_policy_document(doc, "544471417928")
    rendered_by_sid = {statement["Sid"]: statement for statement in rendered["Statement"]}
    assert rendered_by_sid["ReadFirstAdminBootstrapToken"]["Resource"] == secret_pattern
    assert rendered_by_sid["DecryptFirstAdminBootstrapToken"]["Resource"] == (
        "arn:aws:kms:us-east-1:544471417928:key/"
        "91753780-d694-4e5a-9e80-7123af974554"
    )
    assert rendered_by_sid["DecryptFirstAdminBootstrapToken"]["Condition"] == (
        decrypt_statement["conditions"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "broaden-secret-resource",
        "broaden-kms-resource",
        "remove-via-service",
        "broaden-secret-arn-context",
        "add-unconstrained-kms-decrypt",
        "remove-secret-service-forbidden",
        "remove-kms-service-forbidden",
    ],
)
def test_static_checker_rejects_broad_bootstrap_secret_or_decrypt_access(
    tmp_path: Path,
    mutation: str,
) -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    if mutation == "broaden-secret-resource":
        by_sid["ReadFirstAdminBootstrapToken"]["resource"] = (
            "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/*"
        )
    elif mutation == "broaden-kms-resource":
        by_sid["DecryptFirstAdminBootstrapToken"]["resource"] = (
            "arn:aws:kms:us-east-1:544471417928:key/*"
        )
    elif mutation == "remove-via-service":
        by_sid["DecryptFirstAdminBootstrapToken"]["conditions"].pop("StringEquals")
    elif mutation == "broaden-secret-arn-context":
        by_sid["DecryptFirstAdminBootstrapToken"]["conditions"]["StringLike"][
            "kms:EncryptionContext:SecretARN"
        ] = "arn:aws:secretsmanager:us-east-1:544471417928:secret:aether/*"
    elif mutation == "add-unconstrained-kms-decrypt":
        doc["statements"].append(
            {
                "sid": "UnconstrainedDecrypt",
                "actions": ["kms:Decrypt"],
                "resource": "*",
                "scope": "invalid-test-grant",
            }
        )
    elif mutation == "remove-secret-service-forbidden":
        doc["forbidden_actions"].remove("secretsmanager:*")
    else:
        doc["forbidden_actions"].remove("kms:*")
    manifest = tmp_path / "invalid-lifecycle-policy.yaml"
    manifest.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["--manifest", str(manifest)])


def test_lifecycle_manifest_conditions_are_iam_operator_maps() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    assert by_sid["PassOnlyStagingTaskRoles"]["conditions"] == {
        "StringEquals": {"iam:PassedToService": ["ecs-tasks.amazonaws.com"]}
    }


def test_register_scalable_target_never_uses_unsupported_resource_id_condition() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    statement = next(item for item in doc["statements"] if item["sid"] == "PreventAutoscalingRevival")
    condition_keys = {
        key
        for values in statement["conditions"].values()
        for key in values
    }
    assert "application-autoscaling:ResourceId" not in condition_keys
    assert {
        "application-autoscaling:service-namespace",
        "application-autoscaling:scalable-dimension",
        "aws:ResourceTag/Environment",
        "aws:ResourceTag/Project",
    } <= condition_keys




@pytest.mark.parametrize(
    ("condition_key", "replacement"),
    [
        ("aws:ResourceTag/Project", ["OTHER"]),
        ("application-autoscaling:ResourceId", ["service/AETHER-staging/*"]),
    ],
)
def test_static_checker_rejects_invalid_register_scalable_target_contract(
    tmp_path: Path,
    condition_key: str,
    replacement: list[str],
) -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    statement = next(item for item in doc["statements"] if item["sid"] == "PreventAutoscalingRevival")
    if condition_key in statement["conditions"]["StringEquals"]:
        statement["conditions"]["StringEquals"][condition_key] = replacement
    else:
        statement["conditions"]["StringLike"] = {condition_key: replacement}
    manifest = tmp_path / "invalid-lifecycle-policy.yaml"
    manifest.write_text(yaml.safe_dump(doc), encoding="utf-8")

    with pytest.raises(SystemExit, match="invalid PreventAutoscalingRevival contract"):
        main(["--manifest", str(manifest)])


def test_lifecycle_manifest_renders_to_an_aws_policy_document() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    rendered = render_policy_document(doc, "544471417928")
    by_sid = {statement["Sid"]: statement for statement in rendered["Statement"]}
    assert by_sid["InspectStagingTaskDefinitions"]["Resource"] == "*"
    assert by_sid["InspectStagingLogs"]["Resource"] == "*"
    assert by_sid["ReadStagingLogEvents"]["Resource"] == (
        "arn:aws:logs:us-east-1:544471417928:log-group:/ecs/AETHER-staging/*:log-stream:*"
    )
    assert by_sid["PassOnlyStagingTaskRoles"]["Condition"] == {
        "StringEquals": {"iam:PassedToService": ["ecs-tasks.amazonaws.com"]}
    }


def test_effective_lifecycle_policy_comparison_is_exact() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    expected = render_policy_document(doc, "544471417928")
    assert compare_documents(expected, deepcopy(expected)) == ([], [])

    missing = deepcopy(expected)
    missing["Statement"] = missing["Statement"][:-1]
    missing_sids, unexpected_sids = compare_documents(expected, missing)
    assert missing_sids == [expected["Statement"][-1]["Sid"]]
    assert unexpected_sids == []

    unexpected = deepcopy(expected)
    unexpected["Statement"].append(
        {
            "Sid": "UnexpectedStagingPermission",
            "Effect": "Allow",
            "Action": "s3:ListAllMyBuckets",
            "Resource": "*",
        }
    )
    missing_sids, unexpected_sids = compare_documents(expected, unexpected)
    assert missing_sids == []
    assert unexpected_sids == ["UnexpectedStagingPermission"]


def test_effective_lifecycle_policy_requires_an_exact_inline_policy_name_set() -> None:
    assert inline_policy_name_errors({"AetherStagingLifecyclePolicy"}, "AetherStagingLifecyclePolicy") == []
    assert inline_policy_name_errors(set(), "AetherStagingLifecyclePolicy")
    assert inline_policy_name_errors(
        {"AetherStagingLifecyclePolicy", "UnexpectedLifecycleGrant"},
        "AetherStagingLifecyclePolicy",
    ) == ["unexpected inline policies: UnexpectedLifecycleGrant"]


def test_lifecycle_manifest_covers_static_bucket_parameter_reads() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    statement = by_sid["ReadStagingStaticBucketParameters"]
    assert statement["actions"] == ["ssm:GetParameter"]
    assert set(statement["resource"]) == {
        "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/AETHER_STATIC_BUCKET",
        "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/KYBER_STATIC_BUCKET",
    }
