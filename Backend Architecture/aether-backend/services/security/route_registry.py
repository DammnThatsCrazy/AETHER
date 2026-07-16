"""Route policy registry (PR 2).

Derives a :class:`RoutePolicy` for any mounted route from the catalog at
``config/route_registry.yaml``. Authorization becomes a protocol: a route's
classification (public/authed, tenant-scoped, Kyber-operator-required, sensitive,
audit-required, risk) is computed here rather than being implicit in scattered
handler logic.

`classify(path)` returns ``None`` when the route's 2-segment prefix is not in the
catalog's ``known_prefixes`` — the default-deny signal that
``tests/unit/test_route_registry_coverage.py`` turns into a CI failure. The
runtime authorization boundary consumes the same classification and denies
unknown routes in enforced environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import yaml


def _find_catalog() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "route_registry.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/route_registry.yaml not found")


@lru_cache(maxsize=1)
def _catalog() -> dict:
    with _find_catalog().open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass(frozen=True)
class RoutePolicy:
    route_id: str
    path: str
    domain: str
    public: bool
    requires_auth: bool
    tenant_scoped: bool
    kyber_operator_required: bool
    sensitive: bool
    audit_required: bool
    risk_class: str  # low | medium | high


def mounted_route_inventory(routes: Iterable[object]) -> list[dict]:
    """Return the canonical policy inventory for mounted FastAPI routes.

    Route templates (``/v1/profile/{entity_id}``), rather than request paths,
    are recorded so attacker-controlled identifiers never affect policy lookup.
    """
    from fastapi.routing import APIRoute

    inventory: list[dict] = []
    for route in routes:
        if not isinstance(route, APIRoute):
            original = getattr(route, "original_router", None)
            if original is not None:
                inventory.extend(mounted_route_inventory(original.routes))
            continue
        path = getattr(route, "path", None)
        methods = sorted(getattr(route, "methods", set()) or set())
        if not path or not methods:
            continue
        policy = classify(path)
        for method in methods:
            inventory.append({
                "method": method,
                "route_template": path,
                "route_name": getattr(route, "name", ""),
                "policy": policy,
            })
    return inventory


def validate_mounted_routes(routes: Iterable[object]) -> list[dict]:
    """Fail startup if a mounted application route has no canonical policy."""
    inventory = mounted_route_inventory(routes)
    missing = sorted(
        f"{item['method']} {item['route_template']}"
        for item in inventory if item["policy"] is None
    )
    if missing:
        raise RuntimeError("ROUTE_POLICY_UNCLASSIFIED: " + ", ".join(missing))
    return inventory


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def prefix_of(path: str) -> str:
    """The 2-segment classification prefix for a path."""
    seg = _segments(path)
    if not seg:
        return "/"
    if len(seg) >= 2:
        return "/" + "/".join(seg[:2])
    return "/" + seg[0]


def is_public_path(path: str) -> bool:
    """Public path per the canonical feature-gate allowlist."""
    try:
        from shared.rate_limit.feature_gate import PUBLIC_PATHS, PUBLIC_PATH_PREFIXES
    except Exception:  # pragma: no cover - feature_gate always importable in app
        return False
    if path in (set(PUBLIC_PATHS) | {"/v1/metrics"}):
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def classify(path: str) -> Optional[RoutePolicy]:
    """Return the RoutePolicy for a path, or None if its prefix is unclassified."""
    cat = _catalog()
    known = set(cat.get("known_prefixes", []) or [])
    prefix = prefix_of(path)
    if prefix not in known:
        return None

    seg = _segments(path)
    domain = seg[1] if len(seg) >= 2 else (seg[0] if seg else "root")
    is_kyber = "/kyber" in path or "kyber" in seg
    sensitive = bool(
        is_kyber
        or "admin" in seg
        or domain in set(cat.get("sensitive_domains", []) or [])
    )
    infra = domain in set(cat.get("infra_domains", []) or [])
    public = is_public_path(path)

    if is_kyber or domain in set(cat.get("high_risk_domains", []) or []):
        risk = "high"
    elif sensitive:
        risk = "medium"
    else:
        risk = "low"

    return RoutePolicy(
        route_id=prefix,
        path=path,
        domain=domain,
        public=public,
        requires_auth=not public,
        tenant_scoped=not infra and not public,
        kyber_operator_required=is_kyber,
        sensitive=sensitive,
        audit_required=sensitive,
        risk_class=risk,
    )
