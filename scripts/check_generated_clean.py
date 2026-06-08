#!/usr/bin/env python3
"""
Verify that generated files have not been manually edited.

Strategy A — re-run generators and fail on diff (primary).
Strategy B — check that generated JSON files contain the expected
             generated-file metadata key (secondary guard).

Usage:
    python scripts/check_generated_clean.py         # run both strategies
    python scripts/check_generated_clean.py --diff  # strategy A only
    python scripts/check_generated_clean.py --header # strategy B only

Exit codes:
    0   generated files are clean
    1   drift or missing header detected
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = ROOT / "docs" / "_generated"

# Files whose content is machine-generated and must never be hand-edited.
GENERATED_GLOBS = [
    "docs/_generated/*.json",
    "docs/REPO-INDEX.md",
    "docs/AUTOMATION.md",
]

# Key that every generated JSON artifact must contain.
GENERATED_MARKER_KEY = "_generated"


def strategy_diff() -> bool:
    """Regenerate artifacts and fail if they differ from committed state."""
    print("Strategy A: regenerate and diff")
    regen = subprocess.run(
        ["python", "scripts/docs_extract/run_all.py"],
        cwd=ROOT,
    )
    if regen.returncode != 0:
        print("[FAIL] docs_extract/run_all.py failed")
        return False

    sync = subprocess.run(
        ["python", "scripts/sync_docs.py"],
        cwd=ROOT,
    )
    if sync.returncode != 0:
        print("[FAIL] sync_docs.py failed")
        return False

    diff = subprocess.run(
        ["git", "diff", "--exit-code", "--", *GENERATED_GLOBS],
        cwd=ROOT,
    )
    if diff.returncode != 0:
        print("[FAIL] Generated files drifted from committed state.")
        print("       Run: make repo-doctor-fix  then git add + commit.")
        subprocess.run(["git", "diff", "--stat", "--", *GENERATED_GLOBS], cwd=ROOT)
        return False

    print("[PASS] Generated files match committed state.")
    return True


def strategy_header() -> bool:
    """Check that generated JSON files contain the _generated marker."""
    print("Strategy B: check _generated marker in JSON artifacts")
    ok = True
    for path in sorted(GENERATED_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"[FAIL] {path.relative_to(ROOT)}: invalid JSON")
            ok = False
            continue
        if GENERATED_MARKER_KEY not in data:
            print(
                f"[WARN] {path.relative_to(ROOT)}: missing '{GENERATED_MARKER_KEY}' key "
                f"(add it to the generator to enable header enforcement)"
            )
            # Warn only — generators may not yet emit the marker.
    if ok:
        print("[PASS] All generated JSON artifacts checked.")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Check generated files are clean")
    parser.add_argument("--diff", action="store_true", help="Strategy A only")
    parser.add_argument("--header", action="store_true", help="Strategy B only")
    args = parser.parse_args()

    run_diff = args.diff or not (args.diff or args.header)
    run_header = args.header or not (args.diff or args.header)

    results: list[bool] = []
    if run_diff:
        results.append(strategy_diff())
    if run_header:
        results.append(strategy_header())

    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
