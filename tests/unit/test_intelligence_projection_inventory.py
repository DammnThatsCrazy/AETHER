"""Intelligence Projection inventory-honesty tests (P0.8, group 5).

The tetris gate: the registry is a truthful inventory of existing work, not a
placeholder list. Every in_flight projection's legacyBindings must resolve
against real routes, surfaces and services.

The REAL registry passes ``validate_inventory``, and the same honesty is
re-asserted from FIRST PRINCIPLES (independent scans of route_registry.yaml,
backend route-declaration lines, the surface registry, and the filesystem) so a
lib regression can be caught even if the lib and its tests drift together.
Negative fixtures prove the gate: a fictional route, a nonexistent service glob,
an implemented projection without converged bindings, and a deprecated
projection without a reason all error.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lib.intelligence_projection_validation import (  # noqa: E402
    Violation,
    load_context,
    validate_inventory,
)

_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"
)
_SURFACE_REGISTRY_JSON = (
    REPO_ROOT / "packages" / "shared" / "contracts" / "surface-capability-registry.json"
)
_ROUTE_REGISTRY_YAML = REPO_ROOT / "config" / "route_registry.yaml"
_BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"

# A route only counts as evidence of a mounted router when its /v1/... literal
# sits on a ROUTE-DECLARATION line (APIRouter / include_router / add_api_route /
# @router.* / @app.* / prefix=). A literal in a test assertion, config file or
# docstring is NOT evidence and must not let a fictional binding through.
_DECL_MARKER_RE = re.compile(
    r"APIRouter\(|include_router\(|add_api_route\(|@router\.|@app\.|prefix\s*="
)
_ROUTE_LITERAL_RE = re.compile(
    r"(/v1/[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*)"
)


def _prefix2(route: str) -> str:
    """First two path segments, e.g. ``/v1/foo/bar`` -> ``/v1/foo``."""
    parts = [part for part in route.split("/") if part]
    if len(parts) >= 2:
        return "/" + parts[0] + "/" + parts[1]
    return route


def _route_decl_paths() -> set[str]:
    """Every ``/v1/...`` literal on a route-declaration line in backend source,
    plus every segment prefix of each such literal.

    Re-derived from first principles (not via the lib) so it can catch lib
    drift: the mounted-but-feature-flag-gated routers absent from
    route_registry.yaml (``/v1/risk-overlays``, ``/v1/integrations``,
    ``/v1/provider-connections``, ``/v1/client-sync``, ``/v1/agent``) must
    still resolve through this scan.
    """
    found: set[str] = set()
    for py in sorted(_BACKEND.rglob("*.py")):
        try:
            lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if not _DECL_MARKER_RE.search(line):
                continue
            for match in _ROUTE_LITERAL_RE.finditer(line):
                parts = [part for part in match.group(1).split("/") if part]
                acc = ""
                for part in parts:
                    acc += "/" + part
                    found.add(acc)
    return found


def _route_resolves(route: str, known_prefixes: set[str], decl_paths: set[str]) -> bool:
    """Independent route-resolution acceptance (mirrors the lib's OR rule)."""
    if _prefix2(route) in known_prefixes:
        return True
    return route in decl_paths


def _surface_ids() -> set[str]:
    surface_reg = json.loads(_SURFACE_REGISTRY_JSON.read_text(encoding="utf-8"))
    return {s["surfaceId"] for s in surface_reg["surfaces"]}


def _real_registry() -> dict:
    return json.loads(_REGISTRY_JSON.read_text(encoding="utf-8"))


# --- fixtures ---------------------------------------------------------------


def _mk_reg(entries: list[dict]) -> dict:
    return {
        "schemaVersion": "1.0.0",
        "contractVersion": "1.0.0",
        "projections": entries,
    }


def _entry(
    pid: str,
    state: str = "in_flight",
    routes: list[str] | None = None,
    services: list[str] | None = None,
    migration_mode: str = "adapter",
    deprecated_reason: str | None = None,
) -> dict:
    return {
        "id": pid,
        "implementationState": state,
        "implementationBlueprint": "docs/ACCESS-CONTROL.md",
        "legacyBindings": {
            "routes": routes or [],
            "surfaceIds": [],
            "services": services or [],
            "migrationMode": migration_mode,
        },
        "pendingAuthority": [],
        "pendingReference": [],
        "deprecatedReason": deprecated_reason,
    }


def _messages(violations: list[Violation]) -> list[str]:
    return [v.message for v in violations]


# --- the real registry is a truthful inventory ------------------------------


def test_real_registry_inventory_has_zero_errors() -> None:
    reg = _real_registry()
    violations = validate_inventory(reg, load_context())
    errors = [v for v in violations if v.severity == "error"]
    assert errors == [], [v.message for v in errors]


def test_real_registry_routes_resolve_independently() -> None:
    """Every legacy route resolves against route_registry.yaml OR backend source.

    Written from first principles (independent scans) so a lib regression in
    the route-existence acceptance cannot go undetected.
    """
    reg = _real_registry()
    known_prefixes = set(
        yaml.safe_load(_ROUTE_REGISTRY_YAML.read_text(encoding="utf-8"))["known_prefixes"]
    )
    decl_paths = _route_decl_paths()
    assert decl_paths, "route-declaration scan must not come back empty"

    unresolved: list[tuple[str, str]] = []
    for p in reg["projections"]:
        for route in (p.get("legacyBindings") or {}).get("routes", []):
            if not _route_resolves(route, known_prefixes, decl_paths):
                unresolved.append((p["id"], route))
    assert unresolved == [], f"unresolved legacy routes: {unresolved}"


def test_real_registry_surfaces_resolve_independently() -> None:
    reg = _real_registry()
    registered = _surface_ids()
    # 13 surfaces incl. the 3 UI-less additions (outcome360/economic360/connection360).
    assert len(registered) >= 13
    for surface in ("outcome360", "economic360", "connection360"):
        assert surface in registered

    missing: list[tuple[str, str]] = []
    for p in reg["projections"]:
        for surface in p.get("surfaceIds", []):
            if surface not in registered:
                missing.append((p["id"], f"surfaceIds:{surface}"))
        for surface in (p.get("legacyBindings") or {}).get("surfaceIds", []):
            if surface not in registered:
                missing.append((p["id"], f"legacyBindings.surfaceIds:{surface}"))
    assert missing == [], f"unresolved surfaces: {missing}"


def test_real_registry_services_exist_on_disk() -> None:
    reg = _real_registry()
    missing: list[tuple[str, str]] = []
    for p in reg["projections"]:
        for service in (p.get("legacyBindings") or {}).get("services", []):
            if not (REPO_ROOT / service).exists():
                missing.append((p["id"], service))
    assert missing == [], f"nonexistent service globs: {missing}"


# --- negative fixtures ------------------------------------------------------


def test_fictional_route_reported() -> None:
    reg = _mk_reg([_entry("a", routes=["/v1/definitely-not-a-route"])])
    violations = validate_inventory(reg, load_context())
    assert any(
        v.rule == "inventory"
        and "no known prefix" in v.message
        and "/v1/definitely-not-a-route" in v.message
        for v in violations
    )


def test_nonexistent_service_glob_reported() -> None:
    reg = _mk_reg(
        [
            _entry(
                "a",
                services=["Backend Architecture/aether-backend/services/definitely_not_there"],
            )
        ]
    )
    violations = validate_inventory(reg, load_context())
    assert any(
        v.rule == "inventory"
        and "does not exist on disk" in v.message
        and "definitely_not_there" in v.message
        for v in violations
    )


def test_implemented_requires_converged_migration_mode() -> None:
    reg = _mk_reg([_entry("a", state="implemented", migration_mode="adapter")])
    violations = validate_inventory(reg, load_context())
    assert any(
        v.rule == "inventory"
        and "migrationMode == 'converged'" in v.message
        for v in violations
    )


def test_deprecated_requires_deprecated_reason() -> None:
    reg = _mk_reg([_entry("a", state="deprecated", deprecated_reason=None)])
    violations = validate_inventory(reg, load_context())
    assert any(
        v.rule == "inventory" and "deprecatedReason" in v.message for v in violations
    )
