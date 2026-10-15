"""Reads keyed by a caller-supplied id stay inside the caller's tenant.

Each test drives the real router through ``TestClient``: ``own_tenant`` writes a
row, ``other_tenant`` asks for it by id and gets a 404 or an empty result, and
``own_tenant`` still reads its own data. Both callers are plain viewers, so no
route passes because of an admin bypass.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("AETHER_CREDENTIAL_BACKEND", "in_memory")

import pytest  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.auth.auth import Role, TenantContext  # noqa: E402
from shared.decorators import register_error_handlers  # noqa: E402

OWN = "own_tenant"
OTHER = "other_tenant"
PERMS = [
    "read", "write", "commerce:read", "commerce:write",
    "agent:manage", "notifications:approve",
]


def _client(*routers, overrides=None) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.middleware("http")
    async def _inject_tenant(request: Request, call_next):
        request.state.tenant = TenantContext(
            tenant_id=request.headers["x-test-tenant"],
            user_id=request.headers.get("x-test-user", "user-1"),
            role=Role.VIEWER,
            permissions=PERMS,
        )
        request.state.request_id = "req"
        return await call_next(request)

    for router in routers:
        app.include_router(router)
    for dep, impl in (overrides or {}).items():
        app.dependency_overrides[dep] = impl
    return TestClient(app, raise_server_exceptions=False)


def _as(tenant: str, user: str = "user-1") -> dict:
    return {"x-test-tenant": tenant, "x-test-user": user, "X-API-Key": f"key-{tenant}"}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _connected_graph():
    from shared.graph.graph import GraphClient

    graph = GraphClient()
    _run(graph.connect())
    return graph


# ── expectations ─────────────────────────────────────────────────────────────


def test_expectation_signals_stay_in_owning_tenant():
    from intelligence.expectations import routes
    from intelligence.expectations.engine import signal_repo
    from intelligence.expectations.models import (
        BaselineSource, SignalSeverity, SignalType, make_signal_record,
    )

    signal = make_signal_record(
        entity_id="0xwallet", entity_type="wallet",
        signal_type=SignalType.IDENTITY_CONTRADICTION, severity=SignalSeverity.HIGH,
        expected="x", observed="own-observation", baseline_source=BaselineSource.SOURCE_NORM,
        confidence=0.7, explanation="own-only", tenant_id=OWN, population_id="pop-own",
    )
    _run(signal_repo.insert(signal["id"], signal))
    c = _client(routes.router)

    assert c.get(f"/v1/expectations/signal/{signal['id']}", headers=_as(OTHER)).status_code == 404
    assert c.get("/v1/expectations/entity/0xwallet/signals", headers=_as(OTHER)).json()["data"]["count"] == 0
    assert c.get("/v1/expectations/group/pop-own", headers=_as(OTHER)).json()["data"]["total_signals"] == 0
    explain = c.get("/v1/expectations/entity/0xwallet/explain", headers=_as(OTHER)).json()["data"]
    assert "own-observation" not in str(explain)

    assert c.get(f"/v1/expectations/signal/{signal['id']}", headers=_as(OWN)).status_code == 200
    assert c.get("/v1/expectations/entity/0xwallet/signals", headers=_as(OWN)).json()["data"]["count"] == 1
    assert c.get("/v1/expectations/group/pop-own", headers=_as(OWN)).json()["data"]["total_signals"] == 1


# ── behavioral ───────────────────────────────────────────────────────────────


def test_behavioral_signals_stay_in_owning_tenant():
    from intelligence.behavioral import routes
    from intelligence.behavioral.engines import signal_repo

    _run(signal_repo.insert("bs-1", {
        "id": "bs-1", "entity_id": "0xwallet", "tenant_id": OWN,
        "signal_family": "friction", "created_at": "2026-10-01T00:00:00+00:00",
    }))
    c = _client(routes.router)

    assert c.get("/v1/behavioral/entity/0xwallet/signals", headers=_as(OTHER)).json()["data"]["count"] == 0
    assert c.get("/v1/behavioral/entity/0xwallet/signals", headers=_as(OWN)).json()["data"]["count"] == 1


# ── RWA ──────────────────────────────────────────────────────────────────────


def test_rwa_asset_reads_and_writes_stay_in_owning_tenant():
    from graph.rwa import routes

    c = _client(routes.router)
    asset_id = c.post("/v1/rwa/assets", headers=_as(OWN), json={
        "name": "own bond", "asset_class": "private_credit", "total_supply": 1000,
    }).json()["data"]["id"]
    assert c.post("/v1/rwa/policies", headers=_as(OWN), json={
        "asset_id": asset_id, "policy_type": "whitelist", "rules": {"allowed_addresses": ["0xa"]},
    }).status_code == 200
    assert c.post("/v1/rwa/cashflows", headers=_as(OWN), json={
        "asset_id": asset_id, "cashflow_type": "redemption", "amount": 100,
    }).status_code == 200
    assert c.post("/v1/rwa/holders", headers=_as(OWN), json={
        "asset_id": asset_id, "entity_id": "0xholder", "amount": 500,
    }).status_code == 200

    assert c.get(f"/v1/rwa/assets/{asset_id}", headers=_as(OTHER)).status_code == 404
    for suffix in ("policies", "cashflows", "holders", "reserve-credibility", "redemption-pressure"):
        assert c.get(f"/v1/rwa/assets/{asset_id}/{suffix}", headers=_as(OTHER)).status_code == 404, suffix
    sim = c.post("/v1/rwa/simulate-transfer", headers=_as(OTHER), json={
        "asset_id": asset_id, "from_entity": "0xa", "to_entity": "0xz", "amount": 1,
    })
    assert sim.status_code == 404
    exposure = c.get("/v1/rwa/exposure/0xholder", headers=_as(OTHER)).json()["data"]
    assert exposure["holding_count"] == 0

    for path, body in (
        ("/v1/rwa/policies", {"asset_id": asset_id, "policy_type": "lockup", "rules": {}}),
        ("/v1/rwa/cashflows", {"asset_id": asset_id, "cashflow_type": "redemption", "amount": 1}),
        ("/v1/rwa/holders", {"asset_id": asset_id, "entity_id": "0xother", "amount": 1}),
    ):
        assert c.post(path, headers=_as(OTHER), json=body).status_code == 404, path

    assert c.get(f"/v1/rwa/assets/{asset_id}", headers=_as(OWN)).status_code == 200
    assert c.get(f"/v1/rwa/assets/{asset_id}/policies", headers=_as(OWN)).json()["data"]["count"] == 1
    assert c.get(f"/v1/rwa/assets/{asset_id}/cashflows", headers=_as(OWN)).json()["data"]["count"] == 1
    assert c.get(f"/v1/rwa/assets/{asset_id}/holders", headers=_as(OWN)).json()["data"]["count"] == 1
    pressure = c.get(f"/v1/rwa/assets/{asset_id}/redemption-pressure", headers=_as(OWN)).json()["data"]
    assert pressure["redemption_count"] == 1 and pressure["total_supply"] == 1000
    assert c.get("/v1/rwa/exposure/0xholder", headers=_as(OWN)).json()["data"]["holding_count"] == 1


# ── population ───────────────────────────────────────────────────────────────


def test_population_members_stay_in_owning_tenant():
    from identity.population import routes
    from identity.population.models import make_membership_record

    c = _client(routes.router)
    pid = c.post("/v1/population/groups", headers=_as(OWN), json={
        "name": "own segment", "population_type": "segment",
    }).json()["data"]["id"]
    member = make_membership_record(pid, "member@own.example", tenant_id=OWN)
    _run(routes.membership_repo.insert(member["id"], member))

    assert c.get(f"/v1/population/groups/{pid}/members", headers=_as(OTHER)).status_code == 404
    assert c.get(f"/v1/population/groups/{pid}/members", headers=_as(OWN)).json()["data"]["count"] == 1


# ── commerce ─────────────────────────────────────────────────────────────────


def test_commerce_spend_and_fee_report_stay_in_owning_tenant():
    from value.commerce import routes

    routes._service._payments.clear()
    c = _client(routes.router)
    assert c.post("/v1/commerce/payments", headers=_as(OWN), json={
        "payer_id": "agent-1", "payer_type": "agent", "payee_id": "merchant",
        "payee_type": "service", "amount": 42.0, "method": "usdc",
    }).status_code == 200

    other_spend = c.get("/v1/commerce/agent/agent-1/spend", headers=_as(OTHER)).json()["data"]
    assert other_spend["transaction_count"] == 0 and other_spend["payments"] == []
    assert c.get("/v1/commerce/fees/report", headers=_as(OTHER)).json()["data"]["total_transactions"] == 0

    assert c.get("/v1/commerce/agent/agent-1/spend", headers=_as(OWN)).json()["data"]["transaction_count"] == 1
    assert c.get("/v1/commerce/fees/report", headers=_as(OWN)).json()["data"]["total_transactions"] == 1


# ── PnL ──────────────────────────────────────────────────────────────────────


class _RecordingClickHouse:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def query(self, sql, params=None, **_kw):
        self.calls.append((sql, dict(params or {})))
        return []


class _NoProviders:
    class registry:
        @staticmethod
        def get(_name):
            return None


def test_pnl_reads_only_the_owning_tenants_wallets():
    from dependencies.providers import get_clickhouse, get_provider_gateway
    from repositories.repos import EntityRepository, WalletRepository
    from value.pnl import routes

    _run(EntityRepository().create_entity("entity-1", OWN, "human"))
    _run(WalletRepository().link_wallet("w-own", "entity-1", OWN, "eth", "0xown"))
    _run(WalletRepository().link_wallet("w-other", "entity-1", OTHER, "eth", "0xother"))
    ch = _RecordingClickHouse()
    c = _client(routes.router, overrides={
        get_clickhouse: lambda: ch, get_provider_gateway: lambda: _NoProviders(),
    })

    assert c.get("/v1/profile/entity-1/pnl?window=lifetime", headers=_as("third_tenant")).status_code == 404
    assert ch.calls == []

    assert c.get("/v1/profile/entity-1/pnl?window=lifetime", headers=_as(OWN)).status_code == 200
    tx_calls = [(sql, p) for sql, p in ch.calls if "silver_web3_events" in sql]
    assert len(tx_calls) == 1
    sql, params = tx_calls[0]
    assert "FROM wallets" not in sql
    assert list(params["addresses"]) == ["0xown"]
    tvl = [p for s, p in ch.calls if "gold_web3_daily_metrics" in s]
    assert tvl and all(p["tenant_id"] == OWN for p in tvl)


# ── wallet risk features ─────────────────────────────────────────────────────


def test_wallet_risk_features_are_tenant_scoped():
    from intelligence.intelligence import routes
    from repositories.lake import gold_identity, silver_onchain, silver_social

    _run(silver_onchain.upsert_record(
        entity_id="0xabc", entity_type="wallet", source="src", source_tag="t",
        normalized={"protocol": "own-protocol"}, tenant_id=OWN,
    ))
    _run(silver_social.upsert_record(
        entity_id="0xabc", entity_type="wallet", source="src", source_tag="t",
        normalized={"handle": "@own"}, tenant_id=OWN,
    ))
    c = _client(routes.router)

    other = c.get("/v1/intelligence/wallet/0xabc/risk", headers=_as(OTHER)).json()["data"]["features"]
    assert other["tx_count"] == 0 and other["has_social_link"] is False
    gold_rows = _run(gold_identity.get_metrics(
        "0xabc", entity_type="wallet", metric_name="wallet_features", tenant_id="third_tenant",
    ))
    assert gold_rows == []

    own = c.get("/v1/intelligence/wallet/0xabc/risk", headers=_as(OWN)).json()["data"]["features"]
    assert own["tx_count"] == 1 and own["has_social_link"] is True


# ── analytics automation ─────────────────────────────────────────────────────


def test_automation_metrics_are_keyed_by_tenant():
    from intelligence.analytics_automation import routes

    routes._pipelines.clear()
    c = _client(routes.router)
    assert c.post("/v1/automation/ingest", headers=_as(OWN), json={
        "type": "purchase", "campaign_id": "default", "wallet_address": "0xuser",
        "properties": {"amount": 99},
    }).status_code == 200

    assert c.get("/v1/automation/metrics/default", headers=_as(OTHER)).json()["total_events"] == 0
    assert c.get("/v1/automation/overview", headers=_as(OTHER)).json()["total_events"] == 0

    assert c.get("/v1/automation/metrics/default", headers=_as(OWN)).json()["total_events"] == 1
    assert c.get("/v1/automation/overview", headers=_as(OWN)).json()["total_events"] == 1


# ── agent graph / trust ──────────────────────────────────────────────────────


def test_agent_graph_and_trust_require_an_agent_in_the_callers_tenant(monkeypatch):
    from actions.agent import routes
    from config.settings import settings
    from shared.graph.graph import Edge, EdgeType, Vertex, VertexType

    monkeypatch.setattr(settings, "intelligence_graph", dataclasses.replace(
        settings.intelligence_graph, enable_agent_layer=True, enable_trust_scoring=True,
    ))
    graph = _connected_graph()
    monkeypatch.setattr(routes, "_graph", graph)
    _run(graph.add_vertex(Vertex(VertexType.AGENT, "agent-own", {"tenantId": OWN})))
    _run(graph.add_vertex(Vertex(VertexType.SERVICE, "svc-own", {"tenantId": OWN, "secret": "own"})))
    _run(graph.add_vertex(Vertex(VertexType.SERVICE, "svc-other", {"tenantId": OTHER})))
    _run(graph.add_vertex(Vertex(VertexType.SERVICE, "svc-unowned", {})))
    for target in ("svc-own", "svc-other", "svc-unowned"):
        _run(graph.add_edge(Edge(EdgeType.CONSUMES, "agent-own", target, {"tenant_id": OWN})))
    c = _client(routes.router)

    assert c.get("/v1/agent/agent-own/graph", headers=_as(OTHER)).status_code == 404
    assert c.get("/v1/agent/agent-own/graph?layer=A2A", headers=_as(OTHER)).status_code == 404
    assert c.get("/v1/agent/agent-own/trust", headers=_as(OTHER)).status_code == 404

    for layer in ("all", "A2A"):
        data = c.get(f"/v1/agent/agent-own/graph?layer={layer}", headers=_as(OWN)).json()["data"]
        assert {v["id"] for v in data["vertices"]} == {"svc-own"}, layer
    assert c.get("/v1/agent/agent-own/trust", headers=_as(OWN)).status_code == 200


# ── operational graph ────────────────────────────────────────────────────────


def test_graph_anchor_vertices_are_fetched_within_the_tenant():
    from dependencies.providers import get_graph
    from graph.operational_intelligence import routes
    from shared.graph.graph import Vertex, VertexType

    graph = _connected_graph()
    _run(graph.add_vertex(Vertex(VertexType.USER, "user-own", {"tenantId": OWN, "secret": "own-only"})))
    c = _client(routes.router, overrides={get_graph: lambda: graph})
    ref = {"kind": "user", "id": "user-own"}

    responses = [
        c.post("/v1/graph/traverse", headers=_as(OTHER), json={"tenantId": OTHER, "start": ref, "depth": 1}),
        c.post("/v1/graph/path", headers=_as(OTHER), json={"tenantId": OTHER, "from": ref, "to": ref}),
        c.post("/v1/graph/temporal", headers=_as(OTHER), json={
            "tenantId": OTHER, "anchor": ref, "asOf": "2999-01-01T00:00:00Z",
        }),
    ]
    for resp in responses:
        assert resp.status_code == 200, resp.text
        assert "own-only" not in resp.text

    own = c.post("/v1/graph/traverse", headers=_as(OWN), json={"tenantId": OWN, "start": ref, "depth": 1})
    assert "own-only" in own.text


# ── identity profile graph ───────────────────────────────────────────────────


def test_profile_graph_lists_only_the_tenants_neighbours():
    from dependencies.providers import get_cache, get_graph
    from identity.identity import routes
    from repositories.repos import IdentityRepository
    from shared.cache.cache import CacheClient
    from shared.graph.graph import Edge, EdgeType, Vertex, VertexType

    graph = _connected_graph()
    cache = CacheClient()
    _run(IdentityRepository(graph, cache).upsert_profile(OWN, "user-own", {"name": "own"}))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "0xown", {"tenantId": OWN})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "0xother", {"tenantId": OTHER})))
    _run(graph.add_vertex(Vertex(VertexType.WALLET, "0xunowned", {})))
    for target in ("0xown", "0xother", "0xunowned"):
        _run(graph.add_edge(Edge(EdgeType.OWNS_WALLET, "user-own", target, {"tenant_id": OWN})))
    c = _client(routes.router, overrides={get_graph: lambda: graph, get_cache: lambda: cache})

    assert c.get("/v1/identity/profiles/user-own/graph", headers=_as(OTHER)).status_code == 404
    data = c.get("/v1/identity/profiles/user-own/graph", headers=_as(OWN)).json()["data"]
    assert {conn["id"] for conn in data["connections"]} == {"0xown"}


# ── notification escalation ──────────────────────────────────────────────────


def test_notification_escalate_requires_ownership():
    from journeys.notification_intelligence import routes

    _run(routes._notif_repo.create({
        "id": "n-own", "tenant_id": OWN, "lifecycle_state": "queued",
        "detected_at": "2026-10-01T00:00:00+00:00",
    }))
    c = _client(routes.router)

    resp = c.patch(f"/v1/notifications/intelligence/n-own/escalate?tenantId={OTHER}", headers=_as(OTHER))
    assert resp.status_code == 404
    assert _run(routes._notif_repo.find_by_id("n-own"))["lifecycle_state"] == "queued"

    resp = c.patch(f"/v1/notifications/intelligence/n-own/escalate?tenantId={OWN}", headers=_as(OWN))
    assert resp.status_code == 200
    assert _run(routes._notif_repo.find_by_id("n-own"))["lifecycle_state"] == "operator_review"


# ── Noesis conversations ─────────────────────────────────────────────────────


def test_noesis_conversations_belong_to_tenant_and_user(monkeypatch):
    from intelligence.noesis import conversation, routes
    from shared.cache.cache import CacheClient

    store = conversation.NoesisConversationStore(CacheClient())
    monkeypatch.setattr(conversation, "NoesisConversationStore", lambda *a, **k: store)
    _run(store.append(
        "conv-1", OWN, "own question", "alert_lookup", "deterministic", "own answer", user_id="user-1",
    ))
    c = _client(routes.router)

    for headers in (_as(OTHER), _as(OWN, user="user-2")):
        assert c.get("/v1/noesis/conversations/conv-1", headers=headers).json()["count"] == 0
        assert c.get("/v1/noesis/conversations", headers=headers).json()["count"] == 0

    assert c.get("/v1/noesis/conversations/conv-1", headers=_as(OWN)).json()["count"] == 1
    assert c.get("/v1/noesis/conversations", headers=_as(OWN)).json()["count"] == 1


def test_noesis_operator_conversation_is_kept_in_the_operators_scope():
    from intelligence.noesis.models import NoesisQueryRequest
    from intelligence.noesis.service import NoesisService, Scope
    from intelligence.noesis.conversation import NoesisConversationStore
    from repositories.repos import AnalyticsRepository, BaseRepository
    from shared.cache.cache import CacheClient

    class _Flags:
        noesis_enabled = True
        llm_enabled = False
        multi_hop_enabled = False

        def is_tenant_allowed(self, _tenant_id):
            return True

    class _Limiter:
        async def check_and_increment(self, _tenant_id):
            return None

    store = NoesisConversationStore(CacheClient())
    svc = NoesisService(
        graph=_connected_graph(), analytics=AnalyticsRepository(CacheClient()),
        rate_limiter=_Limiter(), conversation_store=store, flags=_Flags(),
    )
    svc._resolve_scope = lambda body, tenant: Scope("kyber", OWN, True, False)
    _run(BaseRepository("alerts").insert("a1", {"tenant_id": OWN, "status": "open"}))
    operator = TenantContext(tenant_id="operator_tenant", user_id="operator-1", role=Role.ADMIN)

    _run(svc.query(
        NoesisQueryRequest(message="show alerts", surface="kyber", tenant_id=OWN, conversation_id="op-conv"),
        operator,
    ))

    assert len(_run(store.get_recent("op-conv", "operator_tenant", user_id="operator-1"))) == 1
    assert _run(store.get_recent("op-conv", OWN, user_id="operator-1")) == []
    assert _run(store.list_for_tenant(OWN, user_id="operator-1")) == []


# ── outcome webhooks ─────────────────────────────────────────────────────────


def test_outcome_webhook_updates_only_the_linked_suggestion(monkeypatch):
    import hashlib
    import hmac
    import json

    from actions.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor
    from config.settings import settings
    from intelligence.suggestions.repository import SuggestionRepository
    from repositories.delivery_repos import (
        DeliveryJobRepository, ExternalOutcomeEventRepository, ExternalResourceLinkRepository,
        ProviderReceiptRepository, WebhookInboxRepository,
    )

    secret = "jira-test-secret"
    monkeypatch.setattr(settings, "delivery", dataclasses.replace(settings.delivery, jira_webhook_secret=secret))
    suggestions = SuggestionRepository()
    _run(suggestions.insert("sugg-own", {"id": "sugg-own", "tenant_id": OWN, "outcome_state": "pending"}))
    _run(suggestions.insert("sugg-other", {"id": "sugg-other", "tenant_id": OTHER, "outcome_state": "pending"}))
    _run(DeliveryJobRepository().insert("j1", {
        "id": "j1", "tenant_id": OWN, "provider_config": {"base_url": "https://own.atlassian.net"},
    }))
    _run(ProviderReceiptRepository().insert("r1", {"id": "r1", "tenant_id": OWN, "job_id": "j1"}))
    links = ExternalResourceLinkRepository()
    _run(links.insert("l1", {
        "id": "l1", "provider": "jira", "external_id": "OWN-1", "tenant_id": OWN,
        "receipt_id": "r1", "resource_type": "suggestion", "resource_id": "sugg-own",
    }))
    body = json.dumps({
        "webhookEvent": "jira:issue_updated",
        "issue": {
            "key": "OWN-1", "self": "https://own.atlassian.net/rest/api/2/issue/1",
            "fields": {"status": {"name": "Done"}},
        },
        "suggestion_id": "sugg-other",
    })
    inbox = WebhookInboxRepository()
    _run(inbox.insert("in1", {
        "id": "in1", "tenant_id": OWN, "provider": "jira", "raw_body": body, "processed": False,
        "headers": {"X-Hub-Signature-256": "sha256=" + hmac.new(
            secret.encode(), body.encode(), hashlib.sha256).hexdigest()},
    }))
    outcomes = ExternalOutcomeEventRepository()
    processor = WebhookInboxProcessor(
        inbox_repo=inbox, outcome_repo=outcomes, link_repo=links,
        router=OutcomeRouter(outcome_repo=outcomes, link_repo=links, suggestion_repo=suggestions),
    )
    _run(processor.process_pending())

    assert _run(suggestions.find_by_id("sugg-other"))["outcome_state"] == "pending"
    assert _run(suggestions.find_by_id("sugg-own"))["outcome_state"] == "in_progress"
