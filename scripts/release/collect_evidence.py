#!/usr/bin/env python3
"""Assemble the founding-tenant evidence bundle index.

Runs the founding-tenant config validators as subprocesses, records their
exit codes, and emits an evidence index (YAML). This is an INDEX, not a gate —
it always exits 0. The individual `make validate-*` targets are the gates.

Usage:
  python scripts/release/collect_evidence.py            # YAML index to stdout
  python scripts/release/collect_evidence.py --out FILE # also write to FILE
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import repo_root  # noqa: E402

import yaml  # noqa: E402

EVIDENCE_CHECKS = [
    ("foundation", "scripts/release/check_foundation.py"),
    ("profile_config", "scripts/release/check_profile_config.py"),
    ("cost_policy", "scripts/release/check_cost_policy.py"),
    ("route_registry", "scripts/release/check_route_registry.py"),
    ("storage_policies", "scripts/release/check_storage_policies.py"),
]


def _run(script: str) -> dict:
    start = datetime.datetime.now(datetime.timezone.utc)
    try:
        proc = subprocess.run(
            [sys.executable, script], cwd=repo_root(),
            capture_output=True, text=True, timeout=120,
        )
        code = proc.returncode
    except Exception as exc:  # pragma: no cover
        return {"script": script, "exit_code": 1, "error": str(exc)}
    dur = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
    return {"script": script, "exit_code": code, "duration_s": round(dur, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    results = {name: _run(script) for name, script in EVIDENCE_CHECKS}
    passed = sum(1 for v in results.values() if v.get("exit_code") == 0)

    index = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "release_train": "FOUNDING_TENANT_PRODUCTION",
        "evidence_checks": results,
        "summary": {"total": len(results), "passed": passed,
                    "failed": len(results) - passed},
        "docs": [
            "docs/FOUNDING-TENANT-PRODUCTION.md",
            "docs/DEPLOYMENT-PROFILES.md",
            "docs/RELEASE-EVIDENCE.md",
        ],
    }
    text = yaml.safe_dump(index, sort_keys=False)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
