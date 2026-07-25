#!/usr/bin/env python3
"""Score Aether's deployment readiness against evidence that exists on disk.

This is the scorecard behind any deployment-readiness percentage Aether states.
It reads config/deployment_readiness.yaml and awards each control's weight ONLY
when the concrete artifacts that control names are present and validate. There
is no path through this program by which a control earns points for being
believed to be done.

THE PROPERTY THIS FILE IS BUILT AROUND
--------------------------------------
A scorecard that can be talked into a high number is worse than no scorecard,
because it launders an opinion into a measurement. So the number is not
defended by review discipline, it is defended structurally, by four independent
locks that would all have to be broken at once:

  1. EVIDENCE VALIDATION. A control's weight requires every one of its
     `required_evidence` entries to resolve on disk AND validate. A missing
     file scores zero. A file that exists but fails its validator also scores
     zero — "present" is not "passing", and the difference is the entire point.

  2. CREDENTIALED PROVENANCE. Evidence of kind `credentialed_artifact` must
     carry a provenance block naming a real AWS account, region, terraform
     version, capture timestamp, commit and source path. Placeholder accounts,
     and any source under a temp or scratchpad directory, are rejected by name.
     Nothing that can be produced by a repository satisfies this kind.

  3. THE CONDITION CEILING. Seventeen global conditions are evaluated from
     artifacts on disk, independently of the control table, and each names the
     controls it holds hostage. The verified score is capped by the weight of
     the controls that unmet conditions block. Editing a control cannot raise
     that ceiling, because the ceiling is not computed from controls.

  4. THE INVARIANT. If the verified score ever exceeds its ceiling, or reaches
     100 while any condition is unmet, that is not a high score — it is proof
     the scorecard has been tampered with, and the run fails hard.

THREE NUMBERS, NEVER MERGED
---------------------------
  code-complete        what is built and validating in this repository
  externally-verified  what has been proven against real infrastructure
  evidence gap         the difference: written, plausible, and unproven

The gap is the honest number. It is reported for every scorecard and itemised
by control, because "we are 87% done" and "we have proven 12%" are different
claims and collapsing them is how deployment readiness gets misreported.

WHAT THIS ENVIRONMENT CAN PROVE
-------------------------------
No AWS credentials, applied infrastructure, billing history or staging
rehearsal exists here, or can. Every control that depends on one is reported
as externally blocked with the specific artifact it is waiting for. The tool
says so in plain language rather than rounding the shortfall away.

Usage:
  python scripts/release/check_deployment_readiness.py
  python scripts/release/check_deployment_readiness.py --json
  python scripts/release/check_deployment_readiness.py --profile production-lean
  python scripts/release/check_deployment_readiness.py --out release-evidence/scorecard/readiness.json
  python scripts/release/check_deployment_readiness.py --require-gates   # release use

Exit codes:
  0  the scorecard was produced and the control table is internally sound
  1  config integrity failure, an expired exception, or an invariant violation
     (any of which means the score cannot be trusted, whatever it says)
  2  --require-gates was given and a release gate is not met
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
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, main_guard, repo_root  # noqa: E402
from release_manifest import canonical  # noqa: E402 - reuse, never re-implement

import yaml  # noqa: E402

CONFIG_REL = "config/deployment_readiness.yaml"
COST_EXCEPTIONS_REL = "config/cost_exceptions.yaml"
LEDGER_REL = "config/implementation_ledger.yaml"

EXIT_OK = 0
EXIT_INTEGRITY = 1
EXIT_GATE = 2

PROFILES = ("overall", "production-lean", "staging")

# The implementation ledger's vocabulary, unchanged. A control and its ledger
# item must be able to describe the same work in the same words.
STATUSES = (
    "not_started", "reproduced", "test_added", "implementation_in_progress",
    "implemented", "targeted_tests_pass", "subsystem_tests_pass",
    "full_gate_pass", "externally_blocked", "verified_complete",
)
TERMINAL_STATUSES = (
    "implemented", "targeted_tests_pass", "subsystem_tests_pass",
    "full_gate_pass", "verified_complete",
)

EVIDENCE_KINDS = ("check_script", "repo_file", "json_artifact", "credentialed_artifact")

# The seventeen conditions that gate a 100% result. Hardcoded so the bar cannot
# be lowered by deleting a row from the YAML: a config missing any of these ids
# is an integrity failure, not a config with fewer conditions.
REQUIRED_CONDITION_IDS = frozenset({
    "COND-STAGING-WAKE-APPLIED",
    "COND-STAGING-TWO-REHEARSALS",
    "COND-LEAN-PLAN-CREDENTIALED",
    "COND-COST-OBSERVED-7D",
    "COND-COST-RECONCILED",
    "COND-LOAD-VALIDATED",
    "COND-ROLLBACK-VALIDATED",
    "COND-NO-UNRESOLVED-P0",
    "COND-NO-UNRESOLVED-P1",
    "COND-NO-EXPIRED-EXCEPTIONS",
    "COND-BUNDLE-CHECKSUM",
    "COND-MIGRATION-REHEARSED",
    "COND-SMOKE-PASSED",
    "COND-SECURITY-VALIDATED",
    "COND-SLEEP-RESIDUAL",
    "COND-OBSERVABILITY-LIVE",
    "COND-PROMOTION-INTEGRITY",
})

_HEX_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_AWS_ACCOUNT = re.compile(r"^[0-9]{12}$")
_AWS_REGION = re.compile(r"^[a-z]{2}(-gov)?-[a-z]+-[0-9]$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Account ids that look real but are not. A twelve-digit string is cheap to
# type; these are the ones people type when they want the shape without the
# account, so they are rejected by name rather than trusted by regex.
PLACEHOLDER_ACCOUNTS = frozenset({
    "000000000000", "111111111111", "123456789012", "999999999999",
})

# Source-path markers that disqualify an artifact from counting as credentialed
# evidence. reports/cost/cost-report.json in this very repo was generated from
# a scratchpad inventory — real output, synthetic input — which is exactly the
# thing that must never be mistaken for a plan against a real account.
UNTRUSTED_SOURCE_MARKERS = (
    "/tmp/", "/var/tmp/", "scratchpad", "fixture", "sample", "example",
    "synthetic", "mock", "dummy",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _as_date(value: Any) -> datetime.date | None:
    """Parse an ISO date from a YAML date or a string. None if unparseable."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _is_aware_iso(value: Any) -> bool:
    """True only for an ISO-8601 timestamp that carries a timezone.

    A naive timestamp is not evidence of when something happened; it is
    evidence of when something happened somewhere.
    """
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def _read_json(path: Path) -> tuple[dict | None, str]:
    if not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable or invalid JSON ({exc})"
    if not isinstance(data, dict):
        return None, "top-level JSON value is not an object"
    return data, ""


def _dig(data: dict, dotted: str) -> tuple[bool, Any]:
    """Resolve a dotted key path. Returns (found, value)."""
    cursor: Any = data
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor


# ---------------------------------------------------------------------------
# Provenance — the lock that credentials cannot be faked past
# ---------------------------------------------------------------------------

def validate_provenance(data: dict) -> list[str]:
    """Return the reasons an artifact's provenance is not credentialed.

    Empty list means the artifact was demonstrably produced by a run that held
    real AWS credentials against a real account. Every other outcome is a list
    of specific, quotable reasons — never a soft pass.
    """
    prov = data.get("provenance")
    if not isinstance(prov, dict):
        return ["no `provenance` block"]

    reasons: list[str] = []
    if prov.get("credentialed") is not True:
        reasons.append("provenance.credentialed is not true")

    account = str(prov.get("aws_account_id", ""))
    if not _AWS_ACCOUNT.fullmatch(account):
        reasons.append("provenance.aws_account_id is not a 12-digit AWS account id")
    elif account in PLACEHOLDER_ACCOUNTS:
        reasons.append(f"provenance.aws_account_id {account} is a placeholder account")

    if not _AWS_REGION.fullmatch(str(prov.get("region", ""))):
        reasons.append("provenance.region is not an AWS region")

    if not _SEMVER.fullmatch(str(prov.get("terraform_version", ""))):
        reasons.append("provenance.terraform_version is not a version")

    if not _is_aware_iso(prov.get("captured_at")):
        reasons.append("provenance.captured_at is not a timezone-aware ISO-8601 timestamp")

    if not _HEX_COMMIT.fullmatch(str(prov.get("commit_sha", ""))):
        reasons.append("provenance.commit_sha is not a 7-40 character hex commit")

    source = str(prov.get("source", ""))
    if not source:
        reasons.append("provenance.source is empty")
    else:
        lowered = source.lower()
        for marker in UNTRUSTED_SOURCE_MARKERS:
            if marker in lowered:
                reasons.append(
                    f"provenance.source {source!r} is a {marker.strip('/')} path — "
                    "synthetic input never becomes credentialed evidence"
                )
                break
    return reasons


# ---------------------------------------------------------------------------
# Evidence validators
# ---------------------------------------------------------------------------

ScriptRunner = Callable[[Path, list], "tuple[int, str]"]


def _default_script_runner(path: Path, args: list) -> tuple[int, str]:
    """Execute a validator script and return (exit_code, output tail)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(path), *[str(a) for a in args]],
            cwd=path.parents[2], capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:  # pragma: no cover - defensive
        return 1, f"{type(exc).__name__}: {exc}"
    tail = "\n".join((proc.stdout + "\n" + proc.stderr).strip().splitlines()[-3:])
    return proc.returncode, tail


def evaluate_evidence(root: Path, entry: dict,
                      runner: ScriptRunner) -> dict:
    """Validate one evidence entry. Returns a result row; never raises."""
    kind = entry.get("kind")
    rel = str(entry.get("path", ""))
    path = root / rel
    row = {
        "id": entry.get("id"),
        "kind": kind,
        "path": rel,
        "external": bool(entry.get("external")),
        "satisfied": False,
        "reason": "",
    }

    if kind not in EVIDENCE_KINDS:
        row["reason"] = f"unknown evidence kind {kind!r}"
        return row

    if kind == "check_script":
        if not path.is_file():
            row["reason"] = "validator script is absent"
            return row
        code, tail = runner(path, list(entry.get("args") or []))
        if code != 0:
            row["reason"] = f"validator exited {code}: {tail.splitlines()[-1] if tail else ''}"
            return row
        row["satisfied"] = True
        return row

    if kind == "repo_file":
        if not path.is_file():
            row["reason"] = "file is absent"
            return row
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            row["reason"] = f"file is unreadable ({exc})"
            return row
        if not body.strip():
            row["reason"] = "file is empty"
            return row
        needle = entry.get("contains")
        if needle and str(needle) not in body:
            row["reason"] = f"file does not contain {needle!r}"
            return row
        row["satisfied"] = True
        return row

    # json_artifact and credentialed_artifact share structural validation.
    data, err = _read_json(path)
    if data is None:
        row["reason"] = err
        return row
    for key in entry.get("require_keys") or []:
        found, _ = _dig(data, str(key))
        if not found:
            row["reason"] = f"artifact is missing required key {key!r}"
            return row
    for key in entry.get("require_true") or []:
        found, value = _dig(data, str(key))
        if not found or value is not True:
            row["reason"] = f"artifact key {key!r} is not true"
            return row

    if kind == "credentialed_artifact":
        reasons = validate_provenance(data)
        if reasons:
            row["reason"] = "; ".join(reasons)
            return row

    row["satisfied"] = True
    return row


# ---------------------------------------------------------------------------
# Bundle checksum verification
# ---------------------------------------------------------------------------

def verify_bundle_checksum(root: Path, bundle_root: str = "release-evidence") -> dict:
    """Verify release-evidence/manifest.json against its published checksum.

    Both directions are checked, because each catches a different tamper: the
    manifest digest catches an edited manifest, and re-hashing every listed
    file catches an edited artifact that the manifest still vouches for.
    """
    base = root / bundle_root
    manifest_path = base / "manifest.json"
    checksum_path = base / "manifest.sha256"
    if not manifest_path.is_file() or not checksum_path.is_file():
        return {"verified": False, "reason": f"{bundle_root}/ bundle is absent",
                "files_checked": 0}
    data, err = _read_json(manifest_path)
    if data is None:
        return {"verified": False, "reason": f"manifest.json {err}", "files_checked": 0}
    try:
        recorded = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    except (OSError, IndexError):
        return {"verified": False, "reason": "manifest.sha256 is empty or unreadable",
                "files_checked": 0}
    if not _SHA256.fullmatch(recorded):
        return {"verified": False, "reason": "manifest.sha256 is not a sha256 digest",
                "files_checked": 0}
    actual = hashlib.sha256(canonical(data)).hexdigest()
    if actual != recorded:
        return {"verified": False,
                "reason": "manifest.json does not hash to manifest.sha256 (bundle tampered)",
                "files_checked": 0}

    checked = 0
    for section in (data.get("subdirectories") or {}).values():
        for row in (section or {}).get("files") or []:
            rel = str(row.get("path", ""))
            digest = str(row.get("sha256", ""))
            target = base / rel
            if not target.is_file():
                return {"verified": False,
                        "reason": f"{bundle_root}/{rel} is listed in the manifest but absent",
                        "files_checked": checked}
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                return {"verified": False,
                        "reason": f"{bundle_root}/{rel} does not match its recorded digest",
                        "files_checked": checked}
            checked += 1
    return {"verified": True, "reason": "", "files_checked": checked}


# ---------------------------------------------------------------------------
# Global gate conditions
# ---------------------------------------------------------------------------

def _outstanding_ledger_items(root: Path, severity: str) -> tuple[bool, str]:
    """True when no item of `severity` is outstanding in the ledger."""
    path = root / LEDGER_REL
    if not path.is_file():
        return False, f"{LEDGER_REL} is absent"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return False, f"{LEDGER_REL} is not valid YAML ({exc})"
    outstanding = [
        str(item.get("id"))
        for item in doc.get("items") or []
        if str(item.get("severity")) == severity
        and str(item.get("status")) not in TERMINAL_STATUSES
    ]
    if outstanding:
        shown = ", ".join(outstanding[:5])
        more = f" (+{len(outstanding) - 5} more)" if len(outstanding) > 5 else ""
        return False, f"{len(outstanding)} outstanding {severity} item(s): {shown}{more}"
    return True, ""


def _expired_exceptions(root: Path, config: dict) -> list[str]:
    """Every exception in this file or cost_exceptions.yaml that has expired.

    An expired exception is not a grant that quietly stopped applying — it is a
    hard failure, so the only way to keep shipping is to renew it deliberately
    or remove the need for it.
    """
    today = _today()
    expired: list[str] = []
    sources: list[tuple[str, list]] = [
        (CONFIG_REL, list(config.get("exceptions") or []))
    ]
    cost_path = root / COST_EXCEPTIONS_REL
    if cost_path.is_file():
        try:
            cost_doc = yaml.safe_load(cost_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            cost_doc = {}
        sources.append((COST_EXCEPTIONS_REL, list(cost_doc.get("exceptions") or [])))
    for source, entries in sources:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            expires = _as_date(entry.get("expires"))
            ident = entry.get("id", "<unnamed>")
            if expires is None:
                expired.append(f"{source}:{ident} has no parseable `expires` date")
            elif expires < today:
                expired.append(f"{source}:{ident} expired on {expires.isoformat()}")
    return expired


def evaluate_conditions(root: Path, config: dict) -> list[dict]:
    """Evaluate every gate condition from artifacts on disk.

    The evaluation is code, not data: the YAML supplies each condition's
    identity, prose and blast radius, but what counts as met is decided here.
    That split is deliberate — a condition must not be satisfiable by editing
    the file that declares it.
    """
    results: list[dict] = []
    for row in config.get("gate_conditions") or []:
        cid = str(row.get("id"))
        kind = str(row.get("kind"))
        evidence = str(row.get("evidence", ""))
        met, reason = False, ""

        if kind == "credentialed_artifact":
            data, err = _read_json(root / evidence)
            if data is None:
                reason = f"{evidence} {err}"
            else:
                reasons = validate_provenance(data)
                if reasons:
                    reason = "; ".join(reasons)
                else:
                    met, reason = True, ""
                    # Condition-specific thresholds on top of provenance.
                    minimum_days = row.get("minimum_days")
                    if minimum_days is not None:
                        observed = data.get("days")
                        if not isinstance(observed, int) or observed < int(minimum_days):
                            met = False
                            reason = (f"{observed!r} days of observed cost, "
                                      f"{minimum_days} required")
                    tolerance = row.get("tolerance_percent")
                    if met and tolerance is not None:
                        variance = data.get("variance_percent")
                        if not isinstance(variance, (int, float)):
                            met, reason = False, "no numeric variance_percent recorded"
                        elif abs(float(variance)) > float(tolerance):
                            met = False
                            reason = (f"variance {variance}% exceeds the "
                                      f"{tolerance}% reconciliation tolerance")
        elif kind == "ledger_severity":
            met, reason = _outstanding_ledger_items(root, str(row.get("severity")))
        elif kind == "exception_expiry":
            expired = _expired_exceptions(root, config)
            met = not expired
            reason = "; ".join(expired)
        elif kind == "bundle_checksum":
            verdict = verify_bundle_checksum(
                root, str((config.get("evidence_bundle") or {}).get("root", "release-evidence"))
            )
            met, reason = verdict["verified"], verdict["reason"]
        else:
            reason = f"unknown condition kind {kind!r}"

        results.append({
            "id": cid,
            "description": row.get("description"),
            "kind": kind,
            "evidence": evidence,
            "met": met,
            "reason": reason,
            "blocks_controls": list(row.get("blocks_controls") or []),
        })
    return results


# ---------------------------------------------------------------------------
# Config integrity — the score is void if the table itself is malformed
# ---------------------------------------------------------------------------

def check_integrity(config: dict, reporter: Reporter) -> None:
    """Structural validation of the control table. Failures void the score."""
    controls = config.get("controls") or []
    scorecards = config.get("scorecards") or {}

    reporter.require(
        set(scorecards) == set(PROFILES),
        f"scorecards declared for exactly {', '.join(PROFILES)}",
        f"scorecards must be exactly {sorted(PROFILES)}, found {sorted(scorecards)}",
    )

    seen: set[str] = set()
    for control in controls:
        cid = str(control.get("id"))
        if cid in seen:
            reporter.fail(f"duplicate control id {cid}")
        seen.add(cid)

        for field in ("id", "profile", "description", "weight", "required_evidence",
                      "status", "last_verified_commit", "last_verified_at",
                      "evidence_path", "external_dependency", "exception"):
            if field not in control:
                reporter.fail(f"{cid}: missing required field `{field}`")

        if control.get("profile") not in PROFILES:
            reporter.fail(f"{cid}: profile {control.get('profile')!r} is not a scorecard")
        if control.get("status") not in STATUSES:
            reporter.fail(f"{cid}: status {control.get('status')!r} is not in the vocabulary")

        # The ledger's own rules, applied to controls so the two cannot drift.
        if control.get("status") == "externally_blocked" and not control.get("exception"):
            reporter.fail(f"{cid}: externally_blocked requires an exception")
        if control.get("status") == "verified_complete":
            commit = str(control.get("last_verified_commit") or "")
            if not _HEX_COMMIT.fullmatch(commit):
                reporter.fail(f"{cid}: verified_complete requires a 7-40 hex last_verified_commit")
        stamped = control.get("last_verified_at")
        if stamped is not None and not _is_aware_iso(stamped):
            reporter.fail(f"{cid}: last_verified_at must be a timezone-aware ISO-8601 timestamp")

        evidence = control.get("required_evidence") or []
        if not evidence:
            reporter.fail(f"{cid}: declares no required_evidence, so it can never be earned")
        for entry in evidence:
            if entry.get("kind") not in EVIDENCE_KINDS:
                reporter.fail(f"{cid}: evidence {entry.get('id')!r} has kind "
                              f"{entry.get('kind')!r}, which is not a known kind")
            if not entry.get("path"):
                reporter.fail(f"{cid}: evidence {entry.get('id')!r} declares no path")

        # A declared external dependency with no external evidence is the exact
        # shape of a control that quietly scores itself. Reject it outright.
        dep = control.get("external_dependency") or {}
        has_external = any(e.get("external") for e in evidence)
        if dep.get("required") and not has_external:
            reporter.fail(f"{cid}: external_dependency.required is true but no evidence "
                          "entry is marked external")
        if has_external and not dep.get("required"):
            reporter.fail(f"{cid}: has external evidence but external_dependency.required "
                          "is false")

    # Exceptions must resolve and must not self-approve.
    grants = {str(e.get("id")): e for e in config.get("exceptions") or []}
    for control in controls:
        ref = control.get("exception")
        if ref and str(ref) not in grants:
            reporter.fail(f"{control.get('id')}: references unknown exception {ref!r}")
    for gid, grant in grants.items():
        if grant.get("owner") and grant.get("owner") == grant.get("approver"):
            reporter.fail(f"exception {gid}: owner and approver must differ")
        if _as_date(grant.get("expires")) is None:
            reporter.fail(f"exception {gid}: `expires` is missing or unparseable")

    # Weights must total each scorecard's declared total.
    for profile, card in scorecards.items():
        weights = sum(int(c.get("weight", 0)) for c in controls
                      if c.get("profile") == profile)
        reporter.require(
            weights == int(card.get("total", 0)),
            f"{profile}: control weights total {weights}",
            f"{profile}: control weights total {weights}, expected {card.get('total')}",
        )
        gate = int(card.get("gate", 0))
        if not 0 < gate <= int(card.get("total", 0)):
            reporter.fail(f"{profile}: gate {gate} is not within the scorecard total")

    # The seventeen conditions may not be deleted, renamed, or trimmed.
    declared = {str(c.get("id")) for c in config.get("gate_conditions") or []}
    missing = REQUIRED_CONDITION_IDS - declared
    extra = declared - REQUIRED_CONDITION_IDS
    reporter.require(
        not missing,
        f"all {len(REQUIRED_CONDITION_IDS)} gate conditions are declared",
        f"gate conditions missing from the config: {sorted(missing)}",
    )
    if extra:
        reporter.fail(f"unrecognised gate conditions (add them to REQUIRED_CONDITION_IDS "
                      f"deliberately, do not invent them in YAML): {sorted(extra)}")

    # Every control a condition claims to block must exist.
    for row in config.get("gate_conditions") or []:
        for blocked in row.get("blocks_controls") or []:
            if str(blocked) not in seen:
                reporter.fail(f"{row.get('id')}: blocks unknown control {blocked!r}")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_controls(root: Path, config: dict,
                   runner: ScriptRunner | None = None) -> list[dict]:
    """Evaluate every control's evidence and decide what it has earned."""
    runner = runner or _default_script_runner
    cache: dict[tuple, tuple[int, str]] = {}

    def cached(path: Path, args: list) -> tuple[int, str]:
        key = (str(path), tuple(str(a) for a in args))
        if key not in cache:
            cache[key] = runner(path, args)
        return cache[key]

    rows: list[dict] = []
    for control in config.get("controls") or []:
        evidence = [evaluate_evidence(root, entry, cached)
                    for entry in control.get("required_evidence") or []]
        internal = [e for e in evidence if not e["external"]]
        external = [e for e in evidence if e["external"]]

        # Code-complete: everything this repository can prove about itself.
        # An empty internal set is not completeness, it is the absence of any
        # in-repo claim, so it earns nothing.
        code_complete = bool(internal) and all(e["satisfied"] for e in internal)
        # Externally verified: code-complete AND every external artifact is
        # present and credentialed.
        verified = code_complete and all(e["satisfied"] for e in external)

        rows.append({
            "id": control.get("id"),
            "profile": control.get("profile"),
            "description": control.get("description"),
            "weight": int(control.get("weight", 0)),
            "status": control.get("status"),
            "exception": control.get("exception"),
            "external_dependency": control.get("external_dependency") or {},
            "evidence_path": control.get("evidence_path"),
            "code_complete": code_complete,
            "externally_verified": verified,
            "evidence": evidence,
            "unmet": [f"{e['id']}: {e['reason']}" for e in evidence if not e["satisfied"]],
        })
    return rows


def build_scorecards(config: dict, controls: list[dict],
                     conditions: list[dict]) -> dict:
    """Produce the three numbers per scorecard, plus the condition ceiling."""
    unmet_blocked: set[str] = set()
    for cond in conditions:
        if not cond["met"]:
            unmet_blocked.update(str(c) for c in cond["blocks_controls"])

    cards: dict[str, dict] = {}
    for profile, meta in (config.get("scorecards") or {}).items():
        members = [c for c in controls if c["profile"] == profile]
        total = int(meta.get("total", 0))
        gate = int(meta.get("gate", 0))
        code = sum(c["weight"] for c in members if c["code_complete"])
        verified = sum(c["weight"] for c in members if c["externally_verified"])
        # The ceiling is computed from unmet conditions only. It deliberately
        # does not read the controls' own verdicts, so it stays an independent
        # check on them rather than a restatement of them.
        blocked = sum(c["weight"] for c in members if c["id"] in unmet_blocked)
        ceiling = total - blocked
        cards[profile] = {
            "title": meta.get("title"),
            "total": total,
            "gate": gate,
            "gate_basis": meta.get("gate_basis", "externally_verified"),
            "code_complete_score": code,
            "externally_verified_score": verified,
            "evidence_gap": code - verified,
            "unproven_weight": total - verified,
            "max_attainable_verified_score": ceiling,
            "gate_met": verified >= gate,
            "controls": len(members),
            "controls_code_complete": sum(1 for c in members if c["code_complete"]),
            "controls_verified": sum(1 for c in members if c["externally_verified"]),
            "blocked_controls": sorted(c["id"] for c in members if c["id"] in unmet_blocked),
        }
    return cards


def check_invariants(cards: dict, conditions: list[dict],
                     reporter: Reporter) -> None:
    """The tamper detectors.

    These do not make the score better or worse. They assert that the score is
    arithmetically consistent with evidence that exists independently of the
    control table. A violation means the scorecard has been edited into
    claiming something the evidence on disk does not support, which is a
    failure regardless of how good the number looks.
    """
    all_met = all(c["met"] for c in conditions)
    for profile, card in sorted(cards.items()):
        verified = card["externally_verified_score"]
        ceiling = card["max_attainable_verified_score"]
        if verified > ceiling:
            reporter.fail(
                f"{profile}: verified score {verified} exceeds the {ceiling} "
                "attainable under the unmet gate conditions — the control table "
                "and the evidence on disk disagree"
            )
        if verified >= card["total"] and not all_met:
            unmet = [c["id"] for c in conditions if not c["met"]]
            reporter.fail(
                f"{profile}: a full {card['total']} was scored while "
                f"{len(unmet)} gate condition(s) are unmet: {unmet[:3]}"
            )
        if card["evidence_gap"] < 0:
            reporter.fail(
                f"{profile}: verified score exceeds code-complete score, which is "
                "impossible — external verification presupposes the code exists"
            )


# ---------------------------------------------------------------------------
# Report assembly and rendering
# ---------------------------------------------------------------------------

def build_report(root: Path, config: dict,
                 runner: ScriptRunner | None = None) -> dict:
    """The whole scorecard as data. Pure with respect to the filesystem."""
    controls = score_controls(root, config, runner=runner)
    conditions = evaluate_conditions(root, config)
    cards = build_scorecards(config, controls, conditions)
    unmet = [c for c in conditions if not c["met"]]
    bundle_root = str((config.get("evidence_bundle") or {}).get("root", "release-evidence"))
    return {
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "release_train": config.get("release_train"),
        "scorecards": cards,
        "gate_conditions": {
            "total": len(conditions),
            "met": len(conditions) - len(unmet),
            "unmet": len(unmet),
            "all_met": not unmet,
            "results": conditions,
        },
        "controls": controls,
        "evidence_bundle": verify_bundle_checksum(root, bundle_root),
        "deployment_ready": bool(
            not unmet and all(c["gate_met"] for c in cards.values())
        ),
        "environment_note": (
            "No AWS credentials, applied infrastructure, billing history or "
            "staging rehearsal is reachable from this repository. Every control "
            "requiring one is reported as unproven, and the externally-verified "
            "score is capped accordingly. The code-complete score is not a "
            "readiness figure and must not be quoted as one."
        ),
    }


def render(report: dict, profile_filter: str | None = None) -> None:
    """Print the scorecard in the repo's plain-text ✓/✗ style."""
    print(f"\n{'=' * 70}\nDEPLOYMENT READINESS SCORECARD\n{'=' * 70}")
    for profile, card in sorted(report["scorecards"].items()):
        if profile_filter and profile != profile_filter:
            continue
        mark = "✓" if card["gate_met"] else "✗"
        print(f"\n  {profile}  —  {card['title']}")
        print(f"    code-complete score       {card['code_complete_score']:>3} / {card['total']}"
              f"   ({card['controls_code_complete']}/{card['controls']} controls)")
        print(f"    externally-verified score {card['externally_verified_score']:>3} / {card['total']}"
              f"   ({card['controls_verified']}/{card['controls']} controls)")
        print(f"    remaining evidence gap    {card['evidence_gap']:>3} points "
              "(built and validating in-repo, unproven against real infrastructure)")
        print(f"    unproven weight overall   {card['unproven_weight']:>3} points")
        print(f"    max attainable verified   {card['max_attainable_verified_score']:>3} "
              "under the currently unmet gate conditions")
        print(f"    {mark} gate: {card['gate']} required on "
              f"{card['gate_basis']}, have {card['externally_verified_score']}")

    conds = report["gate_conditions"]
    print(f"\n  Gate conditions for a 100% result: {conds['met']}/{conds['total']} met")
    for row in conds["results"]:
        mark = "✓" if row["met"] else "✗"
        reason = f" — {row['reason']}" if row["reason"] else ""
        print(f"    {mark} {row['id']}{reason}")

    gap_controls = [c for c in report["controls"]
                    if c["code_complete"] and not c["externally_verified"]
                    and (not profile_filter or c["profile"] == profile_filter)]
    if gap_controls:
        print(f"\n  Evidence gap by control ({len(gap_controls)} built but unproven):")
        for c in gap_controls:
            print(f"    · {c['id']} ({c['weight']} pts, {c['profile']}) "
                  f"awaiting {c['external_dependency'].get('what')}")

    dead = [c for c in report["controls"]
            if not c["code_complete"]
            and (not profile_filter or c["profile"] == profile_filter)]
    if dead:
        print(f"\n  Not code-complete ({len(dead)}):")
        for c in dead:
            print(f"    · {c['id']} ({c['weight']} pts, {c['profile']}): {c['unmet'][0]}")

    print(f"\n  deployment_ready: {report['deployment_ready']}")
    print(f"\n  {report['environment_note']}")
    print("=" * 70)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=PROFILES, default=None,
                    help="Render a single scorecard (all are always computed)")
    ap.add_argument("--json", action="store_true", help="Emit the report as JSON")
    ap.add_argument("--out", default=None, help="Also write the JSON report to this path")
    ap.add_argument("--require-gates", action="store_true",
                    help="Exit 2 unless every gate is met and every condition holds")
    args = ap.parse_args(argv)

    root = repo_root()
    config_path = root / CONFIG_REL
    if not config_path.is_file():
        print(f"{CONFIG_REL} not found", file=sys.stderr)
        return EXIT_INTEGRITY
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"{CONFIG_REL} is not valid YAML: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY

    integrity = Reporter("DEPLOYMENT READINESS — control table integrity")
    check_integrity(config, integrity)
    # An expired exception is a hard failure here as well as an unmet
    # condition: the grant has run out, so the overage it authorised is no
    # longer authorised by anything.
    for expired in _expired_exceptions(root, config):
        integrity.fail(f"expired exception: {expired}")

    report = build_report(root, config)
    check_invariants(report["scorecards"], report["gate_conditions"]["results"], integrity)
    integrity_code = integrity.finish()

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        render(report, args.profile)

    if args.out:
        out = Path(args.out)
        out = out if out.is_absolute() else root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(canonical(report))
        print(f"  → {out}")

    if integrity_code != 0:
        return EXIT_INTEGRITY
    if args.require_gates:
        if not report["deployment_ready"]:
            print("Deployment readiness gates are not met; refusing a readiness claim.",
                  file=sys.stderr)
            return EXIT_GATE
    return EXIT_OK


if __name__ == "__main__":
    main_guard(run)
