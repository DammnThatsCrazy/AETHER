"""Frontend/backend model-runtime contract test (Commit 16, Agent E).

The Aether (C13) and Kyber (C14) frontends ship typed fetch clients that hit
specific ``/v1/model-runtime/*`` paths. If the backend model-runtime routes
(Commit 16, sibling B) do not register those exact paths the surfaces 404. This
test pins the contract: it extracts the URL path literals from the landed
frontend ``types.ts`` files and asserts every one of them is registered on the
model-runtime router.

Concurrency / gating: the HTTP routes module (``services.model_runtime.routes``)
lands in the same commit as this test. Until the module is importable the whole
suite skips cleanly; once it lands the checks run green if the contract holds
and fail loudly — with an explicit gap list — if it does not. No frontend or
backend file is modified; this is read-only.
"""

from __future__ import annotations

import inspect
import re
import typing
from pathlib import Path

import pytest

# The HTTP routes module is Commit-16-B and may land concurrently with this
# test; until it is importable the whole suite skips cleanly.
routes_module = pytest.importorskip("services.model_runtime.routes")

from fastapi.routing import APIRouter  # noqa: E402  (routes module gates fastapi)

_REPO_ROOT = Path(__file__).resolve().parents[4]

_AETHER_TYPES = (
    _REPO_ROOT
    / "frontend"
    / "aether"
    / "src"
    / "features"
    / "model-selection"
    / "types.ts"
)
_KYBER_TYPES = (
    _REPO_ROOT
    / "frontend"
    / "kyber"
    / "src"
    / "features"
    / "model-runtime"
    / "types.ts"
)

# Full path literals, e.g. ``'/v1/model-runtime/models'`` (single or double
# quoted). This also catches the docstring references in the Aether file.
_FULL_PATH_RE = re.compile(r"""['"]/v1/model-runtime/[^'"]+['"]""")

# Resource segments handed to the Kyber typed client, e.g.
# ``modelRuntimeRequest<RegistryResponse>('registry')``.
_RESOURCE_RE = re.compile(
    r"""modelRuntimeRequest<[A-Za-z0-9_]+>\(\s*['"]([a-z0-9_-]+)['"]"""
)

# Contract-shape field sets taken verbatim from the landed frontend types.
_AETHER_MODEL_FIELDS = {
    "capabilities",
    "inputCostPerMTok",
    "modelId",
    "outputCostPerMTok",
    "provider",
    "status",
}
_KYBER_HEALTH_FIELDS = {"checks", "providers", "status"}


def _extract_frontend_paths() -> dict[str, list[str]]:
    """Extract the absolute ``/v1/model-runtime/*`` paths each client hits.

    Returns ``{source_label: sorted_paths}``. A missing frontend file skips that
    source with an explicit reason (the files are landed, so this is defensive
    only).
    """
    extracted: dict[str, list[str]] = {}
    for label, path in (("aether", _AETHER_TYPES), ("kyber", _KYBER_TYPES)):
        if not path.exists():
            pytest.skip(f"frontend types.ts not present yet: {path}")
        text = path.read_text(encoding="utf-8")
        paths: set[str] = set()
        for match in _FULL_PATH_RE.finditer(text):
            paths.add(match.group(0)[1:-1])
        for match in _RESOURCE_RE.finditer(text):
            paths.add(f"/v1/model-runtime/{match.group(1)}")
        extracted[label] = sorted(paths)
    return extracted


def _router_instance(module: object) -> APIRouter:
    """Return the APIRouter exported by the routes module (name-agnostic).

    Fails loudly with the actual module members if no router is exported, so the
    coordinator sees the real gap instead of a generic assertion.
    """
    candidates = [
        value for value in vars(module).values() if isinstance(value, APIRouter)
    ]
    if not candidates:
        public = sorted(name for name in vars(module) if not name.startswith("_"))
        raise AssertionError(
            "services.model_runtime.routes exports no FastAPI APIRouter; "
            f"module members: {public}"
        )
    for name, value in vars(module).items():
        if name == "router" and isinstance(value, APIRouter):
            return value
    for name, value in vars(module).items():
        if isinstance(value, APIRouter) and "model_runtime" in name:
            return value
    return candidates[0]


def _route_regex(path_template: str) -> re.Pattern[str]:
    """Convert a FastAPI path template (``{param}`` supported) to a regex."""
    segments = []
    for segment in path_template.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            segments.append("[^/]+")
        else:
            segments.append(re.escape(segment))
    return re.compile("^" + "/".join(segments) + "/?$")


def _route_candidates(router: APIRouter, route: object) -> list[str]:
    """Full path candidates for a route (prefix applied if the route is bare)."""
    raw = getattr(route, "path", None) or ""
    if not raw:
        return []
    candidates = [raw]
    if not raw.startswith("/v1"):
        prefix = getattr(router, "prefix", None) or ""
        combined = f"{prefix}{raw}"
        if combined not in candidates:
            candidates.append(combined)
    return candidates


def _route_for_path(router: APIRouter, path: str) -> list[tuple[object, set[str]]]:
    """Return ``(route, methods)`` pairs whose path template matches ``path``."""
    matched = []
    for route in router.routes:
        if any(
            _route_regex(candidate).match(path)
            for candidate in _route_candidates(router, route)
        ):
            methods = set(getattr(route, "methods", None) or [])
            matched.append((route, methods))
    return matched


def _annotation_concrete_types(annotation: object) -> list[type]:
    """Expand Optional/Union/List/Dict annotations to concrete types."""
    if annotation is None:
        return []
    origin = typing.get_origin(annotation)
    if origin is None:
        return [annotation] if isinstance(annotation, type) else []
    out: list[type] = []
    for arg in typing.get_args(annotation):
        out.extend(_annotation_concrete_types(arg))
    return out


def _pydantic_model_field_names(model_type: object) -> set[str]:
    """All field names in a pydantic model, including nested models."""
    names: set[str] = set()
    seen: set[int] = set()

    def walk(typ: object) -> None:
        if not isinstance(typ, type) or id(typ) in seen:
            return
        fields = getattr(typ, "model_fields", None)
        if fields is None:
            fields = getattr(typ, "__fields__", None)  # pydantic v1 fallback
        if not fields:
            return
        seen.add(id(typ))
        for field_name, field_info in fields.items():
            names.add(field_name)
            annotation = getattr(field_info, "annotation", None)
            if annotation is None:
                annotation = getattr(field_info, "outer_type_", None)
            for sub in _annotation_concrete_types(annotation):
                walk(sub)

    walk(model_type)
    return names


def _response_model_field_names(route: object) -> set[str] | None:
    """Field names of a route's declared response model (None if undeclared)."""
    response_model = getattr(route, "response_model", None)
    if response_model is None:
        return None
    fields = _pydantic_model_field_names(response_model)
    return fields or None


def _endpoint_source(route: object) -> str:
    """Source text (docstring/sample) of the route's endpoint, or empty."""
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return ""
    try:
        return inspect.getsource(endpoint)
    except (OSError, TypeError):
        return inspect.getdoc(endpoint) or ""


def test_extracts_expected_frontend_paths() -> None:
    """Pin the exact path set the landed frontend clients hit (contract)."""
    extracted = _extract_frontend_paths()
    expected = {
        "aether": sorted(
            [
                "/v1/model-runtime/models",
                "/v1/model-runtime/tenant-default",
            ]
        ),
        "kyber": sorted(
            [
                "/v1/model-runtime/entitlements",
                "/v1/model-runtime/health",
                "/v1/model-runtime/registry",
                "/v1/model-runtime/traces",
                "/v1/model-runtime/usage",
            ]
        ),
    }
    assert extracted == expected, (
        "frontend types.ts path extraction drifted from the pinned contract; "
        f"extracted={extracted} expected={expected}"
    )


def test_every_frontend_path_is_registered() -> None:
    """Every frontend path must be registered on the model-runtime router."""
    router = _router_instance(routes_module)
    frontend = _extract_frontend_paths()
    all_paths = sorted({path for paths in frontend.values() for path in paths})
    unmatched = [
        path
        for path in all_paths
        if not _route_for_path(router, path)
    ]
    assert not unmatched, (
        "frontend model-runtime paths with NO backend route "
        f"(genuine integration gap): {unmatched}"
    )


def test_aether_model_list_response_shape() -> None:
    """Aether model-list response must carry the frontend contract fields."""
    router = _router_instance(routes_module)
    matched = _route_for_path(router, "/v1/model-runtime/models")
    assert matched, "/v1/model-runtime/models has no backend route"
    for route, _methods in matched:
        fields = _response_model_field_names(route)
        if fields is not None:
            missing = sorted(_AETHER_MODEL_FIELDS - fields)
            assert not missing, (
                "backend response model for GET /v1/model-runtime/models is "
                f"missing frontend contract fields: {missing} "
                f"(model fields: {sorted(fields)})"
            )
            return
    # No declared/introspectable response model: fall back to the route sample.
    source = _endpoint_source(matched[0][0])
    missing = sorted(field for field in _AETHER_MODEL_FIELDS if field not in source)
    assert not missing, (
        "backend route for GET /v1/model-runtime/models declares no response "
        f"model and its source does not mention frontend contract fields: {missing}"
    )


def test_kyber_health_response_shape() -> None:
    """Kyber health response must carry the frontend contract fields."""
    router = _router_instance(routes_module)
    matched = _route_for_path(router, "/v1/model-runtime/health")
    assert matched, "/v1/model-runtime/health has no backend route"
    for route, _methods in matched:
        fields = _response_model_field_names(route)
        if fields is not None:
            missing = sorted(_KYBER_HEALTH_FIELDS - fields)
            assert not missing, (
                "backend response model for GET /v1/model-runtime/health is "
                f"missing frontend contract fields: {missing} "
                f"(model fields: {sorted(fields)})"
            )
            return
    source = _endpoint_source(matched[0][0])
    missing = sorted(field for field in _KYBER_HEALTH_FIELDS if field not in source)
    assert not missing, (
        "backend route for GET /v1/model-runtime/health declares no response "
        f"model and its source does not mention frontend contract fields: {missing}"
    )
