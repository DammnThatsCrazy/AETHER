"""Route policy registry (PR 2; schema v3 adds declared Kyber capabilities).

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

Schema v3 layers an OPTIONAL per-route declaration (``kyber_routes``) over that
prefix derivation. A declaration names the Kyber capability the route requires,
the disclosure ceiling it may reveal and the action class it performs, so the
middleware authorization boundary can enforce capability-level authority without
editing every handler. Declarations only ADD authority requirements: an
undeclared Kyber route keeps today's operator-required behaviour, never open
access, and a non-Kyber route is unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

import yaml

#: Highest legal declared action class (mirrors capabilities.MAX_ACTION_CLASS;
#: duplicated as a literal only for the error message when the Kyber package
#: cannot be imported at all).
_MAX_DECLARED_ACTION_CLASS = 5


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
    # ── schema v3: declared Kyber authority (None/0 when undeclared) ─────────
    #: Capability id from services.kyber.access.capabilities.ALL_CAPABILITY_IDS.
    required_capability: Optional[str] = None
    #: Disclosure ceiling token (``D0``..``D5``) this route may reveal.
    minimum_disclosure: Optional[str] = None
    #: Action class this route performs (0 = read).
    action_class: int = 0


@dataclass(frozen=True)
class RouteDeclaration:
    """One ``kyber_routes`` entry, normalised and validated at load time."""

    method: str  # upper-case verb, or "*" for any method
    template: str  # FastAPI path template, e.g. /v1/kyber/tenants/{tenant_id}
    capability: str
    disclosure: Optional[str]
    action_class: int
    #: True when the declared capability names one tenant and therefore needs an
    #: active, purpose-bound tenant access scope.
    tenant_scoped: bool


def _template_regex(template: str) -> re.Pattern[str]:
    """Compile a FastAPI path template into a concrete-path matcher.

    ``{param}`` matches exactly one path segment, so a declaration can be
    matched against a real request path as well as against the template itself.
    """
    parts: list[str] = []
    for chunk in re.split(r"(\{[^{}]+\})", template):
        if chunk.startswith("{") and chunk.endswith("}"):
            parts.append(r"[^/]+")
        else:
            parts.append(re.escape(chunk))
    return re.compile("^" + "".join(parts) + "$")


def _known_capability_ids() -> tuple[frozenset[str], dict[str, bool]]:
    """Capability vocabulary + tenant-scoping flags, or raise if unavailable.

    Imported lazily: the registry is loaded by release scripts and by the app,
    and only the presence of declarations makes the Kyber package a hard
    dependency. A declaration that cannot be validated is a startup failure —
    never a silently unenforced route.
    """
    from services.kyber.access.capabilities import ALL_CAPABILITY_IDS, CAPABILITIES

    return ALL_CAPABILITY_IDS, {cid: c.tenant_scoped for cid, c in CAPABILITIES.items()}


@lru_cache(maxsize=1)
def _declarations() -> tuple[RouteDeclaration, ...]:
    """Load, validate and normalise the catalog's ``kyber_routes`` block.

    Raises :class:`RuntimeError` when a declaration names an unknown capability,
    an unparseable disclosure token, an out-of-range action class or a duplicate
    ``route`` key. A typo must break startup rather than leave a Kyber route
    enforced only by the coarse operator gate.
    """
    raw = _catalog().get("kyber_routes") or []
    if not raw:
        return ()

    try:
        known, tenant_scoped_by_id = _known_capability_ids()
    except Exception as exc:  # pragma: no cover - broken/absent Kyber package
        raise RuntimeError(
            "ROUTE_REGISTRY_CAPABILITY_VOCABULARY_UNAVAILABLE: config/route_registry.yaml "
            f"declares kyber_routes but the capability vocabulary could not be loaded ({exc})"
        ) from exc

    from services.kyber.access.disclosure import DisclosureLevel

    seen: set[str] = set()
    out: list[RouteDeclaration] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RuntimeError(f"ROUTE_REGISTRY_INVALID_DECLARATION: {entry!r} is not a mapping")
        route = str(entry.get("route", "")).strip()
        if not route:
            raise RuntimeError("ROUTE_REGISTRY_INVALID_DECLARATION: missing 'route'")
        if route in seen:
            raise RuntimeError(f"ROUTE_REGISTRY_DUPLICATE_ROUTE: {route!r} declared twice")
        seen.add(route)

        method, _, template = route.partition(" ")
        if not template:
            method, template = "*", method
        method = method.strip().upper()
        template = template.strip()
        if not template.startswith("/"):
            raise RuntimeError(
                f"ROUTE_REGISTRY_INVALID_DECLARATION: {route!r} path must start with '/'"
            )

        capability = str(entry.get("capability", "")).strip()
        if capability not in known:
            raise RuntimeError(
                f"ROUTE_REGISTRY_UNKNOWN_CAPABILITY: {capability!r} declared for {route!r} "
                "is not in services.kyber.access.capabilities.ALL_CAPABILITY_IDS"
            )

        disclosure_raw = entry.get("disclosure")
        disclosure: Optional[str] = None
        if disclosure_raw is not None:
            try:
                disclosure = DisclosureLevel.parse(disclosure_raw).name_token
            except ValueError as exc:
                raise RuntimeError(
                    f"ROUTE_REGISTRY_INVALID_DISCLOSURE: {disclosure_raw!r} for {route!r}"
                ) from exc

        action_class = int(entry.get("action_class", 0) or 0)
        if not 0 <= action_class <= _MAX_DECLARED_ACTION_CLASS:
            raise RuntimeError(
                f"ROUTE_REGISTRY_INVALID_ACTION_CLASS: {action_class} for {route!r} "
                f"(must be 0..{_MAX_DECLARED_ACTION_CLASS})"
            )

        out.append(RouteDeclaration(
            method=method,
            template=template,
            capability=capability,
            disclosure=disclosure,
            action_class=action_class,
            tenant_scoped=bool(tenant_scoped_by_id.get(capability, False)),
        ))
    return tuple(out)


@lru_cache(maxsize=1)
def _declaration_index() -> tuple[dict[tuple[str, str], RouteDeclaration],
                                  tuple[tuple[re.Pattern[str], RouteDeclaration], ...]]:
    """(exact ``(method, template)`` lookup, ordered regex fallbacks)."""
    exact: dict[tuple[str, str], RouteDeclaration] = {}
    patterned: list[tuple[re.Pattern[str], RouteDeclaration]] = []
    for decl in _declarations():
        exact[(decl.method, decl.template)] = decl
        if "{" in decl.template:
            patterned.append((_template_regex(decl.template), decl))
    return exact, tuple(patterned)


def match_declaration(path: str, method: Optional[str] = None) -> Optional[RouteDeclaration]:
    """The declaration governing ``path`` (a template or a concrete path).

    Exact template matches win; a concrete request path falls back to the
    compiled ``{param}`` matchers. A declaration with an explicit method is
    preferred over a ``*`` wildcard for the same template.
    """
    exact, patterned = _declaration_index()
    verb = (method or "*").upper()
    for candidate in (verb, "*"):
        decl = exact.get((candidate, path))
        if decl is not None:
            return decl
    if "{" in path:
        # A template that is not declared verbatim never matches by regex: the
        # `{param}` placeholders are literal text, not a concrete value.
        return None
    for pattern, decl in patterned:
        if decl.method in (verb, "*") and pattern.match(path):
            return decl
    return None


def declaration_path_params(template: str, path: str) -> dict[str, str]:
    """Bind a declared template's ``{param}`` names to a concrete path's segments.

    Returns an empty mapping when the shapes do not line up. The authorization
    boundary uses this to learn which tenant a declared route targets without
    waiting for Starlette to populate ``request.path_params``.
    """
    t_segments = [s for s in template.strip("/").split("/") if s]
    p_segments = [s for s in path.strip("/").split("/") if s]
    if len(t_segments) != len(p_segments):
        return {}
    params: dict[str, str] = {}
    for t_seg, p_seg in zip(t_segments, p_segments):
        if t_seg.startswith("{") and t_seg.endswith("}"):
            params[t_seg[1:-1]] = p_seg
        elif t_seg != p_seg:
            return {}
    return params


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
        for method in methods:
            inventory.append({
                "method": method,
                "route_template": path,
                "route_name": getattr(route, "name", ""),
                "policy": classify(path, method),
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


@lru_cache(maxsize=4)
def founding_excluded_domains(active_profile: str) -> frozenset[str]:
    """Excluded route domains for the founding-tenant release surface.

    ``config/founding_tenant_release.yaml`` narrows the release surface by
    domain. The manifest is loaded lazily on first use and ONLY applies when
    the active deployment profile matches the profile the manifest declares —
    every other profile resolves to an empty frozenset (no startup cost, and
    the cached lookup is free per request).
    """
    try:
        here = Path(__file__).resolve()
        manifest_path = None
        for parent in here.parents:
            candidate = parent / "config" / "founding_tenant_release.yaml"
            if candidate.exists():
                manifest_path = candidate
                break
        if manifest_path is None:
            return frozenset()
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}
        if str(manifest.get("profile", "")) != active_profile:
            return frozenset()
        surface = manifest.get("release_surface") or {}
        return frozenset(str(d) for d in (surface.get("excluded_domains") or []))
    except Exception:  # pragma: no cover - malformed manifest: registry stays authoritative
        return frozenset()


def founding_domain_excluded(domain: str, active_profile: str) -> bool:
    """True when the founding-tenant manifest excludes ``domain``.

    Plural route domains (``stablecoins``) match their singular manifest entry
    (``stablecoin``); nothing matches when the founding profile is not active.
    """
    excluded = founding_excluded_domains(active_profile)
    if not excluded:
        return False
    return domain in excluded or (domain.endswith("s") and domain[:-1] in excluded)


def classify(path: str, method: Optional[str] = None) -> Optional[RoutePolicy]:
    """Return the RoutePolicy for a path, or None if its prefix is unclassified.

    ``method`` is optional so every existing single-argument caller keeps
    working. It only selects between per-method ``kyber_routes`` declarations;
    the prefix-derived fields are identical with or without it, and a route with
    no declaration classifies exactly as it did under schema v2 (the three v3
    fields defaulting to ``None``/``0``).
    """
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

    # A declaration only ADDS authority requirements on top of the derived
    # policy. An undeclared Kyber route therefore keeps the operator-required
    # fallback rather than becoming reachable.
    decl = match_declaration(path, method) if is_kyber else None

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
        required_capability=decl.capability if decl else None,
        minimum_disclosure=decl.disclosure if decl else None,
        action_class=decl.action_class if decl else 0,
    )
