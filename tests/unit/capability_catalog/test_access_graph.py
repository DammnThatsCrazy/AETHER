"""Capability access graph — bounded agents→servers→capabilities derivation (PR 4).

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (``test_capability_risk.py``, ``test_capability_authority_routes.py``) — so
permission gates and tenant scoping are exercised without standing up the middleware.

The load-bearing test here is ``test_never_observed_agent_reports_unknown_not_zero``. It
guards the property the surface exists for: an agent nobody has observed must produce
``neighborhood_known: false`` with ``null`` counts, never ``0``. "0 capabilities reached"
is a claim about the world; when no installation was ever recorded, the only true answer
is "we do not know". ``_zero_numbers`` (copied from ``test_capability_risk.py``) walks the
whole response recursively and fails on any zero-valued number anywhere in it, so a
future refactor cannot reintroduce the lie through a new field.

The other invariant with its own test is the tri-state ``authorized``: ``null`` when the
authorization read could not be completed, never ``false``. Reporting ``false`` there
reads as "unauthorized" and points an operator at a revocation that should not happen —
the exact bug just fixed one module over in ``risk_service``.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import BadRequestError, ForbiddenError

import services.agent_access_intelligence.access_graph as access_graph
import services.agent_access_intelligence.access_graph_routes as access_graph_routes
from services.agent_access_intelligence.access_graph import (
    EDGE_AUTHORIZED_FOR,
    EDGE_CONNECTS_TO,
    EDGE_EXPOSES,
    MAX_DEPTH,
    capability_access_graph_service,
)
from services.agent_access_intelligence.authority import server_ref_for
from services.agent_access_intelligence.authority_routes import (
    CapabilityAuthorizationGrant,
    grant_authorization,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service


class FakeProducer:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _seed(
    tenant_id: str = "t1",
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: Optional[str] = "search",
    server_name: Optional[str] = "srvX",
    server_url: Optional[str] = None,
    provider: str = "acme",
) -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "server_url": server_url,
        "provider": provider,
        "risk_level": "high",
    })
    return result["capability_id"]


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``neighborhood_known: false`` is the honest
    answer, not a count. Copied from ``test_capability_risk.py`` so both surfaces are held
    to the same rule by the same check."""
    hits: list[str] = []
    if isinstance(value, bool):
        return hits
    if isinstance(value, (int, float)):
        if value == 0:
            hits.append(path)
        return hits
    if isinstance(value, dict):
        for key, item in value.items():
            hits.extend(_zero_numbers(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_zero_numbers(item, f"{path}[{index}]"))
    return hits


def _edges(data: dict, kind: str) -> list[dict]:
    return [e for e in data["edges"] if e["kind"] == kind]


def _node_ids(data: dict) -> set[str]:
    return {n["node_id"] for n in data["nodes"]}


# ══════════════════════════════════════════════════════════════════════════════
# UNKNOWN IS NEVER ZERO
# ══════════════════════════════════════════════════════════════════════════════

async def test_never_observed_agent_reports_unknown_not_zero():
    await _seed()  # a populated tenant, so "empty store" is not what makes this pass
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t1"),
            agent_id="ghost-agent",
            capability_id=None,
            server_key=None,
            depth=1,
            limit=500,
        )
    )["data"]

    assert data["neighborhood_known"] is False
    assert data["complete"] is False
    assert data["missing_inputs"], "an absent input must be named, not silently dropped"
    assert any("capability_installations" in e for e in data["missing_inputs"])
    assert any("ghost-agent" in e for e in data["missing_inputs"])

    # Every count is null. Not 0 — 0 would be a claim we have no evidence for.
    assert set(data["counts"]) == {
        "nodes",
        "edges",
        "agents",
        "servers",
        "capabilities",
        "edges_connects_to",
        "edges_exposes",
        "edges_authorized_for",
        "edges_authorized",
        "edges_unauthorized",
    }
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when it could not be computed"

    # And nowhere else in the response either.
    assert _zero_numbers(data) == []

    assert "UNKNOWN" in data["summary"]
    assert "not empty" in data["summary"]


async def test_unknown_capability_id_is_unknown_not_an_existence_oracle():
    await _seed("t1")
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t2"),
            agent_id=None,
            capability_id="cap_does_not_exist",
            server_key=None,
            depth=1,
            limit=500,
        )
    )["data"]
    assert data["neighborhood_known"] is False
    assert any("capability_catalog" in e for e in data["missing_inputs"])
    assert _zero_numbers(data) == []


async def test_unobserved_server_key_is_unknown_not_empty():
    await _seed("t1", server_name="srvX")
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t1"),
            agent_id=None,
            capability_id=None,
            server_key="never-seen-server",
            depth=1,
            limit=500,
        )
    )["data"]
    assert data["neighborhood_known"] is False
    assert any("never-seen-server" in e for e in data["missing_inputs"])
    assert _zero_numbers(data) == []


async def test_capability_without_server_binding_is_unknown_not_zero():
    # A provider action with no server → no installation row and no key to join on.
    cap_id = await _seed(server_name=None, server_url=None, tool_name="transfer")
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t1"),
            agent_id=None,
            capability_id=cap_id,
            server_key=None,
            depth=1,
            limit=500,
        )
    )["data"]
    assert data["neighborhood_known"] is False
    assert any("capability_server_binding" in e for e in data["missing_inputs"])
    assert all(v is None for v in data["counts"].values())
    # The anchor node is still returned as evidence — a list is not a total.
    assert _node_ids(data) == {f"capability:{cap_id}"}


# ══════════════════════════════════════════════════════════════════════════════
# NODE IDS AND THE STRUCTURAL WALK
# ══════════════════════════════════════════════════════════════════════════════

async def test_node_ids_agree_with_server_ref_for():
    cap_id = await _seed(server_name="srvX")
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t1"),
            agent_id="agentA",
            capability_id=None,
            server_key=None,
            depth=MAX_DEPTH,
            limit=500,
        )
    )["data"]

    expected_ref = server_ref_for("t1", "srvX")
    assert _node_ids(data) == {
        "agent:agentA",
        f"server:{expected_ref}",
        f"capability:{cap_id}",
    }
    server = next(n for n in data["nodes"] if n["kind"] == "server")
    assert server["server_ref"] == expected_ref
    assert server["server_ref"].startswith("srv_")
    # The digest, never the raw observed key: a ":" or "*" in a server URL must not be
    # able to corrupt an id, and this is exactly what the authorization rows are keyed by.
    assert "srvX" not in server["node_id"]
    assert server["server_key"] == "srvX"


async def test_server_url_with_a_colon_cannot_corrupt_a_node_id():
    await _seed(server_name=None, server_url="https://mcp.example.com:8443/v1")
    data = (
        await access_graph_routes.read_access_neighborhood(
            _request("t1"),
            agent_id="agentA",
            capability_id=None,
            server_key=None,
            depth=1,
            limit=500,
        )
    )["data"]
    server = next(n for n in data["nodes"] if n["kind"] == "server")
    # Exactly two segments: "server" and the digest. A raw URL would produce more.
    assert server["node_id"].count(":") == 1
    assert server["node_id"] == f"server:{server_ref_for('t1', 'https://mcp.example.com:8443/v1')}"


async def test_depth_separates_invoked_from_merely_server_reachable():
    """One hop reaches what the agent was observed invoking; two hops reach the rest of
    the server. That is the ``invoked`` / ``server_reachable`` distinction ``risk_service``
    draws, expressed as distance — conflating them lets a summary claim an agent was
    "observed reaching" every tool on a server it touched once."""
    invoked = await _seed(source_event_id="e1", agent_id="agentA", tool_name="search")
    # Same server, invoked by a different agent: server-reachable for agentA, not invoked.
    reachable = await _seed(source_event_id="e2", agent_id="agentB", tool_name="write")

    one = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=1
    )
    assert one["neighborhood_known"] is True
    assert one["counts"]["servers"] == 1
    assert _node_ids(one) == {
        "agent:agentA",
        f"server:{server_ref_for('t1', 'srvX')}",
        f"capability:{invoked}",
    }
    assert [e["basis"] for e in _edges(one, EDGE_AUTHORIZED_FOR)] == ["invoked"]

    two = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=2
    )
    assert f"capability:{reachable}" in _node_ids(two)
    assert len(_edges(two, EDGE_EXPOSES)) == 2
    assert {
        e["target"]: e["basis"] for e in _edges(two, EDGE_AUTHORIZED_FOR)
    } == {
        f"capability:{invoked}": "invoked",
        f"capability:{reachable}": "server_reachable",
    }


async def test_capability_anchor_finds_the_agents_that_reach_it():
    cap_id = await _seed(source_event_id="e1", agent_id="agentA")
    await _seed(source_event_id="e2", agent_id="agentB")  # same server + tool

    data = await capability_access_graph_service.neighborhood(
        "t1", capability_id=cap_id, depth=MAX_DEPTH
    )
    assert data["neighborhood_known"] is True
    assert {"agent:agentA", "agent:agentB"} <= _node_ids(data)
    assert data["counts"]["agents"] == 2
    assert {e["source"] for e in _edges(data, EDGE_AUTHORIZED_FOR)} == {
        "agent:agentA",
        "agent:agentB",
    }


async def test_server_anchor_accepts_the_url_form_the_catalog_stores():
    await _seed(server_name=None, server_url="https://mcp.example.com/v1")
    data = await capability_access_graph_service.neighborhood(
        "t1", server_key="HTTPS://MCP.EXAMPLE.COM/v1", depth=MAX_DEPTH
    )
    # Case-insensitive, sanitized comparison — the same rule
    # `CapabilityAuthorityService._canonical_server_key` applies at grant time, so an
    # operator naming the server either way lands on the same node id.
    assert data["neighborhood_known"] is True
    assert data["anchor"]["server_ref"] == server_ref_for("t1", "https://mcp.example.com/v1")
    assert data["counts"]["agents"] == 1
    assert data["counts"]["capabilities"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# AUTHORIZED IS TRI-STATE
# ══════════════════════════════════════════════════════════════════════════════

async def test_authorized_is_computed_true_or_false_when_the_read_succeeds():
    cap_id = await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")  # second capability, same server

    before = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    assert {e["authorized"] for e in _edges(before, EDGE_AUTHORIZED_FOR)} == {False}
    # A computed zero is legitimate: we checked, and nothing was authorized.
    assert before["counts"]["edges_authorized"] == 0
    assert before["counts"]["edges_unauthorized"] == 2

    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )
    after = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    granted = [
        e for e in _edges(after, EDGE_AUTHORIZED_FOR) if e["target"] == f"capability:{cap_id}"
    ]
    assert [e["authorized"] for e in granted] == [True]
    assert after["counts"]["edges_authorized"] == 1
    assert after["counts"]["edges_unauthorized"] == 1


async def test_server_wide_grant_authorizes_the_connects_to_edge():
    await _seed(server_name="srvX")
    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", server_key="srvX"),
        _request("t1"),
        producer=FakeProducer(),
    )
    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    connects = _edges(data, EDGE_CONNECTS_TO)
    assert [e["authorized"] for e in connects] == [True]
    assert connects[0]["authorization_scope"] == "server"
    # And it covers every capability on that server.
    assert {e["authorized"] for e in _edges(data, EDGE_AUTHORIZED_FOR)} == {True}


async def test_authorized_is_null_when_the_authorization_read_truncated(monkeypatch):
    """The rule this package was bitten by: a split that could not be computed is null.

    Defaulting to ``false`` reads as "unauthorized" and points an operator at a
    revocation that should not happen — the exact bug just fixed in ``risk_service``.
    """
    cap_id = await _seed()
    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )

    async def _truncated(self, tenant_id, *, agent_id, missing):
        missing.append("capability_authorizations:scan_truncated")
        return None

    monkeypatch.setattr(
        access_graph.CapabilityRiskService, "_active_authorizations", _truncated
    )

    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    assert data["neighborhood_known"] is False
    assert "capability_authorizations:scan_truncated" in data["missing_inputs"]
    assert data["truncation"]["authorizations_truncated"] is True
    assert all(v is None for v in data["counts"].values())
    # Never False. The capability IS authorized; a false here would be a lie in the
    # dangerous direction.
    for edge in _edges(data, EDGE_AUTHORIZED_FOR) + _edges(data, EDGE_CONNECTS_TO):
        assert edge["authorized"] is None


async def test_exposes_edges_carry_null_authorization_marked_not_applicable():
    await _seed()
    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    for edge in _edges(data, EDGE_EXPOSES):
        # Authorization is agent-relative and this edge has no agent — the scope says so
        # rather than leaving a bare null to be read as "unknown" or "denied".
        assert edge["authorized"] is None
        assert edge["authorization_scope"] == "not_applicable"


# ══════════════════════════════════════════════════════════════════════════════
# BOUNDS — depth cap, node budget, truncation disclosure
# ══════════════════════════════════════════════════════════════════════════════

async def test_depth_cap_is_enforced_and_disclosed():
    await _seed()
    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=7
    )
    assert data["depth"] == {
        "requested": 7,
        "applied": MAX_DEPTH,
        "max_depth": MAX_DEPTH,
        "capped": True,
    }
    assert data["truncation"]["depth_capped"] is True
    # The caller asked a wider question than this surface answers, so the counts are not
    # an answer to their question.
    assert f"graph:depth_capped_at_{MAX_DEPTH}" in data["missing_inputs"]
    assert all(v is None for v in data["counts"].values())

    # The route enforces the same cap at its edge rather than relying on the clamp alone.
    depth_param = inspect.signature(
        access_graph_routes.read_access_neighborhood
    ).parameters["depth"].default
    assert any(getattr(m, "le", None) == MAX_DEPTH for m in depth_param.metadata)


async def test_node_budget_is_disclosed_and_withholds_counts():
    for index in range(6):
        await _seed(source_event_id=f"e{index}", tool_name=f"tool{index}")
    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH, limit=3
    )
    assert len(data["nodes"]) == 3
    assert data["truncation"]["node_limit_reached"] is True
    assert "graph:node_limit_reached" in data["missing_inputs"]
    assert data["complete"] is False
    # A truncated graph must not claim completeness, and its counts are not totals.
    assert all(v is None for v in data["counts"].values())
    assert data["counts_scope"] == "not_computed"
    assert data["limits"]["nodes_applied"] == 3


async def test_a_complete_neighborhood_says_so():
    await _seed()
    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    assert data["complete"] is True
    assert data["missing_inputs"] == []
    assert data["truncation"] == {
        "node_limit_reached": False,
        "edge_limit_reached": False,
        "depth_capped": False,
        "catalog_truncated": False,
        "installations_truncated": False,
        "authorizations_truncated": False,
    }
    assert "not a proof of total reach" in data["summary"]
    assert data["basis"] == "observed_only"


# ══════════════════════════════════════════════════════════════════════════════
# TENANT SCOPING, PERMISSIONS, ANCHOR RULE
# ══════════════════════════════════════════════════════════════════════════════

async def test_another_tenants_nodes_never_appear():
    mine = await _seed("t1", source_event_id="e1", agent_id="agentA", tool_name="mine")
    theirs = await _seed("t2", source_event_id="e2", agent_id="agentB", tool_name="theirs")

    data = await capability_access_graph_service.neighborhood(
        "t1", agent_id="agentA", depth=MAX_DEPTH
    )
    ids = _node_ids(data)
    assert f"capability:{mine}" in ids
    assert f"capability:{theirs}" not in ids
    assert "agent:agentB" not in ids
    # Server refs are salted by tenant, so even the same observed server name is a
    # different node in another tenant.
    assert server_ref_for("t2", "srvX") not in "".join(ids)

    # t1's agent is unknown in t2 — identical to an absent one, never t1's graph.
    cross = await capability_access_graph_service.neighborhood("t2", agent_id="agentA")
    assert cross["neighborhood_known"] is False
    assert _zero_numbers(cross) == []


async def test_routes_require_read_permission():
    await _seed()
    with pytest.raises(ForbiddenError):
        await access_graph_routes.read_access_neighborhood(
            _request("t1", permissions=[]),
            agent_id="agentA",
            capability_id=None,
            server_key=None,
            depth=1,
            limit=500,
        )
    with pytest.raises(ForbiddenError):
        await access_graph_routes.read_access_graph_summary(_request("t1", permissions=[]))


async def test_exactly_one_anchor_is_required():
    with pytest.raises(BadRequestError):
        await capability_access_graph_service.neighborhood("t1")
    with pytest.raises(BadRequestError):
        await capability_access_graph_service.neighborhood(
            "t1", agent_id="agentA", capability_id="cap_1"
        )
    with pytest.raises(BadRequestError):
        await capability_access_graph_service.neighborhood(
            "t1", agent_id="agentA", server_key="srvX"
        )
    with pytest.raises(BadRequestError):
        await capability_access_graph_service.neighborhood(
            "t1", agent_id="agentA", capability_id="cap_1", server_key="srvX"
        )
    # Blank is not an anchor — it is an absent one.
    with pytest.raises(BadRequestError):
        await capability_access_graph_service.neighborhood("t1", agent_id="   ")


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

async def test_summary_counts_by_node_and_edge_kind():
    cap_id = await _seed(source_event_id="e1", agent_id="agentA", tool_name="search")
    await _seed(source_event_id="e2", agent_id="agentB", tool_name="write")
    await _seed("t2", source_event_id="e3", agent_id="agentZ", tool_name="other")
    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_id),
        _request("t1"),
        producer=FakeProducer(),
    )

    data = (await access_graph_routes.read_access_graph_summary(_request("t1")))["data"]
    assert data["summary_known"] is True
    assert data["complete"] is True
    assert data["observed_any"] is True
    counts = data["counts"]
    assert counts["agents"] == 2
    assert counts["servers"] == 1  # both agents on srvX; t2's server is not counted
    assert counts["capabilities"] == 2
    assert counts["edges_connects_to"] == 2
    assert counts["edges_exposes"] == 2
    assert counts["edges_authorized_for"] == 4  # each agent reaches both server tools
    assert counts["authorizations_active"] == 1
    assert counts["nodes"] == counts["agents"] + counts["servers"] + counts["capabilities"]


async def test_summary_withholds_every_count_when_a_read_truncates(monkeypatch):
    await _seed()

    async def _truncated(self, tenant_id, *, agent_id, missing):
        missing.append("capability_authorizations:scan_truncated")
        return None

    monkeypatch.setattr(
        access_graph.CapabilityRiskService, "_active_authorizations", _truncated
    )
    data = await capability_access_graph_service.summary("t1")
    assert data["summary_known"] is False
    assert data["complete"] is False
    assert all(v is None for v in data["counts"].values())
    assert "UNKNOWN, not zero" in data["summary"]


async def test_summary_for_an_unobserved_tenant_says_absence_of_observation():
    await _seed("t1")
    data = await capability_access_graph_service.summary("t2")
    assert data["summary_known"] is True
    assert data["observed_any"] is False
    # A complete, untruncated read that found nothing is a computed zero — but the
    # summary must not let it read as "this tenant's agents reach nothing".
    assert "absence of observation" in data["summary"]
