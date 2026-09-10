#!/usr/bin/env python3
"""Classify Terraform desired/state/remote ownership and plan reconciliation.

The planner is pure and dry-run only.  It accepts a Terraform plan JSON,
Terraform state JSON, and a complete remote inventory fixture.  It never runs
Terraform, AWS, or a provider.  Every remote fixture must identify ownership;
missing/invalid ownership, incomplete inventories, conflicting identities, and
plaintext secret material block reconciliation instead of producing a guessed
mutation plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = 1
OWNER_VALUES = frozenset({"terraform", "external", "shared", "unknown"})
SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|"
    r"client[_-]?secret|connection[_-]?string)(?:$|_)",
    re.IGNORECASE,
)
SENSITIVE_VALUE = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|-----BEGIN[^-]*PRIVATE KEY-----|"
    r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]+|password\s*=|secret\s*=)",
    re.IGNORECASE,
)
REDACTED_VALUES = frozenset({
    "<sensitive>",
    "(sensitive value)",
    "REDACTED",
    "***",
    # Canonical Terraform plan sanitisation marker emitted by
    # scripts/release/sanitize_terraform_plan_json.py.
    "__REDACTED_SENSITIVE__",
})


class ReconciliationError(ValueError):
    """Raised when an input cannot safely support reconciliation."""


@dataclass(frozen=True)
class Resource:
    address: str
    resource_type: str
    values: Mapping[str, Any]
    actions: tuple[str, ...] = ()
    resource_id: str | None = None
    owner: str | None = None


@dataclass(frozen=True)
class RemoteInventory:
    resources: tuple[Resource, ...]
    complete: bool
    source: str


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"cannot read reconciliation input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReconciliationError(f"reconciliation input {path} must be a JSON object")
    return value


def _secret_paths(
    value: Any,
    path: str = "$",
    *,
    key: str | None = None,
    sensitive_mask: bool = False,
) -> list[str]:
    """Find plaintext secret material without returning its value."""

    # Terraform's ``sensitive_values`` tree is a boolean mask describing
    # which values are sensitive; it is not the value tree itself.  Walk it
    # only for shape consistency and never classify its booleans as plaintext
    # credentials.
    if sensitive_mask:
        if isinstance(value, dict):
            for child_key, child in value.items():
                _secret_paths(child, f"{path}.{child_key}", sensitive_mask=True)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                _secret_paths(child, f"{path}[{index}]", sensitive_mask=True)
        return []

    found: list[str] = []
    key_is_reference = bool(key and re.search(r"(?:^|_)(?:arn|id|name|ref|version)(?:$|_)", key, re.IGNORECASE))
    if key and SENSITIVE_KEY.search(key) and not key_is_reference:
        if isinstance(value, str) and value and value not in REDACTED_VALUES:
            found.append(path)
        elif value not in (None, "", False, 0, *REDACTED_VALUES):
            found.append(path)
    elif isinstance(value, str) and value not in REDACTED_VALUES and SENSITIVE_VALUE.search(value):
        found.append(path)
    if isinstance(value, dict):
        for child_key, child in value.items():
            found.extend(
                _secret_paths(
                    child,
                    f"{path}.{child_key}",
                    key=str(child_key),
                    sensitive_mask=child_key == "sensitive_values",
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secret_paths(child, f"{path}[{index}]"))
    return found


def reject_plaintext_secrets(data: Mapping[str, Any], source: str) -> None:
    paths = _secret_paths(data)
    if paths:
        raise ReconciliationError(
            f"{source} contains plaintext secret material at {', '.join(paths[:5])}"
        )


def _resource_from(raw: Mapping[str, Any], *, actions: Iterable[str] = (), owner: str | None = None) -> Resource:
    address = raw.get("address")
    resource_type = raw.get("type", raw.get("resource_type"))
    if not isinstance(address, str) or not address:
        raise ReconciliationError("every resource must declare a non-empty address")
    if not isinstance(resource_type, str) or not resource_type:
        raise ReconciliationError(f"resource {address} must declare a type")
    values = raw.get("values", raw.get("attributes", {}))
    if not isinstance(values, dict):
        raise ReconciliationError(f"resource {address} values must be an object")
    resource_id = raw.get("id", raw.get("remote_id"))
    if resource_id is not None and not isinstance(resource_id, str):
        raise ReconciliationError(f"resource {address} id must be a string")
    resolved_owner = owner if owner is not None else raw.get("owner")
    if resolved_owner is not None and not isinstance(resolved_owner, str):
        raise ReconciliationError(f"resource {address} owner must be a string")
    return Resource(address, resource_type, values, tuple(str(item) for item in actions), resource_id, resolved_owner)


def _walk_modules(module: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(module, dict):
        return
    for resource in module.get("resources", []) or []:
        if isinstance(resource, dict):
            yield resource
    for child in module.get("child_modules", []) or []:
        yield from _walk_modules(child)


def load_plan_resources(path: Path) -> tuple[Resource, ...]:
    plan = _read_json(path)
    reject_plaintext_secrets(plan, str(path))
    if not isinstance(plan.get("format_version"), str):
        raise ReconciliationError("Terraform plan must declare format_version")
    changes: dict[str, tuple[str, ...]] = {}
    change_resources: dict[str, dict[str, Any]] = {}
    for raw in plan.get("resource_changes", []) or []:
        if not isinstance(raw, dict) or not isinstance(raw.get("address"), str):
            raise ReconciliationError("Terraform resource_changes contain an invalid resource")
        change = raw.get("change") or {}
        actions = change.get("actions", []) if isinstance(change, dict) else []
        if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
            raise ReconciliationError(f"Terraform actions for {raw['address']} are invalid")
        changes[raw["address"]] = tuple(actions)
        if isinstance(change, dict):
            values = change.get("after")
            if not isinstance(values, dict):
                values = change.get("before")
            if isinstance(values, dict):
                change_resources[raw["address"]] = {
                    "address": raw["address"],
                    "type": raw.get("type"),
                    "values": values,
                }
    root = (plan.get("planned_values") or {}).get("root_module")
    if not isinstance(root, dict):
        raise ReconciliationError("Terraform plan has no planned_values.root_module")
    resources: list[Resource] = []
    for raw in _walk_modules(root):
        address = raw.get("address")
        if not isinstance(address, str):
            raise ReconciliationError("planned Terraform resource has no address")
        actions = changes.get(address, ("no-op",))
        if "delete" in actions and not any(action in actions for action in ("create", "update", "read")):
            # A destroy-only resource is retained as desired-state evidence so
            # reconciliation can produce an explicit, reviewable destroy plan.
            values = raw.get("values") or {}
        else:
            values = raw.get("values") or {}
        resources.append(_resource_from(raw, actions=actions))
    known = {resource.address for resource in resources}
    for address, raw in change_resources.items():
        if address not in known:
            resources.append(_resource_from(raw, actions=changes[address]))
    return _unique(resources, "Terraform plan")


def load_state_resources(path: Path) -> tuple[Resource, ...]:
    state = _read_json(path)
    reject_plaintext_secrets(state, str(path))
    root = ((state.get("values") or {}).get("root_module") if isinstance(state.get("values"), dict) else None)
    if root is None:
        root = state.get("root_module")
    if not isinstance(root, dict):
        raise ReconciliationError("Terraform state has no values.root_module")
    resources = [_resource_from(raw) for raw in _walk_modules(root)]
    return _unique(resources, "Terraform state")


def load_remote_inventory(path: Path) -> RemoteInventory:
    data = _read_json(path)
    reject_plaintext_secrets(data, str(path))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ReconciliationError("remote inventory schema_version must be 1")
    if data.get("source", "offline_fixture") != "offline_fixture":
        raise ReconciliationError("reconciliation currently accepts offline remote fixtures only")
    if data.get("inventory_complete") is not True:
        raise ReconciliationError("remote inventory must explicitly declare inventory_complete=true")
    raw_resources = data.get("resources")
    if not isinstance(raw_resources, list):
        raise ReconciliationError("remote inventory resources must be a list")
    resources: list[Resource] = []
    for raw in raw_resources:
        if not isinstance(raw, dict):
            raise ReconciliationError("remote inventory resource is not an object")
        owner = raw.get("owner")
        if not isinstance(owner, str) or owner not in OWNER_VALUES:
            owner = "unknown"
        resources.append(_resource_from(raw, owner=owner))
    return RemoteInventory(_unique(resources, "remote inventory"), True, "offline_fixture")


def _unique(resources: list[Resource], label: str) -> tuple[Resource, ...]:
    seen: set[str] = set()
    for resource in resources:
        if resource.address in seen:
            raise ReconciliationError(f"{label} contains duplicate address {resource.address}")
        seen.add(resource.address)
    return tuple(sorted(resources, key=lambda item: item.address))


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _fingerprint(resource: Resource) -> str:
    payload = json.dumps({"type": resource.resource_type, "values": _canonical(resource.values)}, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _identity(resource: Resource) -> str | None:
    if resource.resource_id:
        return resource.resource_id
    for key in ("id", "arn", "bucket", "name", "cluster_arn", "repository_url", "queue_url"):
        value = resource.values.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _classification(address: str, desired: Resource | None, state: Resource | None, remote: Resource | None) -> tuple[str, str, bool, str]:
    if remote and remote.owner not in {"terraform", "external", "shared"}:
        return "AMBIGUOUS_OWNERSHIP", "review remote ownership before reconciliation", True, "review"
    if desired and remote and state is None:
        if remote.owner == "terraform":
            desired_identity = _identity(desired)
            remote_identity = _identity(remote)
            if desired_identity and remote_identity and desired_identity == remote_identity:
                return "UNMANAGED_ADOPTABLE", "deterministic Terraform-owned remote matches desired identity and can be imported", True, "import"
            return "OWNERSHIP_CONFLICT", "Terraform-owned remote resource has no unambiguous desired identity", True, "review"
        return "OWNERSHIP_CONFLICT", f"desired Terraform resource overlaps {remote.owner} remote ownership", True, "review"
    if state and remote and _identity(state) and _identity(remote) and _identity(state) != _identity(remote):
        return "DRIFT", "Terraform state identity differs from the remote inventory", True, "review"
    if desired is None and state is not None:
        return "ORPHAN_STATE", "state contains a resource absent from desired state", True, "review"
    if desired is None and remote is not None:
        if remote.owner == "terraform":
            return "ORPHAN_REMOTE", "Terraform-owned remote resource is absent from desired and state", True, "review"
        return "AMBIGUOUS_OWNERSHIP", "remote resource is outside desired state and must be reviewed", True, "review"
    if desired is None:
        return "UNKNOWN", "resource was not found in any authoritative input", True, "review"
    if "delete" in desired.actions and not any(action in desired.actions for action in ("create", "update", "read")):
        return "DESTROY", "Terraform plan requests a destroy", False, "destroy"
    if state is None:
        if remote is not None:
            return "OWNERSHIP_CONFLICT", "remote resource exists but is not represented in Terraform state", True, "review"
        return "CREATE", "desired resource is absent from state and complete remote inventory", False, "create"
    if remote is None:
        return "ORPHAN_STATE", "state resource is absent from the complete remote inventory", True, "review"
    if any(action in desired.actions for action in ("create", "update")):
        return "UPDATE", "Terraform plan requests a change", False, "update"
    if _fingerprint(desired) != _fingerprint(state):
        return "DRIFT", "desired and Terraform state values differ without a matching plan action", True, "review"
    if remote.values and _fingerprint(state) != _fingerprint(remote):
        return "DRIFT", "Terraform state values differ from remote inventory values", True, "review"
    return "IN_SYNC", "desired state, Terraform state, and remote ownership agree", False, "none"


def reconcile(
    profile: str,
    desired: tuple[Resource, ...],
    state: tuple[Resource, ...],
    remote: RemoteInventory,
) -> dict[str, Any]:
    """Classify every address and produce reviewable actions, never mutations."""

    if not profile or not isinstance(profile, str):
        raise ReconciliationError("profile must be a non-empty string")
    desired_by = {item.address: item for item in desired}
    state_by = {item.address: item for item in state}
    remote_by = {item.address: item for item in remote.resources}
    addresses = sorted(set(desired_by) | set(state_by) | set(remote_by))
    resources: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for address in addresses:
        classification, reason, blocking, action = _classification(
            address, desired_by.get(address), state_by.get(address), remote_by.get(address)
        )
        row = {
            "address": address,
            "resource_type": (desired_by.get(address) or state_by.get(address) or remote_by.get(address)).resource_type,
            "classification": classification,
            "reason": reason,
            "blocking": blocking,
            "action": action,
            "ownership": (remote_by.get(address).owner if remote_by.get(address) else "terraform" if state_by.get(address) or desired_by.get(address) else "unknown"),
        }
        resources.append(row)
        if action != "none":
            actions.append({"address": address, "action": action, "blocking": blocking, "reason": reason})
    blocking = [item for item in resources if item["blocking"]]
    reconciliation = [item for item in resources if item["classification"] == "UNMANAGED_ADOPTABLE"]
    planned_changes = [item for item in actions if item["action"] in {"create", "update", "destroy"}]
    status = (
        "RECONCILIATION_REQUIRED"
        if reconciliation
        else "BLOCKED" if blocking else "CHANGES_REQUIRED" if planned_changes else "PASS"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": profile,
        "mode": "offline-dry-run",
        "status": status,
        "resources": resources,
        "actions": actions,
        "summary": {
            "resources_total": len(resources),
            "in_sync": sum(item["classification"] == "IN_SYNC" for item in resources),
            "changes_required": len(planned_changes),
            "reconciliation_required": len(reconciliation),
            "blocking": len(blocking),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--plan-json", type=Path, required=True)
    parser.add_argument("--state-json", type=Path, required=True)
    parser.add_argument("--remote-fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = reconcile(
            args.profile,
            load_plan_resources(args.plan_json),
            load_state_resources(args.state_json),
            load_remote_inventory(args.remote_fixture),
        )
        rendered = json.dumps(report, indent=2) + "\n"
    except ReconciliationError as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
