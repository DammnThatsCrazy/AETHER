#!/usr/bin/env python3
"""Build a fail-closed environment capability snapshot.

This module is intentionally an observation boundary, not an AWS client.  The
default input is a checked-in or operator-supplied typed fixture.  A Terraform
plan can be inspected for shape, but it cannot prove that the remote account
supports or currently owns the resulting resources, so plan-derived
capabilities remain ``UNKNOWN``.  A live reader may be injected by a hosted
workflow only when the workflow explicitly opts in and supplies credentials.

No AWS SDK or CLI is imported at module load time.  This keeps local and CI
dry-runs credentialless and makes accidental cloud calls test-detectable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import yaml

# Direct script execution places scripts/release on sys.path, not the repo
# root.  Add the root before importing the sibling release authority module;
# this keeps both `python -m ...` and the Makefile-style direct invocation
# offline-safe and importable.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release.resolve_environment import load_requirements, resolve

SNAPSHOT_SCHEMA_VERSION = 1


class CapabilityStatus(str, Enum):
    PASS = "PASS"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


CAPABILITY_STATUSES = frozenset(item.value for item in CapabilityStatus)
SAFE_FIXTURE_SOURCES = frozenset({"offline_fixture", "terraform_plan", "config", "aws_read_only"})


class CapabilityDiscoveryError(ValueError):
    """Raised when capability evidence cannot be trusted or parsed."""


@dataclass(frozen=True)
class CapabilityObservation:
    capability: str
    status: CapabilityStatus
    source: str
    reason: str | None = None
    evidence_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "source": self.source,
            **({"reason": self.reason} if self.reason else {}),
            **({"evidence_ref": self.evidence_ref} if self.evidence_ref else {}),
        }


@dataclass(frozen=True)
class CapabilitySnapshot:
    profile: str
    capabilities: Mapping[str, CapabilityObservation]
    mode: str = "offline"
    schema_version: int = SNAPSHOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "mode": self.mode,
            "capabilities": {
                name: observation.to_dict()
                for name, observation in sorted(self.capabilities.items())
            },
        }


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityDiscoveryError(f"{label} must be a non-empty string")
    return value.strip()


def _status(value: Any, label: str) -> CapabilityStatus:
    try:
        return CapabilityStatus(_require_string(value, label).upper())
    except ValueError as exc:
        raise CapabilityDiscoveryError(
            f"{label} must be one of {sorted(CAPABILITY_STATUSES)}"
        ) from exc


def explicit_aws_credentials(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether the caller explicitly supplied an AWS credential source.

    A profile name is an explicit operator choice, but the live workflow still
    needs its SDK/CLI to resolve that profile.  The function deliberately does
    not inspect credential files or call STS: file presence is not proof that
    usable credentials exist.
    """

    environ = environ or os.environ
    access_key = environ.get("AWS_ACCESS_KEY_ID") or environ.get("AWS_ACCESS_KEY")
    secret_key = environ.get("AWS_SECRET_ACCESS_KEY") or environ.get("AWS_SECRET_KEY")
    return bool((access_key and secret_key) or environ.get("AWS_PROFILE"))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CapabilityDiscoveryError(f"cannot read capability input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CapabilityDiscoveryError(f"capability input {path} must be a JSON object")
    return value


def load_fixture(path: Path, *, profile: str | None = None) -> CapabilitySnapshot:
    """Load and validate an offline capability fixture without side effects."""

    data = _load_json(path)
    if data.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise CapabilityDiscoveryError("capability fixture schema_version must be 1")
    fixture_profile = _require_string(data.get("profile"), "fixture profile")
    if profile and profile != fixture_profile:
        raise CapabilityDiscoveryError(
            f"capability fixture is for {fixture_profile}, not requested {profile}"
        )
    mode = _require_string(data.get("mode", "offline"), "fixture mode")
    if mode != "offline":
        raise CapabilityDiscoveryError("offline capability fixtures must use mode=offline")
    raw_capabilities = data.get("capabilities")
    if not isinstance(raw_capabilities, dict) or not raw_capabilities:
        raise CapabilityDiscoveryError("capability fixture must declare capabilities")
    observations: dict[str, CapabilityObservation] = {}
    for name, raw in raw_capabilities.items():
        capability = _require_string(name, "capability name")
        if capability in observations:
            raise CapabilityDiscoveryError(f"duplicate capability {capability}")
        if not isinstance(raw, dict):
            raise CapabilityDiscoveryError(f"capability {capability} must be an object")
        source = _require_string(raw.get("source", "offline_fixture"), f"{capability}.source")
        if source not in SAFE_FIXTURE_SOURCES:
            raise CapabilityDiscoveryError(f"{capability}.source is not approved for a fixture")
        observations[capability] = CapabilityObservation(
            capability=capability,
            status=_status(raw.get("status"), f"{capability}.status"),
            source=source,
            reason=raw.get("reason"),
            evidence_ref=raw.get("evidence_ref"),
        )
    return CapabilitySnapshot(profile=fixture_profile, capabilities=observations)


def _plan_resource_types(value: Any) -> Iterable[str]:
    if not isinstance(value, dict):
        return
    for resource in value.get("resources", []) or []:
        if isinstance(resource, dict) and isinstance(resource.get("type"), str):
            yield resource["type"]
    for child in value.get("child_modules", []) or []:
        yield from _plan_resource_types(child)


PLAN_RESOURCE_CAPABILITIES: dict[str, frozenset[str]] = {
    "aws_vpc": frozenset({"vpc"}),
    "aws_ecs_cluster": frozenset({"ecs"}),
    "aws_ecs_service": frozenset({"ecs"}),
    "aws_ecr_repository": frozenset({"ecr"}),
    "aws_sqs_queue": frozenset({"sqs"}),
    "aws_sns_topic": frozenset({"sns"}),
    "aws_dynamodb_table": frozenset({"dynamodb"}),
    "aws_s3_bucket": frozenset({"s3"}),
    "aws_kms_key": frozenset({"kms"}),
    "aws_secretsmanager_secret": frozenset({"secrets"}),
    "aws_rds_cluster": frozenset({"aurora"}),
    "aws_rds_cluster_instance": frozenset({"aurora"}),
}


def discover_from_plan(plan_path: Path, profile: str) -> CapabilitySnapshot:
    """Inspect plan shape while refusing to turn desired state into live proof."""

    plan = _load_json(plan_path)
    if not isinstance(plan.get("format_version"), str):
        raise CapabilityDiscoveryError("Terraform plan must declare format_version")
    planned_values = plan.get("planned_values") or {}
    resource_types = set(_plan_resource_types(planned_values.get("root_module", {})))
    present = set().union(*(PLAN_RESOURCE_CAPABILITIES.get(kind, frozenset()) for kind in resource_types))
    requirements = load_requirements()
    profile_config = requirements["profiles"].get(profile)
    if not isinstance(profile_config, dict):
        raise CapabilityDiscoveryError(f"unknown deployment profile: {profile}")
    names = set(profile_config.get("required", [])) | set(profile_config.get("optional", []))
    observations = {
        name: CapabilityObservation(
            capability=name,
            status=CapabilityStatus.UNKNOWN,
            source="terraform_plan",
            reason=(
                "Terraform desired state is present, but a plan cannot prove "
                "remote capability or ownership"
                if name in present
                else "no matching resource in the plan; remote capability is unobserved"
            ),
            evidence_ref=str(plan_path),
        )
        for name in sorted(names)
    }
    return CapabilitySnapshot(profile=profile, capabilities=observations)


def resolve_snapshot(snapshot: CapabilitySnapshot, requirements: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve a snapshot through the existing profile authority."""

    observed = {name: item.status.value for name, item in snapshot.capabilities.items()}
    result = resolve(snapshot.profile, observed, requirements=requirements)
    result["capability_evidence"] = {
        name: item.to_dict() for name, item in sorted(snapshot.capabilities.items())
    }
    return result


def discover(
    profile: str,
    *,
    fixture_path: Path | None = None,
    plan_path: Path | None = None,
    live: bool = False,
    aws_reader: Callable[[str], Mapping[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> CapabilitySnapshot:
    """Discover capabilities from a fixture, plan, or explicitly injected live reader.

    ``aws_reader`` is intentionally an injection point.  A hosted adapter may
    provide it after validating its own read-only IAM contract; this module
    never invents an AWS client or silently falls back to credentials on disk.
    """

    if fixture_path and plan_path:
        raise CapabilityDiscoveryError("choose one of fixture_path or plan_path")
    if live and (fixture_path or plan_path):
        raise CapabilityDiscoveryError("live discovery cannot be combined with offline input")
    if fixture_path:
        return load_fixture(fixture_path, profile=profile)
    if plan_path:
        return discover_from_plan(plan_path, profile)
    if not live:
        raise CapabilityDiscoveryError(
            "offline discovery requires --fixture or --plan-json; no cloud call was made"
        )
    if not explicit_aws_credentials(environ):
        raise CapabilityDiscoveryError(
            "live discovery requires explicit AWS credentials; no cloud call was made"
        )
    if aws_reader is None:
        raise CapabilityDiscoveryError(
            "live discovery requires an injected read-only AWS reader; no cloud call was made"
        )
    raw = aws_reader(profile)
    if not isinstance(raw, Mapping):
        raise CapabilityDiscoveryError("live AWS reader returned a non-object result")
    observations: dict[str, CapabilityObservation] = {}
    for name, item in raw.items():
        capability = _require_string(name, "capability name")
        if not isinstance(item, Mapping):
            raise CapabilityDiscoveryError(f"live AWS reader returned invalid observation for {capability}")
        observations[capability] = CapabilityObservation(
            capability=capability,
            status=_status(item.get("status"), f"{capability}.status"),
            source="aws_read_only",
            reason=item.get("reason"),
            evidence_ref=item.get("evidence_ref"),
        )
    if not observations:
        raise CapabilityDiscoveryError("live AWS reader returned no typed capabilities")
    return CapabilitySnapshot(profile=profile, capabilities=observations, mode="live")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--plan-json", type=Path)
    parser.add_argument("--live", action="store_true", help="require explicit credentials and a hosted reader")
    parser.add_argument("--resolve", action="store_true", help="also emit the profile resolution")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        snapshot = discover(
            args.profile,
            fixture_path=args.fixture,
            plan_path=args.plan_json,
            live=args.live,
        )
        result: dict[str, Any] = snapshot.to_dict()
        if args.resolve:
            result["resolution"] = resolve_snapshot(snapshot)
        rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    except (CapabilityDiscoveryError, OSError, yaml.YAMLError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
