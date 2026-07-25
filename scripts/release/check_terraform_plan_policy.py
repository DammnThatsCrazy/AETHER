#!/usr/bin/env python3
"""Prove a Terraform plan actually excludes the resources its profile forbids.

check_cost_policy_terraform.py reads `profiles.tf` and statically evaluates the
local booleans that GATE each heavy module. That proves the Terraform *encodes*
the policy. It does not prove that any particular plan *realises* it: a local
can be correct while a module is wired to the wrong gate, a resource can be
added outside every gated module, or a module can be instantiated twice.

This validator closes that gap. It consumes real `terraform show -json` output,
enumerates every managed resource and the action planned for it, maps each one
onto the canonical policy keys in config/deployment_profiles.yaml using the
matchers in config/terraform_resource_contracts.yaml, and asserts:

  * every `forbidden_resources` key has ZERO actively-planned instances;
  * every `required_resources` key is present at its contracted cardinality;
  * the ECS service count matches config/runtime_deployment.yaml exactly, so a
    collapsed worker topology cannot pass as a dedicated one;
  * the network egress mode in the plan agrees with the NAT gateway count the
    profile is contracted to have;
  * static SPA origins exist wherever the runtime matrix declares them;
  * no dedicated ML service, ECS-hosted frontend or legacy RDS instance in a
    cost-capped profile;
  * staging compute is not pinned always-on.

FAIL-CLOSED RULES
  Silence must never read as success, so two conditions fail the gate outright
  even though nothing "forbidden" was found:

  1. An actively-planned resource of an EXPENSIVE type that appears in no
     matcher anywhere in the contracts file. "Expensive" is derived from
     config/aws_price_book.yaml -> fixed_resources (every type the cost model
     treats as a fixed monthly commitment), plus CURATED_EXPENSIVE_TYPES for
     heavyweight managed services the price book has not needed yet. Such a
     resource is reported in the inventory's `unmapped_expensive` list.
  2. A canonical key in the profile's cost_policy that has no matcher in the
     contracts file. A policy nobody can check is not a policy.

  A weaker third condition is reported as a WARNING rather than a failure: a
  resource of a covered expensive type that no individual rule matched (for
  example a KMS key in a module no rule is scoped to). The type has an opinion
  attached to it somewhere, so this is drift, not a blind spot.

DESTROY IS NOT A VIOLATION
  A resource whose only planned action is `delete` is on its way out and does
  not count against a forbidden key. `no-op` (retained), `update`, and any
  replace (`delete`+`create`) do count -- they all leave the resource existing
  and billing. This matches `_will_exist()` in check_cost_model.py.

FARGATE SIZING
  Terraform puts `cpu`/`memory` on `aws_ecs_task_definition`, never on
  `aws_ecs_service`. check_cost_model.py prices Fargate from the SERVICE entry
  and hard-errors on a service it cannot size, which would make every ECS
  service unpriceable. This validator therefore RESOLVES the owning task
  definition for each service and copies `cpu`/`memory` onto the service's
  `values`. Both entries remain in the inventory (the task definition keeps its
  own sizing and is zero-cost in the price book); consumers must read sizing
  from the `aws_ecs_service` entry. Every resolution is recorded under the
  inventory's top-level `fargate_sizing_resolution` so the provenance of a
  priced number is auditable. An actively-planned service whose sizing cannot
  be resolved fails the gate rather than travelling downstream as a zero.

OUTPUTS (written to --out-dir, default `artifacts/`)
  profile-resource-inventory.json   canonical machine-readable inventory
                                    (schema_version 1) -- consumed by
                                    check_cost_model.py --inventory
  profile-resource-inventory.md     the same inventory, human-readable
  profile-policy-result.json        per-check machine-readable verdicts
  profile-policy-result.md          the same verdicts, human-readable

Usage:
  python scripts/release/check_terraform_plan_policy.py \\
      --profile production-lean --plan-json path/to/plan.json
  python scripts/release/check_terraform_plan_policy.py \\
      --profile staging --plan-json plan.json --out-dir artifacts/staging

Exit codes:
  0  the plan satisfies the profile's cost policy
  1  policy violation -- a forbidden resource is actively planned, a required
     resource is missing or miscounted, or a fail-closed rule tripped
  2  the check could not run -- missing/unparseable plan or contracts, unknown
     profile, profile declares no cost_policy, unsupported plan format_version
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

PROFILES_YAML = "config/deployment_profiles.yaml"
CONTRACTS_YAML = "config/terraform_resource_contracts.yaml"
RUNTIME_YAML = "config/runtime_deployment.yaml"
PRICE_BOOK_YAML = "config/aws_price_book.yaml"

INVENTORY_SCHEMA_VERSION = 1

# The canonical artifact name three siblings and two workflows read by path.
INVENTORY_JSON = "profile-resource-inventory.json"
INVENTORY_MD = "profile-resource-inventory.md"
RESULT_JSON = "profile-policy-result.json"
RESULT_MD = "profile-policy-result.md"
DEFAULT_OUT_DIR = "artifacts"

# Exit code for "the gate could not run", distinct from "the gate failed".
EXIT_USAGE = 2

# `terraform show -json` plan format versions this parser understands. The
# document shape below (planned_values.root_module.child_modules +
# resource_changes[].change.actions) has been stable across all of them.
SUPPORTED_PLAN_FORMATS = {"0.1", "0.2", "1.0", "1.1", "1.2"}

# Heavyweight managed services that carry a material standing bill and are NOT
# in config/aws_price_book.yaml -> fixed_resources (the price book only prices
# what Aether's roots actually provision). Listed here so that introducing one
# trips the fail-closed rule instead of sliding past an inventory that has no
# opinion about it. This list only ever grows.
CURATED_EXPENSIVE_TYPES = frozenset({
    "aws_opensearch_domain",
    "aws_opensearchserverless_collection",
    "aws_elasticsearch_domain",
    "aws_redshift_cluster",
    "aws_redshiftserverless_workgroup",
    "aws_emr_cluster",
    "aws_eks_cluster",
    "aws_eks_node_group",
    "aws_eks_fargate_profile",
    "aws_docdb_cluster",
    "aws_docdb_cluster_instance",
    "aws_memorydb_cluster",
    "aws_keyspaces_table",
    "aws_qldb_ledger",
    "aws_timestreamwrite_table",
    "aws_dms_replication_instance",
    "aws_mq_broker",
    "aws_kinesis_stream",
    "aws_kinesisanalyticsv2_application",
    "aws_sagemaker_endpoint",
    "aws_sagemaker_notebook_instance",
    "aws_fsx_lustre_file_system",
    "aws_fsx_windows_file_system",
    "aws_fsx_ontap_file_system",
    "aws_efs_file_system",
    "aws_transfer_server",
    "aws_directory_service_directory",
    "aws_workspaces_workspace",
    "aws_appstream_fleet",
    "aws_networkfirewall_firewall",
    "aws_ec2_client_vpn_endpoint",
    "aws_globalaccelerator_accelerator",
    "aws_dx_connection",
    "aws_cloudhsm_v2_cluster",
    "aws_rds_global_cluster",
    "aws_neptune_cluster",
    "aws_autoscaling_group",
    "aws_spot_fleet_request",
    "aws_batch_compute_environment",
})

# Resource types that constitute "compute" for the always-on staging check.
COMPUTE_TYPES = frozenset({
    "aws_ecs_service", "aws_instance", "aws_autoscaling_group",
})


class PlanError(Exception):
    """The plan document could not be read as a Terraform plan."""


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def _strip_index(address: str) -> str:
    """Drop every `[...]` index from a module address.

    `module.msk[0].module.inner["a"]` -> `module.msk.module.inner`. Contract
    matchers are written without indices, so both sides are normalised before
    comparison.
    """
    out: list[str] = []
    depth = 0
    for ch in address:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _walk_planned_values(module: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Flatten planned_values into {address: {module_address, values, ...}}."""
    found: dict[str, dict[str, Any]] = {}
    module_address = str(module.get("address") or "")
    for resource in module.get("resources") or []:
        if resource.get("mode", "managed") != "managed":
            continue
        address = str(resource.get("address") or "")
        if not address:
            continue
        found[address] = {
            "module_address": module_address,
            "type": str(resource.get("type") or ""),
            "name": str(resource.get("name") or ""),
            "index": resource.get("index"),
            "values": resource.get("values") or {},
        }
    for child in module.get("child_modules") or []:
        found.update(_walk_planned_values(child))
    return found


def enumerate_resources(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one normalised entry per managed resource in the plan.

    Built from `resource_changes` (the only place planned ACTIONS live) and
    back-filled from `planned_values` (the only place values live for a
    resource that has no change entry). Data sources are excluded: they
    provision nothing and cost nothing.
    """
    planned = _walk_planned_values((plan.get("planned_values") or {}).get("root_module") or {})

    resources: dict[str, dict[str, Any]] = {}
    for change in plan.get("resource_changes") or []:
        if change.get("mode", "managed") != "managed":
            continue
        address = str(change.get("address") or "")
        if not address:
            continue
        detail = change.get("change") or {}
        actions = [str(a) for a in (detail.get("actions") or [])]
        after = detail.get("after")
        before = detail.get("before")
        # A pure delete carries its state in `before`; everything else in
        # `after`. Keeping the values either way means a destroy plan can still
        # be described precisely in the inventory.
        values = after if isinstance(after, dict) else (before if isinstance(before, dict) else {})
        # planned_values fills gaps `after` leaves behind. It never overrides:
        # `after` is the authoritative post-apply shape.
        base = dict((planned.get(address) or {}).get("values") or {})
        base.update({k: v for k, v in (values or {}).items() if v is not None})
        resources[address] = {
            "address": address,
            "module_address": str(change.get("module_address") or ""),
            "type": str(change.get("type") or ""),
            "name": str(change.get("name") or ""),
            "index": change.get("index"),
            "actions": actions or ["no-op"],
            "values": base,
        }

    # Resources present in planned_values but absent from resource_changes are
    # unchanged by this plan. They still exist and still bill.
    for address, detail in planned.items():
        if address in resources:
            continue
        resources[address] = {
            "address": address,
            "module_address": detail["module_address"],
            "type": detail["type"],
            "name": detail["name"],
            "index": detail["index"],
            "actions": ["no-op"],
            "values": dict(detail["values"]),
        }

    return [resources[a] for a in sorted(resources)]


def is_active(resource: dict[str, Any]) -> bool:
    """True unless the plan does nothing but destroy this resource.

    Mirrors `_will_exist()` in check_cost_model.py: a resource being destroyed
    is not a violation; one being created, replaced, updated or retained is.
    """
    actions = {a for a in (resource.get("actions") or []) if a}
    if not actions:
        return True
    return actions != {"delete"}


# ---------------------------------------------------------------------------
# Fargate sizing resolution
# ---------------------------------------------------------------------------

def resolve_fargate_sizing(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Copy task-definition cpu/memory onto each aws_ecs_service entry.

    check_cost_model.py prices `aws_ecs_service` with pricing_model `fargate`
    and reads `cpu`/`memory`/`desired_count` straight off the service's plan
    values. Terraform only ever puts cpu/memory on the task definition, so
    without this step every service is an unpriced hard error.

    Returns (resolution records, addresses of services still unsized).
    """
    services = [r for r in resources if r["type"] == "aws_ecs_service"]
    task_defs = [r for r in resources if r["type"] == "aws_ecs_task_definition"]
    records: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for service in services:
        values = service["values"]
        if values.get("cpu") is not None and values.get("memory") is not None:
            records.append({
                "service": service["address"], "source": "service",
                "task_definition": None,
                "cpu": values.get("cpu"), "memory": values.get("memory"),
            })
            continue

        match = _match_task_definition(service, task_defs, services)
        if match is None:
            if is_active(service):
                unresolved.append(service["address"])
            records.append({
                "service": service["address"], "source": "unresolved",
                "task_definition": None, "cpu": None, "memory": None,
            })
            continue

        task_def, how = match
        for key in ("cpu", "memory"):
            if values.get(key) is None and task_def["values"].get(key) is not None:
                values[key] = task_def["values"][key]
        still_missing = values.get("cpu") is None or values.get("memory") is None
        if still_missing and is_active(service):
            unresolved.append(service["address"])
        records.append({
            "service": service["address"],
            "source": "unresolved" if still_missing else f"task_definition:{how}",
            "task_definition": task_def["address"],
            "cpu": values.get("cpu"), "memory": values.get("memory"),
        })

    return records, unresolved


def _match_task_definition(
    service: dict[str, Any],
    task_defs: list[dict[str, Any]],
    services: list[dict[str, Any]],
) -> tuple[dict[str, Any], str] | None:
    """Find the task definition a service runs, most specific strategy first."""
    module = service["module_address"]
    same_module = [t for t in task_defs if t["module_address"] == module]

    # 1. The service names its task definition outright. At plan time this is
    #    usually an unknown ARN, but a pinned family or an existing service's
    #    resolved ARN both land here.
    reference = service["values"].get("task_definition")
    if isinstance(reference, str) and reference:
        bare = reference.split("/")[-1]
        family = bare.split(":")[0]
        for candidate in task_defs:
            cvals = candidate["values"]
            arn = cvals.get("arn")
            cfamily = cvals.get("family")
            if (isinstance(arn, str) and arn and arn == reference) or (
                isinstance(cfamily, str) and cfamily and cfamily in (family, bare)
            ):
                return candidate, "reference"

    # 2. Same module, same resource name, same for_each/count key. This is the
    #    `aws_ecs_service.runtime_role["x"]` / `aws_ecs_task_definition
    #    .runtime_role["x"]` pairing the ECS module actually uses.
    for candidate in same_module:
        if candidate["name"] == service["name"] and candidate["index"] == service["index"]:
            return candidate, "name_and_index"

    # 3. Same module and same resource name, ignoring the index.
    by_name = [t for t in same_module if t["name"] == service["name"]]
    if len(by_name) == 1:
        return by_name[0], "name"

    # 4. The service's own name value matches a task definition family.
    svc_name = service["values"].get("name")
    if isinstance(svc_name, str) and svc_name:
        by_family = [
            t for t in task_defs
            if isinstance(t["values"].get("family"), str)
            and t["values"]["family"] == svc_name
        ]
        if len(by_family) == 1:
            return by_family[0], "family"

    # 5. One service and one task definition in the module: unambiguous by
    #    exhaustion. Deliberately NOT applied when the module holds several
    #    services -- with 2 services and 1 task definition the likeliest cause
    #    is a MISSING task definition, and guessing would hand the cost model a
    #    confidently wrong size instead of failing closed.
    if len(same_module) == 1 and len(
        [s for s in services if s["module_address"] == module]
    ) == 1:
        return same_module[0], "sole_task_definition"

    return None


# ---------------------------------------------------------------------------
# Contract matchers
# ---------------------------------------------------------------------------

def iter_rules(contracts: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Yield (canonical_key, kind, rule) for every matcher, sub-rules included."""
    out: list[tuple[str, str, dict[str, Any]]] = []
    for kind in ("required_resources", "forbidden_resources"):
        for key, rule in (contracts.get(kind) or {}).items():
            if not isinstance(rule, dict):
                continue
            out.append((key, kind, rule))
            for extra in rule.get("additional_rules") or []:
                if isinstance(extra, dict):
                    out.append((key, kind, extra))
    return out


def contract_types(contracts: dict[str, Any]) -> set[str]:
    """Every Terraform resource type any matcher in the contracts file names."""
    types: set[str] = set()
    for _key, _kind, rule in iter_rules(contracts):
        for res_type in rule.get("resource_types") or []:
            types.add(str(res_type))
    return types


def module_matches(rule_address: Any, resource_module: str) -> bool:
    """True when a resource's module address satisfies a rule's address."""
    if rule_address is None:
        return False
    rule = str(rule_address)
    if rule == "any":
        return True
    if rule == "root":
        return resource_module == ""
    normalised = _strip_index(resource_module)
    return normalised == rule or normalised.startswith(rule + ".")


def rule_matches(rule: dict[str, Any], resource: dict[str, Any]) -> bool:
    """True when one resource is an instance of what a rule describes."""
    types = [str(t) for t in (rule.get("resource_types") or [])]
    if not types or resource["type"] not in types:
        return False
    if not module_matches(rule.get("module_address"), resource["module_address"]):
        return False
    prefixes = [str(p) for p in (rule.get("name_prefixes") or [])]
    if prefixes and not any(resource["name"].startswith(p) for p in prefixes):
        return False
    return True


def parse_cardinality(spec: Any) -> tuple[int, float]:
    """Translate the contract cardinality grammar into (minimum, maximum)."""
    text = str(spec or "").strip()
    if text == "zero":
        return 0, 0
    if text == "at_least_one":
        return 1, math.inf
    if text.startswith("exactly:"):
        try:
            exact = int(text.split(":", 1)[1])
        except ValueError as exc:  # pragma: no cover - contract typo
            raise PlanError(f"unparseable cardinality {spec!r}") from exc
        return exact, exact
    raise PlanError(f"unknown cardinality {spec!r}")


def describe_cardinality(spec: Any) -> str:
    text = str(spec or "").strip()
    if text == "zero":
        return "exactly 0"
    if text == "at_least_one":
        return "at least 1"
    if text.startswith("exactly:"):
        return f"exactly {text.split(':', 1)[1]}"
    return text


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def expensive_types(price_book: dict[str, Any]) -> set[str]:
    """Types whose presence is a standing cost commitment.

    Derived from the price book rather than hand-listed: whatever the cost
    model treats as a FIXED monthly charge is exactly what the shape policy
    must have an opinion about. CURATED_EXPENSIVE_TYPES covers heavyweight
    services the price book has not needed to price yet.
    """
    return set(price_book.get("fixed_resources") or {}) | set(CURATED_EXPENSIVE_TYPES)


def build_inventory(
    profile: str,
    plan: dict[str, Any],
    resources: list[dict[str, Any]],
    contracts: dict[str, Any],
    price_book: dict[str, Any],
    sizing_records: list[dict[str, Any]],
    plan_path: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (inventory document, resources of a covered-but-unmatched type)."""
    rules = iter_rules(contracts)
    covered_types = contract_types(contracts)
    expensive = expensive_types(price_book)

    entries: list[dict[str, Any]] = []
    summary: dict[str, dict[str, Any]] = {}
    unmapped: list[dict[str, Any]] = []
    unmatched_instances: list[dict[str, Any]] = []

    for resource in resources:
        keys: list[str] = []
        for key, _kind, rule in rules:
            if key not in keys and rule_matches(rule, resource):
                keys.append(key)
        entries.append({
            "address": resource["address"],
            "module_address": resource["module_address"],
            "type": resource["type"],
            "name": resource["name"],
            "index": resource["index"],
            "actions": list(resource["actions"]),
            "canonical_keys": keys,
            "values": resource["values"],
        })

        if not is_active(resource):
            continue
        for key in keys:
            bucket = summary.setdefault(key, {"count": 0, "addresses": []})
            bucket["count"] += 1
            bucket["addresses"].append(resource["address"])

        if resource["type"] in expensive:
            if resource["type"] not in covered_types:
                unmapped.append({
                    "address": resource["address"],
                    "type": resource["type"],
                    "module_address": resource["module_address"],
                    "reason": (
                        f"resource type {resource['type']!r} carries fixed cost but no "
                        f"matcher in {CONTRACTS_YAML} names it, so no canonical policy "
                        f"key can allow or forbid it"
                    ),
                })
            elif not keys:
                unmatched_instances.append({
                    "address": resource["address"],
                    "type": resource["type"],
                    "module_address": resource["module_address"],
                })

    # Every canonical key the contracts declare appears in the summary, so a
    # zero is an asserted zero rather than a missing entry a reader must guess at.
    for key, _kind, _rule in rules:
        summary.setdefault(key, {"count": 0, "addresses": []})

    inventory = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "profile": profile,
        "terraform_version": str(plan.get("terraform_version") or ""),
        "resources": entries,
        "canonical_summary": {k: summary[k] for k in sorted(summary)},
        "unmapped_expensive": unmapped,
        # Additive, outside the pinned schema: provenance for downstream readers.
        "plan_format_version": str(plan.get("format_version") or ""),
        "generated_from": plan_path,
        "fargate_sizing_resolution": sizing_records,
    }
    return inventory, unmatched_instances


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _count(summary: dict[str, Any], key: str) -> int:
    return int((summary.get(key) or {}).get("count", 0))


def _addresses(summary: dict[str, Any], key: str) -> list[str]:
    return list((summary.get(key) or {}).get("addresses") or [])


def _record(results: list[dict[str, Any]], name: str, passed: bool,
            detail: str, **extra: Any) -> None:
    entry = {"check": name, "status": "pass" if passed else "fail", "detail": detail}
    entry.update(extra)
    results.append(entry)


def check_contract_coverage(
    r: Reporter, results: list[dict[str, Any]], policy: dict[str, Any],
    contracts: dict[str, Any],
) -> None:
    """Fail closed on a canonical key nobody wrote a matcher for."""
    declared = {key for key, _kind, _rule in iter_rules(contracts)}
    for kind in ("required_resources", "forbidden_resources"):
        for key in policy.get(kind) or []:
            name = f"contract_coverage.{kind}.{key}"
            if key in declared:
                r.ok(f"{key}: matcher present in {CONTRACTS_YAML}")
                _record(results, name, True, f"{key} has a matcher")
            else:
                message = (
                    f"{key}: declared under {kind} in {PROFILES_YAML} but no matcher "
                    f"exists in {CONTRACTS_YAML}; the policy cannot be checked and "
                    f"must not be assumed satisfied"
                )
                r.fail(message)
                _record(results, name, False, message)


def check_forbidden(
    r: Reporter, results: list[dict[str, Any]], policy: dict[str, Any],
    contracts: dict[str, Any], summary: dict[str, Any],
    resources: list[dict[str, Any]],
) -> None:
    """Every forbidden key must have zero actively-planned instances."""
    forbidden_rules = contracts.get("forbidden_resources") or {}
    for key in policy.get("forbidden_resources") or []:
        rule = forbidden_rules.get(key)
        name = f"forbidden.{key}"
        if not isinstance(rule, dict):
            continue  # already reported by check_contract_coverage
        if rule.get("not_plan_checkable"):
            continue  # handled by check_always_on_staging_compute
        count = _count(summary, key)
        addresses = _addresses(summary, key)
        if count == 0:
            destroying = [
                res["address"] for res in resources
                if not is_active(res)
                and any(rule_matches(sub, res)
                        for k, _kind, sub in iter_rules(contracts) if k == key)
            ]
            suffix = f" ({len(destroying)} being destroyed)" if destroying else ""
            r.ok(f"forbidden {key}: 0 actively-planned instances{suffix}")
            _record(results, name, True, f"{key}: 0 actively-planned instances",
                    count=0, destroying=destroying)
        else:
            message = (
                f"forbidden {key}: {count} actively-planned instance(s) in a "
                f"{policy['_profile']} plan -- {', '.join(addresses[:6])}"
            )
            r.fail(message)
            _record(results, name, False, message, count=count, addresses=addresses)


def check_required(
    r: Reporter, results: list[dict[str, Any]], policy: dict[str, Any],
    contracts: dict[str, Any], summary: dict[str, Any],
) -> None:
    """Every required key must be present at its contracted cardinality."""
    required_rules = contracts.get("required_resources") or {}
    for key in policy.get("required_resources") or []:
        rule = required_rules.get(key)
        name = f"required.{key}"
        if not isinstance(rule, dict):
            continue  # already reported by check_contract_coverage
        low, high = parse_cardinality(rule.get("cardinality"))
        count = _count(summary, key)
        if low <= count <= high:
            r.ok(f"required {key}: {count} instance(s) "
                 f"({describe_cardinality(rule.get('cardinality'))})")
            _record(results, name, True, f"{key}: {count} instance(s)", count=count)
        else:
            evidence = rule.get("evidence") or "n/a"
            message = (
                f"required {key}: found {count} instance(s), contract requires "
                f"{describe_cardinality(rule.get('cardinality'))} "
                f"(evidence resource: {evidence})"
            )
            r.fail(message)
            _record(results, name, False, message, count=count,
                    expected=str(rule.get("cardinality")))


def check_alarm_names(
    r: Reporter, results: list[dict[str, Any]], policy: dict[str, Any],
    contracts: dict[str, Any], resources: list[dict[str, Any]],
) -> None:
    """Replacement-backend alarms must exist; absent-backend alarms must not."""
    if "cloudwatch_alarms" not in (policy.get("required_resources") or []):
        return
    rule = (contracts.get("required_resources") or {}).get("cloudwatch_alarms") or {}
    present = {
        res["name"] for res in resources
        if res["type"] == "aws_cloudwatch_metric_alarm" and is_active(res)
    }
    missing = [n for n in (rule.get("required_alarm_names") or []) if n not in present]
    if missing:
        message = (
            f"cloudwatch_alarms: missing required alarm(s) {', '.join(missing)} -- a "
            f"substituted backend without its own alarm is an observability gap "
            f"bought with the cost reduction"
        )
        r.fail(message)
        _record(results, "required.cloudwatch_alarms.names", False, message,
                missing=missing)
    else:
        r.ok("cloudwatch_alarms: every required alarm name present")
        _record(results, "required.cloudwatch_alarms.names", True,
                "all required alarm names present")

    # An alarm is only forbidden while the backend it points at is forbidden.
    # `elasticache_memory` is a gap in a lean plan and correct in a scale plan,
    # so the rule is resolved against THIS profile's forbidden list rather than
    # applied as a flat denylist that would reject every legitimate scale plan.
    profile_forbidden = set(policy.get("forbidden_resources") or [])
    forbidden = [
        n for n in (rule.get("forbidden_alarm_names") or [])
        if n in present and any(
            n.startswith(key) for key in profile_forbidden
        )
    ]
    if forbidden:
        message = (
            f"cloudwatch_alarms: alarm(s) {', '.join(forbidden)} point at a backend "
            f"this profile does not provision"
        )
        r.fail(message)
        _record(results, "forbidden.cloudwatch_alarms.names", False, message,
                present=forbidden)
    else:
        r.ok("cloudwatch_alarms: no alarms for absent backends")
        _record(results, "forbidden.cloudwatch_alarms.names", True,
                "no alarms for absent backends")


def check_service_cardinality(
    r: Reporter, results: list[dict[str, Any]], profile: str,
    runtime: dict[str, Any], resources: list[dict[str, Any]],
) -> None:
    """The ECS service count must equal the canonical runtime topology.

    `explicit_runtime_role_services` is only `at_least_one` in the contracts
    file, which any topology satisfies. The real invariant lives in
    config/runtime_deployment.yaml: exactly one ECS service per declared
    service, plus the dedicated ML service iff `remote_ml`.

    Both matrix schemas are accepted. Schema v2 declares a `services:` map
    (whose `execution_mode` may pack several logical roles into one task);
    schema v1 declared a flat `roles:` map with one service per role. Reading
    whichever is present keeps this gate correct across that migration instead
    of silently deriving zero from the key it did not find.
    """
    entry = (runtime.get("profiles") or {}).get(profile)
    if not isinstance(entry, dict):
        return
    declared = entry.get("services")
    if isinstance(declared, dict):
        schema, units = "v2 services", sorted(declared)
    elif isinstance(entry.get("roles"), dict):
        schema, units = "v1 roles", sorted(entry["roles"])
    else:
        message = (
            f"ecs services: {RUNTIME_YAML} profile {profile} declares neither a "
            f"`services:` map (schema v2) nor a `roles:` map (schema v1), so the "
            f"expected service count cannot be derived"
        )
        r.fail(message)
        _record(results, "cardinality.ecs_services", False, message)
        return

    remote_ml = bool(entry.get("remote_ml"))
    expected = len(units) + (1 if remote_ml else 0)
    mode = str(entry.get("execution_mode") or "unspecified")
    services = [
        res for res in resources if res["type"] == "aws_ecs_service" and is_active(res)
    ]
    observed = len(services)
    name = "cardinality.ecs_services"
    shape = (
        f"{len(units)} declared service(s) [{schema}, execution_mode={mode}]"
        f"{' + dedicated ml' if remote_ml else ''}"
    )
    if observed == expected:
        r.ok(f"ecs services: {observed} (expected {expected} = {shape})")
        _record(results, name, True, f"{observed} ECS services", expected=expected,
                observed=observed, execution_mode=mode)
        return
    addresses = sorted(res["address"] for res in services)
    message = (
        f"ecs services: found {observed}, expected {expected} from {RUNTIME_YAML} "
        f"({shape}); the plan's service topology does not match the canonical "
        f"runtime matrix -- {', '.join(addresses[:10])}"
    )
    r.fail(message)
    _record(results, name, False, message, expected=expected, observed=observed,
            execution_mode=mode, addresses=addresses)


def check_network_egress(
    r: Reporter, results: list[dict[str, Any]], profile: str,
    contracts: dict[str, Any], plan: dict[str, Any],
    resources: list[dict[str, Any]],
) -> None:
    """NAT gateway count must match the profile's contracted egress posture."""
    rule = (contracts.get("forbidden_resources") or {}).get(
        "nat_gateway_unless_explicit") or {}
    expected_by_profile = rule.get("expected_by_profile") or {}
    spec = expected_by_profile.get(profile)
    gateways = [
        res for res in resources
        if res["type"] == "aws_nat_gateway" and is_active(res)
    ]
    observed = len(gateways)

    declared = ((plan.get("variables") or {}).get("network_egress_mode") or {}).get("value")
    mode = str(declared) if declared not in (None, "") else "unset"
    override_values = [str(v) for v in (rule.get("override_values") or [])]

    name = "network_egress_mode"
    if spec is None:
        detail = f"no expected_by_profile entry for {profile}; observed {observed} NAT gateway(s)"
        r.warn(f"network egress: {detail}")
        _record(results, name, True, detail, observed=observed, mode=mode)
        return

    low, high = parse_cardinality(spec)
    explicit = mode in override_values
    if low <= observed <= high:
        # The count is right. It must also agree with the declared mode, or the
        # plan is describing one topology and provisioning another.
        if observed == 0 and explicit:
            message = (
                f"network egress: var.network_egress_mode={mode!r} requests NAT but the "
                f"plan provisions 0 NAT gateway(s)"
            )
            r.fail(message)
            _record(results, name, False, message, observed=observed, mode=mode)
            return
        if observed > 0 and not explicit:
            message = (
                f"network egress: {observed} NAT gateway(s) planned but "
                f"var.network_egress_mode={mode!r} does not request NAT "
                f"(expected one of {', '.join(override_values)})"
            )
            r.fail(message)
            _record(results, name, False, message, observed=observed, mode=mode)
            return
        r.ok(f"network egress: mode={mode}, {observed} NAT gateway(s) "
             f"({describe_cardinality(spec)})")
        _record(results, name, True, f"mode={mode}, {observed} NAT gateway(s)",
                observed=observed, mode=mode)
        return

    cause = (
        f"; var.network_egress_mode={mode!r} is the explicit opt-in that caused it, "
        f"and it is not permitted for {profile}"
        if explicit and high == 0 else
        f"; var.network_egress_mode={mode!r} does not request NAT"
        if observed > 0 and not explicit else
        f"; var.network_egress_mode={mode!r}"
    )
    message = (
        f"network egress: {observed} NAT gateway(s) planned, contract expects "
        f"{describe_cardinality(spec)} for {profile}{cause}"
    )
    r.fail(message)
    _record(results, name, False, message, observed=observed, mode=mode,
            expected=str(spec))


def check_static_frontends(
    r: Reporter, results: list[dict[str, Any]], profile: str,
    runtime: dict[str, Any], contracts: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    """A profile that declares static frontends must actually plan them."""
    entry = (runtime.get("profiles") or {}).get(profile)
    if not isinstance(entry, dict):
        return
    declares = bool(entry.get("static_frontends"))
    count = _count(summary, "cloudfront_s3_frontends")
    name = "static_frontends"
    if not declares:
        r.ok(f"static frontends: {RUNTIME_YAML} declares none for {profile}")
        _record(results, name, True, "profile declares no static frontends")
        return
    rule = (contracts.get("required_resources") or {}).get("cloudfront_s3_frontends") or {}
    low, _high = parse_cardinality(rule.get("cardinality") or "at_least_one")
    if count >= max(low, 1):
        r.ok(f"static frontends: {count} S3-origin resource(s) planned; SPAs are "
             f"served from immutable S3 origins, not ECS")
        _record(results, name, True, f"{count} static-frontend resources", count=count)
        return
    message = (
        f"static frontends: {RUNTIME_YAML} declares static_frontends: true for "
        f"{profile} but the plan contains {count} static-origin resource(s)"
    )
    r.fail(message)
    _record(results, name, False, message, count=count)


def check_lean_exclusions(
    r: Reporter, results: list[dict[str, Any]], profile: str,
    profile_cfg: dict[str, Any], policy: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    """Restate the three architectural exclusions a cost-capped profile holds.

    These are already covered by check_forbidden, but they are named
    individually here so a report says which invariant broke rather than
    leaving a reader to infer it from a key name.
    """
    if not profile_cfg.get("cost_capped"):
        return
    for key, label in (
        ("dedicated_ml_service", "dedicated ML serving (inference runs inline in the backend task)"),
        ("frontend_ecs_services", "ECS-hosted frontends (SPAs are immutable S3 origins)"),
        ("legacy_rds", "legacy standalone RDS (Aurora Serverless v2 is the database of record)"),
    ):
        if key not in (policy.get("forbidden_resources") or []):
            continue
        count = _count(summary, key)
        name = f"lean_exclusion.{key}"
        if count == 0:
            r.ok(f"lean exclusion {key}: none planned -- {label}")
            _record(results, name, True, f"{key}: 0 planned")
        else:
            message = (
                f"lean exclusion {key}: {count} planned in cost-capped profile "
                f"{profile} -- {label}; see {', '.join(_addresses(summary, key)[:4])}"
            )
            r.fail(message)
            _record(results, name, False, message, count=count)


def check_always_on_staging_compute(
    r: Reporter, results: list[dict[str, Any]], profile: str,
    profiles: dict[str, Any], profile_cfg: dict[str, Any],
    policy: dict[str, Any], plan: dict[str, Any],
    resources: list[dict[str, Any]],
) -> None:
    """Staging compute must be wake/sleep scheduled, not pinned always-on.

    The contracts file marks this key `not_plan_checkable` because there is no
    resource to count. There is still a plan-observable half, and leaving it
    unchecked would let the strongest cost control in the staging budget rest
    on nothing this gate can see:

      * a non-staging profile must provision no staging-environment resources;
      * a staging plan is only permitted awake compute because the profile
        declares `wake_sleep: true` and a bounded awake-hours budget.

    The lifecycle half -- that the environment is actually put back to sleep --
    is enforced by scripts/release/check_cost_policy.py and the wake/sleep
    automation, and is reported here as deferred rather than as a pass.
    """
    if "always_on_staging_compute" not in (policy.get("forbidden_resources") or []):
        return
    name = "forbidden.always_on_staging_compute"
    environment = ((plan.get("variables") or {}).get("environment") or {}).get("value")
    env = str(environment) if environment not in (None, "") else ""

    if profile != "staging":
        if env == "staging":
            message = (
                f"always_on_staging_compute: plan is for profile {profile} but "
                f"var.environment={env!r}; a {profile} plan provisions no "
                f"staging-environment resources"
            )
            r.fail(message)
            _record(results, name, False, message, environment=env)
            return
        r.ok(f"always_on_staging_compute: {profile} plan provisions no "
             f"staging-environment compute (var.environment={env or 'unset'})")
        _record(results, name, True, f"no staging compute in a {profile} plan",
                environment=env)
        return

    compute = [
        res for res in resources
        if res["type"] in COMPUTE_TYPES and is_active(res)
    ]
    desired = 0
    for res in compute:
        value = res["values"].get("desired_count")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            desired += int(value)
    state = "awake" if desired > 0 else "asleep"
    staging_cfg = (profiles.get("staging") or {})
    wake_sleep = bool(staging_cfg.get("wake_sleep"))
    awake_hours = ((staging_cfg.get("budget") or {})
                   .get("maximum_scheduled_awake_hours_per_month"))

    if desired > 0 and not wake_sleep:
        message = (
            f"always_on_staging_compute: staging plans {desired} always-on task(s) "
            f"across {len(compute)} compute resource(s) and {PROFILES_YAML} does not "
            f"declare wake_sleep: true for staging"
        )
        r.fail(message)
        _record(results, name, False, message, desired_total=desired, state=state)
        return
    if desired > 0 and awake_hours is None:
        message = (
            f"always_on_staging_compute: staging plans {desired} running task(s) but "
            f"{PROFILES_YAML} declares no maximum_scheduled_awake_hours_per_month, so "
            f"nothing bounds how long they run"
        )
        r.fail(message)
        _record(results, name, False, message, desired_total=desired, state=state)
        return

    r.ok(f"always_on_staging_compute: staging is {state} "
         f"({desired} desired task(s)), wake_sleep declared, "
         f"awake-hours capped at {awake_hours}/month")
    r.warn("always_on_staging_compute: the lifecycle half (the environment is "
           "actually slept after validation) is enforced by "
           "scripts/release/check_cost_policy.py and the wake/sleep automation, "
           "not by this plan gate")
    _record(results, name, True,
            f"staging {state}: {desired} desired task(s), wake_sleep declared",
            desired_total=desired, state=state,
            deferred_to="scripts/release/check_cost_policy.py")


def check_fail_closed(
    r: Reporter, results: list[dict[str, Any]], inventory: dict[str, Any],
    unmatched_instances: list[dict[str, Any]],
) -> None:
    """No expensive resource type may pass without a matcher having an opinion."""
    unmapped = inventory.get("unmapped_expensive") or []
    name = "fail_closed.unmapped_expensive"
    if unmapped:
        by_type: dict[str, list[str]] = {}
        for item in unmapped:
            by_type.setdefault(item["type"], []).append(item["address"])
        for res_type, addresses in sorted(by_type.items()):
            message = (
                f"unmapped expensive resource type {res_type}: {len(addresses)} "
                f"actively-planned instance(s) ({', '.join(addresses[:4])}) match no "
                f"matcher in {CONTRACTS_YAML}; add a canonical key for it rather than "
                f"letting the gate pass in silence"
            )
            r.fail(message)
            _record(results, f"{name}.{res_type}", False, message,
                    addresses=addresses)
    else:
        r.ok("fail-closed: every expensive resource type in the plan is named by "
             "a matcher")
        _record(results, name, True, "no unmapped expensive resource types")

    if unmatched_instances:
        addresses = [item["address"] for item in unmatched_instances]
        r.warn(
            f"{len(unmatched_instances)} expensive resource(s) matched no individual "
            f"rule though their type is contracted elsewhere: "
            f"{', '.join(addresses[:6])}"
        )
        _record(results, "fail_closed.unmatched_instances", True,
                f"{len(unmatched_instances)} expensive resources matched no rule",
                addresses=addresses, severity="warning")


def check_fargate_sizing(
    r: Reporter, results: list[dict[str, Any]], unresolved: list[str],
    records: list[dict[str, Any]],
) -> None:
    """Every actively-planned Fargate service must carry resolvable sizing."""
    name = "fargate_sizing"
    if unresolved:
        message = (
            f"fargate sizing: {len(unresolved)} actively-planned ECS service(s) have "
            f"no resolvable cpu/memory ({', '.join(unresolved[:6])}); "
            f"check_cost_model.py cannot price them and an unsized always-on task "
            f"must not be waved through at zero"
        )
        r.fail(message)
        _record(results, name, False, message, unresolved=unresolved)
        return
    resolved = [rec for rec in records if str(rec["source"]).startswith("task_definition")]
    r.ok(f"fargate sizing: every ECS service carries cpu/memory "
         f"({len(resolved)} resolved from its task definition)")
    _record(results, name, True,
            f"{len(records)} service(s) sized, {len(resolved)} via task definition")


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def render_inventory_md(inventory: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Profile resource inventory — {inventory['profile']}")
    add("")
    add(f"- **Generated from:** `{inventory['generated_from']}`")
    add(f"- **Terraform version:** {inventory['terraform_version'] or 'unknown'}")
    add(f"- **Plan format version:** {inventory['plan_format_version'] or 'unknown'}")
    add(f"- **Schema version:** {inventory['schema_version']}")
    add(f"- **Managed resources:** {len(inventory['resources'])}")
    add("")
    add("Generated by `scripts/release/check_terraform_plan_policy.py`. "
        "Do not edit by hand.")
    add("")
    add("## Canonical policy keys")
    add("")
    add("| Canonical key | Actively planned | Example address |")
    add("| --- | ---: | --- |")
    for key, detail in inventory["canonical_summary"].items():
        example = (detail["addresses"] or ["—"])[0]
        add(f"| `{key}` | {detail['count']} | `{example}` |")
    add("")
    add("## Fargate sizing resolution")
    add("")
    add("`check_cost_model.py` prices Fargate from the **`aws_ecs_service`** entry. "
        "Terraform declares `cpu`/`memory` on the task definition only, so the "
        "sizing below was copied onto each service's `values`.")
    add("")
    if inventory["fargate_sizing_resolution"]:
        add("| Service | cpu | memory | Source |")
        add("| --- | ---: | ---: | --- |")
        for rec in inventory["fargate_sizing_resolution"]:
            add(f"| `{rec['service']}` | {rec['cpu'] or '—'} | {rec['memory'] or '—'} "
                f"| {rec['source']} |")
    else:
        add("_No ECS services in this plan._")
    add("")
    add("## Unmapped expensive resources")
    add("")
    if inventory["unmapped_expensive"]:
        for item in inventory["unmapped_expensive"]:
            add(f"- `{item['address']}` (`{item['type']}`) — {item['reason']}")
    else:
        add("_None — every expensive resource type in this plan is named by a "
            "matcher in `config/terraform_resource_contracts.yaml`._")
    add("")
    add("## Resources by action")
    add("")
    add("| Address | Type | Actions | Canonical keys |")
    add("| --- | --- | --- | --- |")
    for res in inventory["resources"]:
        keys = ", ".join(f"`{k}`" for k in res["canonical_keys"]) or "—"
        add(f"| `{res['address']}` | `{res['type']}` | "
            f"{', '.join(res['actions'])} | {keys} |")
    add("")
    return "\n".join(lines)


def render_result_md(result: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# Plan policy result — {result['profile']}")
    add("")
    add(f"- **Verdict:** {'PASS' if result['passed'] else 'FAIL'}")
    add(f"- **Checks:** {result['checks_total']} "
        f"({result['checks_failed']} failed)")
    add(f"- **Plan:** `{result['plan_json']}`")
    add(f"- **Inventory:** `{result['inventory_json']}`")
    add(f"- **Terraform version:** {result['terraform_version'] or 'unknown'}")
    add("")
    add("Generated by `scripts/release/check_terraform_plan_policy.py`. "
        "Do not edit by hand.")
    add("")
    if result["violations"]:
        add("## Violations")
        add("")
        for item in result["violations"]:
            add(f"- **`{item['check']}`** — {item['detail']}")
        add("")
    add("## All checks")
    add("")
    add("| Check | Status | Detail |")
    add("| --- | --- | --- |")
    for item in result["results"]:
        detail = str(item["detail"]).replace("|", r"\|")
        add(f"| `{item['check']}` | {item['status']} | {detail} |")
    add("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _resolve_input(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return repo_root() / path


def _resolve_out_dir(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else repo_root() / path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assert a Terraform plan satisfies its deployment profile's cost policy.",
    )
    parser.add_argument("--profile", required=True,
                        help="Deployment profile name from config/deployment_profiles.yaml")
    parser.add_argument("--plan-json", required=True,
                        help="Path to `terraform show -json <planfile>` output")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR,
                        help=f"Directory for generated reports (default: {DEFAULT_OUT_DIR}/). "
                             f"{INVENTORY_JSON} is always written here and is the path "
                             f"check_cost_model.py and the workflows read.")
    return parser


def check(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = args.profile

    r = Reporter(f"Terraform plan policy — {profile}")

    try:
        profiles_doc = load_yaml(PROFILES_YAML) or {}
        contracts = load_yaml(CONTRACTS_YAML) or {}
        runtime = load_yaml(RUNTIME_YAML) or {}
        price_book = load_yaml(PRICE_BOOK_YAML) or {}
    except FileNotFoundError as exc:
        r.fail(f"required config file missing: {exc}")
        r.finish()
        return EXIT_USAGE

    profiles = profiles_doc.get("profiles") or {}
    profile_cfg = profiles.get(profile)
    if not isinstance(profile_cfg, dict):
        r.fail(f"unknown profile {profile!r}; {PROFILES_YAML} declares "
               f"{', '.join(sorted(profiles))}")
        r.finish()
        return EXIT_USAGE

    policy = profile_cfg.get("cost_policy")
    if not isinstance(policy, dict):
        r.fail(f"profile {profile!r} declares no cost_policy in {PROFILES_YAML}; "
               f"there is no shape policy to enforce against a plan")
        r.finish()
        return EXIT_USAGE
    policy = dict(policy)
    policy["_profile"] = profile

    plan_path = _resolve_input(args.plan_json)
    if not plan_path.exists():
        r.fail(f"plan JSON not found: {args.plan_json}")
        r.finish()
        return EXIT_USAGE
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        r.fail(f"plan JSON is not readable/parseable: {exc}")
        r.finish()
        return EXIT_USAGE
    if not isinstance(plan, dict):
        r.fail("plan JSON is not a JSON object")
        r.finish()
        return EXIT_USAGE

    fmt = str(plan.get("format_version") or "")
    if fmt not in SUPPORTED_PLAN_FORMATS:
        r.fail(f"unsupported plan format_version {fmt!r}; this parser understands "
               f"{', '.join(sorted(SUPPORTED_PLAN_FORMATS))}. Refusing to guess at "
               f"the document shape.")
        r.finish()
        return EXIT_USAGE
    if "resource_changes" not in plan and "planned_values" not in plan:
        r.fail("plan JSON has neither `resource_changes` nor `planned_values`; "
               "it is not `terraform show -json` output for a plan")
        r.finish()
        return EXIT_USAGE
    r.ok(f"plan format_version {fmt}, terraform {plan.get('terraform_version') or 'unknown'}")

    results: list[dict[str, Any]] = []
    _record(results, "plan_shape", True, f"format_version {fmt}")

    try:
        resources = enumerate_resources(plan)
        sizing_records, unresolved = resolve_fargate_sizing(resources)
        inventory, unmatched_instances = build_inventory(
            profile, plan, resources, contracts, price_book, sizing_records,
            str(plan_path),
        )
    except PlanError as exc:
        r.fail(f"plan could not be inventoried: {exc}")
        r.finish()
        return EXIT_USAGE

    active = sum(1 for res in resources if is_active(res))
    r.ok(f"enumerated {len(resources)} managed resource(s); {active} actively planned, "
         f"{len(resources) - active} being destroyed")

    summary = inventory["canonical_summary"]

    check_contract_coverage(r, results, policy, contracts)
    check_forbidden(r, results, policy, contracts, summary, resources)
    check_required(r, results, policy, contracts, summary)
    check_alarm_names(r, results, policy, contracts, resources)
    check_service_cardinality(r, results, profile, runtime, resources)
    check_network_egress(r, results, profile, contracts, plan, resources)
    check_static_frontends(r, results, profile, runtime, contracts, summary)
    check_lean_exclusions(r, results, profile, profile_cfg, policy, summary)
    check_always_on_staging_compute(
        r, results, profile, profiles, profile_cfg, policy, plan, resources)
    check_fail_closed(r, results, inventory, unmatched_instances)
    check_fargate_sizing(r, results, unresolved, sizing_records)

    violations = [item for item in results if item["status"] == "fail"]
    out_dir = _resolve_out_dir(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inventory_path = out_dir / INVENTORY_JSON
    inventory_path.write_text(
        json.dumps(inventory, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    (out_dir / INVENTORY_MD).write_text(render_inventory_md(inventory), encoding="utf-8")

    result_doc = {
        "schema_version": 1,
        "profile": profile,
        "passed": not violations,
        "checks_total": len(results),
        "checks_failed": len(violations),
        "plan_json": str(plan_path),
        "terraform_version": inventory["terraform_version"],
        "inventory_json": str(inventory_path),
        "violations": violations,
        "results": results,
    }
    (out_dir / RESULT_JSON).write_text(
        json.dumps(result_doc, indent=2) + "\n", encoding="utf-8")
    (out_dir / RESULT_MD).write_text(render_result_md(result_doc), encoding="utf-8")

    print(f"\n  inventory : {inventory_path}")
    print(f"  reports   : {out_dir / INVENTORY_MD}, {out_dir / RESULT_JSON}, "
          f"{out_dir / RESULT_MD}")
    return r.finish()


if __name__ == "__main__":
    main_guard(check)
