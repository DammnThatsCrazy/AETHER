#!/usr/bin/env python3
"""Validate the route policy registry catalog schema.

PR 2 upgraded config/route_registry.yaml from the PR 0 seed (a `routes:` list) to
the v2 rule-derived catalog: `default_decision: deny`, `known_prefixes`, and the
`sensitive_domains` / `high_risk_domains` / `infra_domains` sets consumed by
services/security/route_registry.py::classify. Schema v3 adds the optional
`kyber_routes` block declaring each Kyber route's capability, disclosure ceiling
and action class. This gate validates that shape and coherence. Full
mounted-route COVERAGE (default-deny at CI) is enforced by
tests/unit/test_route_registry_coverage.py.

Usage: python scripts/release/check_route_registry.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard  # noqa: E402

_DOMAIN_SETS = ["sensitive_domains", "high_risk_domains", "infra_domains"]
_SCHEMA_VERSION = 3
_MAX_ACTION_CLASS = 5


def _backend_on_path() -> str:
    backend = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "Backend Architecture", "aether-backend",
    )
    if backend not in sys.path:
        sys.path.insert(0, backend)
    os.environ.setdefault("AETHER_ENV", "local")
    return backend


def _check_kyber_routes(r: Reporter, data: dict) -> None:
    """Validate the v3 `kyber_routes` declarations against the capability vocabulary."""
    declarations = data.get("kyber_routes")
    if declarations is None:
        r.warn("no kyber_routes declarations present (v3 block is optional)")
        return
    if not isinstance(declarations, list):
        r.fail("kyber_routes must be a list")
        return

    routes = [str((d or {}).get("route", "")) for d in declarations]
    dupes = sorted({route for route in routes if routes.count(route) > 1})
    r.require(not dupes, f"kyber_routes has no duplicate routes ({len(routes)} declared)",
              f"duplicate kyber_routes entries: {dupes}")

    _backend_on_path()
    try:
        from services.kyber.access.capabilities import ALL_CAPABILITY_IDS  # type: ignore
        from services.kyber.access.disclosure import DisclosureLevel  # type: ignore
    except Exception as exc:  # pragma: no cover - broken/absent Kyber package
        r.fail(f"kyber capability vocabulary could not be imported ({type(exc).__name__}: {exc})")
        return

    unknown: list[str] = []
    bad_disclosure: list[str] = []
    bad_action_class: list[str] = []
    for decl in declarations:
        decl = decl or {}
        route = str(decl.get("route", ""))
        capability = str(decl.get("capability", ""))
        if capability not in ALL_CAPABILITY_IDS:
            unknown.append(f"{route} → {capability!r}")
        disclosure = decl.get("disclosure")
        if disclosure is not None:
            try:
                DisclosureLevel.parse(disclosure)
            except Exception:
                bad_disclosure.append(f"{route} → {disclosure!r}")
        try:
            action_class = int(decl.get("action_class", 0) or 0)
        except (TypeError, ValueError):
            action_class = -1
        if not 0 <= action_class <= _MAX_ACTION_CLASS:
            bad_action_class.append(f"{route} → {decl.get('action_class')!r}")

    r.require(not unknown, "every declared capability is in ALL_CAPABILITY_IDS",
              f"unknown capabilities: {unknown}")
    r.require(not bad_disclosure, "every declared disclosure parses",
              f"unparseable disclosure tokens: {bad_disclosure}")
    r.require(not bad_action_class, f"every declared action_class is 0..{_MAX_ACTION_CLASS}",
              f"out-of-range action classes: {bad_action_class}")


def check() -> int:
    r = Reporter("ROUTE REGISTRY — config/route_registry.yaml (v3 catalog)")

    try:
        data = load_yaml("config/route_registry.yaml")
    except FileNotFoundError:
        r.fail("config/route_registry.yaml not found")
        return r.finish()

    data = data or {}

    r.require(data.get("schema_version") == _SCHEMA_VERSION,
              f"schema_version is {_SCHEMA_VERSION}",
              f"schema_version must be {_SCHEMA_VERSION}, got {data.get('schema_version')!r}")

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

    _check_kyber_routes(r, data)

    # The Python classifier must import and agree with the catalog.
    try:
        _backend_on_path()
        from services.security.route_registry import classify  # type: ignore
        pol = classify("/v1/kyber/tenants/x/operational-envelope")
        r.require(pol is not None and pol.kyber_operator_required and pol.audit_required,
                  "classify() marks /kyber routes operator-required + audited",
                  "classify() did not classify a /kyber route as operator+audit")
        r.require(classify("/v1/totally-unknown-surface/x") is None,
                  "classify() denies an unknown prefix (default-deny)",
                  "classify() must return None for an unknown prefix")
        undeclared = classify("/v1/kyber/not-declared-yet/thing")
        r.require(undeclared is not None
                  and undeclared.kyber_operator_required
                  and undeclared.required_capability is None,
                  "an undeclared /kyber route falls back to operator-required",
                  "an undeclared /kyber route must stay operator-required with no capability")
    except Exception as exc:  # pragma: no cover - import-time env issues
        r.warn(f"classifier import skipped ({type(exc).__name__}: {exc})")

    return r.finish()


if __name__ == "__main__":
    main_guard(check)
