"""
Minimal Locust load test for Aether ML serving.

Usage:
    locust -f locustfile.py --headless -u 10 -r 2 --run-time 30s --host http://localhost:8000
"""
from locust import HttpUser, task, between


class MLServingUser(HttpUser):
    wait_time = between(0.05, 0.2)

    @task(3)
    def health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def ready(self):
        self.client.get("/ready", name="/ready")

    @task(5)
    def session_score(self):
        payload = {
            "entity_id": "load-test-entity",
            "features": {
                "page_count": 5,
                "event_count": 20,
                "session_duration_s": 180.0,
                "max_scroll_depth": 0.6,
                "form_interaction_count": 1,
                "is_return_visit": True,
                "referral_source_score": 0.5,
                "click_count": 12,
                "active_ratio": 0.7,
            },
        }
        with self.client.post(
            "/v1/predict/session-score",
            json=payload,
            name="/v1/predict/session-score",
            catch_response=True,
        ) as resp:
            if resp.status_code not in (200, 401, 503):
                resp.failure(f"Unexpected status {resp.status_code}")
