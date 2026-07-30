#!/usr/bin/env python3
"""Validate the compliance ConsentPurpose enum is in sync with the canonical
consent registry.

The compliance project (`GDPR & SOC2/aether-compliance`) owns a
`config.consent_registry_sync.assert_consent_registry_in_sync()` helper that
compares its `ConsentPurpose` enum + explicit-opt-in flags against
`packages/shared/contracts/consent-registry.json`. This root gate invokes it so
`make ci-check` catches compliance-layer purpose drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPLIANCE_DIR = ROOT / "GDPR & SOC2" / "aether-compliance"


def main() -> int:
    if not COMPLIANCE_DIR.exists():
        print("compliance project not present — skipping consent-purpose reconciliation")
        return 0
    sys.path.insert(0, str(COMPLIANCE_DIR))
    try:
        from config.consent_registry_sync import assert_consent_registry_in_sync
    except Exception as exc:  # infra missing is a failure — the gate must exist
        print("consent-purpose reconciliation FAILED: could not import "
              f"config.consent_registry_sync ({exc})")
        print("Expected: GDPR & SOC2/aether-compliance/config/consent_registry_sync.py")
        return 1
    try:
        assert_consent_registry_in_sync()
    except Exception as exc:
        print(f"consent-purpose reconciliation FAILED: {exc}")
        print("Reconcile ConsentPurpose in GDPR & SOC2/aether-compliance/config/"
              "compliance_config.py with the canonical registry.")
        return 1
    print("consent-purpose reconciliation OK (compliance ConsentPurpose ↔ canonical registry).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
