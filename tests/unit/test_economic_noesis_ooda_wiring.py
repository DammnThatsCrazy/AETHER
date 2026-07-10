"""WS8 wiring tests — Noesis intents/adapters, OODA suggestion adapters,
and notification alert-policy rows for the three economic domains.

Everything here is observation-only: adapters read typed repositories and
map facts to answers or suggestions; nothing mutates domain state.
"""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal
from uuid import uuid4

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

NEW_INTENTS = (
    "stablecoin_flow_lookup",
    "derivatives_exposure_lookup",
    "derivatives_reconciliation_lookup",
    "interop_message_trace",
    "interop_path_reliability",
)


@pytest.fixture(autouse=True)
def _reset_typed_stores():
    from repositories.typed_repo import reset_typed_in_memory_stores

    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


@pytest.fixture()
def tenant() -> str:
    return f"tenant-ws8-{uuid4().hex[:8]}"


# ─── Noesis intent registration ─────────────────────────────────────────


def test_new_intents_in_supported_set():
    from services.noesis.models import SUPPORTED_INTENTS

    for intent in NEW_INTENTS:
        assert intent in SUPPORTED_INTENTS, intent


def test_capability_registry_has_new_intents():
    from services.noesis.capability_registry import get_capability

    for intent in NEW_INTENTS:
        capability = get_capability(intent)
        assert capability is not None, intent
        assert capability.example_prompts
        assert capability.data_sources


def test_capability_registry_matches_supported_intents():
    """Every registered capability must be a supported intent."""
    from services.noesis.capability_registry import CAPABILITY_REGISTRY
    from services.noesis.models import SUPPORTED_INTENTS

    for capability in CAPABILITY_REGISTRY:
        assert capability.intent in SUPPORTED_INTENTS, capability.intent


def test_query_plan_accepts_new_intents():
    from services.noesis.models import QueryPlan

    for intent in NEW_INTENTS:
        assert QueryPlan(intent=intent).intent == intent


def test_classifier_routes_economic_prompts():
    from services.noesis.models import NoesisQueryRequest
    from services.noesis.service import NoesisService, Scope

    svc = object.__new__(NoesisService)  # _classify uses no constructor state
    scope = Scope("kyber", "tenant-x", False, False)

    cases = {
        "Is USDC showing any depeg signals?": "stablecoin_flow_lookup",
        "Summarize our derivatives exposure": "derivatives_exposure_lookup",
        "Any derivatives reconciliation variance this week?": "derivatives_reconciliation_lookup",
        "Trace cross-chain message lz2:0xabc": "interop_message_trace",
        "Which cross-chain paths have poor reliability?": "interop_path_reliability",
    }
    for message, expected in cases.items():
        plan = NoesisService._classify(
            svc, NoesisQueryRequest(message=message, surface="kyber"), scope,
        )
        assert plan.intent == expected, f"{message!r} → {plan.intent}"


# ─── Noesis adapters (read-only, Decimal-safe) ──────────────────────────


@pytest.mark.asyncio
async def test_stablecoin_flow_summary_reports_depeg(tenant):
    from repositories.stablecoin_repos import FlowAggregateRepo, ValuationSnapshotRepo
    from services.noesis.adapters.stablecoin_adapter import StablecoinNoesisAdapter

    await FlowAggregateRepo().insert({
        "tenant_id": tenant,
        "flow_aggregate_id": "fa_1",
        "canonical_asset_id": "usdc",
        "gross_transfer_volume": Decimal("1234.500000"),
        "idempotency_key": f"{tenant}-fa1",
        "execution_by_aether": False,
    })
    await ValuationSnapshotRepo().insert({
        "tenant_id": tenant,
        "valuation_id": "val_1",
        "deployment_id": "usdc-base",
        "price_usd": Decimal("0.985"),
        "peg_deviation_bps": Decimal("-150"),
        "peg_status": "depegged",
        "idempotency_key": f"{tenant}-val1",
        "execution_by_aether": False,
    })

    result = await StablecoinNoesisAdapter().flow_summary(tenant)
    assert result["sufficient"] is True
    assert "peg deviation" in result["answer"]
    assert "usdc-base" in result["answer"]
    # Decimals serialized as strings — never floats
    for row in result["results"]:
        assert not any(isinstance(v, (float, Decimal)) for v in row.values())


@pytest.mark.asyncio
async def test_stablecoin_flow_summary_tenant_isolated(tenant):
    from repositories.stablecoin_repos import FlowAggregateRepo
    from services.noesis.adapters.stablecoin_adapter import StablecoinNoesisAdapter

    await FlowAggregateRepo().insert({
        "tenant_id": f"{tenant}-other",
        "flow_aggregate_id": "fa_other",
        "canonical_asset_id": "usdt",
        "idempotency_key": f"{tenant}-other-fa",
        "execution_by_aether": False,
    })
    result = await StablecoinNoesisAdapter().flow_summary(tenant)
    assert result["results"] == []
    assert result["sufficient"] is False


@pytest.mark.asyncio
async def test_derivatives_exposure_and_reconciliation(tenant):
    from repositories.derivatives_repos import (
        PositionRepo,
        ReconciliationVarianceRepo,
        StreamGapRepo,
    )
    from services.noesis.adapters.derivatives_adapter import DerivativesNoesisAdapter

    await PositionRepo().insert({
        "tenant_id": tenant,
        "position_id": "pos_1",
        "trading_account_id": "acct_1",
        "canonical_market_id": "BTC-PERP",
        "status": "open",
        "size": Decimal("1.500000000000000000"),
        "idempotency_key": f"{tenant}-pos1",
        "execution_by_aether": False,
    })
    await ReconciliationVarianceRepo().insert({
        "tenant_id": tenant,
        "reconciliation_variance_id": "var_1",
        "variance_type": "account_size",
        "severity": "high",
        "status": "variance_detected",
        "idempotency_key": f"{tenant}-var1",
        "execution_by_aether": False,
    })
    await StreamGapRepo().insert({
        "tenant_id": tenant,
        "stream_gap_id": "gap_1",
        "canonical_market_id": "BTC-PERP",
        "expected_sequence": 10,
        "received_sequence": 20,
        "status": "open",
        "idempotency_key": f"{tenant}-gap1",
        "execution_by_aether": False,
    })

    adapter = DerivativesNoesisAdapter()
    exposure = await adapter.position_exposure(tenant, target="acct_1")
    assert "1 currently open" in exposure["answer"]
    for row in exposure["results"]:
        assert not any(isinstance(v, (float, Decimal)) for v in row.values())

    recon = await adapter.reconciliation_status(tenant)
    assert "1 unresolved" in recon["answer"]
    assert "1 open stream gap(s)" in recon["answer"]


@pytest.mark.asyncio
async def test_interop_message_trace_and_path_reliability(tenant):
    from repositories.interop_repos import InteropMessageEventRepo, InteropMessageRepo
    from services.noesis.adapters.interop_adapter import InteropNoesisAdapter

    await InteropMessageRepo().insert({
        "tenant_id": tenant,
        "interop_message_id": "msg_1",
        "provider_kind": "layerzero_v2",
        "correlation_key": "lz2:0xabc",
        "path_id": "path-eth-arb",
        "status": "delivered",
        "idempotency_key": f"{tenant}-msg1",
        "execution_by_aether": False,
    })
    await InteropMessageRepo().insert({
        "tenant_id": tenant,
        "interop_message_id": "msg_2",
        "provider_kind": "layerzero_v2",
        "correlation_key": "lz2:0xdef",
        "path_id": "path-eth-arb",
        "status": "delivery_failed",
        "idempotency_key": f"{tenant}-msg2",
        "execution_by_aether": False,
    })
    await InteropMessageEventRepo().insert({
        "tenant_id": tenant,
        "transition_id": "tr_1",
        "interop_message_id": "msg_1",
        "from_status": "verified",
        "to_status": "delivered",
        "observed_at": "2026-07-08T00:00:00+00:00",
        "idempotency_key": f"{tenant}-tr1",
        "execution_by_aether": False,
    })

    adapter = InteropNoesisAdapter()
    trace = await adapter.message_trace(tenant, target="lz2:0xabc")
    assert trace["sufficient"] is True
    assert "'delivered'" in trace["answer"]
    assert len(trace["results"]) == 2  # message + one transition

    missing = await adapter.message_trace(tenant, target="lz2:0xmissing")
    assert missing["sufficient"] is False

    reliability = await adapter.path_reliability(tenant)
    assert reliability["sufficient"] is True
    (row,) = reliability["results"]
    assert row["path_id"] == "path-eth-arb"
    assert row["delivered"] == 1
    assert row["failed"] == 1


# ─── OODA suggestion adapters ───────────────────────────────────────────


def test_depeg_snapshot_maps_to_suggestion(tenant):
    from services.suggestions.adapters.stablecoin_adapter import (
        create_suggestion_from_depeg_snapshot,
    )
    from services.suggestions.models import SuggestionClass

    suggestion = create_suggestion_from_depeg_snapshot(
        {
            "valuation_id": "val_9",
            "deployment_id": "usdc-base",
            "peg_status": "depegged",
            "peg_deviation_bps": "-180",
        },
        tenant,
    )
    assert suggestion is not None
    assert suggestion.suggestion_class is SuggestionClass.STABLECOIN_DEPEG
    assert suggestion.tenant_id == tenant
    assert suggestion.lineage_event_ids == ["val_9"]

    on_peg = create_suggestion_from_depeg_snapshot(
        {"valuation_id": "val_10", "peg_status": "on_peg"}, tenant,
    )
    assert on_peg is None


def test_variance_and_gap_map_to_suggestions(tenant):
    from services.suggestions.adapters.derivatives_adapter import (
        create_suggestion_from_reconciliation_variance,
        create_suggestion_from_stream_gap,
    )
    from services.suggestions.models import SuggestionClass

    variance = create_suggestion_from_reconciliation_variance(
        {
            "reconciliation_variance_id": "var_9",
            "variance_type": "account_balance",
            "severity": "high",
            "status": "variance_detected",
            "expected_value": "10.0",
            "observed_value": "9.5",
        },
        tenant,
    )
    assert variance is not None
    assert variance.suggestion_class is SuggestionClass.DERIVATIVES_RECONCILIATION

    low = create_suggestion_from_reconciliation_variance(
        {"reconciliation_variance_id": "var_10", "severity": "low"}, tenant,
    )
    assert low is None

    gap = create_suggestion_from_stream_gap(
        {
            "stream_gap_id": "gap_9",
            "canonical_market_id": "ETH-PERP",
            "expected_sequence": 5,
            "received_sequence": 50,
            "status": "open",
        },
        tenant,
    )
    assert gap is not None
    assert gap.suggestion_class is SuggestionClass.DERIVATIVES_RISK

    recovered = create_suggestion_from_stream_gap(
        {"stream_gap_id": "gap_10", "status": "recovered"}, tenant,
    )
    assert recovered is None


def test_stuck_message_and_policy_change_map_to_suggestions(tenant):
    from services.suggestions.adapters.interop_adapter import (
        create_suggestion_from_policy_change,
        create_suggestion_from_stuck_message,
    )
    from services.suggestions.models import SuggestionClass

    stuck = create_suggestion_from_stuck_message(
        {
            "interop_message_id": "msg_9",
            "path_id": "path-eth-arb",
            "correlation_key": "lz2:0x9",
            "status": "verification_in_progress",
        },
        tenant,
        stuck_minutes=45,
    )
    assert stuck is not None
    assert stuck.suggestion_class is SuggestionClass.INTEROP_DELIVERY_HEALTH
    assert "45" in stuck.summary

    settled = create_suggestion_from_stuck_message(
        {"interop_message_id": "msg_10", "status": "settled"}, tenant, stuck_minutes=45,
    )
    assert settled is None

    change = create_suggestion_from_policy_change(
        {"content_hash": "aaa"},
        {"security_snapshot_id": "snap_9", "path_id": "path-eth-arb", "content_hash": "bbb"},
        tenant,
    )
    assert change is not None

    unchanged = create_suggestion_from_policy_change(
        {"content_hash": "aaa"}, {"content_hash": "aaa"}, tenant,
    )
    assert unchanged is None


# ─── Alert policy + config wiring ───────────────────────────────────────


def test_alert_topics_registered():
    from shared.events.events import Topic

    expected = {
        "STABLECOIN_DEPEG_DETECTED": "aether.stablecoin.depeg.detected",
        "DERIVATIVES_VARIANCE_DETECTED": "aether.derivatives.reconciliation.variance",
        "DERIVATIVES_STREAM_GAP_STALLED": "aether.derivatives.stream.gap.stalled",
        "INTEROP_MESSAGE_STUCK": "aether.interop.message.stuck",
        "INTEROP_SECURITY_POLICY_CHANGED": "aether.interop.security.policy.changed",
    }
    for name, value in expected.items():
        assert getattr(Topic, name).value == value


def test_alert_policy_rows_exist_for_new_topics():
    from services.notification_intelligence.consumer import _TOPIC_MAP
    from shared.events.events import Topic

    for topic in (
        Topic.STABLECOIN_DEPEG_DETECTED,
        Topic.DERIVATIVES_VARIANCE_DETECTED,
        Topic.DERIVATIVES_STREAM_GAP_STALLED,
        Topic.INTEROP_MESSAGE_STUCK,
        Topic.INTEROP_SECURITY_POLICY_CHANGED,
    ):
        severity, notification_class, title, why = _TOPIC_MAP[topic.value]
        assert severity in ("P0", "P1", "P2", "P3")
        assert notification_class == "alert"
        assert title and why


def test_suggestions_config_has_economic_adapter_flags_default_off(monkeypatch):
    for var in (
        "AETHER_SUGGESTIONS_STABLECOIN_ADAPTER_ENABLED",
        "AETHER_SUGGESTIONS_DERIVATIVES_ADAPTER_ENABLED",
        "AETHER_SUGGESTIONS_INTEROP_ADAPTER_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)

    from config.settings import SuggestionsConfig

    config = SuggestionsConfig()
    assert config.stablecoin_adapter_enabled is False
    assert config.derivatives_adapter_enabled is False
    assert config.interop_adapter_enabled is False
