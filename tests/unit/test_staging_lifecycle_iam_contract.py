from pathlib import Path

from scripts.release.check_staging_lifecycle_policy import EXPECTED, main
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


def test_lifecycle_manifest_uses_task_specific_scopes() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    assert by_sid["InspectStagingTaskDefinitions"]["resource"].endswith("task-definition/AETHER-staging-*")
    assert by_sid["RunStagingMigrationTasks"]["resource"] == [
        "arn:aws:ecs:us-east-1:${account_id}:task-definition/AETHER-staging-*",
        "arn:aws:ecs:us-east-1:${account_id}:cluster/AETHER-staging",
    ]


def test_lifecycle_manifest_covers_static_bucket_parameter_reads() -> None:
    doc = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in doc["statements"]}
    statement = by_sid["ReadStagingStaticBucketParameters"]
    assert statement["actions"] == ["ssm:GetParameter"]
    assert set(statement["resource"]) == {
        "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/AETHER_STATIC_BUCKET",
        "arn:aws:ssm:us-east-1:${account_id}:parameter/aether/staging/KYBER_STATIC_BUCKET",
    }
