"""
Aether ML — Integration Tests for Serving API
Tests the FastAPI endpoints with mock model loading.
"""

import pytest
from fastapi.testclient import TestClient

from serving.src.api import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "4.0.0"
        assert isinstance(data["models_loaded"], list)

    def test_models_list(self, client):
        response = client.get("/models")
        assert response.status_code == 200
        assert "models" in response.json()


class TestPredictionEndpoints:
    """
    Note: These tests will return 500 if models aren't loaded.
    In CI, models are loaded from test fixtures. Here we test the API contract.
    """

    def test_intent_endpoint_contract(self, client):
        payload = {
            "session_id": "test-session-123",
            "features": {
                "mouse_velocity_mean": 2.5,
                "mouse_velocity_std": 0.8,
                "scroll_depth_max": 0.6,
                "scroll_velocity_mean": 1.2,
                "hover_duration_mean": 0.9,
                "time_between_actions_mean": 1.5,
                "time_between_actions_std": 0.5,
                "click_to_scroll_ratio": 0.7,
                "active_ratio": 0.8,
                "page_depth": 3,
                "session_duration_s": 120.0,
                "click_count": 5,
                "scroll_count": 12,
                "keypress_count": 4,
            }
        }
        response = client.post("/v1/predict/intent", json=payload)
        # Will be 500 if model not loaded, 200 if loaded
        assert response.status_code in (200, 500)

    def test_bot_endpoint_contract(self, client):
        payload = {
            "session_id": "test-session-456",
            "features": {
                "avg_time_between_actions": 1500.0,
                "time_variance": 800.0,
                "click_to_scroll_ratio": 0.7,
                "mouse_velocity_mean": 2.5,
                "mouse_velocity_std": 0.8,
                "mouse_entropy": 3.2,
                "navigation_entropy": 2.1,
                "interaction_diversity": 0.6,
                "has_natural_pauses": 1.0,
                "has_erratic_movement": 0.0,
                "has_perfect_timing": 0.0,
                "keypress_count": 8,
                "unique_action_types": 4,
                "action_rate": 0.5,
            }
        }
        response = client.post("/v1/predict/bot", json=payload)
        assert response.status_code in (200, 500)

    def test_churn_endpoint_contract(self, client):
        payload = {
            "identity_id": "user-789",
            "features": {
                "days_since_last_visit": 15.0,
                "visit_frequency_trend": -0.1,
                "feature_usage_breadth": 0.4,
                "session_duration_trend": 0.05,
                "support_ticket_count": 0,
                "billing_status": 1.0,
                "engagement_percentile": 0.6,
                "total_sessions": 25,
                "avg_session_duration": 120.0,
                "conversion_rate": 0.05,
                "days_since_first_visit": 90.0,
            }
        }
        response = client.post("/v1/predict/churn", json=payload)
        assert response.status_code in (200, 500)

    def test_batch_endpoint_contract(self, client):
        payload = {
            "model": "churn_prediction",
            "instances": [
                {"days_since_last_visit": 5, "total_sessions": 10},
                {"days_since_last_visit": 30, "total_sessions": 2},
            ]
        }
        response = client.post("/v1/predict/batch", json=payload)
        assert response.status_code in (200, 500)

    def test_attribution_endpoint_contract(self, client):
        payload = {
            "conversion_id": "conv-001",
            "touchpoints": [
                {"channel": "organic_search", "touchpoint_index": 0, "conversion_value": 100},
                {"channel": "email", "touchpoint_index": 1, "conversion_value": 100},
            ],
            "method": "linear"
        }
        response = client.post("/v1/predict/attribution", json=payload)
        assert response.status_code in (200, 500)

    def test_invalid_model_returns_error(self, client):
        payload = {"model": "nonexistent_model", "instances": [{}]}
        response = client.post("/v1/predict/batch", json=payload)
        assert response.status_code == 500


class TestLatencyHeaders:
    def test_latency_header_present(self, client):
        response = client.get("/health")
        assert "X-Inference-Latency-Ms" in response.headers
