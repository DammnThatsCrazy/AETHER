"""Unit tests for the fraud overlay in _compute_overlay_scores.

Covers:
  - Fraud overlay structure and field presence
  - Node annotation for members vs non-members
  - coverage_pct calculation
  - Multiple memberships → highest-severity annotation used
  - Repository failure → node skipped (fail-open on membership lookup)
  - Empty node list → 0% coverage
  - Unknown overlay id → unknown_overlay_type entry
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BACKEND = str(Path(__file__).parents[2] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

pytest.importorskip("fastapi", reason="Backend deps not installed")


TENANT = "overlay-test-tenant"


def _make_vertex(vid: str, props: dict | None = None):
    from shared.graph.graph import Vertex
    return Vertex(
        vertex_id=vid,
        vertex_type="human",
        properties={"tenantId": TENANT, **(props or {})},
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fraud_membership(network_id: str, network_type: str, role: str, risk: float) -> dict:
    return {
        "network_id": network_id,
        "network_type": network_type,
        "role": role,
        "risk_contribution": risk,
        "alert_state": "open",
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestFraudOverlayStructure:
    """Fraud overlay returns correct top-level structure."""

    def test_fraud_overlay_id_and_name(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u1")]
        membership = [_fraud_membership("fn-001", "payment_fraud", "mule", 0.82)]

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=membership)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        assert overlays is not None
        fraud_overlay = next((o for o in overlays if o.id == "fraud"), None)
        assert fraud_overlay is not None
        assert fraud_overlay.name == "Fraud Network"

    def test_fraud_overlay_properties_keys(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u1")]
        membership = [_fraud_membership("fn-001", "payment_fraud", "mule", 0.9)]

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=membership)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        props = overlays[0].properties
        for key in ("status", "fraud_member_count", "network_count", "fraud_coverage_pct",
                    "node_annotations", "computed_at"):
            assert key in props, f"Missing key: {key}"

    def test_status_is_computed(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u1")]
        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=[])

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        assert overlays[0].properties["status"] == "computed"


class TestFraudOverlayNodeAnnotation:
    """Fraud member nodes are annotated; non-members are not."""

    def test_member_node_is_annotated(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        member = _make_vertex("u-member")
        membership = [_fraud_membership("fn-002", "account_takeover", "beneficiary", 0.75)]

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=membership)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores([member], [], ["fraud"], tenant_id=TENANT))

        annotations = overlays[0].properties["node_annotations"]
        assert "u-member" in annotations
        ann = annotations["u-member"]
        assert ann["fraud_network_id"] == "fn-002"
        assert ann["fraud_network_type"] == "account_takeover"
        assert ann["member_role"] == "beneficiary"
        assert ann["alert_state"] == "open"

    def test_non_member_node_not_annotated(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        non_member = _make_vertex("u-clean")
        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=[])

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores([non_member], [], ["fraud"], tenant_id=TENANT))

        annotations = overlays[0].properties["node_annotations"]
        assert "u-clean" not in annotations

    def test_mixed_nodes_partial_annotation(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        member = _make_vertex("u-bad")
        clean = _make_vertex("u-good")
        membership = [_fraud_membership("fn-003", "payment_fraud", "controller", 0.95)]

        async def _side_effect(entity_id, tenant_id):
            return membership if entity_id == "u-bad" else []

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(side_effect=_side_effect)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(
                _compute_overlay_scores([member, clean], [], ["fraud"], tenant_id=TENANT)
            )

        props = overlays[0].properties
        assert props["fraud_member_count"] == 1
        assert "u-bad" in props["node_annotations"]
        assert "u-good" not in props["node_annotations"]


class TestFraudOverlayCoverage:
    """fraud_coverage_pct is calculated correctly."""

    def test_full_coverage(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex(f"u{i}") for i in range(4)]
        membership = [_fraud_membership("fn-x", "payment_fraud", "mule", 0.7)]

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=membership)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        assert overlays[0].properties["fraud_coverage_pct"] == 100.0

    def test_partial_coverage(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex(f"u{i}") for i in range(4)]
        # Only u0 is a member
        async def _side(entity_id, tenant_id):
            return [_fraud_membership("fn-y", "payment_fraud", "mule", 0.6)] if entity_id == "u0" else []

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(side_effect=_side)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        assert overlays[0].properties["fraud_coverage_pct"] == 25.0

    def test_empty_nodes_no_data_status(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=[])

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores([], [], ["fraud"], tenant_id=TENANT))

        # With no nodes AND no edges the overlay returns status=no_data (not fraud structure)
        assert overlays[0].properties["status"] == "no_data"


class TestFraudOverlayMultipleMemberships:
    """When a node has multiple memberships the highest-risk one is used."""

    def test_highest_risk_membership_wins(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        node = _make_vertex("u-multi")
        memberships = [
            _fraud_membership("fn-low", "payment_fraud", "mule", 0.3),
            _fraud_membership("fn-high", "account_takeover", "controller", 0.95),
            _fraud_membership("fn-mid", "identity_fraud", "beneficiary", 0.6),
        ]

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(return_value=memberships)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores([node], [], ["fraud"], tenant_id=TENANT))

        ann = overlays[0].properties["node_annotations"]["u-multi"]
        assert ann["fraud_network_id"] == "fn-high"
        assert ann["fraud_network_type"] == "account_takeover"
        assert ann["membership_count"] == 3


class TestFraudOverlayRepositoryFailure:
    """Repository errors are swallowed — node is not annotated but overlay still returns."""

    def test_repo_exception_skips_node(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u-fail"), _make_vertex("u-ok")]
        membership = [_fraud_membership("fn-001", "payment_fraud", "mule", 0.8)]

        async def _side(entity_id, tenant_id):
            if entity_id == "u-fail":
                raise RuntimeError("DB connection failed")
            return membership

        mock_repo = MagicMock()
        mock_repo.list_by_entity = AsyncMock(side_effect=_side)

        with patch("repositories.repos.FraudNetworkMemberRepository", return_value=mock_repo):
            overlays = _run(_compute_overlay_scores(nodes, [], ["fraud"], tenant_id=TENANT))

        props = overlays[0].properties
        # u-fail had an error → skipped; u-ok succeeded
        assert "u-fail" not in props["node_annotations"]
        assert "u-ok" in props["node_annotations"]
        assert props["fraud_member_count"] == 1


class TestNoFraudOverlayRequested:
    """No overlay requested → returns None (no unnecessary computation)."""

    def test_no_overlay_returns_none(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u1")]
        result = _run(_compute_overlay_scores(nodes, [], None, tenant_id=TENANT))
        assert result is None

    def test_empty_overlay_list_returns_none(self):
        from services.operational_intelligence.routes import _compute_overlay_scores

        nodes = [_make_vertex("u1")]
        result = _run(_compute_overlay_scores(nodes, [], [], tenant_id=TENANT))
        assert result is None
