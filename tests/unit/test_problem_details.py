"""Canonical Problem-Details error contract tests (backend side)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))

from shared.common.common import (  # noqa: E402
    AetherError,
    BadRequestError,
    ErrorCode,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
    problem_dict,
    problem_response,
)


class TestAetherErrorProblemDetails:
    def test_canonical_members_present(self):
        err = NotFoundError("Campaign", request_id="req-1")
        body = err.to_dict()
        assert body["type"] == "https://errors.aether.dev/not-found"
        assert body["title"] == "Not Found"
        assert body["status"] == 404
        assert body["code"] == "NOT_FOUND"
        assert body["detail"] == "Campaign not found"
        assert body["message"] == "Campaign not found"
        assert body["request_id"] == "req-1"
        assert body["correlation_id"] == "req-1"
        assert body["retryable"] is False

    def test_legacy_nested_envelope_preserved(self):
        err = BadRequestError("nope", details={"field": "x"}, request_id="req-2")
        body = err.to_dict()
        assert body["error"] == {
            "code": 400,
            "message": "nope",
            "details": {"field": "x"},
            "request_id": "req-2",
        }

    def test_retryable_defaults_by_status(self):
        assert RateLimitedError().to_dict()["retryable"] is True
        assert ServiceUnavailableError().to_dict()["retryable"] is True
        assert BadRequestError().to_dict()["retryable"] is False
        assert AetherError(ErrorCode.INTERNAL, "boom").to_dict()["retryable"] is True

    def test_retryable_override(self):
        err = AetherError(ErrorCode.INTERNAL, "permanent", retryable=False)
        assert err.to_dict()["retryable"] is False

    def test_stable_code_derivation(self):
        assert RateLimitedError().to_dict()["code"] == "RATE_LIMITED"
        assert ServiceUnavailableError().to_dict()["code"] == "SERVICE_UNAVAILABLE"


class TestProblemHelpers:
    def test_problem_dict_shape_and_extensions(self):
        body = problem_dict(
            429,
            "Rate Limit Exceeded",
            "Slow down",
            code="RATE_LIMIT_EXCEEDED",
            request_id="req-3",
            extensions={"retry_after_seconds": 30},
        )
        assert body["status"] == 429
        assert body["code"] == "RATE_LIMIT_EXCEEDED"
        assert body["retry_after_seconds"] == 30
        assert body["retryable"] is True
        assert body["message"] == "Slow down"
        assert body["error"]["code"] == 429
        assert body["type"].endswith("rate-limit-exceeded")

    def test_problem_response_is_json_response(self):
        resp = problem_response(
            403,
            "Forbidden",
            "No entitlement",
            code="SERVICE_NOT_AVAILABLE",
            headers={"X-Test": "1"},
            request_id="req-4",
        )
        assert resp.status_code == 403
        assert resp.headers["X-Test"] == "1"
        payload = json.loads(resp.body)
        assert payload["code"] == "SERVICE_NOT_AVAILABLE"
        assert payload["detail"] == "No entitlement"
        assert payload["request_id"] == "req-4"

    def test_type_slug_override(self):
        body = problem_dict(
            403,
            "Service Not Available On Plan",
            "Upgrade required",
            code="SERVICE_NOT_AVAILABLE",
            type_slug="entitlement/service-not-available",
        )
        assert body["type"] == "https://errors.aether.dev/entitlement/service-not-available"

    def test_request_id_minted_when_missing(self):
        body = problem_dict(500, "Internal", "boom", code="INTERNAL")
        assert body["request_id"]
        assert body["request_id"] == body["correlation_id"]
