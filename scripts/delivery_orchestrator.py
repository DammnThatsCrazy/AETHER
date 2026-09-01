#!/usr/bin/env python3
"""Fail-closed repository-side staging, migration, and journey orchestration."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write(result: dict, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"DRY_RUN", "DEPLOYED", "PASS", "NOT_APPLICABLE"} else 1


def run(command: str) -> tuple[str, str]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return "FAILED", f"invalid command: {exc}"
    if not argv:
        return "BLOCKED", "required command was not configured"
    try:
        completed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    except OSError as exc:
        return "BLOCKED", f"command prerequisite unavailable: {exc}"
    detail = (completed.stdout + completed.stderr).strip()[-4000:]
    return ("PASS", detail) if completed.returncode == 0 else ("FAILED", detail or f"exit {completed.returncode}")


def candidate(path: Path) -> dict:
    data = json.loads(path.read_text())
    if not data.get("release_candidate_id") or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(data.get("artifact_digest", ""))):
        raise ValueError("candidate lacks release_candidate_id or artifact_digest")
    return data


def staging(args: argparse.Namespace) -> int:
    try:
        rc = candidate(args.candidate)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"schema_version": 1, "release_candidate_id": "unknown", "profile": args.profile,
                  "artifact_digest": "sha256:" + "0" * 64, "status": "BLOCKED",
                  "checks": [{"check_id": "release_candidate", "status": "BLOCKED", "reason": str(exc)}], "timestamp": now()}
        return write(result, args.output)
    checks: list[dict] = []
    compatible_profiles = rc.get("deployment_profiles", [])
    if compatible_profiles and args.profile not in compatible_profiles:
        checks.append({"check_id": "profile_compatibility", "status": "BLOCKED", "reason": f"candidate is not compatible with {args.profile}"})
        status = "BLOCKED"
    elif args.dry_run:
        for name in ("preflight", "deploy", "migration", "tenant_activation", "golden_journeys"):
            checks.append({"check_id": name, "status": "NOT_APPLICABLE", "reason": "dry-run; command not executed"})
        status = "DRY_RUN"
    elif not os.environ.get("AWS_ACCESS_KEY_ID") and not os.environ.get("AWS_PROFILE"):
        checks.append({"check_id": "aws_credentials", "status": "BLOCKED", "reason": "AWS_ACCESS_KEY_ID or AWS_PROFILE is required"})
        status = "BLOCKED"
    else:
        status = "DEPLOYED"
        identity_status, identity_detail = run("aws sts get-caller-identity --output json")
        checks.append({"check_id": "aws_identity", "status": identity_status, "reason": identity_detail or "AWS identity resolved"})
        if identity_status != "PASS":
            status = "BLOCKED" if identity_status == "BLOCKED" else "FAILED"
        commands = {
            "preflight": args.preflight_command,
            "deploy": args.deploy_command,
            "migration": args.migration_command,
            "tenant_activation": args.tenant_activation_command,
            "golden_journeys": args.journeys_command,
        }
        for name in (() if status != "DEPLOYED" else commands):
            outcome, detail = run(commands[name])
            checks.append({"check_id": name, "status": outcome, "reason": detail or "command passed"})
            if outcome != "PASS":
                status = "BLOCKED" if outcome == "BLOCKED" else "FAILED"
                break
    result = {"schema_version": 1, "release_candidate_id": rc["release_candidate_id"], "profile": args.profile,
              "artifact_digest": rc["artifact_digest"], "status": status, "checks": checks, "timestamp": now()}
    return write(result, args.output)


def migration(args: argparse.Namespace) -> int:
    try:
        metadata = yaml.safe_load(args.metadata.read_text())
    except (OSError, yaml.YAMLError) as exc:
        metadata = {}
        error = str(exc)
    else:
        error = ""
    required = ("migration_id", "owner", "from_version", "to_version", "compatibility", "expected_duration_seconds", "validation", "repair_strategy", "staging_rehearsal_required")
    missing = [key for key in required if not metadata.get(key) and metadata.get(key) is not False]
    status, evidence = "PASS", []
    if error or missing:
        status, evidence = "BLOCKED", [error or f"missing migration metadata: {', '.join(missing)}"]
    elif args.dry_run:
        status, evidence = "NOT_APPLICABLE", ["dry-run; migration not executed"]
    elif not os.environ.get("DATABASE_URL"):
        status, evidence = "BLOCKED", ["DATABASE_URL is required for migration rehearsal"]
    else:
        status, detail = run(args.command)
        evidence.append(detail or "migration command passed")
        if status == "PASS":
            status, detail = run(args.validation_command)
            evidence.append(detail or "validation command passed")
    result = {
        "schema_version": 1,
        **{key: metadata.get(key) for key in required},
        "status": status,
        "evidence": evidence,
    }
    return write(result, args.output)


def journeys(args: argparse.Namespace) -> int:
    registry = yaml.safe_load((ROOT / "config/golden_journeys.yaml").read_text())
    checks, overall = [], "PASS"
    for journey_id, item in registry["journeys"].items():
        if item.get("implementation_status") != "IMPLEMENTED":
            outcome, detail = "BLOCKED", item.get("blocker", "journey is not implemented")
        elif args.dry_run:
            outcome, detail = "NOT_APPLICABLE", "dry-run; journey not executed"
        else:
            outcome, detail = run(item.get("command", ""))
        checks.append({"check_id": journey_id, "status": outcome, "reason": detail})
        if outcome in {"BLOCKED", "FAILED"}:
            overall = "FAILED" if outcome == "FAILED" else ("BLOCKED" if overall != "FAILED" else overall)
    return write({"schema_version": 1, "profile": args.profile, "status": overall, "checks": checks, "timestamp": now()}, args.output)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="action", required=True)
    s = sub.add_parser("staging"); s.set_defaults(func=staging)
    s.add_argument("--candidate", type=Path, required=True); s.add_argument("--profile", required=True); s.add_argument("--output", type=Path, required=True); s.add_argument("--dry-run", action="store_true")
    for name in ("preflight", "deploy", "migration", "tenant-activation", "journeys"):
        s.add_argument(f"--{name}-command", default="")
    m = sub.add_parser("migration"); m.set_defaults(func=migration)
    m.add_argument("--metadata", type=Path, required=True); m.add_argument("--output", type=Path, required=True); m.add_argument("--command", default=""); m.add_argument("--validation-command", default=""); m.add_argument("--dry-run", action="store_true")
    j = sub.add_parser("journeys"); j.set_defaults(func=journeys)
    j.add_argument("--profile", required=True); j.add_argument("--output", type=Path, required=True); j.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
