#!/usr/bin/env python3
"""Compare a reviewed IAM requirement manifest with effective-policy evidence.

The normal mode reads an offline JSON fixture.  It never invokes AWS.  A
hosted caller can use :func:`compare` with statements captured by an already
authorized read-only adapter; the adapter boundary is deliberate so this
comparison cannot accidentally turn a dry-run into an IAM or STS call.

The comparison is conservative: explicit Deny wins, identity-policy Allows
must cover every reviewed action/resource pair, and a permissions boundary (if
present) must independently allow every pair.  Unsupported condition
operators and ambiguous fixture shapes are blocking, not ignored.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

# See the capability discovery module: direct script execution starts with
# scripts/release on sys.path, so make the repository package importable before
# loading the existing staging-policy matcher.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release.verify_effective_staging_apply_policy import (
    GLOBAL_READ_ACTIONS,
    _operation_is_covered,
    _operation_is_denied,
    _request_context_with_alias,
    _resource_samples,
)

DEFAULT_MANIFEST = ROOT / "config" / "staging_apply_iam_policy.yaml"
SCHEMA_VERSION = 1
SAFE_SOURCES = frozenset({"offline_fixture", "aws_read_only"})
SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|"
    r"client[_-]?secret|connection[_-]?string)(?:$|_)", re.IGNORECASE
)
SENSITIVE_VALUE = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|-----BEGIN[^-]*PRIVATE KEY-----|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]+|password\s*=|secret\s*=)",
    re.IGNORECASE,
)
REDACTED_VALUES = frozenset({"<sensitive>", "(sensitive value)", "REDACTED", "***"})


class EffectiveIamError(ValueError):
    """Raised for malformed or unsafe policy evidence."""


def _secret_paths(value: Any, path: str = "$", *, key: str | None = None) -> list[str]:
    paths: list[str] = []
    key_is_reference = bool(key and re.search(r"(?:^|_)(?:arn|id|name|ref|version)(?:$|_)", key, re.IGNORECASE))
    if key and SENSITIVE_KEY.search(key) and not key_is_reference:
        if isinstance(value, str) and value and value not in REDACTED_VALUES:
            paths.append(path)
        elif value not in (None, "", False, 0, *REDACTED_VALUES):
            paths.append(path)
    elif isinstance(value, str) and value not in REDACTED_VALUES and SENSITIVE_VALUE.search(value):
        paths.append(path)
    if isinstance(value, dict):
        for child_key, child in value.items():
            paths.extend(_secret_paths(child, f"{path}.{child_key}", key=str(child_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_secret_paths(child, f"{path}[{index}]"))
    return paths


@dataclass(frozen=True)
class IamRequirement:
    action: str
    resource: str
    conditions: Mapping[str, Any] | None
    statement_id: str


@dataclass(frozen=True)
class IamEvidence:
    role_arn: str
    identity_statements: tuple[dict[str, Any], ...]
    boundary_statements: tuple[dict[str, Any], ...]
    policy_names: tuple[str, ...]
    source: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IamEvidence":
        if data.get("schema_version") != SCHEMA_VERSION:
            raise EffectiveIamError("IAM evidence schema_version must be 1")
        role_arn = data.get("role_arn")
        if not isinstance(role_arn, str) or not role_arn.strip():
            raise EffectiveIamError("IAM evidence role_arn must be a non-empty string")
        source = data.get("source", "offline_fixture")
        if source not in SAFE_SOURCES:
            raise EffectiveIamError("IAM evidence source is not approved")
        secret_paths = _secret_paths(data)
        if secret_paths:
            raise EffectiveIamError(
                "IAM evidence contains plaintext secret material at "
                + ", ".join(secret_paths[:5])
            )
        policies = data.get("identity_statements")
        if not isinstance(policies, list) or not all(isinstance(item, dict) for item in policies):
            raise EffectiveIamError("identity_statements must be a list of policy statements")
        boundary = data.get("boundary_statements", [])
        if not isinstance(boundary, list) or not all(isinstance(item, dict) for item in boundary):
            raise EffectiveIamError("boundary_statements must be a list of policy statements")
        names = data.get("policy_names", [])
        if not isinstance(names, list) or not all(isinstance(item, str) and item for item in names):
            raise EffectiveIamError("policy_names must be a list of non-empty strings")
        for collection_name, statements in (("identity_statements", policies), ("boundary_statements", boundary)):
            for index, statement in enumerate(statements):
                effect = statement.get("Effect")
                if effect not in {"Allow", "Deny"}:
                    raise EffectiveIamError(f"{collection_name}[{index}] has an invalid Effect")
                action_or_not = statement.get("Action", statement.get("NotAction"))
                if not isinstance(action_or_not, (str, list)) or not all(
                    isinstance(item, str) and item for item in _as_list(action_or_not)
                ):
                    raise EffectiveIamError(f"{collection_name}[{index}] has no valid Action/NotAction")
                resource_or_not = statement.get("Resource", statement.get("NotResource", "*"))
                if not isinstance(resource_or_not, (str, list)) or not all(
                    isinstance(item, str) and item for item in _as_list(resource_or_not)
                ):
                    raise EffectiveIamError(f"{collection_name}[{index}] has an invalid Resource/NotResource")
        return cls(role_arn.strip(), tuple(policies), tuple(boundary), tuple(names), source)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def load_evidence(path: Path) -> IamEvidence:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EffectiveIamError(f"cannot read IAM evidence {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise EffectiveIamError("IAM evidence must be a JSON object")
    return IamEvidence.from_dict(data)


def load_requirements(path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], tuple[IamRequirement, ...]]:
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise EffectiveIamError(f"cannot read IAM requirement manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise EffectiveIamError("IAM requirement manifest version must be 1")
    statements = manifest.get("statements")
    if not isinstance(statements, list):
        raise EffectiveIamError("IAM requirement manifest statements must be a list")
    requirements: list[IamRequirement] = []
    for index, statement in enumerate(statements):
        if not isinstance(statement, dict):
            raise EffectiveIamError(f"IAM requirement statement {index} is not an object")
        sid = statement.get("sid", f"statement-{index}")
        if not isinstance(sid, str) or not sid:
            raise EffectiveIamError(f"IAM requirement statement {index} has no sid")
        actions = statement.get("actions")
        resources = _as_list(statement.get("resource", "*"))
        if not isinstance(actions, list) or not actions or not all(isinstance(item, str) and item for item in actions):
            raise EffectiveIamError(f"{sid}.actions must be a non-empty list")
        if not all(isinstance(item, str) and item for item in resources):
            raise EffectiveIamError(f"{sid}.resource must contain only strings")
        conditions = statement.get("conditions")
        if conditions is not None and not isinstance(conditions, dict):
            raise EffectiveIamError(f"{sid}.conditions must be an object")
        for action in actions:
            for resource in resources:
                requirements.append(IamRequirement(action, resource, conditions, sid))
    if not requirements:
        raise EffectiveIamError("IAM requirement manifest declares no operations")
    return manifest, tuple(requirements)


def _account_id(role_arn: str) -> str:
    parts = role_arn.split(":")
    if len(parts) < 6 or parts[0] != "arn" or parts[2] != "iam" or not parts[4].isdigit():
        raise EffectiveIamError("IAM evidence role_arn must be a concrete IAM ARN")
    return parts[4]


def _materialize(requirement: IamRequirement, account_id: str) -> tuple[str, str, Mapping[str, Any] | None]:
    resource = requirement.resource.replace("${account_id}", account_id)
    if requirement.action.lower() in GLOBAL_READ_ACTIONS and resource != "*":
        raise EffectiveIamError(f"{requirement.action} must use account-level resource scope")
    return requirement.action, resource, requirement.conditions


def compare(manifest: Mapping[str, Any], requirements: tuple[IamRequirement, ...], evidence: IamEvidence) -> dict[str, Any]:
    """Produce a typed, non-secret comparison report."""

    account_id = _account_id(evidence.role_arn)
    aliases: dict[str, str] = {}
    operations: list[dict[str, Any]] = []
    for requirement in requirements:
        action, resource, conditions = _materialize(requirement, account_id)
        if action.lower() == "kms:createalias" and ":alias/" in resource:
            sample = _resource_samples(resource)[0]
            aliases["kms:RequestAlias"] = "alias/" + sample.split(":alias/", 1)[1]
        operations.append({"action": action, "resource": resource, "conditions": conditions, "statement_id": requirement.statement_id})

    blockers: list[str] = []
    rows: list[dict[str, Any]] = []
    all_statements = evidence.identity_statements + evidence.boundary_statements
    for operation in operations:
        action = operation["action"]
        resource = operation["resource"]
        conditions = operation["conditions"]
        context = _request_context_with_alias(action, resource, conditions, aliases.get("kms:RequestAlias"))
        denied = any(
            _operation_is_denied(statement, action, resource, conditions, request_context=context)
            for statement in all_statements
        )
        identity_allowed = any(
            _operation_is_covered(statement, action, resource, conditions)
            for statement in evidence.identity_statements
        )
        boundary_allowed = (
            not evidence.boundary_statements
            or any(
                _operation_is_covered(statement, action, resource, conditions, require_required=False)
                for statement in evidence.boundary_statements
            )
        )
        status = "PASS"
        reason = "effective identity policy and boundary cover the reviewed operation"
        if denied:
            status = "BLOCKED"
            reason = "an explicit Deny overlaps the reviewed operation"
        elif not identity_allowed:
            status = "MISSING"
            reason = "no effective identity-policy Allow covers the reviewed operation"
        elif not boundary_allowed:
            status = "MISSING"
            reason = "the permissions boundary does not cover the reviewed operation"
        if status != "PASS":
            blockers.append(f"{action} on {resource}: {reason}")
        rows.append({"statement_id": operation["statement_id"], "action": action, "resource": resource, "status": status, "reason": reason})

    required_policy_names = manifest.get("required_policy_names", [])
    if required_policy_names is not None:
        if not isinstance(required_policy_names, list) or not all(isinstance(item, str) and item for item in required_policy_names):
            raise EffectiveIamError("required_policy_names must be a list of non-empty strings")
        missing_names = sorted(set(required_policy_names) - set(evidence.policy_names))
        if missing_names:
            blockers.append("required IAM policies are not present: " + ", ".join(missing_names))

    return {
        "schema_version": SCHEMA_VERSION,
        "role_arn": evidence.role_arn,
        "source": evidence.source,
        "mode": "offline" if evidence.source == "offline_fixture" else "live-evidence",
        "status": "PASS" if not blockers else "BLOCKED",
        "operations_total": len(rows),
        "operations_passed": sum(row["status"] == "PASS" for row in rows),
        "blockers": blockers,
        "operations": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest, requirements = load_requirements(args.manifest)
        report = compare(manifest, requirements, load_evidence(args.evidence))
        rendered = json.dumps(report, indent=2) + "\n"
    except EffectiveIamError as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
