#!/usr/bin/env python3
"""Assemble the checksummed, tenant-scoped pilot evidence package.

The package is DERIVED from real repo + certification state (never asserted by
hand) and is scoped to one pilot manifest's tenant. In a credentialless
environment the operational results (connection / backfill / webhook /
reconciliation / freshness / coverage) are the descriptor-level certification
outcomes (honest mock) — clearly labelled as such; no secret VALUE is ever read
or emitted, only credential reference names and readiness states.

Contents:
  * repo / deployment-profile / migration versions
  * feature flags + entitlements (from the manifest)
  * provider adapter versions + implementation states (shared/certification)
  * credential states (reference names + readiness; NO secret values)
  * connection/backfill/webhook/reconciliation/freshness/coverage (mock)
  * consent + region decisions (from the manifest)
  * graph / gold status
  * reward delivery / receipt status (shadow => not delivered)
  * agent run / approval evidence
  * kill-switch test
  * restore evidence
  * known limitations
  * pilot-readiness decision
  * sha256 checksum over the canonical bundle

Time comes from shared.temporal (no float). Exit 0 on success.

Usage:
  python scripts/pilot_evidence.py
  python scripts/pilot_evidence.py --manifest config/pilot/examples/usdc-observation.yaml
  python scripts/pilot_evidence.py --out artifacts/pilot-evidence --format json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
DEFAULT_MANIFEST = ROOT / "config" / "pilot" / "examples" / "usdc-observation.yaml"
DEFAULT_OUT = ROOT / "artifacts" / "pilot-evidence"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")


def _now_iso() -> str:
    """Canonical UTC instant via the temporal kernel (no float, no ad-hoc now)."""
    try:
        from shared.temporal import SYSTEM_CLOCK, to_iso_utc  # type: ignore
        return to_iso_utc(SYSTEM_CLOCK.now())
    except Exception:
        import datetime
        return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _platform_version() -> str:
    try:
        data = tomllib.load(open(ROOT / "pyproject.toml", "rb"))
        return data.get("project", {}).get("version") or data.get("tool", {}).get("poetry", {}).get("version") or "unknown"
    except Exception:
        return "unknown"


def _migration_heads() -> dict:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config()
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        script = ScriptDirectory.from_config(cfg)
        heads = list(script.get_heads())
        return {"single_head": len(heads) == 1, "count": len(heads), "heads": heads}
    except Exception as exc:
        return {"single_head": None, "count": None, "heads": [], "error": str(exc)}


def _certification():
    from shared.certification import (  # type: ignore
        build_capability_matrix,
        iter_first_release_descriptors,
        run_certification,
    )
    return build_capability_matrix(), iter_first_release_descriptors(), run_certification


# Map certification checks onto the operational evidence categories the pilot
# gate reports. Each category is PASS if all its underlying checks pass (skips
# count as pass, matching the framework's semantics), FAIL otherwise.
_CATEGORY_CHECKS = {
    "connection": ["check_request_construction", "check_auth_injection", "check_timeout_declared"],
    "backfill": ["check_pagination", "check_cursor_persistence"],
    "webhook": ["check_malformed_input", "check_schema_drift"],
    "reconciliation": ["check_duplicate_handling", "check_out_of_order_handling", "check_idempotent_replay"],
    "freshness": ["check_health_transitions"],
    "coverage": ["check_descriptor_completeness", "check_unsupported_marked", "check_honest_status"],
}


def _provider_evidence(manifest: dict) -> tuple[list, dict]:
    matrix, descriptors, run_certification = _certification()
    selected = {(p.get("domain"), p.get("provider")) for p in manifest.get("providers", [])}
    by_key = {(d.domain, d.provider): d for d in descriptors}

    providers_out: list = []
    op_agg = {cat: {"pass": 0, "fail": 0, "skip": 0} for cat in _CATEGORY_CHECKS}
    for key in sorted(selected):
        d = by_key.get(key)
        if d is None:
            providers_out.append({"domain": key[0], "provider": key[1],
                                  "error": "not in certification matrix"})
            continue
        results = run_certification(d)
        by_name = {r.name: r for r in results}
        passed = sum(1 for r in results if r.passed and not r.skipped)
        skipped = sum(1 for r in results if r.skipped)
        failed = [r.name for r in results if not r.passed]
        per_cat = {}
        for cat, names in _CATEGORY_CHECKS.items():
            present = [by_name[n] for n in names if n in by_name]
            cat_pass = all(r.passed for r in present) if present else True
            per_cat[cat] = "PASS" if cat_pass else "FAIL"
            bucket = "pass" if cat_pass else "fail"
            op_agg[cat][bucket] += 1
        providers_out.append({
            "domain": d.domain,
            "provider": d.provider,
            "adapter": d.adapter,
            "adapter_version": d.adapter_version,
            "implementation_state": d.implementation_state.value,
            "first_release": d.first_release,
            "required_credentials": sorted(d.required_credentials),
            "secret_ref_names": sorted(d.secret_ref_names),
            "certification": {"passed": passed, "skipped": skipped,
                              "failed_checks": failed, "total": len(results)},
            "operational_categories": per_cat,
        })
    return providers_out, op_agg


def _credential_states(manifest: dict) -> list:
    """Reference names + provisioning state. NEVER a secret value."""
    states = []
    for ref in manifest.get("secret_refs", []):
        states.append({"ref": ref, "provided": False, "source": "reference-only",
                       "note": "credentialless — value not read"})
    return states


def build_evidence(manifest_path: Path) -> dict:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    providers, op_agg = _provider_evidence(manifest)
    shadow = bool(manifest.get("shadow_mode"))
    rewards = manifest.get("rewards") or {}

    bundle = {
        "schema": "aether.pilot_evidence/v1",
        "generated_at": _now_iso(),
        "credentialless_mode": True,
        "tenant_id": manifest.get("tenant_id"),
        "manifest": {
            "path": str(manifest_path.relative_to(ROOT)) if manifest_path.is_relative_to(ROOT) else str(manifest_path),
            "manifest_version": manifest.get("manifest_version"),
            "mode": manifest.get("mode"),
            "shadow_mode": shadow,
            "pilot": manifest.get("pilot"),
        },
        "versions": {
            "platform_version": _platform_version(),
            "repo": {"commit": _git("rev-parse", "HEAD"),
                     "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
                     "dirty": bool(_git("status", "--porcelain"))},
            "deployment_profile": "production-lean",
            "migration": _migration_heads(),
        },
        "feature_flags": list(manifest.get("enabled_features", [])),
        "entitlements": manifest.get("entitlements", []),
        "providers": providers,
        "credential_states": _credential_states(manifest),
        "operational_evidence": {
            "mode": "credentialless-mock (descriptor-level certification)",
            "by_category": op_agg,
        },
        "consent_region": {
            "consent": manifest.get("consent"),
            "region_policy": manifest.get("region_policy"),
        },
        "graph_gold_status": {
            "graph_backend": "postgres (lean profile)",
            "gold_layer": "measurement gold (deploy/clickhouse/schemas/008_measurement_gold.sql)",
            "status": "shadow-computed" if shadow else "live",
        },
        "rewards": {
            "enabled": bool(rewards.get("enabled")),
            "delivered": False if shadow or not rewards.get("enabled") else None,
            "receipts": [],
            "note": "shadow mode — rewards computed but not delivered" if shadow else "live delivery",
        },
        "agent_runs": {
            "runs": [], "approvals": [],
            "note": "no agent runs executed in credentialless evidence collection",
        },
        "kill_switch_test": {
            "switches": manifest.get("kill_switches", []),
            "all_armed": all(k.get("default_state") == "armed" for k in manifest.get("kill_switches", [])),
            "test": "declared-state-verified (armed) — live trip test requires a running stack",
        },
        "restore_evidence": {
            "backup_model": "DB-level automated snapshots (aurora/rds/neptune)",
            "restore_suite": "make integration-faults (outbox/storage crash + replay) — requires Docker",
            "verified_here": False,
        },
        "known_limitations": [
            "Operational results are descriptor-level certification (credentialless mock), not live-credential runs.",
            "Distributed tracing is a documented gap (see config/deploy_profile.yaml traces).",
            "Backup/restore is DB-snapshot level; no dedicated AWS Backup vault module yet.",
            "Live kill-switch trip and restore drills require a running stack + cloud creds.",
        ],
    }

    all_first_release_waiting = all(
        p.get("implementation_state") == "credential_waiting"
        for p in providers if "implementation_state" in p
    )
    blocking = []
    if any(p.get("certification", {}).get("failed_checks") for p in providers):
        blocking.append("one or more provider certification checks failed")
    if bundle["versions"]["migration"].get("single_head") is not True:
        blocking.append("alembic is not at a single head")
    unprovided = [c["ref"] for c in bundle["credential_states"] if not c["provided"]]
    decision = "READY_PENDING_CREDENTIALS" if (all_first_release_waiting and not blocking) else (
        "BLOCKED" if blocking else "READY")
    bundle["readiness_decision"] = {
        "decision": decision,
        "blocking": blocking,
        "credentials_pending": unprovided,
        "rationale": (
            "All selected first-release providers are certified at CREDENTIAL_WAITING with no "
            "failed checks; the pilot is code-complete and awaits credential provisioning + a "
            "live staging run."
            if decision == "READY_PENDING_CREDENTIALS"
            else "See blocking list."
        ),
    }
    return bundle


def _checksum(bundle: dict) -> str:
    payload = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output directory (a <tenant>.evidence.<fmt> + .sha256 are written)")
    ap.add_argument("--format", choices=["json", "yaml"], default="json")
    ap.add_argument("--print", action="store_true", help="also print the bundle to stdout")
    ap.add_argument("--no-write", action="store_true", help="do not write files (print checksum only)")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    bundle = build_evidence(manifest_path)
    checksum = _checksum(bundle)
    bundle_with_sum = dict(bundle)
    bundle_with_sum["checksum"] = {"algorithm": "sha256", "value": checksum,
                                   "over": "canonical bundle excluding this field"}

    text = (json.dumps(bundle_with_sum, indent=2) if args.format == "json"
            else yaml.safe_dump(bundle_with_sum, sort_keys=False, width=100))

    if not args.no_write:
        out_dir = Path(args.out)
        if not out_dir.is_absolute():
            out_dir = ROOT / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{bundle['tenant_id']}.evidence"
        out_file = out_dir / f"{stem}.{args.format}"
        out_file.write_text(text, encoding="utf-8")
        (out_dir / f"{stem}.sha256").write_text(f"{checksum}  {out_file.name}\n", encoding="utf-8")
        print(f"pilot evidence written: {out_file}")
        print(f"checksum (sha256): {checksum}")
    else:
        print(f"checksum (sha256): {checksum}")

    if args.print:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
