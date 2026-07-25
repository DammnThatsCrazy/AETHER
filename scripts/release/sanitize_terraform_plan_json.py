#!/usr/bin/env python3
"""Strip secret values out of `terraform show -json` output before it is published.

WHY THIS EXISTS
  `terraform show -json <planfile>` does **not** honour `sensitive = true` for
  ROOT VARIABLES. A variable declared

      variable "auth0_management_client_secret" {
        type      = string
        sensitive = true
      }

  and supplied through `TF_VAR_auth0_management_client_secret` appears verbatim
  in the JSON plan's top-level `variables` block:

      "variables": {"auth0_management_client_secret": {"value": "<the secret>"}}

  Both `.github/workflows/terraform-promote.yml` and
  `.github/workflows/infrastructure.yml` upload that JSON as a build artifact,
  which anyone with repository read access can download. Sanitising here is what
  keeps the Auth0 management client secret out of those artifacts.

WHAT IT KEEPS
  Only the top-level keys any consumer reads, and inside `variables` only the
  values the policy gate actually reads:

    * `scripts/release/check_terraform_plan_policy.py`
        - `format_version`      (plan-shape guard)
        - `terraform_version`   (recorded in the inventory)
        - `planned_values`      (resource enumeration)
        - `resource_changes`    (planned actions)
        - `variables.environment`          -> check_always_on_staging_compute()
        - `variables.network_egress_mode`  -> check_network_egress()
    * `configuration` is retained for human review and because the
      `sensitive` flag of each root variable is only declared there.

  Every other root variable keeps its NAME (so a reviewer can still see what was
  set) and loses its VALUE. That is an allow-list, so a new sensitive variable
  is redacted by default rather than published until someone remembers it.

WHAT ELSE IT REDACTS
  * resource attributes Terraform itself marks sensitive, via the
    `before_sensitive` / `after_sensitive` masks on each resource change and the
    `sensitive_values` mask on each planned value;
  * any literal occurrence anywhere in the document of a value belonging to a
    root variable declared `sensitive = true` -- a secret copied into a resource
    argument is still a secret.

FAIL-CLOSED
  After sanitisation the document is re-scanned for every known secret value.
  If one survives, nothing is written and the process exits non-zero: publishing
  a plan that still carries a secret is worse than failing the job.

Usage:
  python scripts/release/sanitize_terraform_plan_json.py RAW.json SANITISED.json

Exit codes:
  0  a sanitised document was written
  1  the input could not be read/parsed, or a secret survived sanitisation
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# Root variables whose VALUE a downstream consumer actually reads. Everything
# else keeps its name and loses its value.
KEEP_VARIABLE_VALUES = frozenset({"environment", "network_egress_mode"})

# Top-level keys retained in the published document.
KEEP_TOP_LEVEL = frozenset({
    "format_version",
    "terraform_version",
    "variables",
    "planned_values",
    "resource_changes",
    "configuration",
})

REDACTED = "__REDACTED_SENSITIVE__"


def by_mask(value: Any, mask: Any) -> Any:
    """Apply one of Terraform's own sensitivity masks, which mirror the value."""
    if mask is True:
        return REDACTED
    if isinstance(mask, dict) and isinstance(value, dict):
        return {k: by_mask(v, mask.get(k, False)) for k, v in value.items()}
    if isinstance(mask, list) and isinstance(value, list):
        return [
            by_mask(item, mask[i] if i < len(mask) else False)
            for i, item in enumerate(value)
        ]
    return value


def by_literal(node: Any, secrets: frozenset[str]) -> Any:
    """Replace every string equal to a known secret, at any depth."""
    if isinstance(node, str):
        return REDACTED if node in secrets else node
    if isinstance(node, dict):
        return {k: by_literal(v, secrets) for k, v in node.items()}
    if isinstance(node, list):
        return [by_literal(item, secrets) for item in node]
    return node


def sensitive_variable_names(plan: dict[str, Any]) -> set[str]:
    """Root variables the configuration declares `sensitive = true`."""
    declared = (
        ((plan.get("configuration") or {}).get("root_module") or {}).get("variables")
        or {}
    )
    return {
        name
        for name, entry in declared.items()
        if isinstance(entry, dict) and entry.get("sensitive") is True
    }


def secret_values(plan: dict[str, Any], environ: dict[str, str]) -> frozenset[str]:
    """Every literal value that belongs to a `sensitive = true` root variable.

    Read from two independent places so neither one being absent can silently
    empty the set: the plan's own `variables` block, and the `TF_VAR_*`
    environment the plan was produced with.
    """
    names = sensitive_variable_names(plan)
    values: set[str] = set()
    supplied = plan.get("variables") or {}
    for name in names:
        entry = supplied.get(name)
        if isinstance(entry, dict) and isinstance(entry.get("value"), str) and entry["value"]:
            values.add(entry["value"])
        from_env = environ.get(f"TF_VAR_{name}")
        if from_env:
            values.add(from_env)
    return frozenset(values)


def scrub_module(module: dict[str, Any]) -> None:
    """Apply `sensitive_values` to every resource in a planned-values module."""
    for resource in module.get("resources") or []:
        mask = resource.get("sensitive_values")
        if mask:
            resource["values"] = by_mask(resource.get("values") or {}, mask)
    for child in module.get("child_modules") or []:
        scrub_module(child)


def sanitize(plan: dict[str, Any], environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Return a copy of `plan` safe to publish as a build artifact."""
    environ = dict(os.environ if environ is None else environ)
    secrets = secret_values(plan, environ)

    clean = {key: value for key, value in plan.items() if key in KEEP_TOP_LEVEL}

    variables = clean.get("variables")
    if isinstance(variables, dict):
        clean["variables"] = {
            name: (entry if name in KEEP_VARIABLE_VALUES else {"value": REDACTED})
            for name, entry in variables.items()
        }

    scrub_module((clean.get("planned_values") or {}).get("root_module") or {})

    for change in clean.get("resource_changes") or []:
        detail = change.get("change")
        if not isinstance(detail, dict):
            continue
        for side in ("before", "after"):
            mask = detail.get(f"{side}_sensitive")
            if mask and isinstance(detail.get(side), (dict, list)):
                detail[side] = by_mask(detail[side], mask)

    clean = by_literal(clean, secrets)

    # Fail closed: a surviving secret must stop the job, not ship in an artifact.
    blob = json.dumps(clean)
    for secret in secrets:
        if secret in blob:
            raise SystemExit(
                "::error::plan JSON still carries a sensitive variable value after "
                "sanitisation; refusing to write a publishable plan"
            )
    return clean


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} RAW.json SANITISED.json", file=sys.stderr)
        return 1
    _, source, destination = argv
    try:
        plan = json.loads(open(source, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::plan JSON is not readable/parseable: {exc}", file=sys.stderr)
        return 1
    if not isinstance(plan, dict):
        print("::error::`terraform show -json` did not produce a JSON object", file=sys.stderr)
        return 1

    clean = sanitize(plan)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(clean, indent=2) + "\n")
    kept = sorted(k for k in (clean.get("variables") or {}) if k in KEEP_VARIABLE_VALUES)
    print(
        f"sanitised plan JSON -> {destination} "
        f"(variable values retained: {', '.join(kept) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
