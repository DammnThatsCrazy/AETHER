#!/usr/bin/env python3
"""Compliance-readiness inventory generator (readiness-only; not certification).

Maps existing platform controls to a readiness status + evidence pointers and
prints a Markdown report. This is **pre-positioning / evidence mapping** — it
does NOT assert SOC 2 / GDPR / FedRAMP compliance and is not legal advice. Any
certification requires an external audit / authorized assessment.

Usage:
  python scripts/compliance/readiness.py            # print report
  python scripts/compliance/readiness.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# Backend source lives under this subtree; evidence paths are repo-root-relative
# so (ROOT / evidence).exists() resolves correctly from `npm run compliance:*`.
_BK = "Backend Architecture/aether-backend"

# control_id -> (description, evidence path/doc, readiness)
CONTROLS: list[tuple[str, str, str, str]] = [
    ("AC-tenant-isolation", "Tenant isolation enforced + verifier", f"{_BK}/services/security/isolation_verifier.py", "implemented"),
    ("AC-rbac", "Role/permission access control", f"{_BK}/services/security/access_control.py", "implemented"),
    ("AC-break-glass", "Time-boxed operator break-glass + approval", f"{_BK}/services/security/break_glass.py", "implemented"),
    ("AU-audit-ledger", "Tamper-evident audit event ledger", f"{_BK}/services/security/audit_ledger.py", "implemented"),
    ("AU-export-governance", "Governed, integrity-hashed audit exports", f"{_BK}/services/security/export_governance.py", "implemented"),
    ("SC-secrets", "No secrets in logs/UI/exports; vault + sanitization", "docs/SECRETS-MANAGEMENT.md", "implemented"),
    ("SC-webhook-signing", "HMAC-signed webhooks + verification", f"{_BK}/services/security/integration_security.py", "implemented"),
    ("SC-rate-limit", "Per-plan rate limits + quota", f"{_BK}/shared/rate_limit", "implemented"),
    ("DM-retention", "Data retention policies + audit-preserving deletion", f"{_BK}/services/security/retention.py", "implemented"),
    ("DM-data-requests", "DSR / data-request handling", f"{_BK}/services/consent", "implemented"),
    ("RE-reliability", "Service/pipeline/queue health, incidents, SLOs", f"{_BK}/services/reliability", "implemented"),
    ("DQ-data-quality", "Data quality + drift + contamination escalation", f"{_BK}/services/data_quality", "implemented"),
    ("VM-dependency-audit", "Dependency audit tooling — npm run security:deps gated in CI (advisory — reports vulns, never blocks)", "docs/DEPENDENCY-AUDIT.md", "implemented"),
    ("VM-secret-scan", "Secret scanning tooling — npm run security:secrets gated in CI (fail-closed — exits 1 on high-confidence secret)", "scripts/security/secret_scan.py", "implemented"),
    ("IR-incident-response", "Incident response + tabletop", "docs/INCIDENT-RESPONSE-TABLETOP.md", "documented"),
    ("PR-privacy", "Privacy review + consent", "docs/PRIVACY-REVIEW.md", "documented"),
    ("PT-pentest", "Penetration-test readiness", "docs/PENETRATION-TEST-READINESS.md", "documented"),
    ("TM-threat-model", "Threat model review", "docs/THREAT-MODEL.md", "documented"),
]

DISCLAIMER = (
    "Readiness / pre-positioning only. Not certified, not legal advice. "
    "SOC 2 / GDPR / FedRAMP status requires external audit / legal review / "
    "authorized assessment."
)


def build() -> dict:
    items = [
        {"control_id": c, "description": d, "evidence": e, "readiness": r,
         "evidence_present": (ROOT / e).exists()}
        for (c, d, e, r) in CONTROLS
    ]
    return {
        "disclaimer": DISCLAIMER,
        "controls": items,
        "summary": {
            "total": len(items),
            "implemented": sum(1 for i in items if i["readiness"] == "implemented"),
            "evidence_present": sum(1 for i in items if i["evidence_present"]),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print("# Compliance Readiness Inventory\n")
    print(f"> {report['disclaimer']}\n")
    s = report["summary"]
    print(f"Controls: {s['total']} · implemented: {s['implemented']} · evidence present: {s['evidence_present']}\n")
    for i in report["controls"]:
        mark = "✓" if i["evidence_present"] else "·"
        print(f"- [{mark}] {i['control_id']} — {i['description']} ({i['readiness']}) → {i['evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
