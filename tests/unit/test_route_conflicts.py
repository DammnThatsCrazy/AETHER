"""Route-conflict gate: no two endpoint functions may claim the same method and URL.

FastAPI resolves duplicates silently by mount order: the later registration is
shadowed dead code at best and a behavior surprise at worst. Two paths that
differ only in a parameter name (``/profile/{user_id}/pnl`` and
``/profile/{entity_id}/pnl``) match the same URLs, so they are compared with
parameter names erased, and a router included with a prefix is compared by its
full path.

The conflicts below are frozen against the debt-ledger row
``intelligence-duplicate-route-handlers``: this test fails on any NEW conflict and
also fails when a frozen conflict is fixed (remove it from the allowlist so the
ratchet only tightens).
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi.routing import APIRoute  # noqa: E402

LEDGER_ROW = "intelligence-duplicate-route-handlers"

# Duplicate registrations (first-mounted wins at runtime), path parameters written
# as ``{}``. Do NOT add entries here: fix the duplicate instead. Entries may only
# be REMOVED, when the underlying duplication is resolved.
KNOWN_CONFLICTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("/v1/admin/billing/stripe/webhook", "POST"),
        ("/v1/attribution/models", "GET"),
        ("/v1/profile/{}/economic", "GET"),
        ("/v1/profile/{}/economic/agentic", "GET"),
        ("/v1/profile/{}/economic/campaigns", "GET"),
        ("/v1/profile/{}/economic/warnings", "GET"),
        ("/v1/profile/{}/economic/web2", "GET"),
        ("/v1/profile/{}/economic/web3", "GET"),
        ("/v1/profile/{}/pnl", "GET"),
        ("/v1/profile/{}/social-intelligence", "GET"),
        # Resolved since the ratchet was introduced: the 5 /v1/notifications
        # conflicts (the legacy notification router was retired) and the 5
        # /v1/admin/kyber/{tenant-value-health,...} conflicts (the shadowed copies in
        # services/intelligence/routes.py were deleted).
    }
)

_PARAM = re.compile(r"\{[^}]*\}")


def iter_api_routes(app):
    """Yield ``(full_path, APIRoute)`` through lazily included routers and include prefixes."""

    def walk(routes, prefix):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
                continue
            original = getattr(route, "original_router", None)
            if original is not None:
                context = getattr(route, "include_context", None)
                yield from walk(original.routes, prefix + (getattr(context, "prefix", "") or ""))

    yield from walk(app.routes, "")


def normalize(path: str) -> str:
    return _PARAM.sub("{}", path)


def _current_conflicts() -> dict[tuple[str, str], list[str]]:
    import main

    seen: dict[tuple[str, str], list] = defaultdict(list)
    for path, route in iter_api_routes(main.app):
        for method in route.methods or []:
            seen[(normalize(path), method)].append(route.endpoint)
    return {
        key: sorted({f"{fn.__module__}.{fn.__name__}" for fn in fns})
        for key, fns in seen.items()
        if len(set(fns)) > 1
    }


def test_no_new_route_conflicts():
    conflicts = _current_conflicts()
    new = {k: v for k, v in conflicts.items() if k not in KNOWN_CONFLICTS}
    assert not new, (
        "NEW duplicate route registrations detected (the later mount is "
        f"silently shadowed):\n{new}\nDeduplicate the routers instead of "
        "extending KNOWN_CONFLICTS."
    )


def test_conflict_allowlist_is_not_stale():
    conflicts = set(_current_conflicts())
    fixed = KNOWN_CONFLICTS - conflicts
    assert not fixed, (
        f"These allowlisted conflicts no longer exist — remove them from "
        f"KNOWN_CONFLICTS so the ratchet tightens: {sorted(fixed)}"
    )


def test_parameter_names_and_include_prefixes_do_not_hide_a_conflict():
    from fastapi import APIRouter, FastAPI

    def a(): ...
    def b(): ...

    first, second = APIRouter(), APIRouter()
    first.get("/v1/profile/{user_id}/pnl")(a)
    second.get("/pnl")(b)
    app = FastAPI()
    app.include_router(first)
    app.include_router(second, prefix="/v1/profile/{entity_id}")
    paths = {(normalize(path), tuple(sorted(route.methods))) for path, route in iter_api_routes(app)}
    assert paths == {("/v1/profile/{}/pnl", ("GET",))}
    assert len([1 for path, _ in iter_api_routes(app) if normalize(path) == "/v1/profile/{}/pnl"]) == 2


def test_frozen_conflicts_are_recorded_in_the_debt_ledger():
    ledger = yaml.safe_load((ROOT / "config/debt_retirement_ledger.yaml").read_text(encoding="utf-8"))
    ids = {entry["id"] for entry in ledger["entries"]}
    assert not KNOWN_CONFLICTS or LEDGER_ROW in ids, f"ledger row {LEDGER_ROW} must record the frozen conflicts"
