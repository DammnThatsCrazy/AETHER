#!/usr/bin/env python3
"""Build only what a change affects (CI V2; replaces legacy ``build-node`` and ``build-backend-image``).

Uses the same Build Selection v2 the legacy authority consumed, derived from the
Impact Graph by ``scripts/verification_execution_plan.py``: dependency-first npm
workspace builds, plus the backend image when ``services/api`` or the Python
dependency graph changed. Nothing is archived or published.

    python scripts/ci_build_selected.py --base <sha>
    python scripts/ci_build_selected.py --base <sha> --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def selection(base: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "plan.json"
        proc = subprocess.run(
            [sys.executable, "scripts/verification_execution_plan.py", "--base", base, "--output", str(out)],
            cwd=ROOT, capture_output=True, text=True)
        if not out.exists():
            raise SystemExit(f"cannot derive the build selection: {proc.stderr.strip()}")
        plan = json.loads(out.read_text(encoding="utf-8"))
    if plan.get("status") != "READY":
        raise SystemExit(f"execution plan is {plan.get('status')}: {plan.get('reason', 'unknown')}")
    return plan["build"]


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT, env=os.environ).returncode:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=os.environ.get("CI_BASE_SHA"), required=not os.environ.get("CI_BASE_SHA"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    build = selection(args.base)
    workspaces = list(build.get("workspaces") or []) if build.get("node_required") else []
    print(f"workspaces: {workspaces or 'none'}; backend_image: {bool(build.get('backend_image'))}")
    if args.dry_run:
        return 0
    if workspaces:
        if not (ROOT / "node_modules").is_dir():  # the CI checks job has already installed
            run(["npm", "ci", "--ignore-scripts"])
        for ws in workspaces:
            manifest = json.loads((ROOT / ws / "package.json").read_text(encoding="utf-8"))
            if (manifest.get("scripts") or {}).get("build"):
                run(["npm", "run", "build", f"--workspace={ws}"])
    if build.get("backend_image"):
        if not (ROOT / "services/api/Dockerfile").is_file():
            raise SystemExit("services/api/Dockerfile is missing")
        run(["docker", "build", "--file", "services/api/Dockerfile", "--tag", "aether-backend:ci", "."])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
