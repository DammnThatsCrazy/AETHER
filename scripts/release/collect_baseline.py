#!/usr/bin/env python3
"""Emit the founding-tenant baseline artifact (git state + gate inventory).

Produces the machine-readable baseline described in the monoprompt §5: branch,
commit sha, dirty status, and the founding-tenant gate command inventory.
Informational — always exits 0.

Usage:
  python scripts/release/collect_baseline.py            # YAML to stdout
  python scripts/release/collect_baseline.py --out FILE # also write to FILE
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

FOUNDING_TENANT_GATES = [
    "make validate-profile-config",
    "make validate-cost-policy",
    "make validate-route-registry",
    "make validate-storage-policies",
    "make audit-readiness-check",
    "make ci-check",
    "make founding-tenant-release-gate",
]


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root(),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="Write the artifact to this path too")
    args = ap.parse_args()

    dirty = _git("status", "--short")
    artifact = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "release_train": "FOUNDING_TENANT_PRODUCTION",
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit_sha": _git("rev-parse", "HEAD"),
        "dirty_status": "dirty" if dirty else "clean",
        "founding_tenant_gates": FOUNDING_TENANT_GATES,
        "control_spine": {
            "ledger": "config/implementation_ledger.yaml",
            "control_catalog": "config/control_catalog.yaml",
            "posture": "config/posture/founding_tenant_production.yaml",
            "deployment_profiles": "config/deployment_profiles.yaml",
        },
    }

    text = yaml.safe_dump(artifact, sort_keys=False)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"# baseline written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
