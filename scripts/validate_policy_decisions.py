#!/usr/bin/env python3
"""Validate the central consent PolicyDecision evidence service.

Static/contract gate (no backend import): the service exists, the decision record
carries the required evidence fields, the signal-use matrix is the runtime
purpose source (no broad-consent fallback), and the router is wired.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "policy"
MAIN = ROOT / "Backend Architecture" / "aether-backend" / "main.py"

REQUIRED_FILES = ["__init__.py", "contracts.py", "engine.py", "signal_use_matrix.py",
                  "repositories.py", "routes.py"]
REQUIRED_DECISION_FIELDS = [
    "policy_decision_id", "tenant_id", "actor_id", "action", "purpose",
    "signal_type", "required_purposes", "missing_purposes", "granted_purposes",
    "allowed", "denied_reason", "redacted_fields", "consent_snapshot_id",
]

ERRORS: list[str] = []


def fail(m: str) -> None:
    ERRORS.append(m)


def main() -> int:
    if not POLICY.exists():
        fail("missing services/policy/ (central consent PolicyDecision service)")
        return _report()

    for f in REQUIRED_FILES:
        if not (POLICY / f).exists():
            fail(f"services/policy/{f} missing")

    contracts = (POLICY / "contracts.py").read_text() if (POLICY / "contracts.py").exists() else ""
    for field in REQUIRED_DECISION_FIELDS:
        if not re.search(rf"^\s*{field}\s*[:=]", contracts, re.M):
            fail(f"ConsentPolicyDecision missing field: {field}")

    engine = (POLICY / "engine.py").read_text() if (POLICY / "engine.py").exists() else ""
    # Purposes must come from the signal-use matrix or the explicit purpose only.
    if "signal_use_matrix" not in engine and "import matrix" not in engine and "matrix" not in engine:
        fail("engine must resolve purposes via the signal-use matrix (no broad-consent fallback)")
    # Must persist + audit on denial (join the tamper-evident ledger).
    if "audit_ledger" not in engine:
        fail("engine must record decisions in the security audit ledger")

    matrix = (POLICY / "signal_use_matrix.py").read_text() if (POLICY / "signal_use_matrix.py").exists() else ""
    if "signal-use-matrix.json" not in matrix:
        fail("signal_use_matrix.py must load packages/shared/contracts/signal-use-matrix.json")

    main_src = MAIN.read_text() if MAIN.exists() else ""
    if "policy_router" not in main_src or "services.policy.routes" not in main_src:
        fail("policy router not wired into main.py")

    return _report()


def _report() -> int:
    if ERRORS:
        print("consent PolicyDecision validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print("consent PolicyDecision validation OK (service present, evidence fields, matrix-driven, wired).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
