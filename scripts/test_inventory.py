#!/usr/bin/env python3
"""Inventory tests, validate quarantine debt, and select affected tests."""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "test_inventory.yaml"
TEST_PATTERNS = (
    "**/test_*.py", "**/*_test.py",
    "**/*.test.js", "**/*.test.jsx", "**/*.test.mjs", "**/*.test.cjs",
    "**/*.spec.js", "**/*.spec.jsx", "**/*.spec.mjs", "**/*.spec.cjs",
    "**/*.test.ts", "**/*.test.tsx", "**/*.spec.ts", "**/*.spec.tsx",
)
REQUIRED = (
    "owner", "domain", "contract_protected", "risk", "runtime_budget_seconds",
    "dependencies", "flakiness", "execution_lane", "status", "disposition",
)


def matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.endswith("/**") and path.startswith(pattern[:-3])
    )


def tracked_tests() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True,
    ).stdout.decode("utf-8", errors="surrogateescape")
    return sorted(path for path in output.split("\0") if path and any(matches(path, p) for p in TEST_PATTERNS))


def build_inventory(config: dict, paths: list[str]) -> list[dict]:
    records = []
    quarantines = {item["test_id"]: item for item in config.get("quarantines", [])}
    for path in paths:
        metadata = dict(config["defaults"])
        for rule in config.get("rules", []):
            if any(matches(path, pattern) for pattern in rule["paths"]):
                metadata.update({key: value for key, value in rule.items() if key != "paths"})
        metadata.update({"test_id": path, "path": path})
        if path in quarantines:
            metadata.update({"disposition": "QUARANTINE", "quarantine": quarantines[path]})
        records.append(metadata)
    return records


def violations(config: dict, records: list[dict], today: date | None = None) -> list[str]:
    errors: list[str] = []
    today = today or date.today()
    known = {record["test_id"] for record in records}
    for record in records:
        missing = [field for field in REQUIRED if record.get(field) in (None, "")]
        if missing:
            errors.append(f"{record['test_id']}: missing {', '.join(missing)}")
    for quarantine in config.get("quarantines", []):
        test_id = quarantine.get("test_id", "<missing>")
        missing = [field for field in ("test_id", "owner", "reason", "expires") if not quarantine.get(field)]
        if missing:
            errors.append(f"quarantine {test_id}: missing {', '.join(missing)}")
            continue
        if test_id not in known:
            errors.append(f"quarantine {test_id}: test is not tracked")
        try:
            if date.fromisoformat(str(quarantine["expires"])) < today:
                errors.append(f"quarantine {test_id}: expired {quarantine['expires']}")
        except ValueError:
            errors.append(f"quarantine {test_id}: expires must be YYYY-MM-DD")
    return errors


def affected(records: list[dict], changed: list[str]) -> list[str]:
    """Return runnable tests whose source or declared dependencies changed.

    A changed test must always select itself, even when its dependency list is
    intentionally empty. Quarantined, deleted, and inactive tests remain in
    the inventory/debt report but must not leak into an executable selection.
    """
    runnable_dispositions = {"KEEP", "CONSOLIDATE", "MOVE_TO_INTEGRATION", "MOVE_TO_NIGHTLY", "MOVE_TO_RELEASE"}
    return [
        record["test_id"]
        for record in records
        if record.get("status") == "active"
        and record.get("disposition") in runnable_dispositions
        and any(
            path == record["path"]
            or any(matches(path, dependency) for dependency in record["dependencies"])
            for path in changed
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true", help="omit per-test records from stdout")
    args = parser.parse_args()
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise SystemExit("test inventory schema_version must be 1")
    records = build_inventory(config, tracked_tests())
    errors = violations(config, records)
    result = {
        "schema_version": 1,
        "status": "FAILED" if errors else "PASS",
        "test_count": len(records),
        "tests": records,
        "affected_tests": affected(records, args.changed_file),
        "debt": {"quarantined": sum(r["disposition"] == "QUARANTINE" for r in records), "violations": errors},
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    elif args.summary:
        print(json.dumps({key: value for key, value in result.items() if key != "tests"}, indent=2))
    else:
        print(rendered, end="")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
