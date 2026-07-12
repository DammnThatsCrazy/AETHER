#!/usr/bin/env python3
"""Validate the founding-tenant control spine (ledger + catalog + posture).

Checks:
  1. All three control-spine files parse.
  2. Ledger items use only allowed status/severity/release_class values.
  3. Items implemented THIS session (PR 0 + PR 1) are in a terminal status.
  4. No control is marked externally_assessed (never allowed from within repo).

Usage: python scripts/release/check_foundation.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

ALLOWED_STATUS = {
    "not_started", "reproduced", "test_added", "implementation_in_progress",
    "implemented", "targeted_tests_pass", "subsystem_tests_pass",
    "full_gate_pass", "externally_blocked", "verified_complete",
}
TERMINAL_STATUS = {
    "implemented", "targeted_tests_pass", "subsystem_tests_pass",
    "full_gate_pass", "verified_complete",
}
ALLOWED_SEVERITY = {"P0", "P1", "P2", "P3"}
ALLOWED_RELEASE_CLASS = {
    "founding_tenant_release_blocker", "general_availability_blocker",
    "enterprise_ga_blocker", "scale_blocker", "audit_readiness_blocker",
    "external_action", "informational",
}
# Items this session is responsible for completing.
THIS_SESSION_ITEMS = {
    "FT-0-CONTROL-SPINE", "FT-COST-POLICY-DATA",
    "FT-1-NO-HUMAN-API-KEYS", "FT-1-SESSIONS-CREDENTIALS",
}


def check() -> int:
    r = Reporter("FOUNDATION — ledger + control catalog + posture")

    try:
        ledger = load_yaml("config/implementation_ledger.yaml")
    except FileNotFoundError:
        r.fail("config/implementation_ledger.yaml not found")
        return r.finish()
    try:
        catalog = load_yaml("config/control_catalog.yaml")
    except FileNotFoundError:
        r.fail("config/control_catalog.yaml not found")
        return r.finish()
    try:
        load_yaml("config/posture/founding_tenant_production.yaml")
        r.ok("posture file parses")
    except FileNotFoundError:
        r.fail("config/posture/founding_tenant_production.yaml not found")
        return r.finish()

    items = (ledger or {}).get("items", [])
    r.require(bool(items), "ledger has items", "ledger has no items")

    ids = set()
    for item in items or []:
        iid = (item or {}).get("id", "?")
        ids.add(iid)
        status = (item or {}).get("status")
        r.require(status in ALLOWED_STATUS,
                  f"{iid}: status valid ({status})", f"{iid}: invalid status {status}")
        sev = (item or {}).get("severity")
        r.require(sev in ALLOWED_SEVERITY,
                  f"{iid}: severity valid ({sev})", f"{iid}: invalid severity {sev}")
        rc = (item or {}).get("release_class")
        r.require(rc in ALLOWED_RELEASE_CLASS,
                  f"{iid}: release_class valid", f"{iid}: invalid release_class {rc}")

    # This session's items must be present and terminal.
    for iid in sorted(THIS_SESSION_ITEMS):
        item = next((i for i in items if (i or {}).get("id") == iid), None)
        if item is None:
            r.fail(f"{iid}: missing from ledger")
            continue
        r.require((item or {}).get("status") in TERMINAL_STATUS,
                  f"{iid}: terminal status ({item.get('status')})",
                  f"{iid}: not terminal — {item.get('status')}")

    # No control may claim external assessment.
    for control in (catalog or {}).get("controls", []) or []:
        cid = (control or {}).get("control_id", "?")
        if (control or {}).get("status") == "externally_assessed":
            r.fail(f"{cid}: externally_assessed is never allowed from within the repo")
    r.ok("no control claims externally_assessed")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
