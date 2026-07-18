#!/usr/bin/env python3
"""Validate the canonical deploy-profile capability matrix (fail-closed).

Reads config/deploy_profile.yaml and proves the SAME profile spans
local -> staging -> prod:

  * every required capability is represented (present / partial / optional /
    or an explicitly documented `gap`);
  * every declared LOCAL compose service actually exists in docker-compose.yml;
  * every declared CLOUD terraform module actually exists under the modules dir;
  * every declared runtime role is a real role in services/runtime/roles.py;
  * every non-present capability (`gap`) carries an honest `gap` note.

Exit 0 iff the matrix is internally consistent with the repo. This does NOT
require Docker, terraform, or cloud credentials — it validates declared topology
against files on disk.

Usage:
    python scripts/staging_capability_matrix.py
    python scripts/staging_capability_matrix.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "config" / "deploy_profile.yaml"
ROLES_PY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "runtime" / "roles.py"


def _compose_services() -> set[str]:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8")) or {}
    return set((doc.get("services") or {}).keys())


def _terraform_modules(modules_dir: str) -> set[str]:
    d = ROOT / modules_dir
    return {p.name for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()


def _runtime_roles() -> set[str]:
    """Parse WORKER_ROLES + {'api','all'} from roles.py without importing it."""
    text = ROLES_PY.read_text(encoding="utf-8")
    roles: set[str] = set()
    block = re.search(r"WORKER_ROLES[^{]*\{([^}]*)\}", text, re.DOTALL)
    if block:
        roles |= set(re.findall(r'"([a-z-]+)"', block.group(1)))
    return roles | {"api", "all"}


def _local_services(cap: dict) -> list[str]:
    local = cap.get("local") or {}
    svcs: list[str] = []
    if "compose_service" in local:
        svcs.append(local["compose_service"])
    svcs.extend(local.get("compose_services") or [])
    return svcs


def _declared_roles(cap: dict) -> list[str]:
    roles = []
    if "role" in cap:
        roles.append(cap["role"])
    roles.extend(cap.get("roles") or [])
    return roles


def _cloud_module(cap: dict):
    return (cap.get("cloud") or {}).get("terraform_module")


def check() -> dict:
    errors: list[str] = []
    matrix = yaml.safe_load(MATRIX.read_text(encoding="utf-8")) or {}
    required = set(matrix.get("required_capabilities") or [])
    caps = matrix.get("capabilities") or []
    modules_dir = matrix.get("terraform_modules_dir", "AWS Deployment/aether-aws/terraform/modules")

    compose = _compose_services()
    modules = _terraform_modules(modules_dir)
    roles = _runtime_roles()

    seen = {c.get("id") for c in caps}
    missing_caps = sorted(required - seen)
    if missing_caps:
        errors.append(f"required capabilities missing from matrix: {missing_caps}")

    for cap in caps:
        cid = cap.get("id", "?")
        status = cap.get("status")
        if status not in {"present", "partial", "optional", "gap"}:
            errors.append(f"{cid}: invalid status {status!r}")
            continue
        if status == "gap":
            if not cap.get("gap"):
                errors.append(f"{cid}: status=gap requires a 'gap' note")
            continue  # gaps are not asserted to exist
        # asserted capabilities: verify declared representations resolve
        for svc in _local_services(cap):
            if svc not in compose:
                errors.append(f"{cid}: compose service '{svc}' not in docker-compose.yml")
        mod = _cloud_module(cap)
        if mod and mod not in modules:
            errors.append(f"{cid}: terraform module '{mod}' not found under {modules_dir}")
        for role in _declared_roles(cap):
            if role not in roles:
                errors.append(f"{cid}: runtime role '{role}' not in roles.py")
        if status == "partial" and not cap.get("gap"):
            errors.append(f"{cid}: status=partial should document remaining scope via 'gap'")

    return {
        "passed": not errors,
        "counts": {
            "capabilities": len(caps),
            "required": len(required),
            "compose_services": len(compose),
            "terraform_modules": len(modules),
            "runtime_roles": len(roles),
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = check()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1

    print("=" * 70)
    print("AETHER DEPLOY-PROFILE CAPABILITY MATRIX")
    print("=" * 70)
    c = result["counts"]
    print(f"capabilities={c['capabilities']} required={c['required']} "
          f"compose_services={c['compose_services']} tf_modules={c['terraform_modules']} "
          f"roles={c['runtime_roles']}")
    if result["errors"]:
        print("-" * 70)
        for e in result["errors"]:
            print(f"  ERROR: {e}")
    print("-" * 70)
    print(f"RESULT: {'PASS' if result['passed'] else 'FAIL'}")
    print("=" * 70)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
