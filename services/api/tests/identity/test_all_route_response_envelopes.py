"""No route may declare a response model that rejects the envelope it returns.

Routes that build ``APIResponse(...)`` or ``PaginatedResponse(...)`` return the
``{data, status, timestamp, meta}`` envelope. If such a route declares a bare
pydantic model (or a ``list[...]`` of one) as ``response_model``, FastAPI
validates the envelope against it and every request answers 500. Fifteen identity
routes did this until staging rehearsal run 43365158651 surfaced it on
``POST /v1/identity/resolve``.

This walks every ``APIRouter`` defined under ``services/api``, including
feature-gated ones that ``main`` does not mount by default. It lives with the
identity tests, where the defect was found, so the PR-gated
``backend-identity`` suite runs it; ``services/api/tests/unit`` only runs in
the regression-only aggregate suite.
"""

from __future__ import annotations

import importlib
import inspect
import re
import typing
from pathlib import Path

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

API_ROOT = Path(__file__).resolve().parents[2]  # services/api
ENVELOPE_FIELDS = {"data", "status", "timestamp", "meta"}
BUILDS_ENVELOPE = re.compile(r"\b(?:APIResponse|PaginatedResponse)\(")


def _router_modules() -> list[str]:
    modules = []
    for path in sorted(API_ROOT.rglob("*.py")):
        relative = path.relative_to(API_ROOT)
        if relative.parts[0] == "tests" or "APIRouter(" not in path.read_text(errors="ignore"):
            continue
        modules.append(".".join(relative.with_suffix("").parts))
    return modules


def _rejects_envelope(model: object) -> bool:
    """True when FastAPI would refuse an envelope dict for ``model``."""
    origin = typing.get_origin(model)
    if origin in (list, tuple, set, frozenset):
        return True
    if isinstance(model, type) and issubclass(model, BaseModel):
        return not ENVELOPE_FIELDS <= set(model.model_fields)
    return False


def _all_routes() -> list[APIRoute]:
    routers: dict[int, APIRouter] = {}
    for name in _router_modules():
        module = importlib.import_module(name)
        for value in vars(module).values():
            if isinstance(value, APIRouter):
                routers[id(value)] = value
    return [r for router in routers.values() for r in router.routes if isinstance(r, APIRoute)]


def test_router_discovery_covers_the_api():
    routes = _all_routes()
    # Guards against a discovery change silently checking nothing.
    assert len(routes) > 1000
    assert any(r.path == "/v1/identity/resolve" for r in routes)


def test_no_route_declares_a_model_that_rejects_its_envelope():
    mismatches = []
    for route in _all_routes():
        if route.response_model is None or not _rejects_envelope(route.response_model):
            continue
        try:
            source = inspect.getsource(route.endpoint)
        except (OSError, TypeError):
            continue
        if BUILDS_ENVELOPE.search(source):
            where = inspect.getsourcefile(route.endpoint) or "?"
            mismatches.append(
                f"{sorted(route.methods)[0]} {route.path} ({Path(where).relative_to(API_ROOT)}): "
                f"declares {route.response_model!r} but returns the APIResponse envelope"
            )
    assert not mismatches, "\n".join(mismatches)
