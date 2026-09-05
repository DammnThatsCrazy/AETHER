#!/usr/bin/env python3
"""Fail closed when the staging apply role does not realize its contract.

The checked-in YAML is the reviewed intent. This check reads the policies
actually attached to the assumed role and verifies every reviewed operation
against Allow/Deny effects, resource coverage, and condition compatibility.
Action-name presence alone is not sufficient: a wrong ARN, an unsatisfied
condition, or an overriding Deny must fail before Terraform mutation.
It deliberately does not print policy documents or secret values.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, NoReturn

import yaml


def fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def aws_json(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["aws", *args, "--output", "json"], text=True, capture_output=True, check=False
    )
    if result.returncode:
        fail(
            f"AWS policy inspection failed for {args[0]}: {result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"AWS policy inspection returned invalid JSON for {args[0]}: {exc}")
    if isinstance(value, str):
        value = json.loads(urllib.parse.unquote(value))
    return value


def role_name_from_arn(role_arn: str) -> str:
    prefix = "arn:aws:iam::"
    if not role_arn.startswith(prefix) or ":role/" not in role_arn:
        fail("role ARN must be a concrete IAM role ARN")
    name = role_arn.split(":role/", 1)[1]
    if "/" in name:
        fail("role ARN paths are not accepted for the staging apply role")
    return name


def policy_statements(document: dict[str, Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    return [statement for statement in statements if isinstance(statement, dict)]


def policy_actions(document: dict[str, Any]) -> set[str]:
    """Return Allow actions for backwards-compatible diagnostics/tests."""
    allowed: set[str] = set()
    for statement in policy_statements(document):
        if statement.get("Effect") != "Allow":
            continue
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        allowed.update(action for action in actions if isinstance(action, str))
    return allowed


def load_effective_statements(role_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    statements: list[dict[str, Any]] = []
    policy_names: list[str] = []
    inline = aws_json("iam", "list-role-policies", "--role-name", role_name)
    for name in inline.get("PolicyNames", []):
        policy_names.append(f"inline:{name}")
        document = aws_json(
            "iam", "get-role-policy", "--role-name", role_name, "--policy-name", name
        )
        raw = document.get("PolicyDocument", {})
        if isinstance(raw, str):
            raw = json.loads(urllib.parse.unquote(raw))
        statements.extend(policy_statements(raw))

    attached = aws_json("iam", "list-attached-role-policies", "--role-name", role_name)
    for policy in attached.get("AttachedPolicies", []):
        arn = policy.get("PolicyArn")
        name = policy.get("PolicyName", arn)
        if not arn:
            continue
        policy_names.append(f"managed:{name}")
        meta = aws_json("iam", "get-policy", "--policy-arn", arn)
        version = (meta.get("Policy", {}) or {}).get("DefaultVersionId")
        if not version:
            fail(f"managed policy {name} has no default version")
        version_doc = aws_json(
            "iam", "get-policy-version", "--policy-arn", arn, "--version-id", version
        )
        raw = (version_doc.get("PolicyVersion", {}) or {}).get("Document", {})
        if isinstance(raw, str):
            raw = json.loads(urllib.parse.unquote(raw))
        statements.extend(policy_statements(raw))
    return statements, policy_names


def load_permissions_boundary_statements(
    role_name: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Load the role's permissions boundary, if one is attached.

    Identity policies and a permissions boundary are an intersection: an
    identity Allow is not effective unless the boundary also allows it. Keep
    boundary statements separate so a boundary Allow can never accidentally
    satisfy the identity-policy half of the check.
    """
    role = aws_json("iam", "get-role", "--role-name", role_name).get("Role", {}) or {}
    boundary = role.get("PermissionsBoundary") or {}
    arn = boundary.get("PermissionsBoundaryArn")
    if not arn:
        return [], None
    meta = aws_json("iam", "get-policy", "--policy-arn", arn)
    version = (meta.get("Policy", {}) or {}).get("DefaultVersionId")
    if not version:
        fail("permissions boundary has no default version")
    version_doc = aws_json(
        "iam", "get-policy-version", "--policy-arn", arn, "--version-id", version
    )
    raw = (version_doc.get("PolicyVersion", {}) or {}).get("Document", {})
    if isinstance(raw, str):
        raw = json.loads(urllib.parse.unquote(raw))
    return policy_statements(raw), arn


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value]


def _statement_actions(statement: dict[str, Any]) -> list[str]:
    return [value for value in _as_list(statement.get("Action", [])) if isinstance(value, str)]


def _statement_matches_action(statement: dict[str, Any], action: str) -> bool:
    normalized_action = action.lower()
    actions = _statement_actions(statement)
    if actions:
        return any(
            fnmatch.fnmatchcase(normalized_action, pattern.lower()) for pattern in actions
        )
    not_actions = [
        value for value in _as_list(statement.get("NotAction", [])) if isinstance(value, str)
    ]
    return bool(not_actions) and not any(
        fnmatch.fnmatchcase(normalized_action, pattern.lower()) for pattern in not_actions
    )


def _statement_resources(statement: dict[str, Any]) -> list[str]:
    return [value for value in _as_list(statement.get("Resource", "*")) if isinstance(value, str)]


def _statement_matches_resource(statement: dict[str, Any], sample: str) -> bool:
    if "Resource" in statement:
        return any(
            fnmatch.fnmatchcase(sample, pattern)
            for pattern in _statement_resources(statement)
        )
    if "NotResource" in statement:
        excluded = [
            value for value in _as_list(statement.get("NotResource", [])) if isinstance(value, str)
        ]
        return bool(excluded) and not any(
            fnmatch.fnmatchcase(sample, pattern) for pattern in excluded
        )
    return False


SUPPORTED_CONDITION_OPERATORS = frozenset(
    {
        "StringEquals",
        "StringLike",
        "NumericEquals",
        "ArnEquals",
        "ArnLike",
        "ForAllValues:StringEquals",
        "ForAnyValue:StringEquals",
    }
)

# KMS exposes alias discovery only through the account-level ListAliases API.
# Keep this explicit so the live effective-policy check cannot accidentally
# accept a resource-scoped approximation for the reconciliation probe.
GLOBAL_READ_ACTIONS = frozenset({"kms:listaliases"})


def _has_unsupported_condition_operator(condition: Any) -> bool:
    """Return true when a condition cannot be evaluated by this checker."""
    if not condition:
        return False
    if not isinstance(condition, dict):
        return True
    return any(operator not in SUPPORTED_CONDITION_OPERATORS for operator in condition)


def _conditions_compatible(
    actual: Any,
    required: dict[str, Any] | None,
    *,
    require_required: bool = False,
) -> bool:
    """Return whether an attached Allow can satisfy the reviewed context.

    An absent condition is broader and therefore compatible. If an attached
    statement adds a condition, the manifest must provide a matching key/value
    (including list-valued contexts). Unknown operators are rejected instead of
    being treated as equivalent by accident.
    """
    if not actual:
        # An unconditional attached Allow is broader than the reviewed
        # operation. It cannot satisfy a manifest that requires request or
        # resource conditions to keep the role staging-scoped.
        return not required or not require_required
    if not isinstance(actual, dict) or not isinstance(required, dict):
        return False
    matched_keys: set[str] = set()
    for operator, entries in actual.items():
        if operator not in SUPPORTED_CONDITION_OPERATORS:
            return False
        if not isinstance(entries, dict):
            return False
        for key, actual_value in entries.items():
            if key not in required:
                return False
            matched_keys.add(key)
            wanted = required[key]
            actual_values = {str(v) for v in _as_list(actual_value)}
            wanted_values = {str(v) for v in _as_list(wanted)}
            if operator in {"StringLike", "ArnLike"}:
                if not any(
                    fnmatch.fnmatchcase(wanted_value, actual_pattern)
                    for wanted_value in wanted_values
                    for actual_pattern in actual_values
                ):
                    return False
            elif not (wanted_values & actual_values):
                return False
    # Every mandatory manifest condition must survive on the attached Allow;
    # accepting only a subset would turn a scoped contract into a broad grant.
    return not require_required or not required or matched_keys >= set(required)


def _request_context(resource: str, required: dict[str, Any] | None) -> dict[str, Any]:
    """Build the reviewed request context used for policy-condition checks."""
    context = dict(required or {})
    parts = resource.split(":")
    if len(parts) >= 6:
        context.setdefault("aws:RequestedRegion", parts[3] or "us-east-1")
        context.setdefault("aws:ResourceRegion", parts[3] or "us-east-1")
        context.setdefault("aws:ResourceAccount", parts[4])
    context.setdefault("aws:RequestedRegion", "us-east-1")
    context.setdefault("aws:ResourceRegion", "us-east-1")
    if ":alias/" in resource:
        context.setdefault("kms:RequestAlias", "alias/" + resource.split(":alias/", 1)[1])
    return context


def _request_context_with_alias(
    action: str,
    resource: str,
    required: dict[str, Any] | None,
    paired_alias: str | None = None,
) -> dict[str, Any]:
    """Add request-only values for multi-resource KMS alias operations.

    KMS evaluates ``CreateAlias`` once for the alias ARN and once for the
    target-key ARN. The latter has no alias in its resource ARN, but the same
    request still carries ``kms:RequestAlias``. Preserve that paired value so
    a target-key Deny cannot be missed by the preflight check.
    """
    context = _request_context(resource, required)
    if action.lower() == "kms:createalias" and paired_alias:
        context.setdefault("kms:RequestAlias", paired_alias)
    return context


def _resource_samples(resource: str) -> list[str]:
    """Expand a reviewed pattern into representative concrete resources.

    Checking one synthetic value is insufficient for a wildcard contract: a
    policy scoped to ``aether-contract-check`` would otherwise appear to cover
    ``aether-*``. Multiple stable probes catch that narrowing while remaining
    deterministic and offline. A credentialed plan still supplies the real
    resolved resources to the hosted checker.
    """
    if resource == "*":
        return [resource]
    if "*" not in resource and "?" not in resource:
        return [resource]
    probes = ("contract-check", "backend", "worker", "aether-backend", "aether-worker")
    return [resource.replace("*", probe) for probe in probes]


def _resource_pattern_covers(actual: str, reviewed: str) -> bool:
    """Return whether an IAM resource pattern covers the reviewed pattern.

    A literal policy ARN cannot satisfy a reviewed wildcard contract. For
    wildcard ARNs, compare the stable prefix and suffix in addition to the
    concrete probes; this prevents a one-name policy from passing a contract
    that governs a family of Terraform-managed resources.
    """
    if reviewed == "*":
        return actual == "*"
    if "*" not in reviewed and "?" not in reviewed:
        return fnmatch.fnmatchcase(reviewed, actual)
    if actual == "*":
        return True
    if "*" not in actual and "?" not in actual:
        return False
    reviewed_prefix = reviewed.split("*", 1)[0]
    reviewed_suffix = reviewed.rsplit("*", 1)[1]
    actual_prefix = actual.split("*", 1)[0]
    actual_suffix = actual.rsplit("*", 1)[1]
    return reviewed_prefix.startswith(actual_prefix) and reviewed_suffix.endswith(actual_suffix)


def _operation_is_covered(
    statement: dict[str, Any],
    action: str,
    resource: str,
    conditions: dict[str, Any] | None,
    *,
    require_required: bool = True,
) -> bool:
    if statement.get("Effect") != "Allow":
        return False
    if not _statement_matches_action(statement, action):
        return False
    samples = _resource_samples(resource)
    if not all(_statement_matches_resource(statement, sample) for sample in samples):
        return False
    if "Resource" in statement and not any(
        _resource_pattern_covers(pattern, resource)
        for pattern in _statement_resources(statement)
    ):
        return False
    # For an Allow, compare only the conditions explicitly required by the
    # reviewed manifest. The derived request context is for Deny evaluation;
    # requiring it here would reject valid scoped Allows that do not repeat
    # provider-populated region/account keys.
    return _conditions_compatible(
        statement.get("Condition"), conditions, require_required=require_required
    )


def _operation_is_denied(
    statement: dict[str, Any],
    action: str,
    resource: str,
    conditions: dict[str, Any] | None = None,
    *,
    request_context: dict[str, Any] | None = None,
) -> bool:
    if statement.get("Effect") != "Deny":
        return False
    if not _statement_matches_action(statement, action):
        return False
    # A wildcard reviewed resource is a set of independently managed objects:
    # one explicit Deny on any concrete member makes the reviewed operation
    # unsafe even when other representative members are allowed.
    overlaps = any(
        _statement_matches_resource(statement, sample)
        for sample in _resource_samples(resource)
    )
    if not overlaps:
        return False
    # An unsupported condition operator cannot be proven non-applicable. Treat
    # it as a matching deny rather than allowing the preflight to pass and
    # discovering the denial only after Terraform has mutated resources.
    if _has_unsupported_condition_operator(statement.get("Condition")):
        return True
    return _conditions_compatible(
        statement.get("Condition"), request_context or _request_context(resource, conditions)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role-arn", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    role_name = role_name_from_arn(args.role_arn)
    if role_name != "AetherStagingDeploy":
        fail(f"effective policy check must target AetherStagingDeploy, not {role_name}")
    manifest = yaml.safe_load(Path(args.manifest).read_text()) or {}
    statements = manifest.get("statements")
    if manifest.get("profile") != "staging" or not isinstance(statements, list):
        fail("staging apply IAM manifest is malformed")
    account_id = args.role_arn.split(":", 4)[4].split(":", 1)[0]
    required_operations: list[tuple[str, str, dict[str, Any] | None]] = []
    paired_alias: str | None = None
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        resources = _as_list(statement.get("resource", "*"))
        conditions = statement.get("conditions")
        for action in statement.get("actions") or []:
            if not isinstance(action, str):
                continue
            for resource in resources:
                if isinstance(resource, str):
                    if action.lower() in GLOBAL_READ_ACTIONS and resource != "*":
                        fail(f"{action} must be validated with the account-level resource scope")
                    if action.lower() == "kms:createalias" and ":alias/" in resource:
                        alias_sample = _resource_samples(resource)[0]
                        paired_alias = "alias/" + alias_sample.split(":alias/", 1)[1]
                    required_operations.append(
                        (action, resource.replace("${account_id}", account_id), conditions)
                    )
    if not required_operations:
        fail("staging apply IAM manifest declares no actions")
    effective, policy_names = load_effective_statements(role_name)
    boundary, boundary_arn = load_permissions_boundary_statements(role_name)
    if boundary_arn:
        policy_names.append(f"boundary:{boundary_arn}")
    all_statements = effective + boundary
    denied = sorted(
        f"{action} on {resource}"
        for action, resource, conditions in required_operations
        if any(
            _operation_is_denied(
                statement,
                action,
                resource,
                conditions,
                request_context=_request_context_with_alias(
                    action, resource, conditions, paired_alias
                ),
            )
            for statement in all_statements
        )
    )
    if denied:
        fail("AetherStagingDeploy has an explicit Deny for reviewed operations: " + "; ".join(denied))
    missing = sorted(
        f"{action} on {resource}"
        for action, resource, conditions in required_operations
        if not any(
            _operation_is_covered(statement, action, resource, conditions)
            for statement in effective
        )
        or (
            boundary
            and not any(
                _operation_is_covered(
                    statement,
                    action,
                    resource,
                    conditions,
                    require_required=False,
                )
                for statement in boundary
            )
        )
    )
    if missing:
        fail(
            "AetherStagingDeploy effective policy does not cover reviewed operations: "
            + ", ".join(missing)
        )
    if not any(name.endswith("AetherStagingApplyMissingOps") for name in policy_names):
        fail("AetherStagingApplyMissingOps is not attached to AetherStagingDeploy")
    print(
        f"Effective staging apply policy covers {len(required_operations)} reviewed operations across {len(policy_names)} attached policies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
