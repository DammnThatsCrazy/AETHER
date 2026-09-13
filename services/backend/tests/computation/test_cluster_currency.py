"""Currency-awareness regression tests for the cluster economic rollup.

The cluster economic summary must NEVER sum member money across currencies into
one scalar, and must NOT fabricate "USD" when the members' real currency is
something else (or is genuinely mixed / unknown). These tests pin that contract
on ``services.cluster.routes.get_cluster_economic`` directly, mocking the graph
read helpers so only the rollup logic is exercised.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("AETHER_CREDENTIAL_BACKEND", "in_memory")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import services.cluster.routes as routes
from shared.graph.graph import Vertex

TENANT_ID = "tenant-cluster-cur-001"
CLUSTER_ID = "cluster-cur-001"


def _request(tenant_id: str = TENANT_ID):
    req = MagicMock()
    tenant = MagicMock()
    tenant.tenant_id = tenant_id
    tenant.require_permission = MagicMock()
    req.state.tenant = tenant
    return req


def _cluster_vertex(props: dict | None = None) -> Vertex:
    base = {"tenantId": TENANT_ID}
    base.update(props or {})
    return Vertex(vertex_type="ECONOMIC_CLUSTER", vertex_id=CLUSTER_ID, properties=base)


def _member(vertex_id: str, props: dict) -> Vertex:
    return Vertex(vertex_type="ENTITY", vertex_id=vertex_id, properties=props)


async def _run(cluster_props: dict, members: list[Vertex]) -> dict:
    """Invoke the handler with graph helpers mocked; return the ``data`` block."""
    with patch.object(
        routes, "_get_cluster_vertex",
        AsyncMock(return_value=_cluster_vertex(cluster_props)),
    ), patch.object(
        routes, "_get_cluster_member_vertices",
        AsyncMock(return_value=members),
    ):
        result = await routes.get_cluster_economic(
            CLUSTER_ID, _request(), TENANT_ID, MagicMock()
        )
    return result["data"]


@pytest.mark.asyncio
async def test_mixed_currency_members_are_not_summed_into_one_scalar():
    """EUR + GBP members must produce a per-currency breakdown, not a blended sum."""
    members = [
        _member("m-eur-1", {"currency": "EUR", "revenue": 100, "spend": 30}),
        _member("m-eur-2", {"currency": "EUR", "revenue": 50, "spend": 20}),
        _member("m-gbp-1", {"currency": "GBP", "revenue": 40, "spend": 10}),
    ]
    data = await _run({}, members)

    # A by_currency breakdown appears with each native currency kept apart.
    assert set(data["by_currency"].keys()) == {"EUR", "GBP"}
    assert data["by_currency"]["EUR"]["revenue"] == "150"
    assert data["by_currency"]["EUR"]["spend"] == "50"
    assert data["by_currency"]["EUR"]["member_count"] == 2
    assert data["by_currency"]["GBP"]["revenue"] == "40"
    assert data["by_currency"]["GBP"]["member_count"] == 1

    # The scalar total is NOT the mixed-currency sum (150 EUR + 40 GBP == 190).
    assert data["total_revenue"] != 190.0
    # It is the dominant (EUR — most members) currency's slice only.
    assert data["total_revenue"] == 150.0
    assert data["is_mixed_currency"] is True


@pytest.mark.asyncio
async def test_usd_not_hardcoded_when_members_are_eur_gbp():
    """No member is USD, so USD must never appear in the response."""
    members = [
        _member("m-eur-1", {"currency": "EUR", "revenue": 100, "spend": 30}),
        _member("m-gbp-1", {"currency": "GBP", "revenue": 40, "spend": 10}),
    ]
    data = await _run({}, members)

    # Mixed currency -> honest None, never a fabricated "USD".
    assert data["currency"] is None
    assert data["currency"] != "USD"
    assert "USD" not in data["by_currency"]
    # Dominant currency is a real currency the members actually use.
    assert data["dominant_currency"] in {"EUR", "GBP"}


@pytest.mark.asyncio
async def test_single_currency_cluster_reports_that_currency():
    """A single-currency cluster keeps an unambiguous scalar rollup and currency."""
    members = [
        _member("m-eur-1", {"currency": "EUR", "revenue": 100, "spend": 30}),
        _member("m-eur-2", {"currency": "EUR", "revenue": 50, "spend": 20}),
    ]
    data = await _run({}, members)

    assert data["currency"] == "EUR"
    assert data["is_mixed_currency"] is False
    assert set(data["by_currency"].keys()) == {"EUR"}
    assert data["total_revenue"] == 150.0
    assert data["total_spend"] == 50.0


@pytest.mark.asyncio
async def test_members_without_currency_fall_back_to_cluster_currency_not_usd():
    """Members lacking a currency inherit the cluster's declared currency."""
    members = [
        _member("m-1", {"revenue": 10, "spend": 4}),
        _member("m-2", {"revenue": 5, "spend": 1}),
    ]
    data = await _run({"currency": "JPY"}, members)

    assert data["currency"] == "JPY"
    assert set(data["by_currency"].keys()) == {"JPY"}
    assert data["by_currency"]["JPY"]["revenue"] == "15"
    assert "USD" not in data["by_currency"]


@pytest.mark.asyncio
async def test_unknown_currency_is_honest_none_not_usd():
    """No member currency and no cluster currency -> unknown bucket, currency None."""
    members = [
        _member("m-1", {"revenue": 10, "spend": 4}),
    ]
    data = await _run({}, members)

    assert data["currency"] is None
    assert data["dominant_currency"] is None
    assert set(data["by_currency"].keys()) == {"unknown"}
    # Single implicit currency still yields a best-effort scalar (not lost).
    assert data["total_revenue"] == 10.0


@pytest.mark.asyncio
async def test_absent_member_revenue_is_not_coerced_to_zero():
    """A currency whose members reported no revenue exposes None, not 0."""
    members = [
        _member("m-eur-1", {"currency": "EUR", "spend": 20}),  # no revenue
        _member("m-gbp-1", {"currency": "GBP", "revenue": 40, "spend": 10}),
    ]
    data = await _run({}, members)

    assert data["by_currency"]["EUR"]["revenue"] is None
    assert data["by_currency"]["EUR"]["spend"] == "20"
    assert data["by_currency"]["GBP"]["revenue"] == "40"
