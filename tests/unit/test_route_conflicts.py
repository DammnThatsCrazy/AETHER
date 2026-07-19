"""Route-conflict gate: no two endpoint functions may claim the same (path, method).

FastAPI resolves duplicates silently by mount order — the second registration
is shadowed dead code at best and a behavior surprise at worst. The 13
pre-existing conflicts below are frozen: this test fails on any NEW conflict
and also fails when a frozen conflict is fixed (remove it from the allowlist
so the ratchet only tightens).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi.routing import APIRoute  # noqa: E402

# Pre-existing duplicate registrations (first-mounted wins at runtime).
# Do NOT add entries here — fix the duplicate instead. Entries may only be
# REMOVED (when the underlying duplication is resolved).
KNOWN_CONFLICTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("/v1/admin/billing/stripe/webhook", "POST"),
        ("/v1/admin/kyber/model-confidence-drift", "GET"),
        ("/v1/admin/kyber/outcome-capture-health", "GET"),
        ("/v1/admin/kyber/playbook-performance", "GET"),
        ("/v1/admin/kyber/tenant-value-health", "GET"),
        ("/v1/admin/kyber/vertical-solution-signals", "GET"),
        ("/v1/attribution/models", "GET"),
        ("/v1/notifications/alerts", "GET"),
        ("/v1/notifications/alerts", "POST"),
        ("/v1/notifications/webhooks", "GET"),
        ("/v1/notifications/webhooks", "POST"),
        ("/v1/notifications/webhooks/{webhook_id}", "DELETE"),
    }
)


def iter_api_routes(app):
    """Flatten APIRoutes, including those inside lazy _IncludedRouter wrappers."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


def _current_conflicts() -> dict[tuple[str, str], list[str]]:
    import main

    seen: dict[tuple[str, str], list] = defaultdict(list)
    for route in iter_api_routes(main.app):
        for method in route.methods or []:
            seen[(route.path, method)].append(route.endpoint)
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
