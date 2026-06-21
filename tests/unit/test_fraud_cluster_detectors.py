"""Unit tests for fraud_networks.detectors — pure cluster signal detectors."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.fraud_networks.detectors import (
    detect_agentic_delegation_abuse,
    detect_circular_transfers,
    detect_commerce_abuse,
    detect_reward_farming,
    detect_shared_device,
    detect_shared_ip,
    detect_split_merge,
    detect_wallet_cluster,
)


class TestDetectSharedDevice:
    def test_two_entities_same_device_flagged(self) -> None:
        sessions = [
            {"entity_id": "e1", "device_fingerprint": "fp_abc"},
            {"entity_id": "e2", "device_fingerprint": "fp_abc"},
        ]
        results = detect_shared_device(sessions)
        assert len(results) == 1
        signal, entities, detail = results[0]
        assert signal == "shared_device"
        assert "e1" in entities and "e2" in entities
        assert detail["device_fingerprint"] == "fp_abc"

    def test_single_entity_not_flagged(self) -> None:
        sessions = [{"entity_id": "e1", "device_fingerprint": "fp_abc"}]
        results = detect_shared_device(sessions)
        assert results == []

    def test_missing_fields_skipped(self) -> None:
        sessions = [{"entity_id": "e1"}, {"device_fingerprint": "fp_abc"}]
        results = detect_shared_device(sessions)
        assert results == []


class TestDetectSharedIp:
    def test_shared_ip_detected(self) -> None:
        sessions = [
            {"entity_id": "e1", "ip_address": "1.2.3.4"},
            {"entity_id": "e2", "ip_address": "1.2.3.4"},
            {"entity_id": "e3", "ip_address": "9.9.9.9"},
        ]
        results = detect_shared_ip(sessions)
        assert len(results) == 1
        assert results[0][0] == "shared_ip"

    def test_unique_ips_not_flagged(self) -> None:
        sessions = [
            {"entity_id": "e1", "ip_address": "1.2.3.4"},
            {"entity_id": "e2", "ip_address": "5.6.7.8"},
        ]
        assert detect_shared_ip(sessions) == []


class TestDetectWalletCluster:
    def test_shared_wallet_detected(self) -> None:
        links = [
            {"entity_id": "e1", "wallet_address": "0xABC", "chain": "eth"},
            {"entity_id": "e2", "wallet_address": "0xABC", "chain": "eth"},
        ]
        results = detect_wallet_cluster(links)
        assert len(results) == 1
        assert results[0][0] == "shared_wallet"
        assert "e1" in results[0][1] and "e2" in results[0][1]

    def test_different_chains_not_merged(self) -> None:
        links = [
            {"entity_id": "e1", "wallet_address": "0xABC", "chain": "eth"},
            {"entity_id": "e2", "wallet_address": "0xABC", "chain": "polygon"},
        ]
        results = detect_wallet_cluster(links)
        assert results == []


class TestDetectCircularTransfers:
    def test_triangle_cycle_detected(self) -> None:
        transfers = [
            {"from_entity_id": "e1", "to_entity_id": "e2"},
            {"from_entity_id": "e2", "to_entity_id": "e3"},
            {"from_entity_id": "e3", "to_entity_id": "e1"},
        ]
        results = detect_circular_transfers(transfers)
        assert len(results) >= 1
        assert any(r[0] == "circular_transfer" for r in results)

    def test_no_cycle_in_linear_chain(self) -> None:
        transfers = [
            {"from_entity_id": "e1", "to_entity_id": "e2"},
            {"from_entity_id": "e2", "to_entity_id": "e3"},
        ]
        results = detect_circular_transfers(transfers)
        assert results == []

    def test_self_transfers_ignored(self) -> None:
        transfers = [{"from_entity_id": "e1", "to_entity_id": "e1"}]
        results = detect_circular_transfers(transfers)
        assert results == []


class TestDetectSplitMerge:
    def test_split_merge_pattern_detected(self) -> None:
        transfers = [
            # Splitter e1 → e2, e3, e4
            {"from_entity_id": "e1", "to_entity_id": "e2"},
            {"from_entity_id": "e1", "to_entity_id": "e3"},
            {"from_entity_id": "e1", "to_entity_id": "e4"},
            # All merge into e5
            {"from_entity_id": "e2", "to_entity_id": "e5"},
            {"from_entity_id": "e3", "to_entity_id": "e5"},
            {"from_entity_id": "e4", "to_entity_id": "e5"},
        ]
        results = detect_split_merge(transfers)
        assert len(results) >= 1
        assert any(r[0] == "split_merge" for r in results)

    def test_single_path_not_flagged(self) -> None:
        transfers = [
            {"from_entity_id": "e1", "to_entity_id": "e2"},
            {"from_entity_id": "e2", "to_entity_id": "e3"},
        ]
        results = detect_split_merge(transfers)
        assert results == []


class TestDetectRewardFarming:
    def test_cluster_from_same_referrer_detected(self) -> None:
        events = [
            {"entity_id": f"user{i}", "referrer_id": "ref1", "campaign_id": "c1"}
            for i in range(5)
        ]
        results = detect_reward_farming(events, min_cluster_size=3)
        assert len(results) == 1
        assert results[0][0] == "reward_farming"
        assert results[0][2]["referrer_id"] == "ref1"

    def test_small_cluster_not_flagged(self) -> None:
        events = [
            {"entity_id": "u1", "referrer_id": "ref1", "campaign_id": "c1"},
            {"entity_id": "u2", "referrer_id": "ref1", "campaign_id": "c1"},
        ]
        results = detect_reward_farming(events, min_cluster_size=5)
        assert results == []


class TestDetectAgenticDelegationAbuse:
    def test_agent_with_many_targets_flagged(self) -> None:
        delegations = [{"agent_id": "agent1", "principal_id": "human1", "scope": "full"}]
        transfers = [
            {"from_entity_id": "e1", "to_entity_id": f"target{i}", "attributed_agent_id": "agent1"}
            for i in range(6)
        ]
        results = detect_agentic_delegation_abuse(delegations, transfers, min_agent_out_degree=5)
        assert len(results) >= 1
        assert results[0][0] == "agentic_delegation_abuse"
        assert results[0][2]["agent_id"] == "agent1"

    def test_agent_with_few_targets_not_flagged(self) -> None:
        delegations = [{"agent_id": "agent1", "principal_id": "human1", "scope": "read"}]
        transfers = [
            {"from_entity_id": "e1", "to_entity_id": "t1", "attributed_agent_id": "agent1"},
        ]
        results = detect_agentic_delegation_abuse(delegations, transfers, min_agent_out_degree=5)
        assert results == []


class TestDetectCommerceAbuse:
    def test_high_refund_rate_flagged(self) -> None:
        orders = [{"entity_id": "e1", "order_id": f"ord{i}"} for i in range(10)]
        refunds = [{"entity_id": "e1", "order_id": f"ord{i}"} for i in range(8)]
        results = detect_commerce_abuse(orders, refunds, min_refund_rate=0.6, min_order_count=5)
        assert len(results) == 1
        assert results[0][0] == "commerce_abuse"
        assert results[0][2]["refund_rate"] >= 0.6

    def test_low_refund_rate_not_flagged(self) -> None:
        orders = [{"entity_id": "e1", "order_id": f"ord{i}"} for i in range(10)]
        refunds = [{"entity_id": "e1", "order_id": "ord0"}]
        results = detect_commerce_abuse(orders, refunds, min_refund_rate=0.6, min_order_count=5)
        assert results == []

    def test_below_min_order_count_skipped(self) -> None:
        orders = [{"entity_id": "e1", "order_id": "o1"}]
        refunds = [{"entity_id": "e1", "order_id": "o1"}]
        results = detect_commerce_abuse(orders, refunds, min_refund_rate=0.5, min_order_count=5)
        assert results == []
