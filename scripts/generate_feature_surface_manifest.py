#!/usr/bin/env python3
"""Generate and validate the Kyber feature-surface manifest.

The manifest maps every tenant-visible Aether surface to its Kyber Tenant Mirror
counterpart. It is **derived from the Aether router**, not hand-written, because
a hand-written coverage list rots the moment someone adds a route — and a
coverage gate that silently stops covering things is worse than no gate.

``--check`` is the CI mode. It fails when:

1. a route exists in ``frontend/aether/src/app/router.tsx`` with no manifest
   entry — a new tenant surface must be classified, one way or the other;
2. a manifest entry names a route that no longer exists — stale coverage;
3. an entry is ``tenant_parity_required`` with no ``kyber_mirror_route``;
4. an entry is exempt from parity with no ``parity_exception_reason``. Opting a
   surface out is allowed; opting out silently is not.

What the flag means: ``tenant_parity_required`` says the mirror must return
byte-identical ``tenantVisible`` data for the same tenant, query and contract
version. If Kyber recomputes a number differently, an operator investigating a
tenant is debugging a different system than the tenant is running, which defeats
the point of having a mirror at all.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
AETHER_ROUTER = ROOT / "frontend" / "aether" / "src" / "app" / "router.tsx"
MANIFEST = ROOT / "packages" / "shared" / "contracts" / "kyber-feature-surface-manifest.json"

_ROUTE_RE = re.compile(r'<Route\s+path="([^"]+)"')

#: Surfaces with no operator mirror, and the reason. Every entry is a deliberate
#: decision that a Kyber operator has nothing to gain from seeing the tenant's
#: exact view — pre-auth pages, the tenant's own account/settings shell, or a
#: surface whose operator equivalent lives elsewhere in Kyber.
NON_SURFACE: dict[str, str] = {
    "/callback": "pre-authentication OIDC landing",
    "/login": "pre-authentication",
    "/signup": "pre-authentication tenant creation",
    "/legal/data-retention": "static legal copy, no tenant data",
    "/": "redirect only",
    "/onboarding": "tenant self-setup wizard; no operator equivalent",
    "/activation": "tenant self-serve activation wizard; no operator mirror (same class as /onboarding)",
    "/activate": "tenant self-serve guided activation wizard (WS-3 intent-driven goals-to-plan); same class as /activation and /onboarding",
    "/me": "the caller's own account; an operator's own account is /v1/kyber/me",
    "/settings": "tenant self-configuration; operators must not mutate it from a mirror",
    "/settings/notifications": "tenant self-configuration",
    "/settings/data-exchange": "tenant self-configuration (Settings → Data Exchange)",
    "/settings/integrations": (
        "tenant self-configuration of external integrations (Settings → "
        "Integrations); operator connection ops live in their own provider-connection plane"
    ),
    "/settings/integrations/connectors": (
        "tenant self-configuration (connector browser under Settings → Integrations); "
        "same class as /settings/integrations"
    ),
    "/settings/notification-preferences": (
        "tenant self-configuration (notification quiet-hours / timezone / severity)"
    ),
    "/settings/sdk-fleet": (
        "tenant's own SDK fleet (installed packages / versions / activity); "
        "operator equivalent is per-tenant SDK telemetry, not a tenant mirror"
    ),
    "/settings/webhooks": (
        "tenant self-configuration (own outbound delivery endpoints); "
        "operator webhook delivery ops are separately governed"
    ),
    "/notifications": (
        "tenant's own notification inbox is self-scoped attention data not "
        "projected into the tenant graph; operator signals have their own ops "
        "exception queue (services/kyber/ops/exceptions)"
    ),
    "/billing": "tenant billing portal; operator view is /v1/kyber/revops",
    "/usage-plan": "tenant plan self-service; operator view is /v1/kyber/revops",
    "/security": "tenant's own security settings; operator plane is /security/*",
    "/audit-exports": (
        "tenant-initiated export UI; operator exports are capability-gated separately"
    ),
    "/users/:profileId/journey": (
        "profile-scoped journey data is not projected into the tenant graph; "
        "Kyber uses its separately authorized measurement journey operations"
    ),
    "/compare": (
        "comparison definitions and runs are not projected into the tenant graph; "
        "operator comparison parity is not implemented"
    ),
}

MANIFEST_COMMENT = (
    "Canonical map of every tenant-visible Aether surface to its Kyber Tenant "
    "Mirror counterpart. Generated from frontend/aether/src/app/router.tsx by "
    "scripts/generate_feature_surface_manifest.py — edit the generator or the "
    "exception reasons, never the entries by hand. "
    "tenant_parity_required=true means the mirror MUST return byte-identical "
    "tenantVisible data for the same tenant, query and contract version; the "
    "operator is otherwise debugging a different system than the tenant runs. "
    "Only 'tenantVisible' participates in the parity digest; operatorDiagnostics "
    "is additive and never alters a tenant-visible value."
)


def aether_routes() -> list[str]:
    if not AETHER_ROUTER.exists():
        raise SystemExit(f"FAIL — Aether router not found at {AETHER_ROUTER}")
    return [r for r in _ROUTE_RE.findall(AETHER_ROUTER.read_text()) if r != "*"]


def _feature_id(path: str) -> str:
    return path.strip("/").replace("/", "-").replace(":", "") or "root"


def build_entry(path: str) -> dict[str, Any]:
    feature_id = _feature_id(path)
    if path in NON_SURFACE:
        return {
            "feature_id": feature_id,
            "aether_route": path,
            "tenant_parity_required": False,
            "parity_exception_reason": NON_SURFACE[path],
            "kyber_mirror_route": None,
            "minimum_disclosure": "D0",
        }
    return {
        "feature_id": feature_id,
        "aether_route": path,
        "tenant_parity_required": True,
        "parity_exception_reason": None,
        "kyber_mirror_route": f"/tenants/:tenantId/mirror/{path.strip('/') or 'overview'}",
        "minimum_disclosure": "D3",
        "backend_capability": "kyber.tenant.mirror.read",
        "operator_augmentations": [
            "quality", "lineage", "policy", "health", "recomputeOptions",
        ],
    }


def build_manifest() -> dict[str, Any]:
    return {
        "_comment": MANIFEST_COMMENT,
        "schemaVersion": "1.0.0",
        "surfaces": [build_entry(p) for p in aether_routes()],
    }


def check() -> int:
    if not MANIFEST.exists():
        print(f"FAIL — manifest missing: {MANIFEST.relative_to(ROOT)}")
        print("  fix: python scripts/generate_feature_surface_manifest.py --write")
        return 1

    manifest = json.loads(MANIFEST.read_text())
    surfaces = manifest.get("surfaces", [])
    by_route = {s.get("aether_route"): s for s in surfaces}
    routes = set(aether_routes())
    failures: list[str] = []

    for route in sorted(routes - set(by_route)):
        failures.append(
            f"Aether route {route!r} has no manifest entry — classify it as "
            f"parity-required or add a parity_exception_reason"
        )
    for route in sorted(set(by_route) - routes):
        failures.append(
            f"manifest entry {route!r} names a route that no longer exists — "
            f"stale coverage, remove it"
        )
    for surface in surfaces:
        route = surface.get("aether_route")
        if surface.get("tenant_parity_required"):
            if not surface.get("kyber_mirror_route"):
                failures.append(f"{route}: parity required but no kyber_mirror_route")
            if not surface.get("backend_capability"):
                failures.append(f"{route}: parity required but no backend_capability")
        elif not surface.get("parity_exception_reason"):
            failures.append(
                f"{route}: exempt from parity with no parity_exception_reason — "
                f"opting a surface out is allowed, doing it silently is not"
            )

    required = sum(1 for s in surfaces if s.get("tenant_parity_required"))
    print("=" * 70)
    print("  Kyber feature-surface manifest")
    print("=" * 70)
    print(f"  Aether routes: {len(routes)}   surfaces: {len(surfaces)}   "
          f"parity-required: {required}   exempt: {len(surfaces) - required}")
    print("-" * 70)
    if failures:
        print(f"  RESULT: FAIL — {len(failures)} problem(s)\n")
        for failure in failures:
            print(f"    ✗ {failure}")
        print("\n  Regenerate with: python scripts/generate_feature_surface_manifest.py --write")
        print("=" * 70)
        return 1
    print("  RESULT: PASS — every Aether surface is classified")
    print("=" * 70)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate the manifest")
    args = parser.parse_args()
    if args.write:
        MANIFEST.write_text(json.dumps(build_manifest(), indent=2) + "\n")
        print(f"wrote {MANIFEST.relative_to(ROOT)}")
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
