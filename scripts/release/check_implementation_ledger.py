#!/usr/bin/env python3
"""Fail closed when the implementation ledger overstates release truth."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _common import Reporter, load_yaml, main_guard

ALLOWED_STATUS = {
    "not_started",
    "reproduced",
    "test_added",
    "implementation_in_progress",
    "implemented",
    "targeted_tests_pass",
    "subsystem_tests_pass",
    "full_gate_pass",
    "externally_blocked",
    "verified_complete",
}
TERMINAL_STATUS = {
    "implemented",
    "targeted_tests_pass",
    "subsystem_tests_pass",
    "full_gate_pass",
    "verified_complete",
}
_REQUIRED_FIELDS = {
    "id",
    "title",
    "domain",
    "severity",
    "release_class",
    "customer_impact",
    "current_behavior",
    "required_behavior",
    "affected_paths",
    "tests_required",
    "evidence_required",
    "docs_required",
    "owner",
    "status",
    "blocked_by",
    "exception",
    "last_verified_commit",
}
_COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")


def validate_ledger(document: Any, *, root: Path = Path(".")) -> list[str]:
    """Return all truthfulness/schema violations without stopping at the first."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["ledger must be an object"]
    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    items = document.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["items must be a non-empty list"]

    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"items[{index}] must be an object")
            continue
        item_id = str(item.get("id") or f"items[{index}]")
        missing = sorted(_REQUIRED_FIELDS - set(item))
        if missing:
            errors.append(f"{item_id}: missing fields {missing}")
        if item_id in ids:
            errors.append(f"{item_id}: duplicate id")
        ids.add(item_id)

    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "?")
        status = item.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(f"{item_id}: invalid status {status!r}")
            continue

        exception = item.get("exception")
        if status in TERMINAL_STATUS and exception not in (None, ""):
            errors.append(
                f"{item_id}: terminal status {status!r} cannot carry an exception"
            )
        if status == "externally_blocked" and not exception:
            errors.append(f"{item_id}: externally_blocked requires an exception")
        if status == "verified_complete":
            commit = str(item.get("last_verified_commit") or "")
            if not _COMMIT_RE.fullmatch(commit):
                errors.append(
                    f"{item_id}: verified_complete requires a git commit SHA"
                )

        blockers = item.get("blocked_by")
        if not isinstance(blockers, list):
            errors.append(f"{item_id}: blocked_by must be a list")
        else:
            for blocker in blockers:
                if blocker == item_id:
                    errors.append(f"{item_id}: cannot block itself")
                elif blocker not in ids:
                    errors.append(f"{item_id}: unknown blocker {blocker!r}")

        for field in ("affected_paths", "tests_required", "evidence_required", "docs_required"):
            if not isinstance(item.get(field), list):
                errors.append(f"{item_id}: {field} must be a list")

        if status not in {"not_started", "externally_blocked"}:
            for path_value in item.get("affected_paths") or []:
                if not isinstance(path_value, str):
                    errors.append(f"{item_id}: affected path must be a string")
                    continue
                if not (root / path_value).exists():
                    errors.append(f"{item_id}: affected path does not exist: {path_value}")
            for path_value in item.get("docs_required") or []:
                if not isinstance(path_value, str):
                    errors.append(f"{item_id}: docs path must be a string")
                    continue
                if not (root / path_value).exists():
                    errors.append(f"{item_id}: required doc does not exist: {path_value}")

    return errors


def check() -> int:
    reporter = Reporter("IMPLEMENTATION LEDGER — release truth")
    try:
        document = load_yaml("config/implementation_ledger.yaml")
    except FileNotFoundError:
        reporter.fail("config/implementation_ledger.yaml not found")
        return reporter.finish()

    errors = validate_ledger(document)
    if errors:
        for error in errors:
            reporter.fail(error)
    else:
        reporter.ok("ledger schema, blockers, paths, and terminal claims are honest")
    return reporter.finish()


if __name__ == "__main__":
    main_guard(check)
