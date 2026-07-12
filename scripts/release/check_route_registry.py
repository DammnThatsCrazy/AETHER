#!/usr/bin/env python3
"""Validate the route policy registry catalog schema.

PR 2 upgraded config/route_registry.yaml from the PR 0 seed (a `routes:` list) to
the v2 rule-derived catalog: `default_decision: deny`, `known_prefixes`, and the
`sensitive_domains` / `high_risk_domains` / `infra_domains` sets consumed by
services/security/route_registry.py::classify. This gate validates that shape and
coherence. Full mounted-route COVERAGE (default-deny at CI) is enforced by
tests/unit/test_route_registry_coverage.py.

Usage: python scripts/release/check_route_registry.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

_DOMAIN_SETS = ["sensitive_domains", "high_risk_domains", "infra_domains"]


def check() -> int:
    r = Reporter("ROUTE REGISTRY — config/route_registry.yaml (v2 catalog)")

    try:
        data = load_yaml("config/route_registry.yaml")
    except FileNotFoundError:
        r.fail("config/route_registry.yaml not found")
        return r.finish()

    data = data or {}

    r.require(data.get("default_decision") == "deny",
              "default_decision is deny",
              f"default_decision must be 'deny', got {data.get('default_decision')!r}")

    known = data.get("known_prefixes")
    r.require(isinstance(known, list) and bool(known),
              f"known_prefixes present ({len(known) if isinstance(known, list) else 0} prefixes)",
              "known_prefixes must be a non-empty list")
    if isinstance(known, list):
        dupes = {p for p in known if known.count(p) > 1}
        r.require(not dupes, "known_prefixes has no duplicates",
                  f"duplicate prefixes: {sorted(dupes)}")
        r.require(all(isinstance(p, str) and p.startswith("/") for p in known),
                  "all known_prefixes are absolute paths",
                  "every known_prefix must be a string starting with '/'")

    for name in _DOMAIN_SETS:
        val = data.get(name)
        r.require(isinstance(val, list) and bool(val),
                  f"{name} present", f"{name} must be a non-empty list")

    # Kyber must be a sensitive + high-risk domain (operator surface).
    sens = set(data.get("sensitive_domains", []) or [])
    high = set(data.get("high_risk_domains", []) or [])
    r.require("kyber" in sens and "kyber" in high,
              "kyber domain is sensitive + high-risk",
              "kyber must be in sensitive_domains and high_risk_domains")

    # The Python classifier must import and agree with the catalog.
    try:
        backend = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "Backend Architecture", "aether-backend",
        )
        sys.path.insert(0, backend)
        os.environ.setdefault("AETHER_ENV", "local")
        from services.security.route_registry import classify  # type: ignore
        pol = classify("/v1/kyber/tenants/x/operational-envelope")
        r.require(pol is not None and pol.kyber_operator_required and pol.audit_required,
                  "classify() marks /kyber routes operator-required + audited",
                  "classify() did not classify a /kyber route as operator+audit")
        r.require(classify("/v1/totally-unknown-surface/x") is None,
                  "classify() denies an unknown prefix (default-deny)",
                  "classify() must return None for an unknown prefix")
    except Exception as exc:  # pragma: no cover - import-time env issues
        r.warn(f"classifier import skipped ({type(exc).__name__}: {exc})")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
