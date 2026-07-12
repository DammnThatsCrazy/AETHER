#!/usr/bin/env python3
"""Validate the route policy registry config schema.

This session ships the registry SEED (config/route_registry.yaml). This gate
validates its schema + coherence: default-deny declared, every entry has the
required policy fields, and public routes are explicitly classified. Full
mounted-route coverage is a follow-up (ledger FT-2-ROUTE-REGISTRY).

Usage: python scripts/release/check_route_registry.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

REQUIRED_FIELDS = [
    "route_id", "method", "path", "domain", "action", "resource_type",
    "public", "requires_auth", "allowed_principal_types",
    "allowed_credential_classes", "tenant_scoped", "kyber_operator_required",
    "sensitive", "audit_required", "required_capabilities", "risk_class",
]


def check() -> int:
    r = Reporter("ROUTE REGISTRY — config/route_registry.yaml schema")

    try:
        data = load_yaml("config/route_registry.yaml")
    except FileNotFoundError:
        r.fail("config/route_registry.yaml not found")
        return r.finish()

    r.require((data or {}).get("default_decision") == "deny",
              "default_decision is deny",
              f"default_decision must be 'deny', got {(data or {}).get('default_decision')!r}")

    routes = (data or {}).get("routes", [])
    r.require(isinstance(routes, list) and bool(routes),
              "routes list present", "routes list missing or empty")

    seen_ids: set[str] = set()
    for idx, route in enumerate(routes or []):
        rid = (route or {}).get("route_id", f"#{idx}")
        missing = [f for f in REQUIRED_FIELDS if f not in (route or {})]
        r.require(not missing, f"{rid}: all policy fields present",
                  f"{rid}: missing fields {missing}")

        if rid in seen_ids:
            r.fail(f"{rid}: duplicate route_id")
        seen_ids.add(rid)

        # A sensitive route must require an audit decision.
        if (route or {}).get("sensitive") and not (route or {}).get("audit_required"):
            r.fail(f"{rid}: sensitive route must set audit_required")
        # Kyber routes must require the operator capability.
        if (route or {}).get("kyber_operator_required"):
            caps = (route or {}).get("required_capabilities", []) or []
            if "kyber:operator" not in caps:
                r.fail(f"{rid}: kyber route must require kyber:operator capability")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
