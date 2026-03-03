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
        assert exc_info.value.status_code == 503

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


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
