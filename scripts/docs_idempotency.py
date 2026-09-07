#!/usr/bin/env python3
"""Verify that the repository documentation generators are idempotent.

The first generation pass is allowed to reconcile a stale checkout. The
second pass must produce byte-identical generated and sync-managed outputs.
This comparison is intentionally independent of Git's pre-existing diff so
the command can diagnose determinism even when a baseline is being updated.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_PATHS = (
    ROOT / "docs" / "_generated",
    ROOT / "docs" / "REPO-INDEX.md",
    ROOT / "docs" / "AUTOMATION.md",
)


def snapshot_outputs() -> dict[str, bytes]:
    """Return generated outputs keyed by repo-relative path."""
    snapshot: dict[str, bytes] = {}
    for path in GENERATED_PATHS:
        if path.is_dir():
            files = sorted(item for item in path.rglob("*") if item.is_file())
            for item in files:
                snapshot[str(item.relative_to(ROOT))] = item.read_bytes()
        elif path.is_file():
            snapshot[str(path.relative_to(ROOT))] = path.read_bytes()
    return snapshot


def generate_once() -> bool:
    """Run the same two generators used by ``make docs-fix``."""
    for command in (
        [sys.executable, "scripts/docs_extract/run_all.py"],
        [sys.executable, "scripts/sync_docs.py"],
    ):
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            return False
    return True


def main() -> int:
    if not generate_once():
        return 1
    first = snapshot_outputs()

    if not generate_once():
        return 1
    second = snapshot_outputs()

    if first == second:
        print(
            "docs_idempotency: PASS — second generation produced zero diff "
            f"across {len(second)} generated/sync-managed files."
        )
        return 0

    changed = sorted(
        path
        for path in set(first) | set(second)
        if first.get(path) != second.get(path)
    )
    print("docs_idempotency: FAIL — same inputs produced different output:")
    for path in changed:
        print(f"  - {path}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
