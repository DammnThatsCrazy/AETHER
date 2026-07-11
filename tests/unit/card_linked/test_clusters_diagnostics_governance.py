"""CL-PR4: cluster cohorts, Kyber diagnostics, release gates, kyber routes."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio


# ── Seed helpers ─────────────────────────────────────────────────────────────

async def _seed_activity(tenant, ingestion):
    """One user with topup+spends via redotpay/USDC/base, campaign-attributed."""
    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_c1", "chain": "base", "tx_hash": "0xc1", "asset": "USDC",
        "wallet_address_hash": "wh_cluster", "card_program_id": "redotpay",
        "amount_usd": "12000.00", "campaign_id": "camp_c",
        "occurred_at": "2026-07-01T00:00:00Z",
    })
    for i in range(3):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": f"pw_c{i}", "provider": "rain", "provider_event_id": f"evt_c{i}",
            "basis": "spend", "card_program_id": "redotpay", "issuer_id": "rain",
            "payment_network": "visa", "amount_usd": "25.00",
            "wallet_address_hash": "wh_cluster",
            "occurred_at": f"2026-07-0{i + 2}T00:00:00Z",
        })


# ── Cluster360 cohort generation ─────────────────────────────────────────────

async def test_cluster_cohorts_generated(tenant, ingestion):
    from services.card_linked_payments.clusters import build_card_linked_clusters

    await _seed_activity(tenant, ingestion)
    clusters = await build_card_linked_clusters(tenant)
    by_id = {c["cluster_id"]: c for c in clusters}

    assert "card_program:redotpay" in by_id
    assert "card_topup_asset:usdc" in by_id
    assert "card_funding_chain:base" in by_id
    assert "card_high_volume" in by_id          # 12k topup + spends >= 10k
    assert "card_repeat_spend" in by_id         # 3 spends
    assert "card_campaign_converted" in by_id
    assert "card_issuer_exposure:rain" in by_id
    assert by_id["card_program:redotpay"]["members"] == ["wh_cluster"]


async def test_clusters_are_review_only_never_enforcement(tenant, ingestion):
    from services.card_linked_payments.clusters import build_card_linked_clusters

    await _seed_activity(tenant, ingestion)
    # add a refund loop so the suspicious cohort materializes
    for i in range(3):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": f"pw_r{i}", "provider": "rain", "provider_event_id": f"evt_r{i}",
            "basis": "refund", "card_program_id": "redotpay",
            "wallet_address_hash": "wh_cluster", "amount_usd": "25.00",
        })
    clusters = await build_card_linked_clusters(tenant)
    assert clusters, "expected cohorts"
    assert all(c["enforcement"] == "never" for c in clusters)
    suspect = next(c for c in clusters if c["cluster_id"] == "card_refund_loop_suspect")
    assert "human investigation" in suspect["advisory"]
    assert "never auto-deny" in suspect["advisory"]


async def test_benchmark_rows_never_enter_clusters(tenant):
    from services.card_linked_payments.clusters import build_card_linked_clusters
    from services.card_linked_payments.paymentscan import ingest_benchmark

    await ingest_benchmark(tenant, entity_type="card_program", entity_ref="RedotPay",
                           metric_name="monthly_volume", metric_window="2026-06",
                           value="9999999")
    assert await build_card_linked_clusters(tenant) == []


# ── Kyber diagnostics ────────────────────────────────────────────────────────

async def test_diagnostics_response_shape(tenant, ingestion):
    from services.card_linked_payments.diagnostics import card_linked_diagnostics

    await _seed_activity(tenant, ingestion)
    d = await card_linked_diagnostics(tenant)
    assert set(d) >= {
        "paymentscan", "source_health", "flow_count", "by_source", "by_basis",
        "by_reconciliation_state", "unmatched_events", "reconciliation_conflicts",
        "basis_support_by_source", "privacy", "warnings",
    }
    assert d["flow_count"] == 4
    assert d["by_basis"] == {"topup": 1, "spend": 3}
    assert set(d["privacy"]) == {
        "region_restricted_records", "region_suppression_events",
        "consent_suppression_events", "blocked_pii_attempts",
    }


async def test_diagnostics_paymentscan_stale_warning(tenant):
    from services.card_linked_payments.diagnostics import card_linked_diagnostics
    from services.card_linked_payments.paymentscan import sync_catalog

    d = await card_linked_diagnostics(tenant)
    assert d["paymentscan"]["stale"] is True    # never synced

    await sync_catalog(tenant)
    d = await card_linked_diagnostics(tenant)
    assert d["paymentscan"]["stale"] is False
    assert d["paymentscan"]["card_program_count"] >= 23
    assert d["paymentscan"]["issuer_count"] >= 6


async def test_diagnostics_basis_support_shows_source_coverage(tenant, ingestion):
    """The coverage map must show which basis each source can prove —
    provider webhooks prove spend, on-chain proves topup, never vice versa."""
    from services.card_linked_payments.diagnostics import card_linked_diagnostics

    await _seed_activity(tenant, ingestion)
    d = await card_linked_diagnostics(tenant)
    support = d["basis_support_by_source"]
    assert support["onchain_observer"] == ["topup"]
    assert support["provider_webhook"] == ["spend"]


async def test_diagnostics_topup_spend_conflation_warning(tenant, ingestion):
    """An SDK spend claim is downgraded AND surfaces as a mislabeling warning."""
    from services.card_linked_payments.diagnostics import card_linked_diagnostics

    await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_conf_1", "user_id": "u1",
        "properties": {"card_program": "KAST", "basis": "spend", "amount_usd": "10"},
    }, consent_snapshot={"commerce": True})
    d = await card_linked_diagnostics(tenant)
    assert d["warnings"]["basis_mislabeling"] == 1
    assert d["warnings"]["recent_basis_warnings"]


async def test_diagnostics_surfaces_region_and_consent_suppressions(tenant, ingestion):
    from services.card_linked_payments.diagnostics import card_linked_diagnostics

    await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_eu_d", "user_id": "u-eu",
        "properties": {"card_program": "Gnosis Pay", "basis": "topup"},
    }, region_hint="eu", consent_snapshot={"commerce": True})
    await ingestion.ingest_sdk_event(tenant, {
        "type": "payment_completed", "event_id": "sdk_nc_d", "user_id": "u-nc",
        "properties": {"card_program": "KAST", "basis": "topup"},
    }, consent_snapshot={"commerce": False})
    with pytest.raises(ValueError):
        await ingestion.ingest_provider_webhook(tenant, {
            "id": "pw_pii_d", "provider": "rain", "provider_event_id": "evt_pii_d",
            "basis": "spend", "cvv": "123",
        })

    d = await card_linked_diagnostics(tenant)
    assert d["privacy"]["region_suppression_events"] >= 1
    assert d["privacy"]["region_restricted_records"] >= 1
    assert d["privacy"]["consent_suppression_events"] >= 1
    assert d["privacy"]["blocked_pii_attempts"] == 1


async def test_diagnostics_unmatched_evidence_counted(tenant, ingestion):
    from services.card_linked_payments.diagnostics import card_linked_diagnostics

    await ingestion.ingest_onchain_observation(tenant, {
        "id": "oc_um1", "chain": "base", "tx_hash": "0xum1", "asset": "USDC",
        "wallet_address_hash": "wh_um", "card_program_id": "kast",
    })
    d = await card_linked_diagnostics(tenant)
    assert d["unmatched_events"].get("onchain_only") == 1


# ── Release gate (fail-closed governance checks) ─────────────────────────────

def test_release_gate_all_checks_pass():
    from services.card_linked_payments.governance import release_gate_passed, run_release_gate

    results = run_release_gate()
    failing = [r.name for r in results if not r.passed]
    assert failing == [], f"release gate failing: {failing}"
    assert release_gate_passed() is True
    names = {r.name for r in results}
    assert {"catalog_seeded", "basis_validation", "topup_spend_non_conflation",
            "blocked_pii_rejection", "flags_default_off", "paymentscan_benchmark_only",
            "graph_projection_honesty", "docs_source_of_truth_present"} <= names


def test_release_gate_fails_on_invalid_basis(monkeypatch):
    """An unsupported basis must be rejected everywhere — and the gate
    itself fails closed if basis validation is ever weakened."""
    import services.card_linked_payments.models as models
    from services.card_linked_payments.governance import _check_basis_validation
    from services.card_linked_payments.normalizer import normalize_provider_webhook

    assert _check_basis_validation().passed
    with pytest.raises(ValueError):
        normalize_provider_webhook({"id": "x", "tenant_id": "t", "basis": "not_a_basis"})

    monkeypatch.setattr(models, "CardActivityBasis", lambda value: value)  # weakened
    result = _check_basis_validation()
    assert result.passed is False
    assert "accepted" in result.detail


def test_release_gate_fails_on_blocked_pii_acceptance(monkeypatch):
    """If PII rejection is ever weakened, the gate must fail."""
    import services.card_linked_payments.models as models
    from services.card_linked_payments.governance import _check_blocked_pii_rejection

    assert _check_blocked_pii_rejection().passed
    monkeypatch.setattr(models, "reject_blocked_fields", lambda payload: dict(payload))
    result = _check_blocked_pii_rejection()
    assert result.passed is False
    assert "accepted" in result.detail


def test_release_gate_fails_if_flags_default_on(monkeypatch):
    import services.card_linked_payments.governance as governance

    def _tampered():
        from config import settings as settings_module
        original = settings_module.CardLinkedPaymentRailsConfig

        class OnByDefault(original):  # type: ignore[misc, valid-type]
            def __init__(self, **kwargs):
                kwargs.setdefault("enabled", True)
                super().__init__(**kwargs)

        monkeypatch.setattr(settings_module, "CardLinkedPaymentRailsConfig", OnByDefault)
        return governance._check_flags_default_off()

    assert _tampered().passed is False


# ── Kyber routes (operator gating, flag gating) ──────────────────────────────

class _Operator:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = "op-user"
        self.is_platform_admin = True
        from config.settings import settings
        self.permissions = [settings.security_governance.kyber_operator_permission]

    def has_permission(self, permission: str) -> bool:
        return False

    def require_permission(self, permission: str) -> None:
        return None


class _PlainTenant:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.user_id = "tenant-user"
        self.is_platform_admin = False
        self.permissions: list[str] = []

    def has_permission(self, permission: str) -> bool:
        return False

    def require_permission(self, permission: str) -> None:
        return None


def _build_kyber_app(actor) -> TestClient:
    from shared.common.common import AetherError
    from services.card_linked_payments.kyber_routes import card_linked_kyber_router

    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handler(request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.tenant = actor
        return await call_next(request)

    app.include_router(card_linked_kyber_router)
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


def test_kyber_routes_reject_non_operator(tenant, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    client = _build_kyber_app(_PlainTenant(tenant))
    path = f"/v1/admin/kyber/payment-rails/card-linked/diagnostics?tenant_id={tenant}"
    # The non-operator must be denied. Under the full suite's sys.modules churn
    # the guard's ForbiddenError can fail to match the app's registered handler
    # (two `shared.common.common` modules) and TestClient re-raises it instead
    # of returning 403 — either outcome proves the denial.
    try:
        response = client.get(path)
    except Exception as exc:  # noqa: BLE001
        assert type(exc).__name__ == "ForbiddenError"
    else:
        assert response.status_code == 403


def test_kyber_routes_flag_off_rejected_even_for_operator(tenant, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails",
                        _flags(enabled=False, kyber_enabled=False))
    client = _build_kyber_app(_Operator(tenant))
    response = client.get(
        f"/v1/admin/kyber/payment-rails/card-linked/diagnostics?tenant_id={tenant}",
    )
    assert response.status_code == 400


async def test_kyber_diagnostics_route_shape(tenant, ingestion, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    await _seed_activity(tenant, ingestion)
    client = _build_kyber_app(_Operator(tenant))
    body = client.get(
        f"/v1/admin/kyber/payment-rails/card-linked/diagnostics?tenant_id={tenant}",
    ).json()["data"]
    assert body["flow_count"] == 4
    assert body["region_policy_defaults"] == {
        "eu_restricted_mode": True, "apac_restricted_mode": True,
        "provider_pii_block": True,
    }


async def test_kyber_clusters_route_gated_on_clustering_flag(tenant, ingestion, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags(clustering_enabled=False))
    await _seed_activity(tenant, ingestion)
    client = _build_kyber_app(_Operator(tenant))
    path = f"/v1/admin/kyber/payment-rails/card-linked/clusters?tenant_id={tenant}"
    assert client.get(path).status_code == 400

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    body = client.get(path).json()["data"]
    assert body["count"] >= 1
    assert all(item["enforcement"] == "never" for item in body["items"])


def test_kyber_release_gate_route(tenant, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "card_linked_payment_rails", _flags())
    client = _build_kyber_app(_Operator(tenant))
    body = client.get("/v1/admin/kyber/payment-rails/card-linked/release-gate").json()["data"]
    assert body["passed"] is True
    assert {c["name"] for c in body["checks"]} >= {"catalog_seeded", "flags_default_off"}
