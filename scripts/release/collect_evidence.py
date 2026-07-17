#!/usr/bin/env python3
"""Assemble the release evidence bundle from real repo state.

The bundle is derived, never asserted by hand. It contains:

* git state (commit, branch, dirty flag);
* the control-spine validator results (exit codes + output tails), including
  the implementation-ledger truth gate and the storage/cost policy checks;
* the implementation-ledger status breakdown, item by item, with external
  actions (FT-EXT-ATTESTATION) reported exactly as the ledger records them —
  this bundle NEVER claims or implies an external certification (no SOC 2,
  no penetration-test report, no legal sign-off) because none exists in-repo;
* route-registry classification stats derived from config/route_registry.yaml;
* the consent purpose registry derived from
  packages/shared/contracts/consent-registry.json (registry-derived — the
  purpose count is read, never hardcoded);
* the cross-SDK conformance matrix derived by
  scripts/release/sdk_conformance.py from SDK sources and test manifests;
* the latest `make ci-check` gate summary when a log is provided via
  --ci-log; otherwise the bundle records that the summary was not captured
  (it is never fabricated).

This is an INDEX, not a gate — it always exits 0. The individual
`make validate-*` targets and `make ci-check` are the gates.

Usage:
  python scripts/release/collect_evidence.py                # YAML to stdout
  python scripts/release/collect_evidence.py --out FILE     # also write FILE
  python scripts/release/collect_evidence.py --ci-log FILE  # parse a saved
                                                            # ci-check log for
                                                            # the Gates line
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import load_yaml, repo_root  # noqa: E402

import yaml  # noqa: E402

EVIDENCE_CHECKS = [
    ("foundation", "scripts/release/check_foundation.py"),
    ("profile_config", "scripts/release/check_profile_config.py"),
    ("cost_policy", "scripts/release/check_cost_policy.py"),
    ("route_registry", "scripts/release/check_route_registry.py"),
    ("storage_policies", "scripts/release/check_storage_policies.py"),
    ("implementation_ledger", "scripts/release/check_implementation_ledger.py"),
    ("sdk_conformance", "scripts/release/sdk_conformance.py"),
    ("required_release_checks", "scripts/release/check_required_checks.py"),
]

EXTERNAL_ATTESTATION_ID = "FT-EXT-ATTESTATION"

_GATES_LINE_RE = re.compile(r"Gates:\s*(\d+)\s*passed,\s*(\d+)\s*failed")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _run(script: str, extra_args: list[str] | None = None) -> dict:
    start = datetime.datetime.now(datetime.timezone.utc)
    cmd = [sys.executable, script] + (extra_args or [])
    try:
        proc = subprocess.run(
            cmd, cwd=repo_root(), capture_output=True, text=True, timeout=180,
        )
        code = proc.returncode
        tail = "\n".join(
            (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-6:]
        )
    except Exception as exc:  # pragma: no cover
        return {"script": script, "exit_code": 1, "error": str(exc)}
    dur = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
    return {
        "script": script,
        "exit_code": code,
        "duration_s": round(dur, 3),
        "output_tail": tail,
    }


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=repo_root(), capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # pragma: no cover
        return ""


def git_state() -> dict:
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
    }


def ledger_section() -> dict:
    """Summarize config/implementation_ledger.yaml exactly as recorded."""
    try:
        doc = load_yaml("config/implementation_ledger.yaml") or {}
    except FileNotFoundError:
        return {"error": "config/implementation_ledger.yaml not found"}

    items = doc.get("items") or []
    by_status: dict[str, int] = {}
    rows = []
    external = None
    for item in items:
        status = str(item.get("status", "unknown"))
        by_status[status] = by_status.get(status, 0) + 1
        row = {
            "id": item.get("id"),
            "status": status,
            "release_class": item.get("release_class"),
            "blocked_by": list(item.get("blocked_by") or []),
            "has_exception": bool(item.get("exception")),
        }
        rows.append(row)
        if item.get("id") == EXTERNAL_ATTESTATION_ID:
            external = {
                "ledger_id": EXTERNAL_ATTESTATION_ID,
                "status": status,
                "exception": item.get("exception"),
                "certifications_claimed": [],
                "note": (
                    "External SOC 2 / penetration test / legal review is an "
                    "external action outside repo-executable completion. No "
                    "external certification or attestation is claimed or "
                    "implied by this bundle."
                ),
            }

    section = {
        "release_train": doc.get("release_train"),
        "total_items": len(items),
        "by_status": dict(sorted(by_status.items())),
        "items": rows,
        "external_attestation": external or {
            "ledger_id": EXTERNAL_ATTESTATION_ID,
            "status": "missing_from_ledger",
            "certifications_claimed": [],
            "note": "External attestation item not found in the ledger.",
        },
    }
    return section


def route_registry_section() -> dict:
    """Classification stats derived from config/route_registry.yaml."""
    try:
        data = load_yaml("config/route_registry.yaml") or {}
    except FileNotFoundError:
        return {"error": "config/route_registry.yaml not found"}
    return {
        "default_decision": data.get("default_decision"),
        "known_prefixes": len(data.get("known_prefixes") or []),
        "sensitive_domains": sorted(data.get("sensitive_domains") or []),
        "high_risk_domains": sorted(data.get("high_risk_domains") or []),
        "infra_domains": sorted(data.get("infra_domains") or []),
    }


def consent_section() -> dict:
    """Purpose registry derived from the canonical consent registry."""
    import json
    path = repo_root() / "packages/shared/contracts/consent-registry.json"
    if not path.is_file():
        return {"error": "packages/shared/contracts/consent-registry.json not found"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"error": f"consent registry is not valid JSON: {exc}"}
    purposes = data.get("purposes") or []
    ids = [p.get("id") for p in purposes if isinstance(p, dict)]
    return {
        "source": "packages/shared/contracts/consent-registry.json",
        "contract_version": data.get("contractVersion"),
        "schema_version": data.get("schemaVersion"),
        "purpose_count": len(purposes),
        "purpose_ids": ids,
    }


def sdk_conformance_section() -> dict:
    """Cross-SDK conformance matrix derived from sources + test manifests."""
    sys.path.insert(0, str(repo_root() / "scripts" / "release"))
    try:
        from sdk_conformance import build_matrix
    except ImportError as exc:  # pragma: no cover
        return {"error": f"sdk_conformance unavailable: {exc}"}
    matrix, failures = build_matrix(repo_root())
    return {
        "derived": bool(matrix),
        "failures": failures,
        "matrix": matrix,
    }


def ci_check_section(ci_log: str | None) -> dict:
    """Parse a saved `make ci-check` log for the repo-doctor Gates line.

    Never fabricated: without a log the summary is recorded as not captured.
    """
    if not ci_log:
        return {
            "captured": False,
            "command": "make ci-check",
            "note": "No ci-check log provided (--ci-log); summary not captured.",
        }
    path = repo_root() / ci_log if not os.path.isabs(ci_log) else ci_log
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            body = fh.read()
    except OSError as exc:
        return {"captured": False, "command": "make ci-check",
                "error": f"could not read {ci_log}: {exc}"}
    match = None
    for match in _GATES_LINE_RE.finditer(body):
        pass  # keep the last occurrence (final summary)
    if not match:
        return {"captured": False, "command": "make ci-check",
                "error": f"no 'Gates: N passed, M failed' line found in {ci_log}"}
    return {
        "captured": True,
        "command": "make ci-check",
        "log": ci_log,
        "gates_passed": int(match.group(1)),
        "gates_failed": int(match.group(2)),
    }


def _github_api(repo: str, path: str, token: str) -> dict:
    """GET a GitHub REST resource with stdlib urllib. Raises on any error."""
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aether-release-evidence",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read().decode("utf-8"))


def _verify_hosted_check(check_id: str, definition: dict, row: dict,
                         expected_sha: str, allowed: list,
                         repo: str, token: str) -> list[str]:
    """Verify one claimed check against the GitHub REST API (fail closed)."""
    failures: list[str] = []
    run_id = row.get("workflow_run_id")
    try:
        run = _github_api(repo, f"/actions/runs/{run_id}", token)
        jobs = _github_api(repo, f"/actions/runs/{run_id}/jobs?per_page=100", token)
        artifacts = _github_api(repo, f"/actions/runs/{run_id}/artifacts?per_page=100", token)
    except Exception as exc:
        return [f"{check_id}: GitHub API verification failed ({type(exc).__name__}: {exc})"]
    if run.get("head_sha") != expected_sha:
        failures.append(f"{check_id}: hosted run head SHA mismatch")
    if run.get("path") != definition.get("workflow"):
        failures.append(
            f"{check_id}: hosted run belongs to {run.get('path')!r}, "
            f"not {definition.get('workflow')!r}"
        )
    if run.get("conclusion") not in allowed:
        failures.append(
            f"{check_id}: hosted run conclusion {run.get('conclusion')!r} is not allowed"
        )
    job = next(
        (j for j in jobs.get("jobs", []) if j.get("name") == definition.get("job")),
        None,
    )
    if job is None:
        failures.append(f"{check_id}: hosted run has no job {definition.get('job')!r}")
    elif job.get("conclusion") not in allowed:
        failures.append(
            f"{check_id}: hosted job conclusion {job.get('conclusion')!r} is not allowed"
        )
    artifact = next(
        (a for a in artifacts.get("artifacts", [])
         if a.get("name") == definition.get("evidence_artifact")),
        None,
    )
    if artifact is None:
        failures.append(
            f"{check_id}: evidence artifact {definition.get('evidence_artifact')!r} "
            "missing from hosted run"
        )
    elif artifact.get("expired"):
        failures.append(f"{check_id}: evidence artifact expired on the hosted run")
    # When a local copy of the artifact is provided, its checksum is
    # recomputed — the claimed digest is never trusted on its own.
    artifact_path = row.get("artifact_path")
    if artifact_path:
        local = Path(artifact_path)
        local = local if local.is_absolute() else repo_root() / local
        try:
            digest = hashlib.sha256(local.read_bytes()).hexdigest()
        except OSError as exc:
            failures.append(f"{check_id}: local artifact unreadable ({exc})")
        else:
            if digest != row.get("artifact_sha256"):
                failures.append(f"{check_id}: local artifact checksum mismatch")
    return failures


def hosted_checks_section(path_value: str | None, expected_sha: str,
                          repo: str | None = None, token: str | None = None) -> dict:
    """Validate authoritative GitHub check-run evidence for the exact SHA.

    Input is a JSON object with a ``checks`` list.  Every catalog check must be
    represented and bind its workflow run, timestamp and artifact checksum to
    the expected commit.  The claims are then verified against the GitHub REST
    API (run head SHA, workflow path, run/job conclusions, artifact presence;
    local artifact checksums are recomputed when provided) — a local JSON file
    on its own is NEVER authoritative.  Missing token/repository, network
    errors, skipped/cancelled/stale or cross-SHA evidence never become a pass.
    """
    catalog = load_yaml("config/required_release_checks.yaml") or {}
    branch = catalog.get("branch_protection") or {}
    allowed = catalog.get("allowed_terminal_conclusions", [])
    required = {
        row["id"]: row for row in catalog.get("checks") or []
        if row.get("blocks_founding_tenant_release")
    }
    if not path_value:
        return {"captured": False, "authoritative": False, "passed": False,
                "reason": "github_check_evidence_missing", "checks": [],
                "external_action": branch.get("unavailable_action")}
    path = Path(path_value) if os.path.isabs(path_value) else repo_root() / path_value
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"captured": False, "authoritative": False, "passed": False,
                "reason": "github_check_evidence_invalid", "error": str(exc), "checks": []}
    supplied = {str(row.get("id")): row for row in payload.get("checks", [])}
    failures: list[str] = []
    normalized: list[dict] = []
    for check_id, definition in required.items():
        row = supplied.get(check_id)
        if not row:
            failures.append(f"{check_id}: missing")
            continue
        for field in ("commit_sha", "workflow_run_id", "job_name", "conclusion",
                      "completed_at", "artifact_name", "artifact_sha256"):
            if not row.get(field):
                failures.append(f"{check_id}: missing {field}")
        if row.get("commit_sha") != expected_sha:
            failures.append(f"{check_id}: SHA mismatch")
        if row.get("job_name") != definition.get("job"):
            failures.append(f"{check_id}: job name mismatch")
        if row.get("conclusion") not in allowed:
            failures.append(f"{check_id}: conclusion {row.get('conclusion')!r} is not allowed")
        if row.get("artifact_name") != definition.get("evidence_artifact"):
            failures.append(f"{check_id}: artifact name mismatch")
        try:
            completed = datetime.datetime.fromisoformat(
                str(row.get("completed_at", "")).replace("Z", "+00:00")
            )
            if completed.tzinfo is None:
                raise ValueError("timezone is required")
        except ValueError:
            failures.append(f"{check_id}: invalid completed_at timestamp")
        checksum = str(row.get("artifact_sha256", ""))
        if checksum and not re.fullmatch(r"[0-9a-f]{64}", checksum):
            failures.append(f"{check_id}: invalid artifact checksum")
        normalized.append({key: row.get(key) for key in (
            "id", "commit_sha", "workflow_run_id", "job_name", "conclusion",
            "completed_at", "artifact_name", "artifact_sha256"
        )})

    # Hosted verification: the local claims above are structural only. They
    # become authoritative ONLY after the GitHub REST API confirms them for
    # this exact commit. No token / repository / network => non-authoritative.
    token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
    repo = repo if repo is not None else os.environ.get("GITHUB_REPOSITORY", "")
    github_verified = False
    if not failures:
        if not token or not repo:
            failures.append(
                "hosted verification unavailable: GITHUB_TOKEN and "
                "GITHUB_REPOSITORY (or --github-repo) are required to verify "
                "check evidence against the GitHub API"
            )
        else:
            for check_id, definition in required.items():
                failures.extend(_verify_hosted_check(
                    check_id, definition, supplied[check_id],
                    expected_sha, allowed, repo, token,
                ))
            github_verified = not failures
    return {"captured": True, "authoritative": github_verified,
            "passed": github_verified,
            "github_verified": github_verified,
            "repository": repo or None,
            "expected_commit_sha": expected_sha, "failures": failures,
            "checks": normalized}


def build_bundle(ci_log: str | None = None, github_checks: str | None = None,
                 github_repo: str | None = None) -> dict:
    results = {name: _run(script) for name, script in EVIDENCE_CHECKS}
    passed = sum(1 for v in results.values() if v.get("exit_code") == 0)

    git = git_state()
    return {
        "timestamp": _now_iso(),
        "release_train": "FOUNDING_TENANT_PRODUCTION",
        "git": git,
        "evidence_checks": results,
        "implementation_ledger": ledger_section(),
        "route_registry": route_registry_section(),
        "consent_purposes": consent_section(),
        "sdk_conformance": sdk_conformance_section(),
        "ci_check": ci_check_section(ci_log),
        "github_checks": hosted_checks_section(github_checks, git["commit"],
                                               repo=github_repo),
        "summary": {"total": len(results), "passed": passed,
                    "failed": len(results) - passed},
        "docs": [
            "docs/FOUNDING-TENANT-PRODUCTION.md",
            "docs/DEPLOYMENT-PROFILES.md",
            "docs/RELEASE-EVIDENCE.md",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    ap.add_argument("--ci-log", default=None,
                    help="path to a saved `make ci-check` log to summarize")
    ap.add_argument("--github-checks", default=None,
                    help="claimed GitHub check-run JSON for the current commit "
                         "(verified against the GitHub REST API before it "
                         "counts as authoritative)")
    ap.add_argument("--github-repo", default=None,
                    help="owner/repo used for hosted verification "
                         "(default: GITHUB_REPOSITORY)")
    ap.add_argument("--release-mode", action="store_true",
                    help="fail closed unless local and hosted evidence are authoritative")
    args = ap.parse_args()

    bundle = build_bundle(ci_log=args.ci_log, github_checks=args.github_checks,
                          github_repo=args.github_repo)
    text = yaml.safe_dump(bundle, sort_keys=False, width=100)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if args.release_mode:
        ci = bundle["ci_check"]
        hosted = bundle["github_checks"]
        if (not ci.get("captured") or ci.get("gates_failed") != 0
                or not hosted.get("passed") or bundle["summary"]["failed"]):
            print("Release evidence is incomplete or failed; refusing a release claim.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
