"""
Aether Backend — Load & Soak Testing (Locust)

Simulates realistic traffic patterns for:
  - GraphQL queries (high QPS, complexity rejection)
  - Analytics exports (idempotent burst + polling)
  - Agent tasks (burst creation + status polling)
  - Campaign touchpoints (write/read-after-write consistency)
  - Batch event ingest (/v1/ingest/events/batch — highest-volume production workload)
  - Identity resolution (/sdk/identity/resolve — critical latency SLA)
  - Profile360 (/v1/profile360/{entity_type}/{entity_id} — operator + tenant profile queries)
  - Kyber operator summary (deployment readiness, tenant list, SDK fleet health)

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host http://localhost:8000

Headless mode with thresholds:
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
           --headless -u 50 -r 10 --run-time 5m \
           --csv results/load-test

Staging signoff thresholds (see tests/load/thresholds.json for canonical values):
    p95 < 200ms for /v1/ingest/events/batch and /v1/analytics/graphql
    p95 < 300ms for /sdk/identity/resolve
    p95 < 500ms for /v1/profile360/{entity_type}/{entity_id} and analytics exports
    p99 < 1000ms for agent tasks
    Error rate < 1%
    Zero data loss on concurrent touchpoint writes
"""

from __future__ import annotations

import random
import string
import uuid

from locust import HttpUser, TaskSet, between, task

# =========================================================================
# Test Data Generators
# =========================================================================

def _random_string(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _api_headers(tenant_id: str = "load-test-tenant") -> dict:
    return {
        "X-API-Key": f"test-key-{tenant_id}",
        "Content-Type": "application/json",
        "X-Request-ID": str(uuid.uuid4()),
    }


# =========================================================================
# GraphQL Load Tests
# =========================================================================

class GraphQLTasks(TaskSet):
    """High-QPS GraphQL query workload."""

    headers = _api_headers()

    @task(10)
    def valid_events_query(self):
        """Standard events query — should always succeed."""
        self.client.post(
            "/v1/analytics/graphql",
            json={
                "query": "{ events { event_id event_type timestamp } }",
                "variables": {},
            },
            headers=self.headers,
            name="/v1/analytics/graphql [events]",
        )

    @task(5)
    def valid_campaigns_query(self):
        """Campaign query — exercises different resolver path."""
        self.client.post(
            "/v1/analytics/graphql",
            json={
                "query": "{ campaigns { campaign_id name channel } }",
                "variables": {"status": "active"},
            },
            headers=self.headers,
            name="/v1/analytics/graphql [campaigns]",
        )

    @task(2)
    def filtered_events_query(self):
        """Events with variable filters."""
        self.client.post(
            "/v1/analytics/graphql",
            json={
                "query": "{ events { event_id event_type user_id } }",
                "variables": {"event_type": "page_view"},
            },
            headers=self.headers,
            name="/v1/analytics/graphql [filtered]",
        )

    @task(1)
    def introspection_attempt(self):
        """Should be rejected — tests security enforcement at scale."""
        with self.client.post(
            "/v1/analytics/graphql",
            json={"query": "{ __schema { types { name } } }"},
            headers=self.headers,
            name="/v1/analytics/graphql [introspection-rejected]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400:
                resp.success()  # Expected rejection

    @task(1)
    def deep_query_attempt(self):
        """Should be rejected — depth limit enforcement."""
        deep = "{ events { event_id { a { b { c { d { e } } } } } } }"
        with self.client.post(
            "/v1/analytics/graphql",
            json={"query": deep},
            headers=self.headers,
            name="/v1/analytics/graphql [depth-rejected]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400:
                resp.success()


# =========================================================================
# Analytics Export Load Tests
# =========================================================================

class ExportTasks(TaskSet):
    """Idempotent export requests + polling."""

    headers = _api_headers()

    @task(5)
    def create_export(self):
        """Create a new export job."""
        resp = self.client.post(
            "/v1/analytics/export",
            json={"format": random.choice(["csv", "json", "parquet"])},
            headers=self.headers,
            name="/v1/analytics/export [create]",
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            export_id = data.get("export_id")
            if export_id:
                # Immediately poll the status
                self.client.get(
                    f"/v1/analytics/export/{export_id}",
                    headers=self.headers,
                    name="/v1/analytics/export/{id} [poll]",
                )

    @task(3)
    def idempotent_export(self):
        """Submit the same export twice — should return same job."""
        payload = {"format": "csv", "query": {"event_type": "page_view"}}
        self.client.post(
            "/v1/analytics/export",
            json=payload,
            headers=self.headers,
            name="/v1/analytics/export [idempotent-1]",
        )
        self.client.post(
            "/v1/analytics/export",
            json=payload,
            headers=self.headers,
            name="/v1/analytics/export [idempotent-2]",
        )

    @task(1)
    def poll_nonexistent(self):
        """Poll a non-existent export — should 404."""
        with self.client.get(
            f"/v1/analytics/export/nonexistent-{uuid.uuid4()}",
            headers=self.headers,
            name="/v1/analytics/export/{id} [404]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()


# =========================================================================
# Agent Task Load Tests
# =========================================================================

class AgentTaskTasks(TaskSet):
    """Burst task creation + status polling."""

    headers = _api_headers()
    worker_types = [
        "web_crawler", "api_scanner", "social_listener",
        "entity_resolver", "profile_enricher", "quality_scorer",
    ]
    created_task_ids: list[str] = []

    @task(8)
    def create_task(self):
        """Create a new agent task."""
        resp = self.client.post(
            "/v1/agent/tasks",
            json={
                "worker_type": random.choice(self.worker_types),
                "priority": random.choice(["high", "medium", "low"]),
                "payload": {"target": f"entity-{_random_string()}"},
            },
            headers=self.headers,
            name="/v1/agent/tasks [create]",
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            task_id = data.get("task_id")
            if task_id:
                self.created_task_ids.append(task_id)

    @task(5)
    def poll_task(self):
        """Poll a recently created task."""
        if self.created_task_ids:
            task_id = random.choice(self.created_task_ids[-20:])
            self.client.get(
                f"/v1/agent/tasks/{task_id}",
                headers=self.headers,
                name="/v1/agent/tasks/{id} [poll]",
            )

    @task(2)
    def get_audit(self):
        """Fetch audit trail."""
        self.client.get(
            "/v1/agent/audit?limit=20",
            headers=self.headers,
            name="/v1/agent/audit [list]",
        )

    @task(1)
    def invalid_worker_type(self):
        """Should be rejected — validation enforcement."""
        with self.client.post(
            "/v1/agent/tasks",
            json={"worker_type": "nonexistent_worker", "payload": {}},
            headers=self.headers,
            name="/v1/agent/tasks [invalid-rejected]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400:
                resp.success()


# =========================================================================
# Campaign Touchpoint Load Tests
# =========================================================================

# =========================================================================
# Batch Ingest Load Tests
# =========================================================================

class BatchIngestTasks(TaskSet):
    """Batch event ingest — the highest-volume production workload."""

    headers = _api_headers()
    _event_types = ("page_view", "click", "identify", "purchase", "wallet", "support_ticket")

    def _make_event(self) -> dict:
        return {
            "event_id": str(uuid.uuid4()),
            "event_type": random.choice(self._event_types),
            "user_id": f"user-{_random_string()}",
            "session_id": f"sess-{_random_string()}",
            "timestamp": "2026-01-01T00:00:00Z",
            "properties": {"load_test": True},
        }

    @task(10)
    def batch_ingest_small(self):
        """Small batch of 10 events — common high-frequency pattern."""
        self.client.post(
            "/v1/ingest/events/batch",
            json={"events": [self._make_event() for _ in range(10)]},
            headers=self.headers,
            name="/v1/ingest/events/batch [small-10]",
        )

    @task(5)
    def batch_ingest_medium(self):
        """Medium batch of 50 events — typical scheduled flush."""
        self.client.post(
            "/v1/ingest/events/batch",
            json={"events": [self._make_event() for _ in range(50)]},
            headers=self.headers,
            name="/v1/ingest/events/batch [medium-50]",
        )

    @task(3)
    def batch_ingest_feed(self):
        """Feed endpoint — alternative ingest path."""
        self.client.post(
            "/v1/ingest/feed",
            json={"events": [self._make_event() for _ in range(20)]},
            headers=self.headers,
            name="/v1/ingest/feed [feed-20]",
        )

    @task(2)
    def duplicate_event_handling(self):
        """Send the same event_id twice — should be idempotent (no 500)."""
        fixed_id = f"dedup-{_random_string()}"
        event = self._make_event()
        event["event_id"] = fixed_id
        payload = {"events": [event, {**event}]}  # identical duplicate
        with self.client.post(
            "/v1/ingest/events/batch",
            json=payload,
            headers=self.headers,
            name="/v1/ingest/events/batch [duplicate]",
            catch_response=True,
        ) as resp:
            # 200 or 409 are both acceptable; 500 is a failure
            if resp.status_code in (200, 409):
                resp.success()

    @task(1)
    def schema_validation_rejection(self):
        """Malformed payload — should be rejected with 400, not 500."""
        with self.client.post(
            "/v1/ingest/events/batch",
            json={"events": [{"bad_field": "no event_type or user_id"}]},
            headers=self.headers,
            name="/v1/ingest/events/batch [schema-rejected]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 400:
                resp.success()


# =========================================================================
# Identity Resolution Load Tests
# =========================================================================

class IdentityResolveTasks(TaskSet):
    """Identity resolution — critical latency SLA (p95 < 300ms)."""

    headers = _api_headers()

    def _anchor(self, kind: str) -> dict:
        return {"type": kind, "value": f"{kind}-{_random_string()}"}

    @task(8)
    def resolve_single_anchor(self):
        """Single-anchor resolve — most common call pattern."""
        self.client.post(
            "/sdk/identity/resolve",
            json={"anchors": [self._anchor("email")]},
            headers=self.headers,
            name="/sdk/identity/resolve [1-anchor]",
        )

    @task(5)
    def resolve_three_anchors(self):
        """Three-anchor merge — typical cross-device identity."""
        self.client.post(
            "/sdk/identity/resolve",
            json={
                "anchors": [
                    self._anchor("email"),
                    self._anchor("phone"),
                    self._anchor("cookie"),
                ]
            },
            headers=self.headers,
            name="/sdk/identity/resolve [3-anchors]",
        )

    @task(2)
    def resolve_five_anchors(self):
        """Five-anchor merge — heavy identity graph traversal."""
        self.client.post(
            "/sdk/identity/resolve",
            json={
                "anchors": [self._anchor(k) for k in ("email", "phone", "cookie", "device_id", "user_id")]
            },
            headers=self.headers,
            name="/sdk/identity/resolve [5-anchors]",
        )

    @task(3)
    def resolve_anonymous_to_known(self):
        """Anonymous → known resolution — SDK batch endpoint."""
        self.client.post(
            "/sdk/identity/resolve",
            json={
                "anonymous_id": f"anon-{_random_string()}",
                "user_id": f"known-{_random_string()}",
                "traits": {"email": f"{_random_string()}@example.com"},
            },
            headers=self.headers,
            name="/sdk/identity/resolve [anon-to-known]",
        )


# =========================================================================
# Profile360 Load Tests
# =========================================================================

class Profile360Tasks(TaskSet):
    """Profile360 — operator and tenant profile queries (p95 < 500ms)."""

    headers = _api_headers()
    _windows = ("7d", "30d", "90d", "180d")

    @task(8)
    def profile360_default(self):
        """Full surface — most common operator query."""
        user_id = f"user-{_random_string()}"
        self.client.get(
            f"/v1/profile360/user/{user_id}",
            headers=self.headers,
            name="/v1/profile360/user/{id} [default]",
        )

    @task(4)
    def profile360_identity_only(self):
        """Identity section only — tests lightweight include filter."""
        user_id = f"user-{_random_string()}"
        self.client.get(
            f"/v1/profile360/user/{user_id}?include=identity,system",
            headers=self.headers,
            name="/v1/profile360/user/{id} [identity-only]",
        )

    @task(2)
    def profile360_financial(self):
        """Financial + graph sections — heavier traversal load."""
        user_id = f"user-{_random_string()}"
        self.client.get(
            f"/v1/profile360/user/{user_id}?include=identity,financial,graph",
            headers=self.headers,
            name="/v1/profile360/user/{id} [financial+graph]",
        )

    @task(1)
    def profile360_nonexistent(self):
        """Unknown user — Profile360 returns 200 with status=unknown for missing identities."""
        with self.client.get(
            f"/v1/profile360/user/nonexistent-{uuid.uuid4()}",
            headers=self.headers,
            name="/v1/profile360/user/{id} [miss]",
            catch_response=True,
        ) as resp:
            # ProfileComposer falls back to {"status": "unknown"} on miss (HTTP 200),
            # not a 404, so both 200 and 404 are valid non-error responses.
            if resp.status_code in (200, 404):
                resp.success()


# =========================================================================
# Kyber Operator Summary Load Tests
# =========================================================================

class KyberSummaryTasks(TaskSet):
    """Kyber operator summary endpoints — internal use, admin API."""

    headers = _api_headers(tenant_id="kyber-operator")

    @task(5)
    def deployment_readiness(self):
        """Deployment readiness — top-level Kyber operator readiness check."""
        self.client.get(
            "/v1/admin/kyber/deployment-readiness",
            headers=self.headers,
            name="/v1/admin/kyber/deployment-readiness",
        )

    @task(4)
    def tenant_list(self):
        """Tenant list — operator visibility into active tenants."""
        self.client.get(
            "/v1/admin/tenants?limit=50",
            headers=self.headers,
            name="/v1/admin/tenants [list]",
        )

    @task(3)
    def sdk_fleet_health(self):
        """SDK fleet health — operator SDK heartbeat aggregation."""
        self.client.get(
            "/v1/diagnostics/sdk/fleet",
            headers=self.headers,
            name="/v1/diagnostics/sdk/fleet",
        )

    @task(2)
    def tenant_detail(self):
        """Single tenant detail — drilldown from operator view."""
        tenant_id = f"tenant-{random.randint(1, 100)}"
        self.client.get(
            f"/v1/admin/tenants/{tenant_id}",
            headers=self.headers,
            name="/v1/admin/tenants/{id} [detail]",
        )

    @task(1)
    def diagnostics_report(self):
        """Diagnostics report — backend health and circuit-breaker status."""
        self.client.get(
            "/v1/diagnostics/report",
            headers=self.headers,
            name="/v1/diagnostics/report",
        )


# =========================================================================
# Campaign Touchpoint Load Tests
# =========================================================================

class CampaignTasks(TaskSet):
    """Write/read-after-write consistency for campaign touchpoints."""

    headers = _api_headers()

    def on_start(self):
        """Create a test campaign to write touchpoints to."""
        self.campaign_id = None
        resp = self.client.post(
            "/v1/campaigns",
            json={
                "name": f"Load Test Campaign {_random_string()}",
                "channel": "email",
                "start_date": "2025-01-01",
            },
            headers=self.headers,
            name="/v1/campaigns [create-setup]",
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            self.campaign_id = data.get("id")

    @task(8)
    def write_touchpoint(self):
        """Record a touchpoint."""
        if not self.campaign_id:
            return
        self.client.post(
            f"/v1/campaigns/{self.campaign_id}/touchpoints",
            json={
                "channel": random.choice(["email", "social", "direct"]),
                "event_type": random.choice(["view", "click", "purchase"]),
                "is_conversion": random.random() < 0.1,
                "revenue_usd": round(random.uniform(0, 100), 2) if random.random() < 0.1 else 0,
                "user_id": f"user-{random.randint(1, 100)}",
            },
            headers=self.headers,
            name="/v1/campaigns/{id}/touchpoints [write]",
        )

    @task(3)
    def read_attribution(self):
        """Read attribution after writes — consistency check."""
        if not self.campaign_id:
            return
        self.client.get(
            f"/v1/campaigns/{self.campaign_id}/attribution?model=linear",
            headers=self.headers,
            name="/v1/campaigns/{id}/attribution [read]",
        )


# =========================================================================
# User Profiles
# =========================================================================

class SteadyStateUser(HttpUser):
    """Normal production traffic — mixed workload across all subsystems."""
    tasks = {
        GraphQLTasks: 4,
        ExportTasks: 2,
        AgentTaskTasks: 2,
        CampaignTasks: 2,
        BatchIngestTasks: 4,
        IdentityResolveTasks: 3,
        Profile360Tasks: 2,
        FraudEvaluationTasks: 2,
    }
    wait_time = between(0.5, 2.0)


class BurstUser(HttpUser):
    """Burst traffic — hammers agent tasks, GraphQL, and batch ingest."""
    tasks = {
        GraphQLTasks: 6,
        AgentTaskTasks: 4,
        BatchIngestTasks: 6,
    }
    wait_time = between(0.1, 0.5)


class ExportHeavyUser(HttpUser):
    """Export-heavy workload — tests idempotency under load."""
    tasks = {ExportTasks: 1}
    wait_time = between(0.2, 1.0)


class IngestHeavyUser(HttpUser):
    """Ingest-dominated workload — models SDK batch flush pattern."""
    tasks = {
        BatchIngestTasks: 8,
        IdentityResolveTasks: 2,
    }
    wait_time = between(0.05, 0.3)


class OperatorUser(HttpUser):
    """Operator dashboard — Kyber summaries and Profile360."""
    tasks = {
        KyberSummaryTasks: 5,
        Profile360Tasks: 3,
    }
    wait_time = between(1.0, 3.0)


# =========================================================================
# Fraud Evaluation Load Tests
# =========================================================================

class FraudEvaluationTasks(TaskSet):
    """Fraud evaluation pipeline — real-time and batch evaluation + decision CRUD.

    Thresholds (from tests/load/thresholds.json):
      POST /v1/fraud/evaluate        p95 < 500 ms
      POST /v1/fraud/evaluate/batch  p99 < 2000 ms
      GET  /v1/fraud/decisions       p95 < 200 ms
      GET  /v1/fraud/stats           p95 < 100 ms
    """

    headers = _api_headers()
    _subject_types = ("entity", "profile", "cluster")
    _event_types = ("page_view", "purchase", "wallet_transfer", "refund", "agent_execution")

    def _make_event(self) -> dict:
        return {
            "event_type": random.choice(self._event_types),
            "user_id": f"user-{_random_string()}",
            "session_id": f"sess-{_random_string()}",
            "timestamp": "2026-01-01T00:00:00Z",
            "properties": {
                "device_id": f"dev-{_random_string(4)}",
                "ip": f"10.{random.randint(0,255)}.{random.randint(0,255)}.1",
                "load_test": True,
            },
        }

    @task(10)
    def evaluate_single(self):
        """Single-event fraud evaluation — real-time path (p95 < 500 ms)."""
        self.client.post(
            "/v1/fraud/evaluate",
            json={
                "event": self._make_event(),
                "context": {
                    "subject_type": random.choice(self._subject_types),
                    "subject_id": f"subj-{_random_string()}",
                },
            },
            headers=self.headers,
            name="/v1/fraud/evaluate [single]",
        )

    @task(4)
    def evaluate_batch_small(self):
        """Batch of 5 events — scheduled flush pattern (p99 < 2000 ms)."""
        self.client.post(
            "/v1/fraud/evaluate/batch",
            json={"events": [
                {"event": self._make_event(), "context": {}}
                for _ in range(5)
            ]},
            headers=self.headers,
            name="/v1/fraud/evaluate/batch [5]",
        )

    @task(2)
    def evaluate_batch_medium(self):
        """Batch of 20 events — operator replay pattern."""
        self.client.post(
            "/v1/fraud/evaluate/batch",
            json={"events": [
                {"event": self._make_event(), "context": {}}
                for _ in range(20)
            ]},
            headers=self.headers,
            name="/v1/fraud/evaluate/batch [20]",
        )

    @task(6)
    def list_decisions(self):
        """List durable fraud decisions — monitoring path (p95 < 200 ms)."""
        filters: dict[str, str] = {}
        if random.random() < 0.4:
            filters["risk_tier"] = random.choice(["critical", "high", "elevated", "low"])
        if random.random() < 0.3:
            filters["decision"] = random.choice(["block", "flag", "monitor", "clear"])
        if random.random() < 0.2:
            filters["review_state"] = random.choice(["required", "confirmed_fraud", "dispute"])
        qs = "&".join(f"{k}={v}" for k, v in filters.items())
        url = f"/v1/fraud/decisions?limit=25{'&' + qs if qs else ''}"
        self.client.get(url, headers=self.headers, name="/v1/fraud/decisions [list]")

    @task(3)
    def get_stats(self):
        """Fraud detection stats — operator dashboard (p95 < 100 ms)."""
        self.client.get(
            "/v1/fraud/stats",
            headers=self.headers,
            name="/v1/fraud/stats",
        )

    @task(2)
    def get_config(self):
        """Fraud engine config — infrequent read."""
        self.client.get(
            "/v1/fraud/config",
            headers=self.headers,
            name="/v1/fraud/config",
        )

    @task(1)
    def evaluate_exceeds_batch_limit(self):
        """101-event batch — should be rejected with 422, not 500."""
        with self.client.post(
            "/v1/fraud/evaluate/batch",
            json={"events": [{"event": self._make_event(), "context": {}} for _ in range(101)]},
            headers=self.headers,
            name="/v1/fraud/evaluate/batch [over-limit-rejected]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (400, 422):
                resp.success()


class FraudHeavyUser(HttpUser):
    """Fraud-dominated workload — models a fraud analyst or automated scoring pipeline."""
    tasks = {FraudEvaluationTasks: 1}
    wait_time = between(0.2, 1.0)


class FraudBurstUser(HttpUser):
    """Burst fraud evaluation — models a spike from activity ingestion fan-out."""
    tasks = {FraudEvaluationTasks: 1}
    wait_time = between(0.05, 0.2)
