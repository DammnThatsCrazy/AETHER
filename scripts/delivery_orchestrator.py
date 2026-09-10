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

try:  # Works both as a script and when imported by the unit tests.
    from delivery_contracts import FailureEnvelope, sanitize_detail, validate_release_candidate
    from staging_state_machine import StateMachineError, StagingStateMachine
except ModuleNotFoundError:  # pragma: no cover - import-mode compatibility
    from scripts.delivery_contracts import FailureEnvelope, sanitize_detail, validate_release_candidate
    from scripts.staging_state_machine import StateMachineError, StagingStateMachine

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
    detail = sanitize_detail((completed.stdout + completed.stderr).strip())
    return ("PASS", detail) if completed.returncode == 0 else ("FAILED", detail or f"exit {completed.returncode}")


def candidate(path: Path) -> dict:
    data = json.loads(path.read_text())
    errors = validate_release_candidate(data)
    if errors:
        raise ValueError("invalid release candidate: " + "; ".join(errors))
    return data


def verify_candidate_artifacts(
    path: Path,
    components: list[str],
    lockfiles: list[Path],
    expected_commit: str | None,
) -> dict:
    """Verify the exact files consumed by staging immediately before execution."""
    if not components:
        raise ValueError("at least one --component NAME=PATH is required before staging")
    if not expected_commit:
        raise ValueError("--expected-commit is required before staging")
    try:
        from artifact_builder import verify_candidate
    except ModuleNotFoundError:  # pragma: no cover - module execution compatibility
        from scripts.artifact_builder import verify_candidate
    return verify_candidate(path, components, [str(item) for item in lockfiles], expected_commit)


def _failure(
    *,
    operation_id: str,
    stage: str,
    status: str,
    code: str,
    reason: str,
    evidence_ref: Path,
    retryable: bool | None = None,
) -> dict:
    return FailureEnvelope.from_result(
        operation_id=operation_id,
        stage=stage,
        status=status,
        code=code,
        reason=reason,
        evidence_ref=str(evidence_ref),
        retryable=retryable,
    ).as_dict()


def staging(args: argparse.Namespace) -> int:
    try:
        rc = candidate(args.candidate)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"schema_version": 1, "release_candidate_id": "unknown", "profile": args.profile,
                  "artifact_digest": "sha256:" + "0" * 64, "status": "BLOCKED",
                  "checks": [{"check_id": "release_candidate", "status": "BLOCKED", "reason": sanitize_detail(str(exc))}],
                  "failure": _failure(operation_id="unknown", stage="release_candidate", status="BLOCKED",
                                       code="INVALID_CANDIDATE", reason=str(exc), evidence_ref=args.output),
                  "timestamp": now()}
        return write(result, args.output)
    checks: list[dict] = []
    compatible_profiles = rc.get("deployment_profiles", [])
    if compatible_profiles and args.profile not in compatible_profiles:
        checks.append({"check_id": "profile_compatibility", "status": "BLOCKED", "reason": f"candidate is not compatible with {args.profile}"})
        status = "BLOCKED"
        failure = _failure(operation_id=rc["release_candidate_id"], stage="profile_compatibility", status=status,
                           code="PROFILE_INCOMPATIBLE", reason=f"candidate is not compatible with {args.profile}",
                           evidence_ref=args.output, retryable=False)
    elif not args.dry_run:
        try:
            verify_candidate_artifacts(
                args.candidate,
                list(getattr(args, "component", [])),
                list(getattr(args, "lockfile", [])),
                getattr(args, "expected_commit", None),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            checks.append({"check_id": "artifact_identity", "status": "BLOCKED", "reason": sanitize_detail(str(exc))})
            status = "BLOCKED"
            failure = _failure(
                operation_id=rc["release_candidate_id"], stage="artifact_identity", status=status,
                code="ARTIFACT_IDENTITY_UNVERIFIED", reason=str(exc), evidence_ref=args.output,
                retryable=False,
            )
        else:
            status = None
            failure = None
    else:
        checks.append({"check_id": "artifact_identity", "status": "NOT_APPLICABLE", "reason": "dry-run; artifact files not consumed"})
        status = None
        failure = None

    if status == "BLOCKED":
        return write({"schema_version": 1, "release_candidate_id": rc["release_candidate_id"], "profile": args.profile,
                      "artifact_digest": rc["artifact_digest"], "status": status, "checks": checks,
                      "failure": failure, "timestamp": now()}, args.output)

    if getattr(args, "state", None):
        # Opt-in checkpointing keeps the historical one-shot command stable
        # while allowing GitHub or an operator to resume the exact candidate
        # after an interrupted stage.
        try:
            environment_resolution = None
            if getattr(args, "environment_resolution", None):
                environment_resolution = json.loads(
                    args.environment_resolution.read_text(encoding="utf-8")
                )
            machine = StagingStateMachine.open(
                args.state,
                rc,
                args.profile,
                operation_id=rc["release_candidate_id"],
                environment_resolution=environment_resolution,
                persist=not args.dry_run,
            )
        except (OSError, json.JSONDecodeError, StateMachineError) as exc:
            checks.append({"check_id": "staging_checkpoint", "status": "BLOCKED", "reason": sanitize_detail(str(exc))})
            status = "BLOCKED"
            failure = _failure(
                operation_id=rc["release_candidate_id"],
                stage="staging_checkpoint",
                status=status,
                code="INVALID_STAGING_CHECKPOINT",
                reason=str(exc),
                evidence_ref=args.output,
                retryable=False,
            )
            return write({"schema_version": 1, "release_candidate_id": rc["release_candidate_id"],
                          "profile": args.profile, "artifact_digest": rc["artifact_digest"],
                          "status": status, "checks": checks, "failure": failure, "timestamp": now()}, args.output)
        else:
            commands = {
                "preflight": args.preflight_command,
                "deploy": args.deploy_command,
                "migration": args.migration_command,
                "tenant_activation": args.tenant_activation_command,
                "golden_journeys": args.journeys_command,
            }

            def execute(stage: str) -> tuple[str, str]:
                if stage == "aws_identity" and not os.environ.get("AWS_ACCESS_KEY_ID") and not os.environ.get("AWS_PROFILE"):
                    return "BLOCKED", "AWS_ACCESS_KEY_ID or AWS_PROFILE is required"
                command = "aws sts get-caller-identity --output json" if stage == "aws_identity" else commands[stage]
                return run(command)

            state = machine.run(execute, dry_run=args.dry_run)
            checks.extend(state["checks"])
            status = "DRY_RUN" if args.dry_run else {
                "COMPLETE": "DEPLOYED",
                "BLOCKED": "BLOCKED",
                "FAILED": "FAILED",
                "RUNNING": "DEPLOYED",
            }[state["status"]]
            failure = state["failures"][-1] if state["failures"] else None
            result = {
                "schema_version": 1,
                "release_candidate_id": rc["release_candidate_id"],
                "profile": args.profile,
                "artifact_digest": rc["artifact_digest"],
                "status": status,
                "checks": checks,
                "timestamp": now(),
            }
            if failure is not None:
                result["failure"] = failure
            return write(result, args.output)
    elif args.dry_run:
        for name in ("preflight", "deploy", "migration", "tenant_activation", "golden_journeys"):
            checks.append({"check_id": name, "status": "NOT_APPLICABLE", "reason": "dry-run; command not executed"})
        status = "DRY_RUN"
        failure = None
    elif not os.environ.get("AWS_ACCESS_KEY_ID") and not os.environ.get("AWS_PROFILE"):
        checks.append({"check_id": "aws_credentials", "status": "BLOCKED", "reason": "AWS_ACCESS_KEY_ID or AWS_PROFILE is required"})
        status = "BLOCKED"
        failure = _failure(operation_id=rc["release_candidate_id"], stage="aws_identity", status=status,
                           code="AWS_CREDENTIALS_MISSING", reason="AWS_ACCESS_KEY_ID or AWS_PROFILE is required",
                           evidence_ref=args.output)
    else:
        status = "DEPLOYED"
        failure = None
        identity_status, identity_detail = run("aws sts get-caller-identity --output json")
        checks.append({"check_id": "aws_identity", "status": identity_status, "reason": identity_detail or "AWS identity resolved"})
        if identity_status != "PASS":
            status = "BLOCKED" if identity_status == "BLOCKED" else "FAILED"
            failure = _failure(operation_id=rc["release_candidate_id"], stage="aws_identity", status=status,
                               code="AWS_IDENTITY_UNAVAILABLE", reason=identity_detail or "AWS identity could not be resolved",
                               evidence_ref=args.output)
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
                failure = _failure(operation_id=rc["release_candidate_id"], stage=name, status=status,
                                   code="COMMAND_BLOCKED" if outcome == "BLOCKED" else "COMMAND_FAILED",
                                   reason=detail or f"{name} command did not pass", evidence_ref=args.output)
                break
    result = {"schema_version": 1, "release_candidate_id": rc["release_candidate_id"], "profile": args.profile,
              "artifact_digest": rc["artifact_digest"], "status": status, "checks": checks, "timestamp": now()}
    if failure is not None:
        result["failure"] = failure
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
    s = sub.add_parser("staging")
    s.set_defaults(func=staging)
    s.add_argument("--candidate", type=Path, required=True)
    s.add_argument("--profile", required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--state", type=Path, help="durable checkpoint path for resumable staging execution")
    s.add_argument("--environment-resolution", type=Path, help="pre-mutation environment-resolution evidence to bind to the checkpoint")
    s.add_argument("--component", action="append", default=[], metavar="NAME=PATH", help="exact candidate component file to verify before staging")
    s.add_argument("--lockfile", action="append", type=Path, default=[], help="exact dependency lockfile to verify before staging")
    s.add_argument("--expected-commit", help="checked-out commit expected by the candidate")
    s.add_argument("--dry-run", action="store_true")
    for name in ("preflight", "deploy", "migration", "tenant-activation", "journeys"):
        s.add_argument(f"--{name}-command", default="")
    m = sub.add_parser("migration")
    m.set_defaults(func=migration)
    m.add_argument("--metadata", type=Path, required=True)
    m.add_argument("--output", type=Path, required=True)
    m.add_argument("--command", default="")
    m.add_argument("--validation-command", default="")
    m.add_argument("--dry-run", action="store_true")
    j = sub.add_parser("journeys")
    j.set_defaults(func=journeys)
    j.add_argument("--profile", required=True)
    j.add_argument("--output", type=Path, required=True)
    j.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    arguments = parser().parse_args()
    raise SystemExit(arguments.func(arguments))
