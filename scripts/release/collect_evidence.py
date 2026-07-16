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
import os
import re
import subprocess
import sys

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


def build_bundle(ci_log: str | None = None) -> dict:
    results = {name: _run(script) for name, script in EVIDENCE_CHECKS}
    passed = sum(1 for v in results.values() if v.get("exit_code") == 0)

    return {
        "timestamp": _now_iso(),
        "release_train": "FOUNDING_TENANT_PRODUCTION",
        "git": git_state(),
        "evidence_checks": results,
        "implementation_ledger": ledger_section(),
        "route_registry": route_registry_section(),
        "consent_purposes": consent_section(),
        "sdk_conformance": sdk_conformance_section(),
        "ci_check": ci_check_section(ci_log),
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
    args = ap.parse_args()

    bundle = build_bundle(ci_log=args.ci_log)
    text = yaml.safe_dump(bundle, sort_keys=False, width=100)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
