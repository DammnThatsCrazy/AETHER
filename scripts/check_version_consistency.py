#!/usr/bin/env python3
"""Aggregate version/workspace consistency gate.

pyproject.toml remains the single version source of truth (see CLAUDE.md).
This script does not introduce a second source; it aggregates the existing
checks and adds workspace-coverage validation:
  1. scripts/bump_version.py --check   (pyproject <-> package.json/native constants)
  2. scripts/validate_sdk_release_alignment.py (SDK metadata + endpoint drift)
  3. root package.json workspaces cover every intended npm package
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_WORKSPACE_MEMBERS = [
    "packages/shared",
    "packages/web",
    "packages/react-native",
    "frontend/aether",
    "frontend/kyber",
    "frontend/shared",
]


def run_delegated(script: str, *args: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output


def check_workspace_coverage(root: Path = ROOT) -> list[str]:
    """Return uncovered required members given the root package.json workspaces."""
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    workspaces = package.get("workspaces", [])
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])
    missing = []
    for member in REQUIRED_WORKSPACE_MEMBERS:
        if not (root / member / "package.json").exists():
            continue
        if not any(fnmatch.fnmatch(member, pattern.rstrip("/")) for pattern in workspaces):
            missing.append(member)
    return missing


def main() -> int:
    as_json = "--json" in sys.argv
    results: list[dict] = []

    for name, script, args in [
        ("version alignment (bump_version --check)", "bump_version.py", ("--check",)),
        ("sdk release alignment", "validate_sdk_release_alignment.py", ()),
    ]:
        passed, output = run_delegated(script, *args)
        detail = output.splitlines()[-1] if output else ""
        results.append({"name": name, "passed": passed, "detail": detail})

    uncovered = check_workspace_coverage()
    results.append(
        {
            "name": "workspace coverage",
            "passed": not uncovered,
            "detail": f"uncovered members: {uncovered}" if uncovered else "all required members covered",
        }
    )

    ok = all(r["passed"] for r in results)
    if as_json:
        print(json.dumps({"passed": ok, "checks": results}, indent=2))
    else:
        for r in results:
            print(f"  [{'PASS' if r['passed'] else 'FAIL'}] {r['name']} — {r['detail']}")
        print(
            "Version consistency check "
            + ("passed." if ok else "FAILED — fix the items above; pyproject.toml owns the platform version.")
        )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
