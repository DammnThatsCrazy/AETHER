#!/usr/bin/env python3
"""Staging infrastructure plan/validate — never applies.

Validates the canonical Terraform tree and, when the terraform/tofu binary is
available, runs `terraform validate` (and `terraform plan` only when explicitly
enabled with real backend/credentials). With no binary or credentials the
structural validation still runs and the live steps SKIP honestly. This target
NEVER runs `terraform apply`.

Structural (always, credentialless):
  * canonical modules present with a main.tf each;
  * root main.tf + versions.tf + per-profile tfvars present;
  * stale duplicate tree (AWS Deployment/mnt) absent;
  * capability matrix (config/deploy_profile.yaml) is internally consistent.

Live (gated):
  * `terraform validate`   when terraform/tofu is installed;
  * `terraform plan`       only when STAGING_INFRA_PLAN=1 AND credentials are
                           present (an -out plan, still no apply).

Exit 0 iff structural checks pass and any executed live step passes.

Usage:
  make staging-infra-plan
  STAGING_INFRA_PLAN=1 python scripts/staging_infra_plan.py --profile staging
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TF_ROOT = ROOT / "AWS Deployment" / "aether-aws" / "terraform"
TF_MODULES = TF_ROOT / "modules"
STALE_MNT = ROOT / "AWS Deployment" / "mnt"

EXPECTED_MODULES = {
    "alb", "aurora", "auth0", "dynamodb_cache", "ecr", "ecs", "elasticache",
    "ml_drift_lambda", "monitoring", "msk", "neptune", "rds", "s3", "secrets",
    "sqs", "vpc", "vpc_endpoints",
}


def _line(status: str, name: str, detail: str = "") -> tuple[str, str, str]:
    return (status, name, detail)


def structural() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.append(_line("FAIL" if STALE_MNT.exists() else "PASS", "stale-tree-absent",
                      str(STALE_MNT) if STALE_MNT.exists() else "AWS Deployment/mnt removed"))
    present = {p.name for p in TF_MODULES.iterdir() if p.is_dir()} if TF_MODULES.is_dir() else set()
    missing = EXPECTED_MODULES - present
    no_main = [m for m in EXPECTED_MODULES & present if not (TF_MODULES / m / "main.tf").is_file()]
    rows.append(_line("PASS" if not missing and not no_main else "FAIL", "modules-intact",
                      f"{len(EXPECTED_MODULES & present)}/{len(EXPECTED_MODULES)} modules"
                      + (f" missing={sorted(missing)}" if missing else "")
                      + (f" no_main={no_main}" if no_main else "")))
    root_ok = (TF_ROOT / "main.tf").is_file() and (TF_ROOT / "versions.tf").is_file() \
        and any((TF_ROOT / "profiles").glob("*.tfvars"))
    rows.append(_line("PASS" if root_ok else "FAIL", "root-and-profiles",
                      "main.tf + versions.tf + profiles/*.tfvars"))
    cap = subprocess.run([sys.executable, "scripts/staging_capability_matrix.py"],
                         cwd=ROOT, capture_output=True, text=True)
    rows.append(_line("PASS" if cap.returncode == 0 else "FAIL", "capability-matrix",
                      "deploy-profile topology consistent" if cap.returncode == 0 else "matrix drift"))
    return rows


def live(profile: str) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    tf = shutil.which("terraform") or shutil.which("tofu")
    if not tf:
        rows.append(_line("SKIP", "terraform-validate", "terraform/tofu not installed"))
        rows.append(_line("SKIP", "terraform-plan", "terraform/tofu not installed"))
        return rows
    val = subprocess.run([tf, f"-chdir={TF_ROOT}", "validate"], capture_output=True, text=True)
    rows.append(_line("PASS" if val.returncode == 0 else "FAIL", "terraform-validate",
                      "ok" if val.returncode == 0 else val.stderr.strip()[-200:]))
    creds = bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))
    if os.environ.get("STAGING_INFRA_PLAN") == "1" and creds:
        tfvars = TF_ROOT / "profiles" / f"{profile}.tfvars"
        plan = subprocess.run([tf, f"-chdir={TF_ROOT}", "plan", "-input=false",
                               f"-var-file=profiles/{tfvars.name}", "-out=/dev/null"],
                              capture_output=True, text=True)
        rows.append(_line("PASS" if plan.returncode == 0 else "FAIL", "terraform-plan",
                          "plan ok (no apply)" if plan.returncode == 0 else plan.stderr.strip()[-200:]))
    else:
        rows.append(_line("SKIP", "terraform-plan",
                          "set STAGING_INFRA_PLAN=1 with AWS creds to dry-plan (still no apply)"))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="staging")
    args = ap.parse_args(argv)

    rows = structural() + live(args.profile)
    print("=" * 70)
    print("AETHER STAGING INFRA PLAN (validate only — never applies)")
    print("=" * 70)
    width = max(len(n) for _, n, _ in rows) + 2
    for status, name, detail in rows:
        print(f"  [{status}] {name:<{width}} {detail}")
    failed = [n for s, n, _ in rows if s == "FAIL"]
    print("-" * 70)
    print(f"RESULT: {'FAIL' if failed else 'PASS'}")
    print("=" * 70)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
