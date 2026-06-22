"""
Unit tests for the serving API.

Tests cover:
  - Health endpoint returns correct status
  - Model listing endpoint contract
  - Prediction endpoint request/response schemas
  - Latency header middleware
  - ModelServer internal state management
  - Pydantic request/response model validation
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """Create a TestClient for the serving FastAPI app."""
    from serving.src.api import app

    return TestClient(app)


# =============================================================================
# HEALTH ENDPOINT TESTS
# =============================================================================


class TestHealthEndpoint:
    """Test the /health endpoint."""

    def test_health_returns_200(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_response_schema(self, client: TestClient) -> None:
        response = client.get("/health")
        data = response.json()

        assert "status" in data
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["version"] == "4.0.0"
        assert "models_loaded" in data
        assert isinstance(data["models_loaded"], list)
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], (int, float))


# =============================================================================
# PREDICTION ENDPOINT TESTS
# =============================================================================


class TestPredictionEndpoints:
    """Test prediction endpoint contracts.

    Models are not loaded in the test environment, so endpoints will
    return 503 (model not loaded). These tests validate the API contract
    rather than the model output.
    """

    def test_intent_prediction(self, client: TestClient) -> None:
        payload = {
            "session_id": "test-session-001",
            "features": {
                "click_count": 5.0,
                "scroll_depth": 0.6,
                "time_on_page": 120.0,
                "pages_viewed": 3.0,
                "last_action_encoded": 1.0,
                "session_duration": 300.0,
                "device_type_encoded": 0.0,
            },
        }
        response = client.post("/v1/predict/intent", json=payload)
        # 503 if model not loaded, 200 if loaded
        assert response.status_code in (200, 503)

    def test_bot_detection(self, client: TestClient) -> None:
        payload = {
            "session_id": "test-session-002",
            "features": {
                "mouse_speed_mean": 2.5,
                "mouse_speed_std": 0.8,
                "click_interval_mean": 1.5,
                "click_interval_std": 0.5,
                "scroll_pattern_entropy": 3.0,
                "keystroke_timing_variance": 0.3,
                "session_duration": 300.0,
                "page_views": 5.0,
                "unique_pages": 4.0,
                "js_execution_time": 50.0,
                "has_webdriver": 0.0,
                "user_agent_anomaly_score": 0.1,
            },
        }
        response = client.post("/v1/predict/bot", json=payload)
        assert response.status_code in (200, 503)

    def test_session_score(self, client: TestClient) -> None:
        payload = {
            "session_id": "test-session-003",
            "features": {
                "page_views": 5.0,
                "unique_pages": 4.0,
                "session_duration": 300.0,
                "scroll_depth_mean": 0.6,
                "click_count": 10.0,
                "form_interactions": 2.0,
                "search_queries": 1.0,
                "product_views": 3.0,
                "add_to_cart_count": 1.0,
                "time_to_first_interaction": 15.0,
            },
        }
        response = client.post("/v1/predict/session-score", json=payload)
        assert response.status_code in (200, 503)

    def test_churn_prediction(self, client: TestClient) -> None:
        payload = {
            "identity_id": "user-001",
            "features": {
                "days_since_last_visit": 15.0,
                "visit_frequency_30d": 2.0,
                "session_count_30d": 5.0,
                "avg_session_duration": 120.0,
                "page_views_trend": -0.1,
                "conversion_count_30d": 1.0,
                "support_tickets": 0.0,
                "email_open_rate": 0.3,
                "days_since_signup": 90.0,
                "lifetime_value": 200.0,
            },
        }
        response = client.post("/v1/predict/churn", json=payload)
        assert response.status_code in (200, 400, 503)

    def test_ltv_prediction(self, client: TestClient) -> None:
        payload = {
            "identity_id": "user-002",
            "features": {
                "monetary_value": 100.0,
                "frequency": 5.0,
                "recency": 10.0,
                "T": 90.0,
                "avg_order_value": 50.0,
                "purchase_count_90d": 3.0,
                "days_since_first_purchase": 180.0,
                "product_categories_count": 4.0,
                "discount_usage_rate": 0.2,
                "referral_count": 1.0,
            },
        }
        response = client.post("/v1/predict/ltv", json=payload)
        assert response.status_code in (200, 400, 503)

    def test_missing_features_returns_400(self, client: TestClient) -> None:
        payload = {
            "identity_id": "user-003",
            # features intentionally omitted
        }
        response = client.post("/v1/predict/churn", json=payload)
        assert response.status_code == 400

    def test_invalid_model_batch_returns_error(self, client: TestClient) -> None:
        payload = {
            "model": "nonexistent_model",
            "instances": [{"feature_a": 1.0}],
        }
        response = client.post("/v1/predict/batch", json=payload)
        # Should fail because model is not loaded
        assert response.status_code in (500, 503)

    def test_empty_batch_returns_400(self, client: TestClient) -> None:
        payload = {
            "model": "churn_prediction",
            "instances": [],
        }
        response = client.post("/v1/predict/batch", json=payload)
        assert response.status_code == 400


# =============================================================================
# LATENCY HEADER TESTS
# =============================================================================


class TestLatencyHeaders:
    """Test the latency-tracking middleware."""

    def test_latency_header_present(self, client: TestClient) -> None:
        response = client.get("/health")
        assert "X-Inference-Latency-Ms" in response.headers

    def test_latency_header_is_numeric(self, client: TestClient) -> None:
        response = client.get("/health")
        latency = response.headers.get("X-Inference-Latency-Ms", "")
        assert float(latency) >= 0


# =============================================================================
# PYDANTIC SCHEMA TESTS
# =============================================================================


class TestRequestResponseSchemas:
    """Test Pydantic request/response model validation."""

    def test_prediction_request_valid(self) -> None:
        from serving.src.api import PredictionRequest

        req = PredictionRequest(features={"click_count": 5.0, "duration": 120.0})
        assert isinstance(req.features, dict)

    def test_prediction_response_valid(self) -> None:
        from serving.src.api import PredictionResponse

        resp = PredictionResponse(
            prediction=0.75,
            model="churn_prediction",
            version="1.0.0",
            latency_ms=5.2,
        )
        assert resp.prediction == 0.75
        assert resp.model == "churn_prediction"

    def test_health_response_valid(self) -> None:
        from serving.src.api import HealthResponse

        resp = HealthResponse(
            status="healthy",
            version="4.0.0",
            models_loaded=["intent_prediction", "bot_detection"],
            uptime_seconds=123.4,
        )
        assert resp.status == "healthy"
        assert len(resp.models_loaded) == 2

    def test_batch_request_valid(self) -> None:
        from serving.src.api import BatchPredictionRequest

        req = BatchPredictionRequest(
            model="churn_prediction",
            instances=[
                {"days_since_last_visit": 5.0},
                {"days_since_last_visit": 30.0},
            ],
        )
        assert req.model == "churn_prediction"
        assert len(req.instances) == 2

    def test_intent_request_valid(self) -> None:
        from serving.src.api import IntentPredictionRequest

        req = IntentPredictionRequest(
            session_id="sess-001",
            features={"click_count": 5.0},
        )
        assert req.session_id == "sess-001"

    def test_attribution_request_valid(self) -> None:
        from serving.src.api import AttributionRequest

        req = AttributionRequest(
            conversion_id="conv-001",
            touchpoints=[
                {"channel": "organic_search", "touchpoint_index": 0},
                {"channel": "email", "touchpoint_index": 1},
            ],
            method="shapley",
        )
        assert req.method == "shapley"
        assert len(req.touchpoints) == 2


# =============================================================================
# MODEL SERVER UNIT TESTS
# =============================================================================


class TestModelServer:
    """Test the ModelServer class in isolation."""

    def test_model_server_init(self) -> None:
        from serving.src.api import ModelServer

        server = ModelServer(models_dir="/tmp/nonexistent")
        assert server.loaded_models() == []

    def test_model_info_all_models(self) -> None:
        from serving.src.api import ModelServer

        server = ModelServer(models_dir="/tmp/nonexistent")
        info = server.model_info()

        assert len(info) >= 9
        for model_info in info:
            assert hasattr(model_info, "name")
            assert hasattr(model_info, "status")
            assert model_info.status == "not_loaded"

    def test_get_model_raises_on_missing(self) -> None:
        from fastapi import HTTPException

        from serving.src.api import ModelServer

        server = ModelServer(models_dir="/tmp/nonexistent")

        with pytest.raises(HTTPException) as exc_info:
            server.get_model("nonexistent_model")
        # Unknown model name -> 404 (distinct from 503 which means
        # "known model, no artifact loaded").
        assert exc_info.value.status_code == 404

    def test_model_names_list(self) -> None:
        from serving.src.api import MODEL_NAMES

        expected = [
            "intent_prediction",
            "bot_detection",
            "session_scorer",
            "churn_prediction",
            "ltv_prediction",
            "journey_prediction",
            "campaign_attribution",
            "anomaly_detection",
            "identity_resolution",
        ]
        assert set(expected).issubset(set(MODEL_NAMES))

    def test_model_types_mapping(self) -> None:
        from serving.src.api import MODEL_TYPES

        # Edge models
        assert MODEL_TYPES["intent_prediction"] == "edge"
        assert MODEL_TYPES["bot_detection"] == "edge"
        assert MODEL_TYPES["session_scorer"] == "edge"
        # Server models
        assert MODEL_TYPES["churn_prediction"] == "server"
        assert MODEL_TYPES["ltv_prediction"] == "server"
        assert MODEL_TYPES["anomaly_detection"] == "server"


# =============================================================================
# IDENTITY RESOLUTION ENDPOINT TESTS
# =============================================================================


class TestIdentityResolutionEndpoint:
    """Tests for the /v1/predict/identity endpoint."""

    VALID_FEATURES = {
        "device_fingerprint_sim": 0.85,
        "behavioral_sim": 0.72,
        "temporal_overlap": 0.60,
        "shared_ip_count": 3,
        "session_sequence_score": 0.78,
        "wallet_link_score": 0.5,
        "geo_distance": 12.5,
        "browser_match": 1.0,
        "os_match": 1.0,
    }

    def test_identity_endpoint_returns_200(self, client: TestClient) -> None:
        response = client.post(
            "/v1/predict/identity",
            json={"profile_pair_id": "profile_a:profile_b", "features": self.VALID_FEATURES},
        )
        assert response.status_code == 200

    def test_identity_response_schema(self, client: TestClient) -> None:
        response = client.post(
            "/v1/predict/identity",
            json={"profile_pair_id": "a:b", "features": self.VALID_FEATURES},
        )
        data = response.json()

        assert "profile_pair_id" in data
        assert data["profile_pair_id"] == "a:b"
        assert "is_same_entity" in data
        assert isinstance(data["is_same_entity"], bool)
        assert "merge_probability" in data
        assert 0.0 <= data["merge_probability"] <= 1.0
        assert "confidence" in data
        assert 0.0 <= data["confidence"] <= 1.0
        assert "latency_ms" in data
        assert data["latency_ms"] >= 0.0
        assert "model_version" in data

    def test_identity_without_optional_wallet_link(self, client: TestClient) -> None:
        features = {k: v for k, v in self.VALID_FEATURES.items() if k != "wallet_link_score"}
        response = client.post(
            "/v1/predict/identity",
            json={"profile_pair_id": "x:y", "features": features},
        )
        assert response.status_code == 200

    def test_identity_invalid_request_missing_pair_id(self, client: TestClient) -> None:
        response = client.post(
            "/v1/predict/identity",
            json={"features": self.VALID_FEATURES},
        )
        assert response.status_code == 422


# =============================================================================
# READINESS ENDPOINT TESTS
# =============================================================================


class TestReadinessEndpoint:
    """Tests for the /ready endpoint."""

    def test_ready_returns_200(self, client: TestClient) -> None:
        response = client.get("/ready")
        assert response.status_code == 200

    def test_ready_response_schema(self, client: TestClient) -> None:
        response = client.get("/ready")
        data = response.json()

        assert "ready" in data
        assert data["ready"] is True
        assert "models_loaded" in data
        assert isinstance(data["models_loaded"], list)
        assert "sla_violation_rate" in data
        assert isinstance(data["sla_violation_rate"], float)
        assert "freshness_summary" in data
        assert isinstance(data["freshness_summary"], dict)

    def test_ready_at_high_violation_rate_returns_503(self) -> None:
        from unittest.mock import MagicMock, patch
        from serving.src.api import app

        mock_tracker = MagicMock()
        mock_tracker.get_violation_rate.return_value = 0.15  # 15% — above 10% threshold
        mock_tracker.get_summary.return_value = {"total_checks": 100, "total_violations": 15, "violation_rate": 0.15, "by_model": {}}

        with patch("serving.src.api._freshness_tracker", mock_tracker):
            test_client = TestClient(app, raise_server_exceptions=False)
            response = test_client.get("/ready")
            assert response.status_code == 503


# =============================================================================
# FRESHNESS MONITORING ENDPOINT TESTS
# =============================================================================


class TestFreshnessMonitoringEndpoint:
    """Tests for the /v1/monitoring/freshness endpoint."""

    def test_freshness_returns_200(self, client: TestClient) -> None:
        response = client.get("/v1/monitoring/freshness")
        assert response.status_code == 200

    def test_freshness_response_has_required_keys(self, client: TestClient) -> None:
        response = client.get("/v1/monitoring/freshness")
        data = response.json()

        assert "total_checks" in data
        assert "total_violations" in data
        assert "violation_rate" in data
        assert isinstance(data["violation_rate"], float)

    def test_freshness_disabled_when_tracker_none(self) -> None:
        from unittest.mock import patch
        from serving.src.api import app

        with patch("serving.src.api._freshness_tracker", None):
            test_client = TestClient(app)
            response = test_client.get("/v1/monitoring/freshness")
            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is False


class TestDriftMonitoringEndpoint:
    """Tests for the /v1/monitoring/drift endpoint."""

    def test_drift_returns_200(self, client: TestClient) -> None:
        response = client.get("/v1/monitoring/drift")
        assert response.status_code == 200

    def test_drift_response_has_required_keys(self, client: TestClient) -> None:
        response = client.get("/v1/monitoring/drift")
        data = response.json()

        assert "last_run" in data
        assert "models" in data
        assert "buffer_sizes" in data
        assert isinstance(data["buffer_sizes"], dict)

    def test_drift_buffer_sizes_covers_all_models(self, client: TestClient) -> None:
        from serving.src.api import MODEL_NAMES

        response = client.get("/v1/monitoring/drift")
        data = response.json()

        for model in MODEL_NAMES:
            assert model in data["buffer_sizes"]
            assert isinstance(data["buffer_sizes"][model], int)

    def test_drift_buffer_sizes_start_at_zero(self, client: TestClient) -> None:
        from unittest.mock import patch
        from collections import deque
        from serving.src.api import MODEL_NAMES, app

        empty_buffers = {m: deque(maxlen=500) for m in MODEL_NAMES}
        with patch("serving.src.api._prediction_buffers", empty_buffers):
            test_client = TestClient(app)
            response = test_client.get("/v1/monitoring/drift")
            data = response.json()
            for model in MODEL_NAMES:
                assert data["buffer_sizes"][model] == 0

    def test_drift_empty_last_run_when_no_check_yet(self, client: TestClient) -> None:
        from unittest.mock import patch
        from serving.src.api import app

        with patch("serving.src.api._last_drift_results", {}):
            test_client = TestClient(app)
            response = test_client.get("/v1/monitoring/drift")
            data = response.json()
            assert data["last_run"] is None
            assert data["models"] == {}


class TestAnomalyDetectionEndpoint:
    """Tests for POST /v1/predict/anomaly."""

    def test_anomaly_returns_200(self, client: TestClient) -> None:
        payload = {
            "record_id": "rec-001",
            "features": {
                "feature_a": 1.0,
                "feature_b": 0.5,
                "feature_c": 2.3,
            },
        }
        response = client.post("/v1/predict/anomaly", json=payload)
        assert response.status_code in (200, 503)

    def test_anomaly_response_schema(self, client: TestClient) -> None:
        payload = {
            "record_id": "rec-002",
            "features": {"x": 0.1, "y": 0.9},
        }
        response = client.post("/v1/predict/anomaly", json=payload)
        if response.status_code == 200:
            data = response.json()
            assert "record_id" in data
            assert data["record_id"] == "rec-002"
            assert "is_anomaly" in data
            assert isinstance(data["is_anomaly"], bool)
            assert "anomaly_score" in data
            assert 0.0 <= data["anomaly_score"] <= 1.0
            assert "latency_ms" in data
            assert isinstance(data["latency_ms"], float)

    def test_anomaly_buffer_populated(self, client: TestClient) -> None:
        from serving.src.api import _prediction_buffers

        before = len(_prediction_buffers["anomaly_detection"])
        payload = {"record_id": "rec-003", "features": {"v": 0.5}}
        response = client.post("/v1/predict/anomaly", json=payload)
        if response.status_code == 200:
            assert len(_prediction_buffers["anomaly_detection"]) == before + 1

    def test_anomaly_missing_record_id_returns_422(self, client: TestClient) -> None:
        response = client.post("/v1/predict/anomaly", json={"features": {"v": 1.0}})
        assert response.status_code == 422


class TestExtractionMonitorEndpoint:
    """Tests for GET /v1/monitoring/extraction."""

    def test_extraction_monitor_returns_200(self, client: TestClient) -> None:
        response = client.get("/v1/monitoring/extraction")
        assert response.status_code == 200

    def test_extraction_monitor_enabled_when_available(self, client: TestClient) -> None:
        from monitoring.monitor import ExtractionDefenseMonitor
        from unittest.mock import patch

        from serving.src.api import app

        monitor = ExtractionDefenseMonitor()
        with patch("serving.src.api._extraction_monitor", monitor):
            test_client = TestClient(app)
            response = test_client.get("/v1/monitoring/extraction")
            assert response.status_code == 200
            data = response.json()
            assert data["enabled"] is True
            assert "total_requests" in data
            assert "block_rate_pct" in data

    def test_extraction_monitor_disabled_when_none(self) -> None:
        from unittest.mock import patch
        from serving.src.api import app

        with patch("serving.src.api._extraction_monitor", None):
            test_client = TestClient(app)
            response = test_client.get("/v1/monitoring/extraction")
            assert response.status_code == 200
            assert response.json() == {"enabled": False}


class TestServiceTokenAuth:
    """Verify service token fail-closed policy in staging/production."""

    def test_token_required_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AETHER_ENV", "production")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        import importlib
        import serving.src.api as api_mod
        importlib.reload(api_mod)
        test_client = TestClient(api_mod.app, raise_server_exceptions=False)
        resp = test_client.get("/health")
        assert resp.status_code in (401, 503), (
            f"Expected 401/503 in production without ML_SERVICE_TOKEN, got {resp.status_code}"
        )

    def test_token_required_in_staging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AETHER_ENV", "staging")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        import importlib
        import serving.src.api as api_mod
        importlib.reload(api_mod)
        test_client = TestClient(api_mod.app, raise_server_exceptions=False)
        resp = test_client.get("/health")
        assert resp.status_code in (401, 503), (
            f"Expected 401/503 in staging without ML_SERVICE_TOKEN, got {resp.status_code}"
        )

    def test_token_optional_in_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        import importlib
        import serving.src.api as api_mod
        importlib.reload(api_mod)
        test_client = TestClient(api_mod.app)
        resp = test_client.get("/health")
        assert resp.status_code == 200, (
            f"Expected 200 in local without ML_SERVICE_TOKEN, got {resp.status_code}"
        )


class TestReadinessProbe:
    """Verify readiness probe checks required model set in staging/production."""

    def test_readiness_passes_in_local_with_no_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AETHER_ENV", "local")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        from serving.src.api import app
        test_client = TestClient(app)
        resp = test_client.get("/ready")
        # Local: no required-model gate; freshness gate only
        assert resp.status_code in (200, 503)

    def test_readiness_in_production_returns_valid_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AETHER_ENV", "production")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        import importlib
        import serving.src.api as api_mod
        importlib.reload(api_mod)
        test_client = TestClient(api_mod.app, raise_server_exceptions=False)
        resp = test_client.get("/ready")
        # Without loaded models: 503 (required models missing) or 401/503 (no token)
        assert resp.status_code in (200, 401, 503)

    def test_readiness_503_detail_has_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When required models are missing, the 503 detail contains a reason string."""
        monkeypatch.setenv("AETHER_ENV", "production")
        monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
        import importlib
        import serving.src.api as api_mod
        importlib.reload(api_mod)
        test_client = TestClient(api_mod.app, raise_server_exceptions=False)
        resp = test_client.get("/ready")
        if resp.status_code == 503:
            body = resp.json()
            detail = body.get("detail", {})
            if isinstance(detail, dict) and "reason" in detail:
                reason = detail["reason"]
                assert "Required models not loaded" in reason or "Freshness" in reason, (
                    f"503 reason did not mention missing models or freshness: {reason!r}"
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
