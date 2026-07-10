"""Graph projection, Profile360 summary/story, filters, and tenant routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


# ── Graph projection ─────────────────────────────────────────────────────────

def _flow(**overrides) -> dict:
    base = {
        "id": "clf_1", "tenant_id": "t1", "actor_kind": "human",
        "user_id": "u1", "wallet_address_hash": "wh_1",
        "card_program_id": "redotpay", "issuer_id": "rain",
        "payment_network": "visa", "rail": "onchain", "basis": "topup",
        "chain": "base", "asset": "USDC", "amount_usd": "100",
        "campaign_id": "camp_1", "journey_id": "j1",
        "source": "onchain_observer", "confidence": "probable",
        "evidence_refs": ["0xabc"], "reconciliation_state": "onchain_only",
        "occurred_at": "2026-07-10T00:00:00Z", "observed_at": "2026-07-10T00:00:00Z",
        "created_at": "2026-07-10T00:00:00Z", "updated_at": "2026-07-10T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_flow_projection_builds_expected_edges():
    from services.card_linked_payments.graph_projector import build_flow_mutations
    from shared.graph.graph import EdgeType

    vertices, edges = build_flow_mutations(_flow())
    vertex_types = {str(v.vertex_type) for v in vertices}
    assert "CardLinkedFlow" in vertex_types and "CardProgram" in vertex_types

    edge_types = {e.edge_type for e in edges}
    assert EdgeType.USED_PROVIDER in edge_types      # user → program
    assert EdgeType.FUNDED in edge_types             # wallet → flow
    assert EdgeType.ATTRIBUTED_TO in edge_types      # flow → campaign
    assert EdgeType.CAME_FROM in edge_types          # user → campaign
    assert EdgeType.PARTICIPATED_IN in edge_types    # user → journey
    assert EdgeType.OCCURRED_ON in edge_types        # flow → chain
    assert EdgeType.USED_ASSET in edge_types         # flow → token


def test_flow_projection_idempotency_keys_stable():
    from services.card_linked_payments.graph_projector import build_flow_mutations

    _, edges_a = build_flow_mutations(_flow())
    _, edges_b = build_flow_mutations(_flow())
    keys_a = sorted(e.properties.get("idempotency_key", "") for e in edges_a)
    keys_b = sorted(e.properties.get("idempotency_key", "") for e in edges_b)
    assert keys_a == keys_b and all(keys_a)


def test_benchmark_rows_never_projected_to_graph():
    from services.card_linked_payments.graph_projector import build_flow_mutations

    vertices, edges = build_flow_mutations(_flow(
        basis="benchmark_only", reconciliation_state="benchmark_only", source="paymentscan",
    ))
    assert vertices == [] and edges == []


def test_agent_influence_edge():
    from services.card_linked_payments.graph_projector import build_flow_mutations
    from shared.graph.graph import EdgeType

    _, edges = build_flow_mutations(_flow(agent_id="agent-1", actor_kind="agent"))
    assert EdgeType.INITIATED_OR_INFLUENCED in {e.edge_type for e in edges}


def test_catalog_projection_nodes():
    from services.card_linked_payments.graph_projector import build_catalog_mutations
    from shared.graph.graph import EdgeType

    vertices, edges = build_catalog_mutations("t1", {
        "slug": "redotpay", "display_name": "RedotPay",
        "issuer_id": "rain", "payment_network": "visa",
    })
    types = {str(v.vertex_type) for v in vertices}
    assert types == {"CardProgram", "CardIssuer", "PaymentNetwork"}
    assert {e.edge_type for e in edges} == {EdgeType.ISSUED_BY, EdgeType.RUNS_ON}


# ── Profile360 summary / story / filters ────────────────────────────────────

async def _seed_story(tenant, ingestion):
    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_s1", "chain": "base", "tx_hash": "0xs1", "asset": "USDC",
        "wallet_address_hash": "wh_story", "card_program_id": "redotpay",
        "amount_usd": "200.00", "campaign_id": "camp_base_usdc",
        "occurred_at": "2026-07-01T00:00:00Z",
    })
    for i in range(5):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": f"pw_s{i}", "provider": "rain", "provider_event_id": f"evt_s{i}",
            "basis": "spend", "card_program_id": "redotpay", "issuer_id": "rain",
            "payment_network": "visa", "amount_usd": "12.00",
            "wallet_address_hash": "wh_story",
            "occurred_at": f"2026-07-0{i + 2}T00:00:00Z",
        })


async def test_profile_summary_story_sequence(tenant, ingestion):
    from services.card_linked_payments.profile_summary import get_card_linked_profile_summary

    await _seed_story(tenant, ingestion)
    summary = await get_card_linked_profile_summary(tenant, "wh_story")
    kinds = [step["kind"] for step in summary["story"]]
    # campaign source and program adoption precede the funding event,
    # spends follow — the entity story reads campaign → provider → top-up → spends
    assert kinds[0] == "campaign_source"
    assert kinds[1] == "card_program_used"
    assert kinds[2] == "card_topup"
    assert kinds.count("card_spend") == 5
    assert summary["summary"]["basis"] == "mixed"
    assert "onchain_observer" in summary["provenance"]
    assert "provider_webhook" in summary["provenance"]


async def test_profile_summary_filters(tenant, ingestion):
    from services.card_linked_payments.profile_summary import get_card_linked_profile_summary

    await _seed_story(tenant, ingestion)
    only_spend = await get_card_linked_profile_summary(tenant, "wh_story", {"basis": "spend"})
    assert len(only_spend["flows"]) == 5
    only_topup = await get_card_linked_profile_summary(tenant, "wh_story", {"basis": "topup"})
    assert len(only_topup["flows"]) == 1
    big = await get_card_linked_profile_summary(tenant, "wh_story", {"volume_min": "100"})
    assert len(big["flows"]) == 1  # only the 200 USD top-up


async def test_topup_only_entity_gets_warning(tenant, ingestion):
    from services.card_linked_payments.profile_summary import get_card_linked_profile_summary

    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_w1", "chain": "base", "tx_hash": "0xw1",
        "wallet_address_hash": "wh_warn", "card_program_id": "kast",
        "amount_usd": "50",
    })
    summary = await get_card_linked_profile_summary(tenant, "wh_warn")
    assert any("not card spend" in w for w in summary["warnings"])


async def test_drilldown_shows_evidence_and_provenance(tenant, ingestion):
    from services.card_linked_payments.profile_summary import get_card_linked_drilldown

    record, _ = await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_d1", "chain": "base", "tx_hash": "0xd1",
        "wallet_address_hash": "wh_drill", "card_program_id": "redotpay",
    })
    drill = await get_card_linked_drilldown(tenant, "wh_drill", record["id"])
    assert drill is not None
    assert drill["provenance"]["basis"] == "topup"
    assert drill["evidence_refs"] == ["0xd1"]
    # entity scoping: another entity cannot drill into this flow
    assert await get_card_linked_drilldown(tenant, "someone-else", record["id"]) is None


# ── Tenant routes (flag gating, filters, honesty notices) ───────────────────

class _FakeTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.is_platform_admin = False

    def require_permission(self, perm: str) -> None:
        return None


def _build_app(tenant_id: str) -> TestClient:
    from services.card_linked_payments.routes import router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.tenant = _FakeTenant(tenant_id)
        return await call_next(request)

    return TestClient(app)


def _flags(**overrides):
    from config.settings import CardLinkedPaymentRailsConfig

    defaults = dict(
        enabled=True, paymentscan_catalog_enabled=True,
        paymentscan_benchmarks_enabled=True, profile360_enabled=True,
        campaign_attribution_enabled=True, clustering_enabled=True,
        kyber_enabled=True, eu_restricted_mode=True,
        apac_restricted_mode=True, provider_pii_block=True,
    )
    defaults.update(overrides)
    return CardLinkedPaymentRailsConfig(**defaults)


def test_routes_flag_off_returns_404(tenant, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags(enabled=False))
    client = _build_app(tenant)
    assert client.get("/v1/integrations/providers/payment-rails/card-linked/flows").status_code == 404


def test_catalog_route_serves_seed(tenant, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    client = _build_app(tenant)
    response = client.get(
        "/v1/integrations/providers/payment-rails/card-linked/catalog?entity_type=card_program",
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert {i["slug"] for i in items} >= {"redotpay", "kast", "gnosis", "metamask"}


async def test_flows_route_filters_and_excludes_benchmarks(tenant, ingestion, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    await _seed_story(tenant, ingestion)
    from services.card_linked_payments.paymentscan import ingest_benchmark
    await ingest_benchmark(tenant, entity_type="card_program", entity_ref="RedotPay",
                           metric_name="monthly_volume", metric_window="2026-06")

    client = _build_app(tenant)
    response = client.get(
        "/v1/integrations/providers/payment-rails/card-linked/flows?basis=spend",
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 5
    assert all(item["basis"] == "spend" for item in data["items"])


async def test_benchmarks_route_carries_honesty_notice(tenant, ingestion, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    from services.card_linked_payments.paymentscan import ingest_benchmark
    await ingest_benchmark(tenant, entity_type="card_program", entity_ref="KAST",
                           metric_name="monthly_volume", metric_window="2026-06")
    client = _build_app(tenant)
    body = client.get(
        "/v1/integrations/providers/payment-rails/card-linked/benchmarks",
    ).json()["data"]
    assert "not user-level card spend" in body["notice"]


async def test_campaign_outcomes_route(tenant, ingestion, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    await _seed_story(tenant, ingestion)
    client = _build_app(tenant)
    body = client.get(
        "/v1/integrations/providers/payment-rails/card-linked/campaigns/camp_base_usdc/outcomes",
    ).json()["data"]
    assert body["card_topup_users"] == 1
    assert body["card_topup_volume_usd"] == "200.00"
    assert body["attribution_basis"] in ("direct", "temporal")

    monkeypatch.setattr(settings, "card_linked_payment_rails",
                        _flags(campaign_attribution_enabled=False))
    assert client.get(
        "/v1/integrations/providers/payment-rails/card-linked/campaigns/camp_base_usdc/outcomes",
    ).status_code == 404
