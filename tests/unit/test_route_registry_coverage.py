"""Route policy registry coverage (PR 2b) — default-deny at CI.

Enumerates every mounted route (via the same app-import + APIRoute descent used by
tests/unit/test_route_conflicts.py) and asserts:
  1. every route classifies in config/route_registry.yaml — an unclassified prefix
     fails here (the default-deny ratchet: a new route prefix must be classified);
  2. every `/kyber` route is kyber_operator_required + audit_required + high risk;
  3. every sensitive route is audit_required;
  4. every public path (feature-gate allowlist) that is mounted classifies as public,
     and no route is both public and Kyber-operator-required;
  5. an unknown prefix classifies to None (the ratchet actually denies);
  6. (schema v3) every declared Kyber capability resolves to a real entry in
     ALL_CAPABILITY_IDS, an unknown declared capability raises at load, and an
     UNdeclared Kyber route still falls back to operator-required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from fastapi.routing import APIRoute  # noqa: E402


def _iter_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


def _routes():
    import main
    seen = {}
    for route in _iter_api_routes(main.app):
        seen[route.path] = route
    return sorted(seen)


def test_every_mounted_route_is_classified():
    from services.security.route_registry import classify
    unclassified = [p for p in _routes() if classify(p) is None]
    assert not unclassified, (
        "Unclassified route prefixes (add them to config/route_registry.yaml "
        f"known_prefixes — default-deny): {sorted({__import__('services.security.route_registry', fromlist=['prefix_of']).prefix_of(p) for p in unclassified})}"
    )


def test_runtime_inventory_uses_route_templates_and_has_no_unknowns():
    import main
    from services.security.route_registry import validate_mounted_routes

    inventory = validate_mounted_routes(main.app.routes)
    assert inventory
    assert all(item["policy"] is not None for item in inventory)
    assert all("literal-tenant" not in item["route_template"] for item in inventory)


def test_kyber_routes_require_operator_and_audit():
    from services.security.route_registry import classify
    offenders = []
    for path in _routes():
        if "/kyber" in path:
            pol = classify(path)
            if pol is None or not (pol.kyber_operator_required and pol.audit_required and pol.risk_class == "high"):
                offenders.append(path)
    assert not offenders, f"/kyber routes must be operator-required + audited + high risk: {offenders}"


def test_sensitive_routes_are_audited():
    from services.security.route_registry import classify
    offenders = [p for p in _routes() if (c := classify(p)) and c.sensitive and not c.audit_required]
    assert not offenders, f"sensitive routes must be audit_required: {offenders}"


def test_public_paths_classify_public_and_not_kyber():
    from services.security.route_registry import classify, is_public_path
    mounted = set(_routes())
    for path in mounted:
        pol = classify(path)
        if pol is None:
            continue
        if is_public_path(path):
            assert pol.public is True, f"{path} is a public path but not classified public"
            assert pol.kyber_operator_required is False, f"{path} cannot be both public and Kyber-operator"


def test_unknown_prefix_denies():
    from services.security.route_registry import classify
    assert classify("/v1/totally-new-surface/thing") is None
    assert classify("/v1/kyber/anything") is not None  # kyber prefix is known


# ── schema v3: declared Kyber capabilities ───────────────────────────────────


def test_declared_capabilities_resolve_to_real_capability_ids():
    """Every kyber_routes declaration names a capability that actually exists."""
    from services.kyber.access.capabilities import ALL_CAPABILITY_IDS
    from services.security.route_registry import _declarations

    declarations = _declarations()
    assert declarations, "kyber_routes block is empty — no route is capability-classified"
    unknown = [d.route_id if hasattr(d, "route_id") else d.template
               for d in declarations if d.capability not in ALL_CAPABILITY_IDS]
    assert not unknown, f"declared capabilities missing from ALL_CAPABILITY_IDS: {unknown}"


def test_declared_disclosure_and_action_class_are_in_range():
    from services.kyber.access.capabilities import MAX_ACTION_CLASS
    from services.kyber.access.disclosure import DisclosureLevel
    from services.security.route_registry import _declarations

    for decl in _declarations():
        assert 0 <= decl.action_class <= MAX_ACTION_CLASS, decl.template
        if decl.disclosure is not None:
            DisclosureLevel.parse(decl.disclosure)  # raises if unparseable


def test_unknown_declared_capability_raises_at_load(tmp_path, monkeypatch):
    """A typo in a declaration is a startup failure, not a silently open route."""
    import pytest
    import yaml

    from services.security import route_registry as rr

    catalog = dict(rr._catalog())
    catalog["kyber_routes"] = [{
        "route": "GET /v1/kyber/typo",
        "capability": "kyber.tenant.mirror.raed",  # deliberate typo
        "disclosure": "D3",
        "action_class": 0,
    }]
    bad = tmp_path / "route_registry.yaml"
    bad.write_text(yaml.safe_dump(catalog), encoding="utf-8")

    rr._catalog.cache_clear()
    rr._declarations.cache_clear()
    rr._declaration_index.cache_clear()
    monkeypatch.setattr(rr, "_find_catalog", lambda: bad)
    try:
        with pytest.raises(RuntimeError) as exc:
            rr._declarations()
        assert "ROUTE_REGISTRY_UNKNOWN_CAPABILITY" in str(exc.value)
    finally:
        monkeypatch.undo()
        rr._catalog.cache_clear()
        rr._declarations.cache_clear()
        rr._declaration_index.cache_clear()


def test_declared_kyber_route_carries_its_capability():
    from services.security.route_registry import classify

    policy = classify("/v1/kyber/tenants/{tenant_id}/operational-envelope", "GET")

    assert policy is not None
    assert policy.required_capability == "kyber.tenant.mirror.read"
    assert policy.minimum_disclosure == "D3"
    assert policy.action_class == 0
    assert policy.kyber_operator_required is True


def test_undeclared_kyber_route_falls_back_to_operator_required():
    """No declaration must never mean no gate."""
    from services.security.route_registry import classify

    policy = classify("/v1/kyber/a-surface-nobody-declared", "GET")

    assert policy is not None
    assert policy.kyber_operator_required is True
    assert policy.audit_required is True
    assert policy.risk_class == "high"
    assert policy.required_capability is None
    assert policy.minimum_disclosure is None
    assert policy.action_class == 0


def test_non_kyber_route_is_unchanged_by_schema_v3():
    """v2 behaviour is preserved exactly for every non-Kyber route."""
    from services.security.route_registry import classify

    policy = classify("/v1/profile/{entity_id}", "GET")

    assert policy is not None
    assert policy.required_capability is None
    assert policy.minimum_disclosure is None
    assert policy.action_class == 0
    assert policy.kyber_operator_required is False


def test_classify_keeps_the_single_argument_signature():
    """158 existing call sites pass only a path — that must keep working."""
    from services.security.route_registry import classify

    assert classify("/v1/kyber/jobs/timeline") is not None
    assert classify("/v1/kyber/jobs/timeline").kyber_operator_required is True


def test_declared_routes_are_still_operator_required_and_audited():
    """A declaration adds authority requirements; it never relaxes the gate."""
    from services.security.route_registry import _declarations, classify

    for decl in _declarations():
        policy = classify(decl.template, None if decl.method == "*" else decl.method)
        assert policy is not None, decl.template
        assert policy.kyber_operator_required is True, decl.template
        assert policy.audit_required is True, decl.template
        assert policy.risk_class == "high", decl.template
        assert policy.required_capability == decl.capability, decl.template


def test_referral_link_routes_are_tenant_scoped_sensitive_and_audited():
    from services.security.route_registry import classify

    policy = classify("/v1/referral-links/{verified_referral_link_id}/revoke")

    assert policy is not None
    assert policy.requires_auth is True
    assert policy.tenant_scoped is True
    assert policy.sensitive is True
    assert policy.audit_required is True
    assert policy.risk_class == "medium"
