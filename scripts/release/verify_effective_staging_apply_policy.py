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
import re
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


def _backend_name(value: str, kind: str) -> str:
    """Validate a non-secret Terraform backend name before ARN rendering."""
    if kind == "bucket":
        valid = re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", value)
    else:
        valid = re.fullmatch(r"[A-Za-z0-9_.-]{3,255}", value)
    if not valid:
        fail(f"Terraform state {kind} name is not a valid AWS resource name")
    return value


def _resolve_manifest_value(value: Any, account_id: str) -> Any:
    """Resolve account placeholders in resources and condition values."""
    if isinstance(value, str):
        return value.replace("${account_id}", account_id)
    if isinstance(value, list):
        return [_resolve_manifest_value(item, account_id) for item in value]
    if isinstance(value, dict):
        return {
            key: _resolve_manifest_value(item, account_id)
            for key, item in value.items()
        }
    return value


def _render_reviewed_resource(
    resource: str,
    manifest: dict[str, Any],
    account_id: str,
    state_bucket: str | None,
    state_lock_table: str | None,
    state_profile: str | None,
) -> str:
    """Resolve account and the approved runtime state-backend names."""
    rendered = resource.replace("${account_id}", account_id)
    scope = manifest.get("scope")
    if scope in {"terraform-state-backend", "terraform-plan-state-backend"}:
        canonical_bucket = manifest.get("state_bucket")
        if isinstance(canonical_bucket, str) and state_bucket:
            bucket = _backend_name(state_bucket, "bucket")
            rendered = rendered.replace(
                f"arn:aws:s3:::{canonical_bucket}", f"arn:aws:s3:::{bucket}"
            )
        canonical_lock = manifest.get("state_lock_table")
        if isinstance(canonical_lock, str) and state_lock_table:
            lock_table = _backend_name(state_lock_table, "lock table")
            rendered = rendered.replace(
                f":table/{canonical_lock}", f":table/{lock_table}"
            )
        if state_profile:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", state_profile):
                fail("Terraform state profile is not a valid profile name")
            rendered = rendered.replace("/profiles/*", f"/profiles/{state_profile}/*")
    return rendered


def _manifest_operations(
    path: Path,
    account_id: str,
    expected_role: str,
    *,
    primary: bool,
    state_bucket: str | None,
    state_lock_table: str | None,
    state_profile: str | None,
) -> tuple[list[tuple[str, str, dict[str, Any] | None]], dict[str, Any]]:
    """Load one reviewed contract without silently broadening its scope."""
    manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    statements = manifest.get("statements")
    if not isinstance(statements, list):
        fail(f"IAM manifest {path} has no statements list")
    if manifest.get("profile") not in (None, "staging"):
        fail(f"IAM manifest {path} is not a staging contract")
    declared_role = manifest.get("role")
    if declared_role is not None and declared_role != expected_role:
        fail(f"IAM manifest {path} targets {declared_role}, not {expected_role}")
    if primary and declared_role != expected_role:
        fail(f"primary IAM manifest must target {expected_role}")
    operations: list[tuple[str, str, dict[str, Any] | None]] = []
    for statement in statements:
        if not isinstance(statement, dict):
            fail(f"IAM manifest {path} contains a non-object statement")
        resources = _as_list(statement.get("resource", "*"))
        conditions = _resolve_manifest_value(statement.get("conditions"), account_id)
        for action in statement.get("actions") or []:
            if not isinstance(action, str):
                fail(f"IAM manifest {path} contains a non-string action")
            for resource in resources:
                if isinstance(resource, str):
                    if action.lower() in GLOBAL_READ_ACTIONS and resource != "*":
                        fail(f"{action} must be validated with the account-level resource scope")
                    operations.append(
                        (
                            action,
                            _render_reviewed_resource(
                                resource,
                                manifest,
                                account_id,
                                state_bucket,
                                state_lock_table,
                                state_profile,
                            ),
                            conditions,
                        )
                    )
    return operations, manifest


def _statement_actions(statement: dict[str, Any]) -> list[str]:
    return [value for value in _as_list(statement.get("Action", [])) if isinstance(value, str)]


def _action_patterns_overlap(left: str, right: str) -> bool:
    """Return whether two IAM action patterns can describe one action."""
    left = left.lower()
    right = right.lower()
    return fnmatch.fnmatchcase(left, right) or fnmatch.fnmatchcase(right, left)


def _action_pattern_is_within(actual: str, reviewed: str) -> bool:
    """Return whether an attached action pattern is no broader than reviewed."""
    actual = actual.lower()
    reviewed = reviewed.lower()
    if actual == reviewed or reviewed == "*":
        return True
    if "?" in actual or "?" in reviewed:
        # The reviewed contracts use prefix wildcards. Refuse a pattern form
        # this checker cannot prove safe instead of treating it as scoped.
        return False
    if "*" not in actual:
        return fnmatch.fnmatchcase(actual, reviewed)
    if "*" not in reviewed:
        return False
    actual_prefix, actual_suffix = actual.split("*", 1)
    reviewed_prefix, reviewed_suffix = reviewed.split("*", 1)
    return actual_prefix.startswith(reviewed_prefix) and actual_suffix.endswith(reviewed_suffix)


def _forbidden_action_errors(
    statements: list[dict[str, Any]],
    forbidden_actions: list[str],
    required_actions: set[str],
) -> list[str]:
    """Find identity-policy Allows that violate the manifest deny contract.

    A required operation is allowed when it appears as the exact reviewed
    action (for example ``kms:Decrypt`` alongside a broad ``kms:*`` forbidden
    marker). A wildcard or broader attached Allow is still rejected, because it
    would grant capabilities outside the reviewed operation set.
    """
    errors: set[str] = set()
    required = {action.lower() for action in required_actions}
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        actions = _statement_actions(statement)
        not_actions = [
            value
            for value in _as_list(statement.get("NotAction", []))
            if isinstance(value, str)
        ]
        for forbidden in forbidden_actions:
            if actions:
                for action in actions:
                    if (
                        action.lower() not in required
                        and _action_patterns_overlap(action, forbidden)
                    ):
                        errors.add(f"{action} overlaps forbidden {forbidden}")
            elif not_actions and _statement_matches_action(statement, forbidden):
                errors.add(
                    f"NotAction {','.join(not_actions)} leaves forbidden {forbidden} allowed"
                )
    return sorted(errors)


def _resource_pattern_is_within(actual: str, reviewed: str) -> bool:
    """Return whether an attached resource pattern is no broader than reviewed."""
    if reviewed == "*":
        return True
    if actual == "*":
        return False
    if "?" in actual or "?" in reviewed:
        # The reviewed contracts use prefix wildcards. Refuse a pattern form
        # this checker cannot prove safe instead of treating it as scoped.
        return False
    if "*" not in actual:
        return fnmatch.fnmatchcase(actual, reviewed)
    if "*" not in reviewed:
        return False
    actual_prefix, actual_suffix = actual.split("*", 1)
    reviewed_prefix, reviewed_suffix = reviewed.split("*", 1)
    return actual_prefix.startswith(reviewed_prefix) and actual_suffix.endswith(reviewed_suffix)


def _condition_scope_is_within(actual: Any, reviewed: dict[str, Any] | None) -> bool:
    """Return whether attached conditions preserve the reviewed scope."""
    if _has_unsupported_condition_operator(actual):
        return False
    if not actual:
        return not reviewed
    if not isinstance(actual, dict):
        return False
    if not reviewed:
        # Additional supported conditions narrow an exact required action and
        # are therefore safe; unsupported operators failed closed above.
        return True
    actual_entries = _condition_entries(actual)
    for required_operator, key, wanted_values in _condition_entries(reviewed):
        if not any(
            actual_key == key
            and (required_operator is None or actual_operator == required_operator)
            and actual_values
            and actual_values <= wanted_values
            for actual_operator, actual_key, actual_values in actual_entries
        ):
            return False
    return True


def _reviewed_operation_covers(
    candidate: tuple[str, str, dict[str, Any] | None],
    target: tuple[str, str, dict[str, Any] | None],
) -> bool:
    """Return whether one reviewed operation already subsumes another."""
    candidate_action, candidate_resource, candidate_conditions = candidate
    target_action, target_resource, target_conditions = target
    if not _action_pattern_is_within(target_action, candidate_action):
        return False
    if not _resource_pattern_is_within(target_resource, candidate_resource):
        return False
    if not candidate_conditions:
        return True
    return _condition_scope_is_within(target_conditions, candidate_conditions)


def _required_action_scope_errors(
    statements: list[dict[str, Any]],
    required_operations: list[tuple[str, str, dict[str, Any] | None]],
) -> list[str]:
    """Find Allows whose action/resource/condition scope exceeds the review."""
    reviewed_operations: list[tuple[str, str, dict[str, Any] | None]] = []
    for action, resource, conditions in required_operations:
        reviewed_operations.append((action, resource, conditions))

    errors: set[str] = set()
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        not_actions = [
            value
            for value in _as_list(statement.get("NotAction", []))
            if isinstance(value, str)
        ]
        if not_actions:
            errors.add("Allow uses NotAction outside reviewed action scope")
            continue
        resources = _statement_resources(statement)
        for action in _statement_actions(statement):
            scopes = [
                (reviewed_resource, conditions)
                for reviewed_action, reviewed_resource, conditions in reviewed_operations
                if _action_pattern_is_within(action, reviewed_action)
            ]
            if not scopes:
                errors.add(f"{action} grants an action outside its reviewed scope")
                continue
            if "NotResource" in statement:
                errors.add(f"{action} uses NotResource outside reviewed scope")
                continue
            # Resource and condition restrictions are one reviewed scope. Do
            # not match a resource from one scope with conditions from another
            # (for example, an ECS task role with a Lambda service condition).
            if not all(
                any(
                    _resource_pattern_is_within(resource, reviewed)
                    and _condition_scope_is_within(statement.get("Condition"), conditions)
                    for reviewed, conditions in scopes
                )
                for resource in resources
            ):
                errors.add(f"{action} grants a resource/condition pair broader than its reviewed scope")
    return sorted(errors)


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
        "ForAnyValue:StringLike",
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


def _condition_entries(condition: Any) -> list[tuple[str | None, str, set[str]]]:
    """Normalize flat manifest conditions and AWS operator maps."""
    if not isinstance(condition, dict):
        return []
    nested = bool(condition) and all(
        operator in SUPPORTED_CONDITION_OPERATORS and isinstance(entries, dict)
        for operator, entries in condition.items()
    )
    if nested:
        return [
            (operator, key, {str(value) for value in _as_list(raw_value)})
            for operator, entries in condition.items()
            for key, raw_value in entries.items()
        ]
    return [
        (None, key, {str(value) for value in _as_list(raw_value)})
        for key, raw_value in condition.items()
    ]


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
    required_entries = _condition_entries(required)
    matched_entries: set[tuple[str | None, str]] = set()
    for operator, entries in actual.items():
        if operator not in SUPPORTED_CONDITION_OPERATORS:
            return False
        if not isinstance(entries, dict):
            return False
        for key, actual_value in entries.items():
            candidates = [
                (required_operator, required_key, wanted_values)
                for required_operator, required_key, wanted_values in required_entries
                if required_key == key
                and (required_operator is None or required_operator == operator)
            ]
            if not candidates:
                return False
            actual_values = {str(v) for v in _as_list(actual_value)}
            matching = next(
                (
                    (required_operator, required_key, wanted_values)
                    for required_operator, required_key, wanted_values in candidates
                    if (
                        any(
                            fnmatch.fnmatchcase(wanted_value, actual_pattern)
                            for wanted_value in wanted_values
                            for actual_pattern in actual_values
                        )
                        if operator in {"StringLike", "ForAnyValue:StringLike", "ArnLike"}
                        else bool(wanted_values & actual_values)
                    )
                ),
                None,
            )
            if matching is None:
                return False
            matched_entries.add((matching[0], matching[1]))
    # Every mandatory manifest condition must survive on the attached Allow;
    # accepting only a subset would turn a scoped contract into a broad grant.
    if not require_required or not required_entries:
        return True
    return matched_entries >= {
        (required_operator, required_key)
        for required_operator, required_key, _ in required_entries
    }


def _request_context(resource: str, required: dict[str, Any] | None) -> dict[str, Any]:
    """Build the reviewed request context used for policy-condition checks."""
    context = {
        key: value
        for _operator, key, values in _condition_entries(required)
        for value in [next(iter(values), "")]
    }
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
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--supplemental-manifest",
        action="append",
        type=Path,
        default=[],
        help="additional reviewed contract realized by the same role; may be repeated",
    )
    parser.add_argument(
        "--state-bucket",
        help="runtime Terraform state bucket used when rendering a state manifest",
    )
    parser.add_argument(
        "--state-lock-table",
        help="runtime Terraform state lock table used when rendering a state manifest",
    )
    parser.add_argument(
        "--state-profile",
        help="profile whose state path is being checked (for example, staging)",
    )
    parser.add_argument(
        "--expected-role",
        default="AetherStagingDeploy",
        help="role name declared by the manifest (default: AetherStagingDeploy)",
    )
    parser.add_argument(
        "--required-policy-suffix",
        default="AetherStagingApplyMissingOps",
        help="inline/managed policy suffix that must be attached; empty disables this check",
    )
    args = parser.parse_args()

    role_name = role_name_from_arn(args.role_arn)
    if role_name != args.expected_role:
        fail(f"effective policy check must target {args.expected_role}, not {role_name}")
    account_id = args.role_arn.split(":", 4)[4].split(":", 1)[0]
    primary_operations, manifest = _manifest_operations(
        args.manifest,
        account_id,
        args.expected_role,
        primary=True,
        state_bucket=args.state_bucket,
        state_lock_table=args.state_lock_table,
        state_profile=args.state_profile,
    )
    required_operations = list(primary_operations)
    supplemental_names: list[str] = []
    for supplemental_path in args.supplemental_manifest:
        supplemental_operations, _supplemental_manifest = _manifest_operations(
            supplemental_path,
            account_id,
            args.expected_role,
            primary=False,
            state_bucket=args.state_bucket,
            state_lock_table=args.state_lock_table,
            state_profile=args.state_profile,
        )
        required_operations.extend(
            operation
            for operation in supplemental_operations
            if not any(
                _reviewed_operation_covers(primary_operation, operation)
                for primary_operation in primary_operations
            )
        )
        supplemental_names.append(str(supplemental_path))
    paired_alias: str | None = None
    if not required_operations:
        fail("IAM manifests declare no actions")
    for action, resource, _conditions in required_operations:
        if action.lower() == "kms:createalias" and ":alias/" in resource:
            alias_sample = _resource_samples(resource)[0]
            paired_alias = "alias/" + alias_sample.split(":alias/", 1)[1]
    forbidden_actions = manifest.get("forbidden_actions", [])
    if forbidden_actions is None:
        forbidden_actions = []
    if not isinstance(forbidden_actions, list) or not all(
        isinstance(action, str) and action for action in forbidden_actions
    ):
        fail("staging apply manifest forbidden_actions must be a list of strings")
    effective, policy_names = load_effective_statements(role_name)
    boundary, boundary_arn = load_permissions_boundary_statements(role_name)
    if boundary_arn:
        policy_names.append(f"boundary:{boundary_arn}")
    all_statements = effective + boundary
    forbidden = _forbidden_action_errors(
        effective,
        forbidden_actions,
        {action for action, _resource, _conditions in required_operations},
    )
    if forbidden:
        fail(
            f"{args.expected_role} effective policy grants forbidden actions: "
            + "; ".join(forbidden)
        )
    overbroad_required = _required_action_scope_errors(effective, required_operations)
    if overbroad_required:
        fail(
            f"{args.expected_role} effective policy grants required actions outside reviewed scope: "
            + "; ".join(overbroad_required)
        )
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
            f"{args.expected_role} effective policy does not cover reviewed operations: "
            + ", ".join(missing)
        )
    if args.required_policy_suffix and not any(
        name.endswith(args.required_policy_suffix) for name in policy_names
    ):
        fail(
            f"{args.required_policy_suffix} is not attached to {args.expected_role}"
        )
    print(
        f"Effective {args.expected_role} policy covers {len(required_operations)} reviewed operations across {len(policy_names)} attached policies"
        + (f" and {len(supplemental_names)} supplemental contracts." if supplemental_names else ".")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
