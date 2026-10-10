"""Route-conflict gate: no two endpoint functions may claim the same method and URL.

FastAPI resolves duplicates silently by mount order: the later registration is
shadowed dead code at best and a behavior surprise at worst. Two paths that
differ only in a parameter name (``/profile/{user_id}/pnl`` and
``/profile/{entity_id}/pnl``) match the same URLs, so they are compared with
parameter names erased, and a router included with a prefix is compared by its
full path.

Every conflict this gate once froze has been resolved by choosing one handler and
deleting the other, so the allowlist is gone and any duplicate fails the PR that
adds it.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services" / "api"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from fastapi.routing import APIRoute  # noqa: E402


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


def test_no_two_handlers_claim_the_same_method_and_path():
    conflicts = _current_conflicts()
    assert not conflicts, (
        "duplicate route registrations (the later mount is silently shadowed); "
        f"keep one handler and delete the other:\n{conflicts}"
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


# The handler that owns each URL that used to have a second, shadowed handler.
RESOLVED_OWNERS = {
    ("/v1/admin/billing/stripe/webhook", "POST"): "governance.admin.webhook_routes",
    ("/v1/attribution/models", "GET"): "value.attribution.routes",
    ("/v1/profile/{}/economic", "GET"): "identity.profile.routes",
    ("/v1/profile/{}/economic/web2", "GET"): "identity.profile.routes",
    ("/v1/profile/{}/economic/web3", "GET"): "identity.profile.routes",
    ("/v1/profile/{}/economic/warnings", "GET"): "identity.profile.routes",
    ("/v1/profile/{}/economic/agentic", "GET"): "value.economic.routes",
    ("/v1/profile/{}/economic/campaigns", "GET"): "value.economic.routes",
    ("/v1/profile/{}/pnl", "GET"): "value.pnl.routes",
    ("/v1/profile/{}/social-intelligence", "GET"): "identity.profile.routes",
    # The five /v1/admin/kyber/* copies deleted from services/api/intelligence/intelligence/routes.py.
    ("/v1/admin/kyber/tenant-value-health", "GET"): "governance.admin.routes",
    ("/v1/admin/kyber/outcome-capture-health", "GET"): "governance.admin.routes",
    ("/v1/admin/kyber/playbook-performance", "GET"): "governance.admin.routes",
    ("/v1/admin/kyber/model-confidence-drift", "GET"): "governance.admin.routes",
    ("/v1/admin/kyber/vertical-solution-signals", "GET"): "governance.admin.routes",
}


def test_each_formerly_duplicated_url_is_served_by_its_chosen_owner():
    import main

    owners: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path, route in iter_api_routes(main.app):
        for method in route.methods or []:
            owners[(normalize(path), method)].add(route.endpoint.__module__)
    wrong = {key: owners.get(key) for key, owner in RESOLVED_OWNERS.items() if owners.get(key) != {owner}}
    assert not wrong, f"these URLs are not served by the handler chosen for them: {wrong}"
