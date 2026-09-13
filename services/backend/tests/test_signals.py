"""Tests for the signals service — translator, repository, and refresh logic."""
from __future__ import annotations

import pytest

from repositories.repos import SignalRepository, reset_in_memory_stores
from services.signals.signal_translator import (
    SIGNAL_TEMPLATES,
    signals_from_asset_composition,
    signals_from_churn_model,
    signals_from_location_history,
    translate_signal,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


# ── Translator unit tests ──────────────────────────────────────────────────


def test_translate_known_signal():
    sig = translate_signal(
        "AT_RISK_OF_CHURN", "e1", 0.85,
        evidence_refs=["churn_model"],
        template_vars={"churn_probability": 0.85, "days_since_last_visit": 14},
    )
    assert sig is not None
    assert sig["sentiment"] == "caution"
    assert sig["severity"] == "high"
    assert "85%" in sig["explanation"]
    assert "14" in sig["explanation"]


def test_translate_unknown_signal_returns_none():
    assert translate_signal("UNKNOWN_SIGNAL", "e1", 0.5, [], {}) is None


def test_all_20_templates_exist():
    assert len(SIGNAL_TEMPLATES) == 20


def test_signals_from_churn_model_high_risk():
    sigs = signals_from_churn_model("e1", {"days_since_last_visit": 20, "discount_usage_rate": 0.6, "referral_count": 8}, 0.8)
    ids = {s["sentiment"] for s in sigs}
    assert "caution" in ids
    assert len(sigs) == 3  # churn + discount + referral


def test_signals_from_churn_model_low_risk():
    sigs = signals_from_churn_model("e1", {"days_since_last_visit": 1, "discount_usage_rate": 0.1, "referral_count": 0}, 0.2)
    assert sigs == []


def test_signals_from_asset_composition():
    sigs = signals_from_asset_composition("e1", stablecoin_pct=80, altcoin_pct=10, top_symbol="USDC", top_holding_pct=85)
    ids = {s["signal_type"].split(":")[0] for s in sigs}
    # stablecoin_dominant + concentrated_portfolio
    explanations = " ".join(s["explanation"] for s in sigs)
    assert "USDC" in explanations


def test_signals_from_location_history_anomaly():
    locations = [
        {"city": "Tokyo", "country": "Japan", "is_new_primary": True, "classification": "primary", "session_count": 100},
        {"city": "London", "country": "UK", "is_new_primary": False, "classification": "primary", "session_count": 50},
    ]
    sigs = signals_from_location_history("e1", locations)
    sentiments = {s["sentiment"] for s in sigs}
    assert "caution" in sentiments  # LOCATION_ANOMALY


# ── Signal repository tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_repo_upsert_and_list():
    repo = SignalRepository()
    sig = {
        "signal_id": "AT_RISK_OF_CHURN:e1:aabbccdd",
        "entity_id": "e1",
        "tenant_id": "t1",
        "sentiment": "caution",
        "severity": "high",
        "confidence": 0.8,
        "is_stale": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    await repo.upsert_signal(sig)
    results = await repo.list_for_entity("e1", "t1")
    assert len(results) == 1
    assert results[0]["signal_id"] == sig["signal_id"]


@pytest.mark.asyncio
async def test_signal_repo_stale_filter():
    repo = SignalRepository()
    await repo.upsert_signal({"signal_id": "s1", "entity_id": "e1", "tenant_id": "t1", "is_stale": True, "sentiment": "caution", "severity": "high"})
    await repo.upsert_signal({"signal_id": "s2", "entity_id": "e1", "tenant_id": "t1", "is_stale": False, "sentiment": "positive", "severity": "info"})

    fresh = await repo.list_for_entity("e1", "t1", include_stale=False)
    assert len(fresh) == 1
    assert fresh[0]["signal_id"] == "s2"

    all_sigs = await repo.list_for_entity("e1", "t1", include_stale=True)
    assert len(all_sigs) == 2


@pytest.mark.asyncio
async def test_signal_repo_sentiment_filter():
    repo = SignalRepository()
    for i, sent in enumerate(["positive", "caution", "informational"]):
        await repo.upsert_signal({"signal_id": f"s{i}", "entity_id": "e1", "tenant_id": "t1", "sentiment": sent, "is_stale": False, "severity": "info"})

    positive = await repo.list_for_entity("e1", "t1", sentiment="positive")
    assert len(positive) == 1


@pytest.mark.asyncio
async def test_signal_repo_tenant_isolation():
    repo = SignalRepository()
    await repo.upsert_signal({"signal_id": "s1", "entity_id": "e1", "tenant_id": "t1", "is_stale": False})
    results_t2 = await repo.list_for_entity("e1", "t2")
    assert len(results_t2) == 0
