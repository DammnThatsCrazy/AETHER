"""Contract tests for staging ECS scalable target tag verification and repair."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/ensure_staging_autoscaling_target_tags.py"
CONFIG = ROOT / "config/runtime_deployment.yaml"
SPEC = importlib.util.spec_from_file_location("ensure_staging_autoscaling_target_tags", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _expected_ids() -> tuple[str, ...]:
    return checker.load_expected_resource_ids(CONFIG)


def _target(resource_id: str, index: int) -> dict[str, str]:
    return {
        "ServiceNamespace": "ecs",
        "ScalableDimension": "ecs:service:DesiredCount",
        "ResourceId": resource_id,
        "ScalableTargetARN": (
            "arn:aws:application-autoscaling:us-east-1:123456789012:"
            f"scalable-target/target-{index:032d}"
        ),
    }


class FakeApplicationAutoScaling:
    def __init__(
        self,
        targets: list[dict[str, str]],
        tags_by_arn: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.targets = targets
        self.tags_by_arn = tags_by_arn or {}
        self.describe_calls: list[dict[str, str]] = []
        self.list_calls: list[str] = []
        self.tag_calls: list[tuple[str, dict[str, str]]] = []

    def describe_scalable_targets(self, **kwargs: str) -> dict[str, Any]:
        self.describe_calls.append(kwargs)
        return {"ScalableTargets": list(self.targets)}

    def list_tags_for_resource(self, *, ResourceARN: str) -> dict[str, dict[str, str]]:
        self.list_calls.append(ResourceARN)
        return {"Tags": dict(self.tags_by_arn.get(ResourceARN, {}))}

    def tag_resource(self, *, ResourceARN: str, Tags: dict[str, str]) -> dict[str, Any]:
        self.tag_calls.append((ResourceARN, dict(Tags)))
        current = self.tags_by_arn.setdefault(ResourceARN, {})
        current.update(Tags)
        return {}


def _client(
    expected_ids: tuple[str, ...] | None = None,
    *,
    tags_by_arn: dict[str, dict[str, str]] | None = None,
) -> FakeApplicationAutoScaling:
    ids = expected_ids if expected_ids is not None else _expected_ids()
    return FakeApplicationAutoScaling(
        [_target(resource_id, index) for index, resource_id in enumerate(ids, start=1)],
        tags_by_arn,
    )


def test_derives_expected_target_ids_from_staging_runtime_services() -> None:
    document = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))

    assert checker.derive_expected_resource_ids(document) == (
        "service/AETHER-staging/AETHER-staging-backend",
        "service/AETHER-staging/AETHER-staging-lean-worker",
    )

    document["profiles"]["staging"]["services"]["maintenance"] = {
        "desired_count": 1,
        "autoscaling": {"min_capacity": 1, "max_capacity": 2},
    }
    assert "service/AETHER-staging/AETHER-staging-maintenance" in (
        checker.derive_expected_resource_ids(document)
    )


def test_missing_target_fails_before_tag_reads_or_writes() -> None:
    expected = _expected_ids()
    client = _client(expected[:-1])

    with pytest.raises(checker.ReconciliationError, match="missing targets"):
        checker.check_or_apply_tags(client, expected, apply_missing=True)

    assert client.list_calls == []
    assert client.tag_calls == []


def test_extra_target_fails_before_tag_reads_or_writes() -> None:
    expected = _expected_ids()
    client = _client(expected)
    extra_id = "service/AETHER-staging/AETHER-staging-unexpected"
    client.targets.append(_target(extra_id, 99))

    with pytest.raises(checker.ReconciliationError, match="extra targets"):
        checker.check_or_apply_tags(client, expected, apply_missing=True)

    assert client.list_calls == []
    assert client.tag_calls == []


def test_duplicate_target_is_ambiguous_and_fails_closed() -> None:
    expected = _expected_ids()
    client = _client(expected)
    client.targets.append(dict(client.targets[0]))

    with pytest.raises(checker.ReconciliationError, match="ambiguous staging target"):
        checker.check_or_apply_tags(client, expected, apply_missing=True)

    assert client.tag_calls == []


def test_read_only_check_reports_untagged_targets_without_mutation() -> None:
    expected = _expected_ids()
    client = _client(expected)

    missing = checker.check_or_apply_tags(client, expected)

    assert set(missing) == set(expected)
    assert all(tags == checker.REQUIRED_TAGS for tags in missing.values())
    assert client.tag_calls == []
    assert client.describe_calls == [
        {"ServiceNamespace": "ecs"}
    ]


def test_staging_target_with_wrong_dimension_fails_before_tag_access() -> None:
    expected = _expected_ids()
    client = _client(expected)
    client.targets[0]["ScalableDimension"] = "ecs:service:SomeOtherDimension"

    with pytest.raises(checker.ReconciliationError, match="unexpected scalable dimension"):
        checker.check_or_apply_tags(client, expected, apply_missing=True)

    assert client.list_calls == []
    assert client.tag_calls == []


def test_allow_missing_tags_is_read_only_and_requires_reviewed_apply(capsys: pytest.CaptureFixture[str]) -> None:
    client = _client()

    result = checker.main(["--allow-missing-tags"], client=client, config_path=CONFIG)

    captured = capsys.readouterr()
    assert result == 0
    assert "reviewed Terraform apply must repair and verify" in captured.out
    assert client.tag_calls == []


def test_conflicting_tags_abort_all_repairs_without_mutation() -> None:
    expected = _expected_ids()
    targets = [_target(resource_id, index) for index, resource_id in enumerate(expected, start=1)]
    first_arn = targets[0]["ScalableTargetARN"]
    second_arn = targets[1]["ScalableTargetARN"]
    client = FakeApplicationAutoScaling(
        targets,
        {
            first_arn: {"Owner": "release"},
            second_arn: {"Environment": "production", "Project": "AETHER"},
        },
    )

    with pytest.raises(checker.ReconciliationError, match="conflicting Environment tag"):
        checker.check_or_apply_tags(client, expected, apply_missing=True)

    assert client.tag_calls == []


def test_apply_repairs_only_missing_tags_verifies_and_is_idempotent() -> None:
    expected = _expected_ids()
    targets = [_target(resource_id, index) for index, resource_id in enumerate(expected, start=1)]
    first_arn = targets[0]["ScalableTargetARN"]
    second_arn = targets[1]["ScalableTargetARN"]
    client = FakeApplicationAutoScaling(
        targets,
        {
            first_arn: {"Environment": "staging", "Owner": "release"},
            second_arn: {"Project": "AETHER"},
        },
    )

    assert checker.check_or_apply_tags(client, expected, apply_missing=True) == {}
    first_calls = list(client.tag_calls)
    assert first_calls == [
        (first_arn, {"Project": "AETHER"}),
        (second_arn, {"Environment": "staging"}),
    ]
    assert client.tags_by_arn[first_arn] == {
        "Environment": "staging",
        "Project": "AETHER",
        "Owner": "release",
    }
    assert client.tags_by_arn[second_arn] == {
        "Project": "AETHER",
        "Environment": "staging",
    }

    assert checker.check_or_apply_tags(client, expected, apply_missing=True) == {}
    assert client.tag_calls == first_calls


def test_cli_returns_failure_for_aws_inspection_error(capsys: pytest.CaptureFixture[str]) -> None:
    class FailedClient:
        def describe_scalable_targets(self, **kwargs: str) -> dict[str, Any]:
            raise RuntimeError("simulated metadata failure")

    result = checker.main([], client=FailedClient(), config_path=CONFIG)

    captured = capsys.readouterr()
    assert result == 1
    assert "staging autoscaling target tag check FAILED" in captured.err
    assert "simulated metadata failure" in captured.err
