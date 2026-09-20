from pathlib import Path

import yaml

from scripts.release.check_staging_application_delivery_policy import (
    EXPECTED,
    main,
    render_policy_document,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/staging_application_delivery_iam_policy.yaml"


def test_delivery_manifest_is_checker_clean() -> None:
    assert main(["--manifest", str(MANIFEST)]) == 0


def test_delivery_manifest_contains_only_the_runtime_delta() -> None:
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    actions = {action for statement in document["statements"] for action in statement["actions"]}
    assert actions == EXPECTED


def test_delivery_manifest_scopes_runtime_tasks_and_static_assets() -> None:
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    by_sid = {statement["sid"]: statement for statement in document["statements"]}
    assert by_sid["RunStagingApplicationTasks"]["resource"][0].endswith("task-definition/AETHER-staging-*")
    assert by_sid["InspectStagingApplicationTasks"]["resource"].endswith("task/AETHER-staging/*")
    assert by_sid["PublishStagingStaticArtifacts"]["resource"] == [
        "arn:aws:s3:::aether-staging-*",
        "arn:aws:s3:::aether-staging-*/*",
    ]


def test_delivery_manifest_renders_to_an_aws_policy_document() -> None:
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    rendered = render_policy_document(document, "544471417928")
    statements = {statement["Sid"]: statement for statement in rendered["Statement"]}
    assert statements["RunStagingApplicationTasks"]["Condition"]["ArnEquals"]["ecs:cluster"].endswith(
        ":cluster/AETHER-staging"
    )
