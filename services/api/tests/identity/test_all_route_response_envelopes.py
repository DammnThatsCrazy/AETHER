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
import types
import typing
from pathlib import Path

from fastapi import APIRouter
from fastapi.routing import APIRoute
import pytest
from pydantic import BaseModel

from shared.common.common import APIResponse

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
    if model is typing.Any or model is dict or model is object:
        return False
    if model is type(None):
        return True
    origin = typing.get_origin(model)
    if origin in (list, tuple, set, frozenset):
        return True
    if origin is dict:
        # dict[str, Any] accepts the envelope; dict[str, Model] does not,
        # because "data" and "meta" must then each validate as the value type.
        args = typing.get_args(model)
        return bool(args) and args[-1] is not typing.Any
    if origin in (typing.Union, types.UnionType):
        # A union accepts the envelope when any member does.
        return all(_rejects_envelope(arg) for arg in typing.get_args(model))
    if isinstance(model, type) and issubclass(model, BaseModel):
        return not ENVELOPE_FIELDS <= set(model.model_fields)
    return False


def _builds_envelope(endpoint) -> bool:
    """The endpoint, or a module-level helper it calls, builds the envelope."""
    try:
        source = inspect.getsource(endpoint)
    except (OSError, TypeError):
        return False
    if BUILDS_ENVELOPE.search(source):
        return True
    namespace = getattr(endpoint, "__globals__", {})
    for name in set(re.findall(r"\b([A-Za-z_]\w*)\(", source)):
        helper = namespace.get(name)
        if not inspect.isfunction(helper) or helper is endpoint:
            continue
        try:
            if BUILDS_ENVELOPE.search(inspect.getsource(helper)):
                return True
        except (OSError, TypeError):
            continue
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
        if _builds_envelope(route.endpoint):
            where = inspect.getsourcefile(route.endpoint) or "?"
            mismatches.append(
                f"{sorted(route.methods)[0]} {route.path} ({Path(where).relative_to(API_ROOT)}): "
                f"declares {route.response_model!r} but returns the APIResponse envelope"
            )
    assert not mismatches, "\n".join(mismatches)


class _Payload(BaseModel):
    value: int


class _Envelope(BaseModel):
    data: dict
    status: str
    timestamp: str
    meta: dict


def _envelope_helper(data):
    return APIResponse(data=data).to_dict()


async def _endpoint_via_helper():
    return _envelope_helper({"value": 1})


@pytest.mark.parametrize("model, rejects", [
    (_Payload, True),
    (list[_Payload], True),
    (dict[str, _Payload], True),
    (typing.Optional[_Payload], True),
    (_Payload | None, True),
    (dict[str, typing.Any], False),
    (dict, False),
    (_Envelope, False),
    (typing.Optional[_Envelope], False),
])
def test_envelope_rejection_covers_dict_and_union_models(model, rejects):
    assert _rejects_envelope(model) is rejects


def test_envelope_built_by_a_called_helper_is_detected():
    assert _builds_envelope(_endpoint_via_helper)
