#!/usr/bin/env python3
"""Validate the schemas and registries that form the adaptive CI contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent.parent
NORMAL_PR_AUTHORITY = ".github/workflows/repo-consistency.yml"
NORMAL_PR_STATUS = "verification / disposition"
NORMAL_PR_FINALIZATION_EVENT = "ready_for_review"


def _triggers(document: dict) -> dict:
    """Return workflow triggers while handling YAML 1.1's `on` boolean."""
    value = document.get("on") if "on" in document else document.get(True)
    return value if isinstance(value, dict) else {}


def validate_workflow_cadence(root: Path = ROOT) -> list[str]:
    """Require all automatic PR workflow runs to begin at finalization.

    Draft pushes are the accumulation phase. A workflow may still run on
    pushes to main, schedules, releases, or explicit dispatch; only its
    pull-request trigger is constrained here.
    """
    errors: list[str] = []
    policy_path = root / "config/verification_policy.yaml"
    try:
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return [f"cannot load verification policy for workflow cadence: {exc}"]
    normal = policy.get("normal_pr") if isinstance(policy, dict) else None
    finalization_event = normal.get("finalization_event") if isinstance(normal, dict) else None
    if finalization_event != NORMAL_PR_FINALIZATION_EVENT:
        return [
            "verification policy normal_pr.finalization_event must be "
            f"{NORMAL_PR_FINALIZATION_EVENT}"
        ]

    workflow_dir = root / ".github/workflows"
    workflow_paths = sorted(workflow_dir.glob("*.y*ml"))
    authority_path = root / NORMAL_PR_AUTHORITY
    authority_seen = False
    for path in workflow_paths:
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{path.relative_to(root)}: cannot parse workflow: {exc}")
            continue
        triggers = _triggers(document)
        if "pull_request" not in triggers:
            continue
        trigger = triggers["pull_request"]
        relative = path.relative_to(root)
        if not isinstance(trigger, dict):
            errors.append(
                f"{relative}: pull_request must declare types: [{finalization_event}]"
            )
        elif trigger.get("types") != [finalization_event]:
            errors.append(
                f"{relative}: pull_request.types must be exactly [{finalization_event}]"
            )
        if path == authority_path:
            authority_seen = True
            jobs = document.get("jobs") or {}
            publication = jobs.get("publish-evidence") or {}
            if publication.get("name") != NORMAL_PR_STATUS:
                errors.append(
                    f"{relative}: publish-evidence must remain named {NORMAL_PR_STATUS!r}"
                )

    if not authority_seen:
        errors.append(
            f"{NORMAL_PR_AUTHORITY}: must declare the finalization pull_request trigger"
        )
    return errors


def _schema(path: Path, draft: type[jsonschema.Validator]) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    draft.check_schema(raw)


def main() -> int:
    errors: list[str] = []
    delivery_schemas = sorted((ROOT / "contracts/delivery").glob("*.schema.json"))
    for path in delivery_schemas:
        try:
            _schema(path, jsonschema.Draft202012Validator)
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")

    try:
        suite_schema = json.loads((ROOT / "config/test_suites.schema.json").read_text(encoding="utf-8"))
        suite_registry = yaml.safe_load((ROOT / "config/test_suites.yaml").read_text(encoding="utf-8"))
        jsonschema.Draft7Validator(suite_schema).validate(suite_registry)
    except (OSError, json.JSONDecodeError, yaml.YAMLError, jsonschema.SchemaError, jsonschema.ValidationError) as exc:
        errors.append(f"test-suite registry/schema: {exc}")

    errors.extend(validate_workflow_cadence())

    status = "PASS" if not errors else "FAILED"
    print(json.dumps({
        "schema_version": 1,
        "status": status,
        "delivery_schema_count": len(delivery_schemas),
        "test_suite_schema": "config/test_suites.schema.json",
        "normal_pr_authority": NORMAL_PR_STATUS,
        "normal_pr_finalization_event": NORMAL_PR_FINALIZATION_EVENT,
        "errors": errors,
    }, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
