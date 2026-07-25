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
  (it is never fabricated);
* the release-evidence/ bundle layout, when materialized: manifest.json and
  manifest.sha256 alongside one subdirectory per evidence class. A declared
  subdirectory containing no files is reported ABSENT, never as an empty pass,
  because "we collected no rollback evidence" and "rollback evidence was fine"
  must not be the same line in a manifest.

This is an INDEX, not a gate — it always exits 0. The individual
`make validate-*` targets and `make ci-check` are the gates.

Usage:
  python scripts/release/collect_evidence.py                # YAML to stdout
  python scripts/release/collect_evidence.py --out FILE     # also write FILE
  python scripts/release/collect_evidence.py --ci-log FILE  # parse a saved
                                                            # ci-check log for
                                                            # the Gates line
  python scripts/release/collect_evidence.py --bundle-dir   # materialize
                                                            # release-evidence/
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
from release_manifest import canonical  # noqa: E402 - one canonicalisation, reused

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
    # Agent Access Intelligence: the reference packs supply the approved scope
    # baselines that `compute_permission_findings` compares observed grants against.
    # A malformed or missing pack silently removes a provider's baseline, and the
    # permission surface then reports no scope violations for it — a false all-clear,
    # which is exactly the class of thing an evidence bundle exists to rule out.
    ("agent_access_reference_packs", "scripts/validate_reference_packs.py"),
    # Deployment/cost spine. These four already gate `make release-gate` but
    # never reached the bundle, so the bundle could report a clean sweep while
    # the checks that decide whether the infrastructure is affordable and
    # correctly shaped were not represented in it at all.
    ("cost_policy_terraform", "scripts/release/check_cost_policy_terraform.py"),
    ("delivery_topology", "scripts/release/check_delivery_topology.py"),
    ("terraform_plan_policy", "scripts/release/check_terraform_plan_policy.py"),
    ("cost_model", "scripts/release/check_cost_model.py"),
]

# Extra CLI arguments for checks that need them. Kept out of EVIDENCE_CHECKS so
# that stays a list of (name, script) pairs — callers and tests unpack it.
EVIDENCE_CHECK_ARGS: dict[str, list[str]] = {
    # Scored against the plan a credentialed promotion writes, NOT against the
    # committed test fixture. Pointing this at the fixture would make the
    # bundle report a passing profile-policy check on a plan that never came
    # from AWS, which is the precise confusion the bundle exists to prevent.
    # With no real plan present the check fails, and that is the honest result.
    "terraform_plan_policy": [
        "--profile", "production-lean",
        "--plan-json", "artifacts/reviewed.tfplan.json",
    ],
    # Scored against the inventory a credentialed plan produced. The path is the
    # same one `make validate-cost-model` writes the FIXTURE-derived inventory
    # to, so the path alone proves nothing -- the guard below reads the
    # inventory's own provenance and refuses to run the gate at all when its
    # input was a committed test fixture. A cost PASS next to
    # "terraform_plan_policy exit 2 (no real plan)" is the exact confusion the
    # bundle exists to prevent, and it was reachable because only the plan gate
    # was pointed at a path a fixture never occupies.
    "cost_model": [
        "--profile", "production-lean",
        "--inventory", "artifacts/profile-resource-inventory.json",
    ],
}

COST_INVENTORY = "artifacts/profile-resource-inventory.json"


def synthetic_inventory_reason(inventory_rel: str = COST_INVENTORY) -> str | None:
    """Why the cost gate must not be run against this inventory, or None.

    check_terraform_plan_policy.py stamps every inventory with the plan it was
    built from and, when that plan was a fixture/scratch/sample file, the marker
    that made it synthetic. A cost verdict derived from one is a statement about
    a committed JSON file, not about anything AWS would bill for, and it must
    never appear in an evidence bundle as a PASS.

    (A real plan file that someone copied a fixture into is beyond what a path
    can detect; that is what the credentialed-provenance checks in
    check_deployment_readiness.py are for. This guard closes the accidental
    case, which is the one that actually happened.)
    """
    path = repo_root() / inventory_rel
    if not path.is_file():
        return (f"{inventory_rel} is absent; no plan inventory exists to price, "
                f"and a cost gate with no input has not passed")
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"{inventory_rel} is not readable JSON ({exc})"
    if not isinstance(inventory, dict):
        return f"{inventory_rel} is not a JSON object"
    marker = inventory.get("synthetic_input")
    if marker:
        return (
            f"{inventory_rel} was generated from "
            f"{inventory.get('generated_from')!r}, a {marker} source. A cost "
            f"verdict derived from a test fixture is not evidence about any "
            f"real deployment and is not reported as a pass."
        )
    return None


# Checks whose input must be proven before the check is allowed to produce a
# verdict at all. A guard returning a reason means the check is recorded as
# unverifiable — non-zero, counted against the summary — rather than run.
EVIDENCE_CHECK_GUARDS = {"cost_model": synthetic_inventory_reason}

# Where the materialised bundle lives, and the subdirectories it always
# declares. A subdirectory with no files is reported ABSENT rather than as an
# empty pass — "we produced no load evidence" and "load evidence passed with
# nothing to report" must never render identically.
BUNDLE_ROOT = "release-evidence"
BUNDLE_SUBDIRS = (
    "profile", "terraform", "cost", "migrations", "smoke", "security",
    "isolation", "load", "rollback", "lifecycle", "observability", "scorecard",
)
BUNDLE_MANIFEST = "manifest.json"
BUNDLE_CHECKSUM = "manifest.sha256"

EXTERNAL_ATTESTATION_ID = "FT-EXT-ATTESTATION"

_GATES_LINE_RE = re.compile(r"Gates:\s*(\d+)\s*passed,\s*(\d+)\s*failed")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _run(script: str, extra_args: list[str] | None = None) -> dict:
    start = datetime.datetime.now(datetime.timezone.utc)
    # A validator that is not on disk has not passed. It is recorded as absent
    # with a non-zero exit code, so it counts against the bundle summary and
    # blocks --release-mode exactly as a failing check would. Silently omitting
    # it would turn "we never checked" into "nothing was wrong".
    if not (repo_root() / script).is_file():
        return {"script": script, "exit_code": 127, "status": "absent",
                "error": "validator script is not present in the repository"}
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


def scan_bundle_layout(bundle_dir: Path) -> dict:
    """Describe the release-evidence/ layout exactly as it is on disk.

    Every declared subdirectory appears in the result, but one that does not
    exist — or exists with no files in it — is marked ``present: false``. The
    distinction matters more than it looks: an absent load-test directory and a
    load test that produced nothing are the same bytes on disk and must not be
    the same claim in the manifest.
    """
    subdirs: dict[str, dict] = {}
    total = 0
    for name in BUNDLE_SUBDIRS:
        target = bundle_dir / name
        files: list[dict] = []
        if target.is_dir():
            for path in sorted(p for p in target.rglob("*") if p.is_file()):
                data = path.read_bytes()
                files.append({
                    "path": path.relative_to(bundle_dir).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                })
        total += len(files)
        subdirs[name] = {
            "present": bool(files),
            "exists": target.is_dir(),
            "file_count": len(files),
            "files": files,
        }
    return {"subdirectories": subdirs, "file_count": total}


def write_bundle_layout(bundle_dir: Path, git: dict) -> dict:
    """Materialise release-evidence/ and write its manifest + checksum.

    The manifest is canonicalised and digested with release_manifest.py's
    helpers so the bundle hashes identically wherever it is produced, and so
    there is exactly one canonicalisation in the repository rather than two
    that agree until they don't.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_SUBDIRS:
        (bundle_dir / name).mkdir(exist_ok=True)

    layout = scan_bundle_layout(bundle_dir)
    manifest = {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "root": BUNDLE_ROOT,
        "commit": git.get("commit"),
        "branch": git.get("branch"),
        "dirty": git.get("dirty"),
        "file_count": layout["file_count"],
        "subdirectories": layout["subdirectories"],
    }
    payload = canonical(manifest)
    (bundle_dir / BUNDLE_MANIFEST).write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (bundle_dir / BUNDLE_CHECKSUM).write_text(digest + "\n", encoding="utf-8")
    return {"manifest": manifest, "sha256": digest}


def verify_bundle(bundle_dir: Path) -> dict:
    """Re-derive the bundle's digests from disk and compare them to the manifest.

    Writing per-file digests into a manifest and then reading them back is not
    verification, it is transcription: swapping a file under
    release-evidence/<class>/ leaves the manifest and its checksum in perfect
    agreement with each other and in complete disagreement with the bundle.
    Nothing re-derived either until this function existed, so `manifest.sha256`
    sealed the manifest and nothing sealed the evidence.

    Three tampers are caught, because each is separately possible:
      * the manifest was edited            -> its canonical digest moves;
      * a listed file was edited/removed   -> that file's digest moves;
      * an unlisted file was added         -> it is in the bundle and vouched
                                              for by nothing.
    """
    manifest_path = bundle_dir / BUNDLE_MANIFEST
    checksum_path = bundle_dir / BUNDLE_CHECKSUM
    out = {"verified": False, "reason": "", "files_checked": 0,
           "recorded_sha256": None, "computed_sha256": None}
    if not bundle_dir.is_dir():
        out["reason"] = f"{BUNDLE_ROOT}/ is not materialized"
        return out
    if not manifest_path.is_file() or not checksum_path.is_file():
        out["reason"] = f"{BUNDLE_MANIFEST} or {BUNDLE_CHECKSUM} is missing"
        return out
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        recorded = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        out["reason"] = f"manifest or checksum is unreadable ({exc})"
        return out
    if not isinstance(manifest, dict):
        out["reason"] = f"{BUNDLE_MANIFEST} is not a JSON object"
        return out

    computed = hashlib.sha256(canonical(manifest)).hexdigest()
    out["recorded_sha256"], out["computed_sha256"] = recorded, computed
    if computed != recorded:
        out["reason"] = (f"{BUNDLE_MANIFEST} hashes to {computed[:12]}… but "
                         f"{BUNDLE_CHECKSUM} records {recorded[:12]}…")
        return out

    listed: set[str] = set()
    checked = 0
    for section in (manifest.get("subdirectories") or {}).values():
        for row in (section or {}).get("files") or []:
            rel = str(row.get("path", ""))
            listed.add(rel)
            target = bundle_dir / rel
            if not target.is_file():
                out["reason"] = f"{rel} is listed in the manifest but absent from disk"
                out["files_checked"] = checked
                return out
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            if digest != str(row.get("sha256", "")):
                out["reason"] = (f"{rel} does not match its recorded digest "
                                 f"(recorded {str(row.get('sha256'))[:12]}…, "
                                 f"found {digest[:12]}…)")
                out["files_checked"] = checked
                return out
            checked += 1

    on_disk = {
        path.relative_to(bundle_dir).as_posix()
        for name in BUNDLE_SUBDIRS
        for path in (bundle_dir / name).rglob("*")
        if (bundle_dir / name).is_dir() and path.is_file()
    }
    unlisted = sorted(on_disk - listed)
    if unlisted:
        out["reason"] = (f"{len(unlisted)} file(s) in the bundle are not listed in "
                         f"the manifest and are vouched for by nothing: "
                         f"{', '.join(unlisted[:4])}")
        out["files_checked"] = checked
        return out

    out.update({"verified": True, "files_checked": checked})
    return out


def evidence_bundle_section(bundle_dir: Path, written: dict | None) -> dict:
    """Report the bundle layout without ever inventing a directory.

    When nothing has been materialised the section says so plainly. There is no
    representation here for "the bundle is fine, it is just empty".
    """
    if not bundle_dir.is_dir():
        return {
            "root": BUNDLE_ROOT,
            "materialized": False,
            "manifest": None,
            "sha256": None,
            "verification": verify_bundle(bundle_dir),
            "file_count": 0,
            "declared_subdirectories": list(BUNDLE_SUBDIRS),
            "subdirectories": {n: {"present": False, "exists": False,
                                   "file_count": 0, "files": []}
                               for n in BUNDLE_SUBDIRS},
            "note": (f"{BUNDLE_ROOT}/ has not been materialized; every "
                     "subdirectory is reported absent, not empty-passing."),
        }
    layout = scan_bundle_layout(bundle_dir)
    manifest_path = bundle_dir / BUNDLE_MANIFEST
    checksum_path = bundle_dir / BUNDLE_CHECKSUM
    recorded = None
    if checksum_path.is_file():
        text = checksum_path.read_text(encoding="utf-8").strip().split()
        recorded = text[0] if text else None
    return {
        "root": BUNDLE_ROOT,
        "materialized": True,
        "manifest": BUNDLE_MANIFEST if manifest_path.is_file() else None,
        # `sha256` is what the bundle CLAIMS. `verification` is what re-hashing
        # the manifest and every file it lists actually found. They are reported
        # as two different things because reading a recorded digest back is not
        # a check of anything.
        "sha256": (written or {}).get("sha256", recorded),
        "recorded_sha256": recorded,
        "verification": verify_bundle(bundle_dir),
        "file_count": layout["file_count"],
        "declared_subdirectories": list(BUNDLE_SUBDIRS),
        "subdirectories": layout["subdirectories"],
        "absent_subdirectories": sorted(
            name for name, row in layout["subdirectories"].items() if not row["present"]
        ),
    }


def run_evidence_checks() -> dict:
    """Run every evidence check, refusing to run one whose input is unprovable.

    A guarded check that cannot be given trustworthy input is recorded as
    `unverifiable_input` with a non-zero exit code, so it counts against the
    bundle summary and blocks --release-mode. It is NOT run and then reported as
    a pass: a green line derived from a fixture is worse than a red one, because
    it reads as an answer.
    """
    results: dict[str, dict] = {}
    for name, script in EVIDENCE_CHECKS:
        guard = EVIDENCE_CHECK_GUARDS.get(name)
        reason = guard() if guard else None
        if reason:
            results[name] = {
                "script": script,
                "exit_code": 2,
                "status": "unverifiable_input",
                "error": reason,
            }
            continue
        results[name] = _run(script, EVIDENCE_CHECK_ARGS.get(name))
    return results


def build_bundle(ci_log: str | None = None, github_checks: str | None = None,
                 github_repo: str | None = None,
                 bundle_dir: str | None = None) -> dict:
    results = run_evidence_checks()
    passed = sum(1 for v in results.values() if v.get("exit_code") == 0)

    git = git_state()
    target = Path(bundle_dir) if bundle_dir else repo_root() / BUNDLE_ROOT
    if not target.is_absolute():
        target = repo_root() / target
    written = write_bundle_layout(target, git) if bundle_dir else None
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
        "evidence_bundle": evidence_bundle_section(target, written),
        "summary": {"total": len(results), "passed": passed,
                    "failed": len(results) - passed,
                    "absent": sum(1 for v in results.values()
                                  if v.get("status") == "absent")},
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
    ap.add_argument("--bundle-dir", nargs="?", const=BUNDLE_ROOT, default=None,
                    help=f"materialize the {BUNDLE_ROOT}/ layout (manifest.json + "
                         "manifest.sha256 + evidence subdirectories) at this path")
    args = ap.parse_args()

    bundle = build_bundle(ci_log=args.ci_log, github_checks=args.github_checks,
                          github_repo=args.github_repo,
                          bundle_dir=args.bundle_dir)
    text = yaml.safe_dump(bundle, sort_keys=False, width=100)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    if args.release_mode:
        ci = bundle["ci_check"]
        hosted = bundle["github_checks"]
        evidence = bundle["evidence_bundle"]
        verification = evidence.get("verification") or {}
        if (not ci.get("captured") or ci.get("gates_failed") != 0
                or not hosted.get("passed") or bundle["summary"]["failed"]):
            print("Release evidence is incomplete or failed; refusing a release claim.", file=sys.stderr)
            return 1
        # A materialized bundle whose files no longer hash to what its manifest
        # records is a tampered bundle, whatever the manifest says about itself.
        if evidence.get("materialized") and not verification.get("verified"):
            print(f"Release evidence bundle failed verification: "
                  f"{verification.get('reason')}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
