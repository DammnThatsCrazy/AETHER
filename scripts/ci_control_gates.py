#!/usr/bin/env python3
"""Run the always-on control gates for CI V2 (replaces the legacy ``universal-fast`` job).

The legacy authority ran the router's ``fast`` lane checks plus ``contracts`` on
every pull request. ``config/verification_router.yaml`` stays the single source
of which validators exist and their commands; this runner executes them all,
keeps going after a failure, and exits non-zero if any failed or timed out.

    python scripts/ci_control_gates.py            # run
    python scripts/ci_control_gates.py --list     # print the gate ids
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.processes import run_with_timeout, timeout_output  # noqa: E402
from scripts.lib.verification_router import load_router_registry  # noqa: E402

EXTRA_GATES = ("contracts",)  # in the router's `pr` lane, not its `fast` lane


def gate_ids(registry) -> list[str]:
    ids = list(registry.lanes["fast"]) + [g for g in EXTRA_GATES if g not in registry.lanes["fast"]]
    missing = [g for g in ids if g not in registry.checks]
    if missing:
        raise ValueError(f"control gates missing from the router registry: {', '.join(missing)}")
    return ids


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)
    registry = load_router_registry(ROOT / "config/verification_router.yaml")
    ids = gate_ids(registry)
    if args.list:
        print("\n".join(ids))
        return 0
    failed: list[str] = []
    for gate in ids:
        check = registry.checks[gate]
        command = list(check.command)
        if command and command[0] == "python":
            command[0] = sys.executable
        started = time.monotonic()
        try:
            proc = run_with_timeout(command, cwd=ROOT, env={**os.environ, "CI": os.environ.get("CI", "true")},
                                    timeout=check.runtime_budget_seconds)
            output, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = timeout_output(exc), 124
        seconds = time.monotonic() - started
        print(f"{'PASS' if code == 0 else 'FAIL'} {gate} ({seconds:.1f}s)", flush=True)
        if code:
            failed.append(gate)
            print(output[-4000:], flush=True)
    if failed:
        print(f"control gates failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"all {len(ids)} control gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
