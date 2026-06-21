"""Unit tests for fraud_networks.scoring — pure risk scoring functions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.fraud_networks.scoring import (
    score_cluster_risk,
    score_confidence,
    score_edge_risk,
    score_entity_risk,
    score_path_risk,
)


class TestScoreEntityRisk:
    def test_zero_inputs_returns_low_score(self) -> None:
        score = score_entity_risk(
            fraud_score=0.0,
            transfer_volume_usd=0.0,
            shared_device_count=0,
            shared_ip_count=0,
            velocity_flag=False,
            account_age_days=365,
        )
        assert 0.0 <= score <= 15.0

    def test_max_inputs_returns_100(self) -> None:
        score = score_entity_risk(
            fraud_score=100.0,
            transfer_volume_usd=10_000_000.0,
            shared_device_count=10,
            shared_ip_count=10,
            velocity_flag=True,
            account_age_days=1,
        )
        assert score == 100.0

    def test_new_account_adds_risk(self) -> None:
        old = score_entity_risk(0, 0, 0, 0, False, 365)
        new = score_entity_risk(0, 0, 0, 0, False, 1)
        assert new > old

    def test_velocity_flag_adds_risk(self) -> None:
        without = score_entity_risk(50, 1000, 0, 0, False, 100)
        with_ = score_entity_risk(50, 1000, 0, 0, True, 100)
        assert with_ > without

    def test_score_bounded_0_to_100(self) -> None:
        for fraud_score in [0, 50, 100]:
            score = score_entity_risk(fraud_score, 1_000_000, 10, 10, True, 1)
            assert 0.0 <= score <= 100.0


class TestScoreEdgeRisk:
    def test_circular_edge_scores_higher(self) -> None:
        non_circular = score_edge_risk(50, 50, 10, 1000, False, "TRANSFERRED")
        circular = score_edge_risk(50, 50, 10, 1000, True, "TRANSFERRED")
        assert circular > non_circular

    def test_high_risk_link_type_increases_score(self) -> None:
        base = score_edge_risk(30, 30, 5, 500, False, "TRANSFERRED")
        high = score_edge_risk(30, 30, 5, 500, False, "MEMBER_OF_FRAUD_NETWORK")
        assert high >= base

    def test_score_bounded(self) -> None:
        score = score_edge_risk(100, 100, 1000, 10_000_000, True, "USES_MULE")
        assert 0.0 <= score <= 100.0


class TestScorePathRisk:
    def test_cycle_increases_path_risk(self) -> None:
        no_cycle = score_path_risk(3, [50, 60, 70], False, False, 1000.0)
        with_cycle = score_path_risk(3, [50, 60, 70], True, False, 1000.0)
        assert with_cycle > no_cycle

    def test_mule_node_increases_risk(self) -> None:
        no_mule = score_path_risk(3, [50, 50, 50], False, False, 500.0)
        with_mule = score_path_risk(3, [50, 50, 50], False, True, 500.0)
        assert with_mule > no_mule

    def test_empty_risk_scores_defaults_gracefully(self) -> None:
        score = score_path_risk(1, [], False, False, 0.0)
        assert 0.0 <= score <= 100.0


class TestScoreClusterRisk:
    def test_high_severity_network_type_adds_risk(self) -> None:
        low = score_cluster_risk([50], [40], 0, 2, "unknown")
        high = score_cluster_risk([50], [40], 0, 2, "mule_network")
        assert high > low

    def test_cycles_increase_score(self) -> None:
        no_cycles = score_cluster_risk([50], [40], 0, 3, "unknown")
        with_cycles = score_cluster_risk([50], [40], 5, 3, "unknown")
        assert with_cycles > no_cycles

    def test_empty_members_returns_valid_score(self) -> None:
        score = score_cluster_risk([], [], 0, 0, "unknown")
        assert 0.0 <= score <= 100.0


class TestScoreConfidence:
    def test_zero_inputs_low_confidence(self) -> None:
        conf = score_confidence(0, 0, 1, False, False)
        assert 0.0 <= conf <= 0.1

    def test_full_evidence_high_confidence(self) -> None:
        conf = score_confidence(20, 5, 50, True, True)
        assert conf >= 0.9

    def test_circular_transfer_boosts_confidence(self) -> None:
        without = score_confidence(5, 2, 5, False, False)
        with_ = score_confidence(5, 2, 5, True, False)
        assert with_ > without

    def test_confidence_bounded_0_to_1(self) -> None:
        conf = score_confidence(100, 100, 100, True, True)
        assert 0.0 <= conf <= 1.0
