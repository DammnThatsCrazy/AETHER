"""Unit tests: anti-distillation controls — score binning, honeypot, query detection."""
from __future__ import annotations

import pytest

from services.security.anti_distillation import (
    AntiDistillationConfig,
    AntiDistillationService,
    SCORE_BINS_BY_PLAN,
    apply_output_precision,
)


def test_score_binning_p1_hobbyist():
    """P1 plan tier rounds to nearest 0.1."""
    result = apply_output_precision(0.876, "P1_HOBBYIST")
    assert result == 0.9


def test_score_binning_p2_professional():
    """P2 plan tier rounds to nearest 0.05."""
    result = apply_output_precision(0.876, "P2_PROFESSIONAL")
    assert result == 0.9


def test_score_binning_p3_growth():
    """P3 plan tier rounds to nearest 0.01."""
    result = apply_output_precision(0.876, "P3_GROWTH")
    assert result == 0.88


def test_score_binning_p4_protocol():
    """P4 plan tier rounds to nearest 0.001 (near-full precision)."""
    result = apply_output_precision(0.8765, "P4_PROTOCOL")
    assert result == 0.877


def test_score_binning_unknown_plan_falls_back_to_hobbyist():
    result = apply_output_precision(0.876, "UNKNOWN_PLAN")
    assert result == 0.9  # falls back to P1_HOBBYIST bin size of 0.1


def test_score_bins_defined_for_all_plan_tiers():
    expected_plans = {"P1_HOBBYIST", "P2_PROFESSIONAL", "P3_GROWTH", "P4_PROTOCOL"}
    assert set(SCORE_BINS_BY_PLAN.keys()) == expected_plans


def test_honeypot_wallet_detection():
    config = AntiDistillationConfig(
        honeypot_wallets=["0xDEADBEEF0000000000000000000000000000DEAD"]
    )
    svc = AntiDistillationService(config)
    assert svc.is_honeypot_wallet("0xdeadbeef0000000000000000000000000000dead") is True
    assert svc.is_honeypot_wallet("0x1234") is False


def test_honeypot_query_flagged():
    config = AntiDistillationConfig(
        honeypot_wallets=["0xhoneypot"]
    )
    svc = AntiDistillationService(config)
    result = svc.check_query_pattern(
        tenant_id="tenant_1",
        endpoint="/v1/intelligence/wallet",
        query_params={"wallet_address": "0xhoneypot"},
    )
    assert result.is_suspicious is True
    assert result.pattern_type == "honeypot_wallet_query"
    assert result.audit_event_id is not None


def test_rapid_query_detection():
    config = AntiDistillationConfig(
        rapid_diverse_query_threshold=5,
        window_seconds=60,
    )
    svc = AntiDistillationService(config)

    # Fire 5 queries — should not trigger at exactly threshold
    for i in range(4):
        result = svc.check_query_pattern("tenant_2", "/v1/intelligence/wallet", {})
        assert result.is_suspicious is False

    # 5th query crosses threshold
    result = svc.check_query_pattern("tenant_2", "/v1/intelligence/wallet", {})
    assert result.is_suspicious is True
    assert result.pattern_type == "rapid_diverse_query"


def test_normal_query_rate_not_suspicious():
    config = AntiDistillationConfig(
        rapid_diverse_query_threshold=100,
        window_seconds=60,
    )
    svc = AntiDistillationService(config)
    for i in range(10):
        result = svc.check_query_pattern("tenant_3", "/v1/intelligence/wallet", {})
    assert result.is_suspicious is False


def test_alerts_recorded_for_suspicious_patterns():
    config = AntiDistillationConfig(honeypot_wallets=["0xhoneypot2"])
    svc = AntiDistillationService(config)
    svc.check_query_pattern("t", "/endpoint", {"wallet_address": "0xhoneypot2"})
    alerts = svc.get_alerts()
    assert len(alerts) == 1
    assert alerts[0]["pattern_type"] == "honeypot_wallet_query"


def test_stats_summary():
    svc = AntiDistillationService()
    stats = svc.get_stats()
    assert "total_alerts_24h" in stats
    assert "honeypot_queries_24h" in stats
    assert "active_tenant_windows" in stats
