"""Unit tests: anti-distillation controls — score binning, honeypot, query detection."""
from __future__ import annotations

import pytest

from services.security.anti_distillation import (
    AntiDistillationConfig,
    AntiDistillationService,
    SCORE_BINS_BY_PLAN,
    apply_output_precision,
)


def test_score_binning_alpha():
    """Alpha plan tier rounds to nearest 0.1."""
    result = apply_output_precision(0.876, "ALPHA")
    assert result == 0.9


def test_score_binning_beta():
    """Beta plan tier rounds to nearest 0.05."""
    result = apply_output_precision(0.876, "BETA")
    assert result == 0.9


def test_score_binning_gamma():
    """Gamma plan tier rounds to nearest 0.01."""
    result = apply_output_precision(0.876, "GAMMA")
    assert result == 0.88


def test_score_binning_delta():
    """Delta plan tier rounds to nearest 0.001 (near-full precision)."""
    result = apply_output_precision(0.8765, "DELTA")
    assert result == 0.877


def test_score_binning_unknown_plan_falls_back_to_alpha():
    result = apply_output_precision(0.876, "UNKNOWN_PLAN")
    assert result == 0.9


def test_score_bins_defined_for_all_plan_tiers():
    expected_plans = {"ALPHA", "BETA", "GAMMA", "DELTA"}
    assert set(SCORE_BINS_BY_PLAN.keys()) == expected_plans


def test_honeypot_wallet_detection():
    config = AntiDistillationConfig(
        honeypot_wallets=["0xDEADBEEF0000000000000000000000000000DEAD"]
    )
    svc = AntiDistillationService(config)
    result = svc.check_honeypot("0xDEADBEEF0000000000000000000000000000DEAD")
    assert result.is_honeypot is True
    assert result.action == "flag"

    result = svc.check_honeypot("0x1234567890123456789012345678901234567890")
    assert result.is_honeypot is False
