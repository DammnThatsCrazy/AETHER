#!/usr/bin/env python3
"""Replay historical commits through the legacy router and the CI V2 selector.

Shadow-phase tool (CI V2 parity protocol); delete with the legacy router at
cutover. For each commit C it compares the PR-lane suites the legacy
`check_router.py` selects for C^..C with the suites `ci_select.py` selects, and
reports any suite the legacy router selected that V2 did not (a selection gap).

    python scripts/ci_parity.py --rev origin/Development --count 25
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", default="origin/development")
    ap.add_argument("--count", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    commits = run(["git", "rev-list", "--no-merges", f"--max-count={args.count}", args.rev], ROOT).split()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        wt = Path(tmp) / "wt"
        run(["git", "worktree", "add", "--detach", str(wt), commits[0]], ROOT)
        try:
            # V2 selector + rules come from the working tree under test (HEAD of ROOT);
            # the legacy router runs inside each historical checkout.
            sys.path.insert(0, str(ROOT))
            import yaml
            from scripts import ci_select

            rules, suites = ci_select.load()
            pr = {i for i, s in suites.items() if s["lane"] == "pr"}
            for c in commits:
                run(["git", "checkout", "-q", "--detach", c], wt)
                try:
                    old = json.loads(run([sys.executable, "scripts/check_router.py", "--base", f"{c}^"], wt))
                    old_suites = {x["check_id"] for x in old["checks"]} & pr
                except Exception as exc:  # legacy router unusable on that commit
                    rows.append({"commit": c[:8], "error": str(exc)[:80]})
                    continue
                paths = ci_select.changed_paths(f"{c}^", c)
                new = ci_select.select(paths, rules, suites)
                new_suites = set(new["suites"]) & pr
                rows.append({
                    "commit": c[:8], "files": len(paths), "mode": new["mode"],
                    "legacy": len(old_suites), "v2": len(new_suites),
                    "gap": sorted(old_suites - new_suites), "extra": len(new_suites - old_suites),
                })
        finally:
            run(["git", "worktree", "remove", "--force", str(wt)], ROOT)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print(r)
        ok = [r for r in rows if "gap" in r]
        print(f"\ncommits compared: {len(ok)}; with gaps: {sum(1 for r in ok if r['gap'])}; "
              f"legacy-router errors: {len(rows) - len(ok)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
