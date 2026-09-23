#!/usr/bin/env python3
"""Check or add the required tags on staging ECS desired-count targets.

The default mode is read-only. ``--apply-missing-tags`` only calls
Application Auto Scaling's TagResource operation, and only for required keys
that were observed missing on the exact expected existing targets.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "runtime_deployment.yaml"
AWS_REGION = "us-east-1"
PROJECT = "AETHER"
ENVIRONMENT = "staging"
ECS_CLUSTER = f"{PROJECT}-{ENVIRONMENT}"
STAGING_RESOURCE_PREFIX = f"service/{ECS_CLUSTER}/"
SCALABLE_DIMENSION = "ecs:service:DesiredCount"
SERVICE_NAMESPACE = "ecs"
REQUIRED_TAGS = {"Environment": ENVIRONMENT, "Project": PROJECT}
SCALABLE_TARGET_ARN_RE = re.compile(
    r"^arn:aws:application-autoscaling:us-east-1:\d{12}:"
    r"scalable-target/[A-Za-z0-9-]+$"
)
SERVICE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class ReconciliationError(RuntimeError):
    """Raised when staging targets or their required tags are unsafe to change."""


def derive_expected_resource_ids(runtime_deployment: Mapping[str, Any]) -> tuple[str, ...]:
    """Derive every staging ECS desired-count target ID from runtime config."""
    if runtime_deployment.get("schema_version") != 2:
        raise ReconciliationError("runtime_deployment.yaml must use schema_version 2")

    profiles = runtime_deployment.get("profiles")
    if not isinstance(profiles, Mapping):
        raise ReconciliationError("runtime_deployment.yaml profiles must be a mapping")
    staging = profiles.get(ENVIRONMENT)
    if not isinstance(staging, Mapping):
        raise ReconciliationError("runtime_deployment.yaml has no staging profile")
    services = staging.get("services")
    if not isinstance(services, Mapping) or not services:
        raise ReconciliationError("staging profile must declare at least one service")

    resource_ids: list[str] = []
    for service_key, service_config in services.items():
        if not isinstance(service_key, str) or not SERVICE_KEY_RE.fullmatch(service_key):
            raise ReconciliationError(f"invalid staging service key: {service_key!r}")
        if not isinstance(service_config, Mapping):
            raise ReconciliationError(f"staging service {service_key!r} must be a mapping")
        desired_count = service_config.get("desired_count")
        if isinstance(desired_count, bool) or not isinstance(desired_count, int) or desired_count < 0:
            raise ReconciliationError(
                f"staging service {service_key!r} must declare a non-negative desired_count"
            )
        if not isinstance(service_config.get("autoscaling"), Mapping):
            raise ReconciliationError(
                f"staging service {service_key!r} must declare autoscaling"
            )

        # runtime_deployment.yaml documents this single naming exception:
        # logical service key ``api`` is the Terraform ECS ``backend`` service.
        ecs_service_key = "backend" if service_key == "api" else service_key
        ecs_service_name = f"{PROJECT}-{ENVIRONMENT}-{ecs_service_key}"
        resource_ids.append(f"service/{ECS_CLUSTER}/{ecs_service_name}")

    if len(resource_ids) != len(set(resource_ids)):
        raise ReconciliationError("staging config derives duplicate ECS scalable target IDs")
    return tuple(sorted(resource_ids))


def load_expected_resource_ids(config_path: Path | None = None) -> tuple[str, ...]:
    path = config_path or CONFIG_PATH
    try:
        runtime_deployment = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ReconciliationError(f"could not read runtime deployment config: {exc}") from exc
    if not isinstance(runtime_deployment, Mapping):
        raise ReconciliationError("runtime deployment config must be a mapping")
    return derive_expected_resource_ids(runtime_deployment)


def _describe_expected_targets(client: Any, expected_ids: tuple[str, ...]) -> dict[str, str]:
    """Return expected ResourceId -> ARN after an exact, paginated set check."""
    found: dict[str, dict[str, Any]] = {}
    next_token: str | None = None
    seen_tokens: set[str] = set()

    while True:
        request: dict[str, str] = {
            "ServiceNamespace": SERVICE_NAMESPACE,
        }
        if next_token is not None:
            request["NextToken"] = next_token
        response = client.describe_scalable_targets(**request)
        if not isinstance(response, Mapping):
            raise ReconciliationError("DescribeScalableTargets returned a non-object response")
        targets = response.get("ScalableTargets")
        if not isinstance(targets, list):
            raise ReconciliationError("DescribeScalableTargets returned no ScalableTargets list")

        for target in targets:
            if not isinstance(target, Mapping):
                raise ReconciliationError("DescribeScalableTargets returned a malformed target")
            if target.get("ServiceNamespace") != SERVICE_NAMESPACE:
                raise ReconciliationError(
                    "DescribeScalableTargets returned a target outside the requested ECS namespace"
                )
            resource_id = target.get("ResourceId")
            if not isinstance(resource_id, str) or not resource_id:
                raise ReconciliationError("DescribeScalableTargets returned a target without ResourceId")
            if not resource_id.startswith(STAGING_RESOURCE_PREFIX):
                continue
            if target.get("ScalableDimension") != SCALABLE_DIMENSION:
                raise ReconciliationError(
                    f"staging target {resource_id} has an unexpected scalable dimension"
                )
            if resource_id in found:
                raise ReconciliationError(
                    f"ambiguous staging target: duplicate ResourceId {resource_id}"
                )
            found[resource_id] = dict(target)

        token = response.get("NextToken")
        if token is None or token == "":
            break
        if not isinstance(token, str) or token in seen_tokens:
            raise ReconciliationError("DescribeScalableTargets returned an invalid or repeated NextToken")
        seen_tokens.add(token)
        next_token = token

    expected = set(expected_ids)
    actual = set(found)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing targets: {', '.join(missing)}")
        if extra:
            details.append(f"extra targets: {', '.join(extra)}")
        raise ReconciliationError("staging scalable target set mismatch; " + "; ".join(details))

    arn_by_id: dict[str, str] = {}
    ids_by_arn: dict[str, str] = {}
    for resource_id in expected_ids:
        arn = found[resource_id].get("ScalableTargetARN")
        if not isinstance(arn, str) or not SCALABLE_TARGET_ARN_RE.fullmatch(arn):
            raise ReconciliationError(
                f"expected target {resource_id} has no valid us-east-1 scalable target ARN"
            )
        if arn in ids_by_arn:
            raise ReconciliationError(
                f"ambiguous staging targets {ids_by_arn[arn]} and {resource_id} share one ARN"
            )
        arn_by_id[resource_id] = arn
        ids_by_arn[arn] = resource_id
    return arn_by_id


def _read_tags(client: Any, resource_arn: str) -> dict[str, str]:
    response = client.list_tags_for_resource(ResourceARN=resource_arn)
    if not isinstance(response, Mapping):
        raise ReconciliationError("ListTagsForResource returned a non-object response")
    tags = response.get("Tags")
    if not isinstance(tags, Mapping):
        raise ReconciliationError("ListTagsForResource returned no tag mapping")
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items()):
        raise ReconciliationError("ListTagsForResource returned a malformed tag mapping")
    return dict(tags)


def _tag_conflicts(resource_id: str, tags: Mapping[str, str]) -> list[str]:
    return [
        f"{resource_id} has a conflicting {key} tag"
        for key, expected_value in REQUIRED_TAGS.items()
        if key in tags and tags[key] != expected_value
    ]


def _missing_required_tags(tags: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in REQUIRED_TAGS.items() if key not in tags}


def check_or_apply_tags(
    client: Any,
    expected_ids: tuple[str, ...],
    *,
    apply_missing: bool = False,
) -> dict[str, dict[str, str]]:
    """Check required tags, or add only missing required tags and verify them.

    The returned mapping identifies missing tags by ResourceId. In apply mode,
    a successful return is always empty because tags are re-read after writes.
    """
    arn_by_id = _describe_expected_targets(client, expected_ids)

    # Read and validate every target before any optional mutation. A conflict on
    # one target therefore cannot cause another target to be changed first.
    initial_tags = {
        resource_id: _read_tags(client, arn_by_id[resource_id])
        for resource_id in expected_ids
    }
    conflicts = [
        conflict
        for resource_id, tags in initial_tags.items()
        for conflict in _tag_conflicts(resource_id, tags)
    ]
    if conflicts:
        raise ReconciliationError("; ".join(conflicts))

    missing = {
        resource_id: _missing_required_tags(tags)
        for resource_id, tags in initial_tags.items()
        if _missing_required_tags(tags)
    }
    if not apply_missing or not missing:
        return missing

    for resource_id in expected_ids:
        # Re-read immediately before each write, and pass only keys still absent.
        # TagResource replaces same-key values, so never pass an existing key.
        current_tags = _read_tags(client, arn_by_id[resource_id])
        conflicts = _tag_conflicts(resource_id, current_tags)
        if conflicts:
            raise ReconciliationError("; ".join(conflicts))
        tags_to_add = _missing_required_tags(current_tags)
        if tags_to_add:
            client.tag_resource(ResourceARN=arn_by_id[resource_id], Tags=tags_to_add)

    verified_missing: dict[str, dict[str, str]] = {}
    verified_conflicts: list[str] = []
    for resource_id in expected_ids:
        tags = _read_tags(client, arn_by_id[resource_id])
        verified_conflicts.extend(_tag_conflicts(resource_id, tags))
        remaining = _missing_required_tags(tags)
        if remaining:
            verified_missing[resource_id] = remaining
    if verified_conflicts:
        raise ReconciliationError("post-apply verification found " + "; ".join(verified_conflicts))
    if verified_missing:
        details = "; ".join(
            f"{resource_id}: {', '.join(tags)}"
            for resource_id, tags in sorted(verified_missing.items())
        )
        raise ReconciliationError("post-apply verification still finds missing tags: " + details)
    return {}


def _application_autoscaling_client() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise ReconciliationError("boto3 is required to inspect AWS Application Auto Scaling") from exc
    return boto3.client("application-autoscaling", region_name=AWS_REGION)


def main(
    argv: list[str] | None = None,
    *,
    client: Any | None = None,
    config_path: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    tag_modes = parser.add_mutually_exclusive_group()
    tag_modes.add_argument(
        "--apply-missing-tags", action="store_true",
        help="add only missing Environment=staging and Project=AETHER tags",
    )
    tag_modes.add_argument(
        "--allow-missing-tags", action="store_true",
        help=(
            "allow missing canonical tags after exact target/conflict checks so an approved "
            "Terraform apply can repair them"
        ),
    )
    args = parser.parse_args(argv)

    try:
        expected_ids = load_expected_resource_ids(config_path)
        active_client = client if client is not None else _application_autoscaling_client()
        missing = check_or_apply_tags(
            active_client,
            expected_ids,
            apply_missing=args.apply_missing_tags,
        )
    except Exception as exc:
        print(f"staging autoscaling target tag check FAILED: {exc}", file=sys.stderr)
        return 1

    if missing:
        for resource_id, tags in sorted(missing.items()):
            print(f"missing required tags on {resource_id}: {', '.join(tags)}")
        if args.allow_missing_tags and not args.apply_missing_tags:
            print(
                "staging autoscaling target preflight passed: the exact target set has no conflicting tags; "
                "the following reviewed Terraform apply must repair and verify these missing tags"
            )
            return 0
        if args.apply_missing_tags:
            print("staging autoscaling target tag repair FAILED: required tags remain missing", file=sys.stderr)
        else:
            print(
                "staging autoscaling target tag check FAILED; rerun with "
                "--apply-missing-tags to add only the missing required tags",
                file=sys.stderr,
            )
        return 1

    action = "repair and verification" if args.apply_missing_tags else "read-only check"
    print(
        f"staging autoscaling target tag {action} passed for "
        f"{len(expected_ids)} exact existing targets"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
