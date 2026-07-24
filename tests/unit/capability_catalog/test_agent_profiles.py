"""Per-agent access profiles + access journeys (PR 4, ``AAI-4-PROFILES-JOURNEYS``).

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (``test_capability_authority_routes.py``, ``test_capability_risk.py``) — so
permission gates and tenant scoping are exercised without standing up the middleware.

The load-bearing tests in this file:

``test_never_observed_agent_profile_is_unknown_not_zero`` /
``test_never_observed_agent_journey_is_unknown_not_zero``
    An agent we have never observed must produce ``profile_known: false`` /
    ``journey_known: false`` with ``null`` counts, never ``0``. "Reaches 0 capabilities"
    is a claim about the world; when no installation was ever recorded the only true
    answer is "we do not know". Both tests walk the entire response recursively
    (``_zero_numbers``, copied from ``test_capability_risk.py``) and fail on any
    zero-valued number anywhere in it, so a future refactor cannot reintroduce the lie
    through a new field.

``test_journey_is_ordered_by_first_observation_and_labelled_as_such``
    The journey must be ordered by first observation AND must say, in the payload, that
    an observation order is not a causal history.

``test_risk_is_rolled_up_as_counts_by_level_with_no_composite_score``
    No "risk score" / "trust score" / composite number may appear anywhere.

``access_graph.capability_access_graph_service`` is monkeypatched throughout so this lane
is verifiable independently of the parallel lane that builds it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import ForbiddenError

import services.agent_access_intelligence.profiles as profiles
import services.agent_access_intelligence.profile_routes as profile_routes
from services.agent_access_intelligence.authority_routes import (
    CapabilityAuthorizationGrant,
    grant_authorization,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service


class FakeProducer:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event) -> None:
        self.events.append(event)


class StubGraph:
    """Stands in for the access-graph lane so this lane's behaviour is driven by this
    test file, not by that module's traversal.

    Emits the shape ``access_graph.CapabilityAccessGraphService.neighborhood`` actually
    returns — ``neighborhood_known`` + a ``truncation`` mapping + ``complete``, with nodes
    keyed by ``node_id`` — which is NOT the flat ``truncated: bool`` / ``id`` shape the
    lane contract was specified with. ``test_flat_truncated_contract_shape_is_honored``
    covers the specified shape as well, so this lane stays correct against both.
    """

    def __init__(
        self,
        *,
        nodes: Optional[list[dict]] = None,
        edges: Optional[list[dict]] = None,
        counts: Optional[dict] = None,
        missing_inputs: Optional[list[str]] = None,
        truncation: Optional[dict] = None,
        neighborhood_known: bool = True,
    ) -> None:
        self.nodes = list(nodes or [])
        self.edges = list(edges or [])
        self.counts = counts
        self.missing_inputs = list(missing_inputs or [])
        self.truncation = truncation
        self.neighborhood_known = neighborhood_known
        self.calls: list[dict] = []

    async def neighborhood(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        server_key: Optional[str] = None,
        depth: int = 1,
        limit: int = 500,
    ) -> dict:
        self.calls.append({
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "capability_id": capability_id,
            "server_key": server_key,
            "depth": depth,
            "limit": limit,
        })
        truncation = self.truncation if self.truncation is not None else {
            "node_limit_reached": False,
            "edge_limit_reached": False,
            "depth_capped": False,
            "catalog_truncated": False,
            "installations_truncated": False,
            "authorizations_truncated": False,
        }
        return {
            "anchor": {"kind": "agent", "id": agent_id},
            "neighborhood_known": self.neighborhood_known,
            "missing_inputs": self.missing_inputs,
            "basis": "observed_only",
            "truncation": truncation,
            "complete": not any(truncation.values()),
            "counts": (
                self.counts
                if self.counts is not None
                else {"nodes": len(self.nodes), "edges": len(self.edges)}
            ),
            "counts_scope": "returned_neighborhood",
            "nodes": self.nodes,
            "edges": self.edges,
        }

    async def summary(self, tenant_id: str) -> dict:  # pragma: no cover - unused by this lane
        return {"tenant_id": tenant_id}


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


@pytest.fixture(autouse=True)
def _stub_graph(monkeypatch):
    """A graph that answers, unless a test says otherwise."""
    stub = StubGraph(
        nodes=[{"node_id": "agent:agentA"}, {"node_id": "server:srv_x"}],
        edges=[{"kind": "connects_to", "authorized": None}],
    )
    monkeypatch.setattr(profiles, "capability_access_graph_service", stub)
    return stub


async def _seed(
    tenant_id: str = "t1",
    *,
    source_event_id: str = "e1",
    agent_id: Optional[str] = "agentA",
    tool_name: Optional[str] = "search",
    server_name: Optional[str] = "srvX",
    server_url: Optional[str] = None,
    provider: str = "acme",
    occurred_at: str = "2026-07-24T00:00:00Z",
    risk_level: Optional[str] = "high",
) -> str:
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": occurred_at,
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "server_url": server_url,
        "provider": provider,
        "risk_level": risk_level,
    })
    return result["capability_id"]


def _zero_numbers(value: Any, path: str = "$") -> list[str]:
    """Every path in ``value`` holding a numeric zero. ``bool`` is excluded on purpose —
    ``False`` is an ``int`` in Python and ``profile_known: false`` is the honest answer,
    not a count. Copied verbatim from ``test_capability_risk.py`` so both surfaces are
    held to the same rule."""
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


def _walk_strings(value: Any) -> list[str]:
    """Every string (keys included) anywhere in a response."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            out.append(str(key))
            out.extend(_walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_walk_strings(item))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# UNKNOWN IS NEVER ZERO
# ══════════════════════════════════════════════════════════════════════════════

async def test_never_observed_agent_profile_is_unknown_not_zero():
    await _seed()  # a populated tenant, so "empty store" is not what makes this pass
    data = (await profile_routes.read_agent_profile("ghost-agent", _request("t1")))["data"]

    assert data["profile_known"] is False
    assert data["missing_inputs"], "an absent input must be named, not silently dropped"
    assert any("capability_installations" in e for e in data["missing_inputs"])
    assert any("ghost-agent" in e for e in data["missing_inputs"])

    assert set(data["counts"]) == {
        "servers_observed",
        "capabilities_reachable",
        "capabilities_invoked",
        "capabilities_authorized",
        "capabilities_unauthorized",
        "authorizations_active",
        "observations_recorded",
    }
    for key, value in data["counts"].items():
        assert value is None, f"counts.{key} must be null when it could not be computed"

    # Provenance is unknown too — not "seen 0 times".
    assert data["observation"]["first_seen_at"] is None
    assert data["observation"]["last_seen_at"] is None
    assert data["observation"]["observations_recorded"] is None
    # An empty rollup, not {"unknown": 0}.
    assert data["risk"]["known"] is False
    assert data["risk"]["by_latest_risk_level"] == {}
    assert data["authorization"]["known"] is False
    # The graph is not queried for a subject we have never observed, and says so.
    assert data["graph"]["neighborhood_known"] is False
    assert all(v is None for v in data["graph"]["counts"].values())

    # And nowhere else in the response either.
    assert _zero_numbers(data) == []

    assert "UNKNOWN" in data["summary"]
    assert "not empty" in data["summary"]


async def test_never_observed_agent_journey_is_unknown_not_zero():
    await _seed()
    data = (
        await profile_routes.read_agent_journey(_request("t1"), "ghost-agent", limit=200)
    )["data"]

    assert data["journey_known"] is False
    assert any("capability_installations" in e for e in data["missing_inputs"])
    assert set(data["counts"]) == {
        "milestones_total",
        "milestones_returned",
        "server_milestones",
        "capability_milestones",
        "milestones_undated",
    }
    assert all(v is None for v in data["counts"].values())
    assert data["milestones"] == []
    assert _zero_numbers(data) == []
    assert "UNKNOWN" in data["summary"]
    assert "OBSERVATION ORDER" in data["summary"]


async def test_unobserved_agent_is_not_an_existence_oracle():
    """A real agent in another tenant and an agent that does not exist anywhere must be
    answered identically, so the path parameter cannot confirm existence."""
    await _seed("t1", agent_id="agentA")

    other_tenants_agent = (
        await profile_routes.read_agent_profile("agentA", _request("t2"))
    )["data"]
    pure_fiction = (
        await profile_routes.read_agent_profile("no-such-agent", _request("t2"))
    )["data"]

    assert other_tenants_agent["profile_known"] is pure_fiction["profile_known"] is False
    assert other_tenants_agent["counts"] == pure_fiction["counts"]
    assert other_tenants_agent["risk"] == pure_fiction["risk"]
    assert other_tenants_agent["authorization"] == pure_fiction["authorization"]
    # Only the echoed subject/ids differ; the shape and the disclosed reasons do not.
    assert [
        e.replace("agentA", "X") for e in other_tenants_agent["missing_inputs"]
    ] == [e.replace("no-such-agent", "X") for e in pure_fiction["missing_inputs"]]
    assert _zero_numbers(other_tenants_agent) == []

    # Same for the journey.
    j_other = (await profile_routes.read_agent_journey(_request("t2"), "agentA", limit=200))["data"]
    j_fiction = (
        await profile_routes.read_agent_journey(_request("t2"), "no-such-agent", limit=200)
    )["data"]
    assert j_other["journey_known"] is j_fiction["journey_known"] is False
    assert j_other["counts"] == j_fiction["counts"]


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE — computed answers
# ══════════════════════════════════════════════════════════════════════════════

async def test_profile_reports_reach_authorization_and_provenance():
    cap_a = await _seed(source_event_id="e1", tool_name="search", occurred_at="2026-07-01T00:00:00Z")
    await _seed(source_event_id="e2", tool_name="write", occurred_at="2026-07-05T00:00:00Z")

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["profile_known"] is True
    assert data["missing_inputs"] == []
    assert data["basis"] == "observed_only"
    assert data["identity"]["servers_observed"] == ["srvX"]
    assert data["identity"]["providers_observed"] == ["acme"]

    assert data["counts"]["servers_observed"] == 1
    assert data["counts"]["capabilities_reachable"] == 2
    assert data["counts"]["capabilities_invoked"] == 2
    # A computed zero is legitimate: we checked, and nothing was authorized.
    assert data["counts"]["capabilities_authorized"] == 0
    assert data["counts"]["capabilities_unauthorized"] == 2

    # Observation provenance is carried through from the installation rows.
    assert data["observation"]["first_seen_at"] == "2026-07-01T00:00:00Z"
    assert data["observation"]["last_seen_at"] == "2026-07-05T00:00:00Z"
    assert data["counts"]["observations_recorded"] == 2
    assert "bounded-window" in data["observation"]["basis"]

    assert "not a proof of total reach" in data["summary"]

    # Granting flips exactly one capability.
    await grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=cap_a),
        _request("t1"),
        producer=FakeProducer(),
    )
    after = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert after["counts"]["capabilities_authorized"] == 1
    assert after["counts"]["capabilities_unauthorized"] == 1
    assert after["counts"]["authorizations_active"] == 1
    assert [
        c["authorized"] for c in after["reach"]["capabilities"] if c["capability_id"] == cap_a
    ] == [True]


async def test_profile_separates_invoked_from_server_reachable():
    """A capability on a server the agent connects to but was never observed invoking is
    in reach, and is labelled as such rather than as something the agent used."""
    await _seed(source_event_id="e1", agent_id="agentA", tool_name="search")
    other = await _seed(source_event_id="e2", agent_id="agentB", tool_name="danger")

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    bases = {c["capability_id"]: c["basis"] for c in data["reach"]["capabilities"]}
    assert bases[other] == "server_reachable"
    assert data["counts"]["capabilities_reachable"] == 2
    assert data["counts"]["capabilities_invoked"] == 1


async def test_profile_is_tenant_scoped_and_requires_read():
    await _seed("t1", agent_id="agentA")
    other = (await profile_routes.read_agent_profile("agentA", _request("t2")))["data"]
    assert other["profile_known"] is False

    with pytest.raises(ForbiddenError):
        await profile_routes.read_agent_profile("agentA", _request("t1", permissions=[]))
    with pytest.raises(ForbiddenError):
        await profile_routes.read_agent_journey(
            _request("t1", permissions=[]), "agentA", limit=200
        )
    with pytest.raises(ForbiddenError):
        await profile_routes.list_agent_profiles(
            _request("t1", permissions=[]), limit=100, offset=0
        )


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE — risk rollup, never a score
# ══════════════════════════════════════════════════════════════════════════════

async def test_risk_is_rolled_up_as_counts_by_level_with_no_composite_score():
    await _seed(source_event_id="e1", tool_name="search", risk_level="high")
    await _seed(source_event_id="e2", tool_name="write", risk_level="low")
    await _seed(source_event_id="e3", tool_name="quiet", risk_level=None)

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["risk"]["known"] is True
    # Counts by observed level. A capability with no observed level is counted as
    # `unknown`, never folded into `low`.
    assert data["risk"]["by_latest_risk_level"] == {"high": 1, "low": 1, "unknown": 1}
    assert sum(data["risk"]["by_latest_risk_level"].values()) == (
        data["counts"]["capabilities_reachable"]
    )
    assert "no composite risk or trust score" in data["risk"]["note"]

    # No composite number anywhere, under any of the names one would be given.
    keys = _walk_strings({k: v for k, v in data.items()})
    for banned in ("risk_score", "trust_score", "score", "rating", "grade", "posture_score"):
        assert not any(banned == k for k in keys), f"a composite '{banned}' must not exist"


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY
# ══════════════════════════════════════════════════════════════════════════════

async def test_journey_is_ordered_by_first_observation_and_labelled_as_such():
    await _seed(
        source_event_id="e1", tool_name="early", server_name="srvA",
        occurred_at="2026-01-01T00:00:00Z",
    )
    await _seed(
        source_event_id="e2", tool_name="middle", server_name="srvB",
        occurred_at="2026-03-01T00:00:00Z",
    )
    await _seed(
        source_event_id="e3", tool_name="late", server_name="srvC",
        occurred_at="2026-06-01T00:00:00Z",
    )

    data = (
        await profile_routes.read_agent_journey(_request("t1"), "agentA", limit=200)
    )["data"]
    assert data["journey_known"] is True

    stamps = [m["at"] for m in data["milestones"]]
    assert stamps == sorted(stamps), "milestones must be ordered by first observation"
    assert [m["sequence"] for m in data["milestones"]] == list(
        range(1, len(data["milestones"]) + 1)
    )
    assert data["ordering"] == "first_observation_ascending"
    assert data["ordering_complete"] is True

    # Three servers + three capabilities.
    assert data["counts"]["server_milestones"] == 3
    assert data["counts"]["capability_milestones"] == 3
    assert data["counts"]["milestones_total"] == 6

    # It is an observation order, and the payload says so.
    assert data["basis"] == "observation_order"
    assert data["is_causal_history"] is False
    assert "OBSERVATION ORDER" in data["summary"]
    assert "not a causal history" in data["summary"]
    assert "audit trail" in data["summary"]

    # Attribution scope is explicit per milestone: only server milestones are agent-scoped.
    scopes = {m["kind"]: m["observed_scope"] for m in data["milestones"]}
    assert scopes["server_first_observed"] == "agent"
    assert scopes["capability_first_observed"] == "tenant"
    assert "TENANT-scoped" in data["scope_note"]


async def test_journey_discloses_truncation_when_the_limit_is_hit():
    for i in range(4):
        await _seed(
            source_event_id=f"e{i}", tool_name=f"tool{i}", server_name=f"srv{i}",
            occurred_at=f"2026-0{i + 1}-01T00:00:00Z",
        )

    full = (await profile_routes.read_agent_journey(_request("t1"), "agentA", limit=200))["data"]
    assert full["truncated"] is False
    assert full["counts"]["milestones_total"] == 8

    page = (await profile_routes.read_agent_journey(_request("t1"), "agentA", limit=3))["data"]
    assert page["truncated"] is True
    assert page["limit"] == 3
    assert page["counts"]["milestones_returned"] == 3
    # The total still describes the whole journey, not the page.
    assert page["counts"]["milestones_total"] == 8
    assert any("limit_reached" in e for e in page["missing_inputs"])
    assert "page limit was reached" in page["summary"]
    # The page is the earliest milestones, in order.
    assert [m["at"] for m in page["milestones"]] == [m["at"] for m in full["milestones"]][:3]


async def test_journey_moves_unorderable_timestamps_out_of_the_order_and_says_so():
    """A timestamp that cannot be parsed as a canonical instant is not silently placed in a
    sequence whose entire value is its order."""
    await _seed(
        source_event_id="e1", tool_name="good", server_name="srvA",
        occurred_at="2026-01-01T00:00:00Z",
    )
    # Timezone-naive: rejected by the platform's canonical instant authority, because it
    # names a different moment in every timezone.
    await _seed(
        source_event_id="e2", tool_name="naive", server_name="srvB",
        occurred_at="2026-02-01T00:00:00",
    )

    data = (await profile_routes.read_agent_journey(_request("t1"), "agentA", limit=200))["data"]
    assert data["ordering_complete"] is False
    assert data["counts"]["milestones_undated"] >= 1
    assert data["undated"], "an unorderable milestone must still be reported, not dropped"
    assert all(m["at"] is None for m in data["undated"])
    assert any(m["undated_reason"] == "timestamp_naive" for m in data["undated"])
    assert any("first_seen_at" in e for e in data["missing_inputs"])
    # Totals still account for it.
    assert data["counts"]["milestones_total"] == len(data["milestones"]) + len(data["undated"])


# ══════════════════════════════════════════════════════════════════════════════
# INDEX
# ══════════════════════════════════════════════════════════════════════════════

async def test_list_profiles_indexes_observed_agents_and_is_tenant_scoped():
    await _seed("t1", source_event_id="e1", agent_id="agentA", server_name="srvA")
    await _seed("t1", source_event_id="e2", agent_id="agentB", server_name="srvB")
    await _seed("t2", source_event_id="e3", agent_id="agentZ", server_name="srvZ")

    data = (await profile_routes.list_agent_profiles(_request("t1"), limit=100, offset=0))["data"]
    assert [i["agent_id"] for i in data["items"]] == ["agentA", "agentB"]
    assert data["counts"]["agents_observed"] == 2
    assert data["counts"]["scope"] == "all_observed_agents"
    assert data["truncated"] is False
    assert "not known to have no access" in data["note"]

    entry = data["items"][0]
    assert entry["servers"] == ["srvA"]
    assert entry["first_seen_at"] == "2026-07-24T00:00:00Z"
    assert entry["observations_recorded"] == 1

    page = (await profile_routes.list_agent_profiles(_request("t1"), limit=1, offset=1))["data"]
    assert [i["agent_id"] for i in page["items"]] == ["agentB"]
    assert page["limit"] == 1 and page["offset"] == 1
    # The total stays over the whole observed set, not the page.
    assert page["counts"]["agents_observed"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# ACCESS GRAPH — its own honesty scope
# ══════════════════════════════════════════════════════════════════════════════

async def test_profile_carries_a_bounded_graph_neighborhood(_stub_graph):
    await _seed()
    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]

    assert _stub_graph.calls == [{
        "tenant_id": "t1",
        "agent_id": "agentA",
        "capability_id": None,
        "server_key": None,
        "depth": 1,
        "limit": 500,
    }]
    assert data["graph"]["neighborhood_known"] is True
    assert data["graph"]["counts"] == {"nodes": 2, "edges": 1}
    assert data["graph"]["node_ids"] == ["agent:agentA", "server:srv_x"]


async def test_graph_unknowns_do_not_erase_the_store_derived_counts(_stub_graph):
    """The two honesty scopes are independent: a graph that could not answer nulls its own
    counts and nothing else, because the profile's counts come from the stores directly."""
    await _seed()
    _stub_graph.missing_inputs = ["agent_edges:unavailable"]
    _stub_graph.neighborhood_known = False

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["graph"]["neighborhood_known"] is False
    assert all(v is None for v in data["graph"]["counts"].values())
    assert "agent_edges:unavailable" in data["graph"]["missing_inputs"]

    # The profile itself is still known and still counted.
    assert data["profile_known"] is True
    assert data["missing_inputs"] == []
    assert data["counts"]["capabilities_reachable"] == 1


async def test_graph_truncation_is_disclosed_in_the_shipped_response_shape(_stub_graph):
    """The shipped graph reports capping through a ``truncation`` mapping, not the flat
    ``truncated`` bool this lane's contract specified. Reading only the flat key would
    report every capped neighborhood as complete."""
    await _seed()
    _stub_graph.truncation = {
        "node_limit_reached": True,
        "edge_limit_reached": False,
        "depth_capped": False,
        "catalog_truncated": False,
        "installations_truncated": False,
        "authorizations_truncated": False,
    }

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["graph"]["neighborhood_known"] is False
    assert "capability_access_graph:truncated" in data["graph"]["missing_inputs"]
    assert all(v is None for v in data["graph"]["counts"].values())
    assert data["profile_known"] is True


async def test_flat_truncated_contract_shape_is_honored(monkeypatch):
    """The originally-specified contract shape (flat ``truncated`` bool, nodes keyed by
    ``id``) must keep working, so this lane is not coupled to one of the two."""

    class FlatGraph:
        async def neighborhood(self, tenant_id, **kwargs):
            return {
                "nodes": [{"id": "agent:agentA"}],
                "edges": [],
                "missing_inputs": [],
                "truncated": True,
                "counts": {"nodes": 1, "edges": None},
            }

    monkeypatch.setattr(profiles, "capability_access_graph_service", FlatGraph())
    await _seed()
    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["graph"]["neighborhood_known"] is False
    assert "capability_access_graph:truncated" in data["graph"]["missing_inputs"]
    assert data["graph"]["node_ids"] == ["agent:agentA"]


async def test_graph_null_counts_are_never_replaced_by_a_page_length(_stub_graph):
    """The graph contract says a count it could not compute is null. Substituting the
    length of the returned page would turn "unknown" into a confident number."""
    await _seed()
    _stub_graph.counts = {"nodes": None, "edges": None}

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["graph"]["neighborhood_known"] is False
    assert data["graph"]["counts"] == {"nodes": None, "edges": None}
    assert any("counts_unavailable" in e for e in data["graph"]["missing_inputs"])


async def test_real_access_graph_flows_through_unstubbed(monkeypatch):
    """One end-to-end pass with the real access-graph module, so the two lanes are wired
    together and not only against a stub."""
    from services.agent_access_intelligence.access_graph import (
        capability_access_graph_service,
    )

    monkeypatch.setattr(
        profiles, "capability_access_graph_service", capability_access_graph_service
    )
    await _seed(source_event_id="e1", tool_name="search")
    await _seed(source_event_id="e2", tool_name="write")

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["profile_known"] is True
    assert data["graph"]["neighborhood_known"] is True
    # agent + server + two capabilities.
    assert data["graph"]["counts"]["nodes"] == 4
    assert data["graph"]["node_ids"][0] == "agent:agentA"
    assert all(":" in node_id for node_id in data["graph"]["node_ids"])
    # The graph agrees with the store-derived reach it was asked about.
    assert sum(
        1 for node_id in data["graph"]["node_ids"] if node_id.startswith("capability:")
    ) == data["counts"]["capabilities_reachable"]


async def test_profile_survives_an_absent_graph_lane(monkeypatch):
    """This lane must be verifiable — and shippable — without the graph module."""
    monkeypatch.setattr(profiles, "capability_access_graph_service", None)
    monkeypatch.setattr(profiles.AgentAccessProfileService, "_graph", staticmethod(lambda: None))
    await _seed()

    data = (await profile_routes.read_agent_profile("agentA", _request("t1")))["data"]
    assert data["profile_known"] is True
    assert data["graph"]["neighborhood_known"] is False
    assert "capability_access_graph:service_unavailable" in data["graph"]["missing_inputs"]
    assert all(v is None for v in data["graph"]["counts"].values())
