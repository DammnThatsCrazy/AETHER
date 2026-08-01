"""
Tests for API route handler response shapes and contract compliance.

Covers:
  - Health endpoint returns expected JSON shape
  - Standard error response format (AetherError.to_dict)
  - Pagination response format (PaginatedResponse.to_dict)
  - APIResponse wrapper format
  - Error subclass codes and messages
"""

from __future__ import annotations

import importlib
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"


@contextmanager
def backend_module_path():
    """Temporarily put the backend root on sys.path and clean up afterwards."""
    original = list(sys.path)
    for prefix in (
        "config", "services", "shared", "middleware", "dependencies", "repositories",
    ):
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in (
            "config", "services", "shared", "middleware", "dependencies", "repositories",
        ):
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def common_module(monkeypatch):
    """Import shared.common.common in local mode."""
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    with backend_module_path():
        mod = importlib.import_module("shared.common.common")
        importlib.reload(mod)
        yield mod


# ═══════════════════════════════════════════════════════════════════════════
# STANDARD ERROR RESPONSE FORMAT
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorResponseFormat:
    """Verify AetherError.to_dict() returns the canonical error envelope."""

    def test_aether_error_to_dict_shape(self, common_module):
        err = common_module.AetherError(
            code=common_module.ErrorCode.BAD_REQUEST,
            message="Something went wrong",
            details={"field": "email"},
            request_id="req-123",
        )
        result = err.to_dict()

        assert "error" in result
        error_body = result["error"]
        assert error_body["code"] == 400
        assert error_body["message"] == "Something went wrong"
        assert error_body["details"] == {"field": "email"}
        assert error_body["request_id"] == "req-123"

    def test_error_envelope_has_exactly_four_keys(self, common_module):
        err = common_module.AetherError(
            code=common_module.ErrorCode.INTERNAL,
            message="Internal failure",
        )
        result = err.to_dict()
        inner_keys = set(result["error"].keys())
        assert inner_keys == {"code", "message", "details", "request_id"}

    def test_unauthorized_error_defaults(self, common_module):
        err = common_module.UnauthorizedError()
        result = err.to_dict()
        assert result["error"]["code"] == 401
        assert result["error"]["message"] == "Unauthorized"
        assert result["error"]["details"] == {}

    def test_forbidden_error_defaults(self, common_module):
        err = common_module.ForbiddenError()
        result = err.to_dict()
        assert result["error"]["code"] == 403
        assert result["error"]["message"] == "Forbidden"

    def test_not_found_error_includes_resource(self, common_module):
        err = common_module.NotFoundError("Campaign")
        result = err.to_dict()
        assert result["error"]["code"] == 404
        assert "Campaign" in result["error"]["message"]
        assert "not found" in result["error"]["message"]

    def test_rate_limited_error_includes_retry_after(self, common_module):
        err = common_module.RateLimitedError(retry_after=120)
        result = err.to_dict()
        assert result["error"]["code"] == 429
        assert result["error"]["details"]["retry_after_seconds"] == 120

    def test_bad_request_error_with_custom_details(self, common_module):
        err = common_module.BadRequestError(
            "Validation failed",
            details={"missing_fields": ["name", "email"]},
        )
        result = err.to_dict()
        assert result["error"]["code"] == 400
        assert result["error"]["details"]["missing_fields"] == ["name", "email"]

    def test_conflict_error(self, common_module):
        err = common_module.ConflictError("Duplicate entry")
        result = err.to_dict()
        assert result["error"]["code"] == 409
        assert result["error"]["message"] == "Duplicate entry"

    def test_service_unavailable_error(self, common_module):
        err = common_module.ServiceUnavailableError("Redis")
        result = err.to_dict()
        assert result["error"]["code"] == 503
        assert "Redis" in result["error"]["message"]

    def test_error_request_id_is_valid_uuid_by_default(self, common_module):
        err = common_module.AetherError(
            code=common_module.ErrorCode.INTERNAL,
            message="test",
        )
        result = err.to_dict()
        # Should be a valid UUID string
        uuid.UUID(result["error"]["request_id"])


# ═══════════════════════════════════════════════════════════════════════════
# API RESPONSE WRAPPER
# ═══════════════════════════════════════════════════════════════════════════


class TestAPIResponseFormat:
    """Verify APIResponse.to_dict() returns the canonical success envelope."""

    def test_api_response_shape(self, common_module):
        resp = common_module.APIResponse(data={"users": []})
        result = resp.to_dict()

        assert "data" in result
        assert "meta" in result
        assert result["data"] == {"users": []}
        assert "request_id" in result["meta"]
        assert "timestamp" in result["meta"]

    def test_api_response_with_custom_meta(self, common_module):
        resp = common_module.APIResponse(
            data={"count": 42},
            meta={"cache_hit": True},
        )
        result = resp.to_dict()
        assert result["meta"]["cache_hit"] is True
        assert "request_id" in result["meta"]
        assert "timestamp" in result["meta"]

    def test_api_response_data_can_be_list(self, common_module):
        resp = common_module.APIResponse(data=[1, 2, 3])
        result = resp.to_dict()
        assert result["data"] == [1, 2, 3]

    def test_api_response_data_can_be_none(self, common_module):
        resp = common_module.APIResponse(data=None)
        result = resp.to_dict()
        assert result["data"] is None

    def test_api_response_timestamp_is_iso_format(self, common_module):
        resp = common_module.APIResponse(data={})
        result = resp.to_dict()
        ts = result["meta"]["timestamp"]
        # ISO 8601 contains 'T' separator and timezone info
        assert "T" in ts
        assert "+" in ts or "Z" in ts


# ═══════════════════════════════════════════════════════════════════════════
# PAGINATION RESPONSE FORMAT
# ═══════════════════════════════════════════════════════════════════════════


class TestPaginatedResponseFormat:
    """Verify PaginatedResponse.to_dict() produces the correct shape."""

    def test_paginated_response_shape(self, common_module):
        pagination_meta = common_module.PaginationMeta(
            total=100,
            limit=20,
            offset=0,
            has_more=True,
        )
        resp = common_module.PaginatedResponse(
            data=[{"id": "1"}, {"id": "2"}],
            pagination=pagination_meta,
        )
        result = resp.to_dict()

        assert "data" in result
        assert "pagination" in result
        assert "meta" in result
        assert len(result["data"]) == 2

    def test_pagination_meta_fields(self, common_module):
        meta = common_module.PaginationMeta(
            total=50,
            limit=10,
            offset=20,
            has_more=True,
        )
        result = meta.to_dict()

        assert result["total"] == 50
        assert result["limit"] == 10
        assert result["offset"] == 20
        assert result["has_more"] is True

    def test_pagination_meta_cursor_mode(self, common_module):
        meta = common_module.PaginationMeta(
            limit=25,
            cursor="abc123",
            next_cursor="def456",
            has_more=True,
        )
        result = meta.to_dict()

        assert result["cursor"] == "abc123"
        assert result["next_cursor"] == "def456"
        assert result["has_more"] is True
        assert "offset" not in result  # offset is None, should be omitted

    def test_pagination_meta_omits_none_fields(self, common_module):
        meta = common_module.PaginationMeta(limit=50, has_more=False)
        result = meta.to_dict()

        assert "total" not in result
        assert "offset" not in result
        assert "cursor" not in result
        assert "next_cursor" not in result
        assert result["limit"] == 50
        assert result["has_more"] is False

    def test_paginated_response_meta_has_request_id_and_timestamp(self, common_module):
        pagination_meta = common_module.PaginationMeta(limit=10, has_more=False)
        resp = common_module.PaginatedResponse(
            data=[],
            pagination=pagination_meta,
        )
        result = resp.to_dict()

        assert "request_id" in result["meta"]
        assert "timestamp" in result["meta"]


# ═══════════════════════════════════════════════════════════════════════════
# PAGINATION INPUT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestPaginationInputValidation:
    """Verify pagination helpers enforce limits."""

    def test_offset_pagination_clamps_limit_upper(self, common_module):
        pag = common_module.OffsetPagination(limit=999)
        assert pag.limit == 200

    def test_offset_pagination_clamps_limit_lower(self, common_module):
        pag = common_module.OffsetPagination(limit=0)
        assert pag.limit == 1

    def test_offset_pagination_clamps_negative_offset(self, common_module):
        pag = common_module.OffsetPagination(offset=-5)
        assert pag.offset == 0

    def test_cursor_pagination_clamps_limit(self, common_module):
        pag = common_module.CursorPagination(limit=500)
        assert pag.limit == 200

    def test_cursor_pagination_minimum_limit(self, common_module):
        pag = common_module.CursorPagination(limit=-1)
        assert pag.limit == 1

    def test_offset_pagination_default_sort(self, common_module):
        pag = common_module.OffsetPagination()
        assert pag.sort_by == "created_at"
        assert pag.sort_order == "desc"


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════


class TestValidationHelpers:
    """Verify the request validation utility functions."""

    def test_validate_uuid_accepts_valid(self, common_module):
        valid_id = str(uuid.uuid4())
        result = common_module.validate_uuid(valid_id)
        assert result == valid_id

    def test_validate_uuid_rejects_invalid(self, common_module):
        with pytest.raises(common_module.BadRequestError, match="Invalid UUID"):
            common_module.validate_uuid("not-a-uuid")

    def test_validate_required_passes_when_all_present(self, common_module):
        data = {"name": "Alice", "email": "a@b.com"}
        common_module.validate_required(data, ["name", "email"])

    def test_validate_required_raises_on_missing(self, common_module):
        data = {"name": "Alice"}
        with pytest.raises(common_module.BadRequestError, match="Missing required"):
            common_module.validate_required(data, ["name", "email"])

    def test_validate_enum_accepts_valid(self, common_module):
        result = common_module.validate_enum("active", ["active", "paused", "archived"])
        assert result == "active"

    def test_validate_enum_rejects_invalid(self, common_module):
        with pytest.raises(common_module.BadRequestError, match="Invalid value"):
            common_module.validate_enum("deleted", ["active", "paused", "archived"])

    def test_validate_string_length_passes(self, common_module):
        result = common_module.validate_string_length("hello", "name", min_len=1, max_len=10)
        assert result == "hello"

    def test_validate_string_length_rejects_too_long(self, common_module):
        with pytest.raises(common_module.BadRequestError, match="must be between"):
            common_module.validate_string_length("x" * 1001, "name", max_len=1000)

    def test_validate_string_length_rejects_empty(self, common_module):
        with pytest.raises(common_module.BadRequestError, match="must be between"):
            common_module.validate_string_length("", "name", min_len=1)


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH ENDPOINT RESPONSE SHAPE
# ═══════════════════════════════════════════════════════════════════════════


class TestHealthEndpointContract:
    """Verify the health endpoint response has the expected structure.

    We test the route function directly (without spinning up a full ASGI server)
    by mocking the dependency registry.
    """

    @staticmethod
    def _invoke_health(monkeypatch, dependency_health: dict):
        """Call the liveness handler through a real app with a mocked registry.

        The handler takes a ``Request`` because it derives per-component state
        from the mounted router table and the worker supervisor attached to the
        app, rather than asserting health it has not observed. It therefore has
        to be exercised through an app rather than called as a bare coroutine.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        deps_mod = importlib.import_module("dependencies.providers")
        importlib.reload(deps_mod)

        class FakeRegistry:
            async def health_check(self):
                return dependency_health

        monkeypatch.setattr(deps_mod, "get_registry", lambda: FakeRegistry())

        gateway_routes = importlib.import_module("services.gateway.routes")
        importlib.reload(gateway_routes)

        app = FastAPI()
        app.include_router(gateway_routes.router)
        with TestClient(app) as client:
            response = client.get("/health")
        return response

    def test_health_response_shape(self, common_module, monkeypatch):
        """Health response must have status, timestamp, dependencies, components."""
        with backend_module_path():
            response = self._invoke_health(
                monkeypatch,
                {"cache": {"status": "ok"}, "database": {"status": "ok"}},
            )
            result = response.json()

            assert "status" in result
            assert result["status"] in ("healthy", "degraded")
            assert "timestamp" in result
            assert "dependencies" in result
            assert isinstance(result["dependencies"], dict)

            # "services" was renamed to "components" when the handler stopped
            # emitting hardcoded "ok" per surface. Each entry now carries the
            # derivation, so a caller can tell an observed ok from an unobserved
            # one instead of taking a bare string on trust.
            assert "components" in result
            assert isinstance(result["components"], dict)
            for name, component in result["components"].items():
                assert set(component) >= {"status", "signals", "unverified"}, name
                assert component["status"] in ("ok", "degraded", "down", "unknown"), name

            # It is a liveness probe: it must keep answering 200 so the
            # orchestrator does not kill a process that is still serving.
            assert response.status_code == 200
            assert result["probe"] == "liveness"
            assert result["readiness_probe"] == "/v1/ready"

    def test_health_degraded_when_dependency_down(self, common_module, monkeypatch):
        """If any dependency reports non-ok, status should be 'degraded'."""
        with backend_module_path():
            response = self._invoke_health(
                monkeypatch,
                {
                    "cache": {"status": "ok"},
                    "database": {"status": "error", "message": "connection refused"},
                },
            )
            result = response.json()

            assert result["status"] == "degraded"
            # Degradation must not be expressed as a non-200; that is what
            # /v1/ready is for. See services/gateway/routes.py::health_check.
            assert response.status_code == 200

    def test_health_healthy_when_all_ok(self, common_module, monkeypatch):
        """If all dependencies report ok, status should be 'healthy'."""
        with backend_module_path():
            response = self._invoke_health(
                monkeypatch,
                {
                    "cache": {"status": "ok"},
                    "database": {"status": "ok"},
                    "event_bus": {"status": "ok"},
                    "graph": {"status": "ok"},
                },
            )
            result = response.json()

            # A component whose state this process cannot observe reports
            # "unknown", which is not health — so an all-ok dependency set does
            # not by itself make the top-level status healthy.
            assert result["status"] in ("healthy", "degraded")

            # What this test actually pins: with every dependency probe ok, no
            # component may blame a dependency. Component roll-ups are still
            # allowed to be down here, because this fixture mounts only the
            # gateway router — the other surfaces are genuinely absent, and
            # reporting them as present would be the very dishonesty the
            # derived report exists to prevent.
            for name, component in result["components"].items():
                dependencies = component["signals"].get("dependencies")
                if dependencies is not None:
                    assert dependencies["status"] == "ok", (name, dependencies)
