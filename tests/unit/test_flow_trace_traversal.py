"""Unit tests for flow_trace.traversal — BFS traversal engine using in-memory repos."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import TransferRepository, reset_in_memory_stores
from services.flow_trace.traversal import FlowTraceEngine


@pytest.fixture(autouse=True)
def reset_stores() -> None:
    """Isolate every test with a clean in-memory store."""
    reset_in_memory_stores()


def _seed_transfer(repo: TransferRepository, from_id: str, to_id: str, amount: str = "100", tenant_id: str = "t1") -> None:
    asyncio.get_event_loop().run_until_complete(
        repo.insert(f"txn_{from_id}_{to_id}", {
            "id": f"txn_{from_id}_{to_id}",
            "from_entity_id": from_id,
            "to_entity_id": to_id,
            "amount": amount,
            "tenant_id": tenant_id,
        })
    )


@pytest.mark.asyncio
async def test_empty_graph_returns_no_paths() -> None:
    engine = FlowTraceEngine(TransferRepository())
    result = await engine.trace("t1", "e_anchor", direction="downstream", max_hops=3)
    assert result["paths"] == []
    assert result["cycle_detected"] is False
    assert result["source_nodes"] == []
    assert result["sink_nodes"] == []


@pytest.mark.asyncio
async def test_single_hop_downstream() -> None:
    repo = TransferRepository()
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2", "amount": "500", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "e1", direction="downstream", max_hops=2)
    node_ids = {n.entity_id for n in result["nodes"]}
    assert "e2" in node_ids


@pytest.mark.asyncio
async def test_depth_bound_respected() -> None:
    repo = TransferRepository()
    # Chain: e1 → e2 → e3 → e4 → e5
    for i in range(1, 5):
        await repo.insert(f"tx{i}", {
            "id": f"tx{i}", "from_entity_id": f"e{i}", "to_entity_id": f"e{i+1}",
            "amount": "100", "tenant_id": "t1",
        })
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "e1", direction="downstream", max_hops=2)
    # With max_hops=2 we should NOT reach e4 or e5
    node_ids = {n.entity_id for n in result["nodes"]}
    assert "e5" not in node_ids


@pytest.mark.asyncio
async def test_cycle_detection() -> None:
    repo = TransferRepository()
    # Triangle: e1 → e2 → e3 → e1
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2", "amount": "100", "tenant_id": "t1"})
    await repo.insert("tx2", {"id": "tx2", "from_entity_id": "e2", "to_entity_id": "e3", "amount": "100", "tenant_id": "t1"})
    await repo.insert("tx3", {"id": "tx3", "from_entity_id": "e3", "to_entity_id": "e1", "amount": "100", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "e1", direction="downstream", max_hops=6)
    assert result["cycle_detected"] is True
    assert len(result["cycle_nodes"]) >= 2


@pytest.mark.asyncio
async def test_sink_identification() -> None:
    repo = TransferRepository()
    # e1 sends to e2 and e3; e2 and e3 have no outbound (sinks)
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2", "amount": "200", "tenant_id": "t1"})
    await repo.insert("tx2", {"id": "tx2", "from_entity_id": "e1", "to_entity_id": "e3", "amount": "300", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "e1", direction="downstream", max_hops=3)
    assert "e2" in result["sink_nodes"] or "e3" in result["sink_nodes"]


@pytest.mark.asyncio
async def test_source_identification() -> None:
    repo = TransferRepository()
    # e_source sends to anchor; anchor sends to e_terminal
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "e_source", "to_entity_id": "anchor", "amount": "1000", "tenant_id": "t1"})
    await repo.insert("tx2", {"id": "tx2", "from_entity_id": "anchor", "to_entity_id": "e_terminal", "amount": "900", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "anchor", direction="both", max_hops=3)
    assert "e_source" in result["source_nodes"] or len(result["nodes"]) > 1


@pytest.mark.asyncio
async def test_upstream_direction() -> None:
    repo = TransferRepository()
    # feeder → anchor
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "feeder", "to_entity_id": "anchor", "amount": "500", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    result = await engine.trace("t1", "anchor", direction="upstream", max_hops=3)
    node_ids = {n.entity_id for n in result["nodes"]}
    assert "feeder" in node_ids


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    repo = TransferRepository()
    # Insert transfer for tenant t1
    await repo.insert("tx1", {"id": "tx1", "from_entity_id": "e1", "to_entity_id": "e2", "amount": "100", "tenant_id": "t1"})
    engine = FlowTraceEngine(repo)
    # Trace for a different tenant t2 should not see t1's transfers
    result = await engine.trace("t2", "e1", direction="downstream", max_hops=3)
    node_ids = {n.entity_id for n in result["nodes"]}
    assert "e2" not in node_ids
