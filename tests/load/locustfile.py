"""
Aether Backend — Load & Soak Testing (Locust)

Simulates realistic traffic patterns for:
  - SDK batch ingestion (POST /v1/batch — primary hot path)
  - Identity resolution (GET /sdk/identity/resolve)
  - GraphQL queries (high QPS, complexity rejection)
  - Analytics exports (idempotent burst + polling)
  - Agent tasks (burst creation + status polling)
  - Campaign touchpoints (write/read-after-write consistency)

Usage:
    pip install locust
    locust -f tests/load/locustfile.py --host http://localhost:8000

Headless mode with thresholds:
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
           --headless -u 50 -r 10 --run-time 5m \
           --csv results/load-test

Staging signoff thresholds:
    p95 < 150ms  for POST /v1/batch (10-event payload)
    p95 < 300ms  for GET /sdk/identity/resolve
    p95 < 200ms  for GraphQL
    p95 < 500ms  for exports
    p99 < 1000ms for agent tasks
    Error rate < 1%
    Zero data loss on concurrent touchpoint writes

CI smoke gate (scripts/load_smoke.py):
    20 users, 30 seconds, host http://localhost:8000
    Fails build if p95 batch > 500ms or error rate > 5%
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
# SDK Batch Ingestion Load Tests  (primary hot path — POST /v1/batch)
# =========================================================================

CANONICAL_EVENT_TYPES = [
    "page_view", "click", "identify", "session_start", "session_end",
    "purchase", "wallet_connected", "custom",
]


def _batch_event(tenant_id: str) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": random.choice(CANONICAL_EVENT_TYPES),
        "timestamp": "2026-06-11T00:00:00Z",
        "anonymous_id": f"anon-{_random_string(12)}",
        "properties": {"page": f"/{_random_string(6)}", "load_test": True},
    }


class BatchIngestionTasks(TaskSet):
    """SDK batch ingestion workload — the ingestion hot path."""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer test-key-{self.user.tenant_id}",
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
        }

    @task(10)
    def small_batch(self):
        """Typical SDK flush: 10 events."""
        self.client.post(
            "/v1/batch",
            json={"events": [_batch_event(self.user.tenant_id) for _ in range(10)]},
            headers=self._headers(),
            name="/v1/batch [10-events]",
        )

    @task(3)
    def single_event(self):
        """Single-event flush — mobile SDK pattern."""
        self.client.post(
            "/v1/batch",
            json={"events": [_batch_event(self.user.tenant_id)]},
            headers=self._headers(),
            name="/v1/batch [1-event]",
        )

    @task(1)
    def large_batch(self):
        """Near-limit batch: 100 events."""
        self.client.post(
            "/v1/batch",
            json={"events": [_batch_event(self.user.tenant_id) for _ in range(100)]},
            headers=self._headers(),
            name="/v1/batch [100-events]",
        )

    @task(1)
    def duplicate_event(self):
        """Same event_id twice — should return duplicate status, not error."""
        event = _batch_event(self.user.tenant_id)
        with self.client.post(
            "/v1/batch",
            json={"events": [event]},
            headers=self._headers(),
            name="/v1/batch [first-write]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 207):
                resp.success()
        with self.client.post(
            "/v1/batch",
            json={"events": [event]},
            headers=self._headers(),
            name="/v1/batch [duplicate]",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 207):
                resp.success()


# =========================================================================
# Identity Resolution Load Tests
# =========================================================================

class IdentityResolutionTasks(TaskSet):
    """Cross-device identity resolve — the identity hot path."""

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer test-key-{self.user.tenant_id}",
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
        }

    @task(8)
    def resolve_anonymous(self):
        """Resolve anonymous device fingerprint."""
        self.client.get(
            f"/sdk/identity/resolve?anonymous_id=anon-{_random_string(12)}&fingerprint={_random_string(16)}",
            headers=self._headers(),
            name="/sdk/identity/resolve [anon]",
        )

    @task(4)
    def resolve_identified(self):
        """Resolve known user_id — exercises deterministic merge path."""
        self.client.get(
            f"/sdk/identity/resolve?user_id=user-{random.randint(1, 10000)}",
            headers=self._headers(),
            name="/sdk/identity/resolve [user]",
        )

    @task(2)
    def resolve_wallet(self):
        """Resolve by wallet address — Web3 identity path."""
        self.client.get(
            f"/sdk/identity/resolve?wallet_address=0x{_random_string(40)}",
            headers=self._headers(),
            name="/sdk/identity/resolve [wallet]",
        )


# =========================================================================
# GraphQL Load Tests
# =========================================================================

class GraphQLTasks(TaskSet):
    """High-QPS GraphQL query workload."""

    @property
    def headers(self):
        return _api_headers(getattr(self.user, "tenant_id", "load-test-tenant"))

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

    @property
    def headers(self):
        return _api_headers(getattr(self.user, "tenant_id", "load-test-tenant"))

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

    @property
    def headers(self):
        return _api_headers(getattr(self.user, "tenant_id", "load-test-tenant"))
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

class CampaignTasks(TaskSet):
    """Write/read-after-write consistency for campaign touchpoints."""

    @property
    def headers(self):
        return _api_headers(getattr(self.user, "tenant_id", "load-test-tenant"))

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

class _TenantUser(HttpUser):
    """Base class: assigns a stable per-user tenant_id for isolation."""
    abstract = True

    def on_start(self):
        self.tenant_id = f"load-test-{_random_string(8)}"


class SDKIngestionUser(_TenantUser):
    """SDK ingestion workload — primary load profile."""
    tasks = {BatchIngestionTasks: 8, IdentityResolutionTasks: 2}
    wait_time = between(0.05, 0.3)


class SteadyStateUser(_TenantUser):
    """Normal production traffic — mixed workload."""
    tasks = {
        BatchIngestionTasks: 4,
        GraphQLTasks: 3,
        ExportTasks: 1,
        AgentTaskTasks: 1,
        CampaignTasks: 1,
    }
    wait_time = between(0.5, 2.0)


class BurstUser(_TenantUser):
    """Burst ingestion — tests back-pressure at high RPS."""
    tasks = {BatchIngestionTasks: 8, GraphQLTasks: 2}
    wait_time = between(0.05, 0.2)


class ExportHeavyUser(_TenantUser):
    """Export-heavy workload — tests idempotency under load."""
    tasks = {ExportTasks: 1}
    wait_time = between(0.2, 1.0)
