#!/usr/bin/env python3
"""Validate AETHER source-of-truth ownership map enforcement.

The validator is intentionally change-aware: in CI it compares the PR against the
merge base with the base branch; locally it checks staged, unstaged, and
untracked files. For each changed source category in the ownership map, at least
one required derived surface must move in the same change set and each declared
validator command must be available.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "docs" / "source-of-truth" / "repo_consistency_ownership.json"


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True)


def _origin_base() -> str | None:
    candidates: list[str] = []
    base_ref = os.environ.get("GITHUB_BASE_REF")
    if base_ref:
        candidates.extend([f"origin/{base_ref}", base_ref])
    candidates.extend(["origin/main", "main"])
    for candidate in candidates:
        if git("rev-parse", "--verify", candidate).returncode == 0:
            merge_base = git("merge-base", "HEAD", candidate)
            if merge_base.returncode == 0 and merge_base.stdout.strip():
                return merge_base.stdout.strip()
    return None


def changed_files() -> list[str]:
    """Return changed files for CI/branch comparisons or local working trees."""
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        base = _origin_base()
        if base:
            diff = git("diff", "--name-only", f"{base}...HEAD")
            if diff.returncode == 0:
                return sorted({line for line in diff.stdout.splitlines() if line})

    changed: set[str] = set()
    for args in [("diff", "--name-only"), ("diff", "--cached", "--name-only")]:
        proc = git(*args)
        if proc.returncode == 0:
            changed.update(line for line in proc.stdout.splitlines() if line)
    untracked = git("ls-files", "--others", "--exclude-standard")
    if untracked.returncode == 0:
        changed.update(line for line in untracked.stdout.splitlines() if line)
    if changed:
        return sorted(changed)

    base = _origin_base()
    if base:
        diff = git("diff", "--name-only", f"{base}...HEAD")
        if diff.returncode == 0:
            return sorted({line for line in diff.stdout.splitlines() if line})
    return []


def _matches(path: str, patterns: list[str]) -> bool:
    included = False
    for pattern in patterns:
        negate = pattern.startswith("!")
        pat = pattern[1:] if negate else pattern
        alternates = [pat]
        if "/**/" in pat:
            alternates.append(pat.replace("/**/", "/"))
        if any(fnmatch(path, alt) or Path(path).match(alt) for alt in alternates):
            included = not negate
    return included


def _command_available(command: str) -> bool:
    parts = command.split()
    if not parts:
        return False
    if parts[0] in {"python", "python3"} and len(parts) > 1:
        script = parts[1]
        if script == "-m":
            return True
        return (ROOT / script).exists()
    if parts[0] == "npm":
        return (ROOT / "package.json").exists() and shutil.which("npm") is not None
    if parts[0] == "make" and len(parts) > 1:
        makefile = ROOT / "Makefile"
        return makefile.exists() and f"{parts[1]}:" in makefile.read_text(encoding="utf-8")
    if parts[0] == "git":
        return shutil.which("git") is not None
    return shutil.which(parts[0]) is not None


def main() -> int:
    if not MAP_PATH.exists():
        print(f"ownership validator failed: missing {MAP_PATH.relative_to(ROOT)}")
        return 1
    data: dict[str, Any] = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    categories = data.get("change_categories", [])
    if not isinstance(categories, list) or not categories:
        print("ownership validator failed: map has no change_categories")
        return 1

    changed = changed_files()
    if not changed:
        print("consistency ownership: no local/PR changes detected; map loaded successfully.")
        return 0

    failures: list[str] = []
    triggered = 0
    for category in categories:
        cid = category.get("id", "<missing-id>")
        source_globs = category.get("source_globs", [])
        required_globs = category.get("required_changed_globs", [])
        required_commands = category.get("required_commands", [])
        if not isinstance(source_globs, list) or not isinstance(required_globs, list):
            failures.append(f"{cid}: source_globs and required_changed_globs must be lists")
            continue
        source_hits = [path for path in changed if _matches(path, source_globs)]
        if not source_hits:
            continue
        triggered += 1
        derived_hits = [path for path in changed if _matches(path, required_globs)]
        if not derived_hits:
            failures.append(
                f"{cid}: changed {source_hits}, but none of required surfaces changed: {required_globs}. "
                f"Remediation: {category.get('remediation', 'update required derived surfaces')}"
            )
        missing_commands = [cmd for cmd in required_commands if not _command_available(cmd)]
        if missing_commands:
            failures.append(f"{cid}: required validator/remediation commands are unavailable: {missing_commands}")

    if failures:
        print("consistency ownership validation failed:")
        print("Changed files considered:")
        for path in changed:
            print(f"  - {path}")
        print("Failures:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nRun: make repo-doctor-fix && make ci-check")
        return 1

    print(
        f"consistency ownership: {len(changed)} changed file(s), "
        f"{triggered} ownership categor(ies) triggered, all required surfaces/commands present."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
