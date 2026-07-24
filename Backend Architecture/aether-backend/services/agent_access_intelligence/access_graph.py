"""Capability access graph — agents → servers → capabilities (PR 4, ``AAI-4-GRAPH``).

A third read-only derivation over the stores Phase C already reads
(``capability_catalog``, ``capability_installations``, and the capability
authorizations held in ``delegations``). Nothing here writes a row, registers an event
type, or creates a table.

**Why this is not a Silver projector.** PR 2 established the precedent and it still
holds: an access graph is a *table→table* derivation over stores that already exist,
while Silver projectors are Bronze-event-driven. Forcing one in would touch four
CI-guarded artifacts (``dispatcher.py::_ALL_PROJECTORS``,
``projector-ownership-registry.json``, generated ``services/silver/generated_ownership.py``
and ``validate_projector_ownership.py``) for no benefit.
``SilverGraphProjector._emit_agent_execution`` already emits the bounded agent/tool/MCP
vertices and edges; this module **reads and composes** them, it does not add emission.
Node and edge payloads carry ``graph_vertex_type`` / ``graph_edge_type`` naming the real
graph vocabulary (``ExternalAgent``, ``MCPConnection``, ``AgentToolObserved``,
``AGENT_CONNECTED_VIA_MCP``, ``AGENT_USED_TOOL_OBS``) so this surface and the graph agree
about the name of the same thing instead of inventing a second scheme.

Vocabulary
----------

``node_id``
    ``agent:{agent_id}`` · ``server:{server_ref}`` · ``capability:{capability_id}``.
    The server segment is ``authority.server_ref_for``'s digest, never the raw observed
    name/URL: a ``:`` or ``*`` in an observed server URL must not be able to corrupt an
    id or widen a scope, and the digest is exactly what the authorization rows are keyed
    by, so the ids join.

``kind`` on an edge
    ``connects_to``    agent → server, from an observed installation.
    ``exposes``        server → capability, from the catalog's server binding.
    ``authorized_for`` agent → capability — the *authorization question* for that pair,
                       answered by ``authorized: true | false | null``. The edge exists
                       because the agent can reach the capability; ``authorized`` says
                       whether it may.

The invariants this module exists to protect, each of which this package has already
been bitten by once:

1. **Unknown is never zero.** An agent nobody has observed has an *unknown*
   neighborhood, not an empty one. When any required input is absent, every count is
   ``None`` (``null``), ``missing_inputs`` names what was absent, and the summary says
   the neighborhood is unknown. ``nodes``/``edges`` are still returned — they are
   *evidence*, not totals, and the response never claims they are complete.
2. **Every bounded read discloses truncation.** Hitting the node budget, the edge
   budget, the catalog/installation windows, or the depth cap puts a named entry in
   ``missing_inputs`` and flips ``complete`` to ``False``. A truncated graph must not
   read as a complete one.
3. **``authorized`` is tri-state.** ``null`` when the authorization read truncated or
   was unavailable — never ``false``, which reads as "unauthorized" and drives a
   revocation that should not happen. That exact bug (0 authorized for a fully
   authorized agent) was just fixed in ``risk_service``; it is not reintroduced here.
4. **No unbounded fan-out.** Authorizations are read ONCE per request in a single
   bounded query (through ``risk_service``'s fixed reader) and matched in memory. A
   per-node authorization lookup was removed from this package for issuing ~400
   sequential round-trips on one read-gated GET.
5. Tenant scoping is fail-closed: another tenant's anchor resolves identically to an
   absent one, so a node id is never an existence oracle.

Even a fully computed neighborhood is bounded by observation: it is "what we have seen",
never "everything that exists". The summary says so.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Optional

from shared.common.common import BadRequestError, NotFoundError

from services.agent_access_intelligence.authority import server_ref_for
from services.agent_access_intelligence.catalog_service import (
    _sanitize_server_url,
    capability_catalog_service,
)

# `_server_key` and `_authorizes` are imported from `risk_service` rather than
# re-derived: both sides of the installation↔catalog↔authorization join have to agree
# about what a server key is and about which authorization row covers which capability,
# and a second copy of either would diverge silently the first time one is fixed.
from services.agent_access_intelligence.risk_service import (
    CapabilityRiskService,
    _server_key,
    capability_risk_service,
)

__all__ = [
    "EDGE_AUTHORIZED_FOR",
    "EDGE_CONNECTS_TO",
    "EDGE_EXPOSES",
    "MAX_DEPTH",
    "MAX_NODES",
    "NODE_AGENT",
    "NODE_CAPABILITY",
    "NODE_SERVER",
    "CapabilityAccessGraphService",
    "capability_access_graph_service",
]

NODE_AGENT = "agent"
NODE_SERVER = "server"
NODE_CAPABILITY = "capability"

EDGE_CONNECTS_TO = "connects_to"
EDGE_EXPOSES = "exposes"
EDGE_AUTHORIZED_FOR = "authorized_for"

# Hard depth cap. Two hops is the whole domain (agent → server → capability, or the
# reverse); anything beyond it is a tenant-wide dump wearing a neighborhood's clothes.
# The cap is always stated in the response, and a request that asked for more is told
# its answer was capped rather than being handed a smaller graph silently.
MAX_DEPTH = 2
DEFAULT_DEPTH = 1

# Node budget for one neighborhood. Hitting it is disclosed, never silently truncating.
MAX_NODES = 1000
DEFAULT_NODES = 500
# Edges are derived from the node set, so they need their own budget: a dense server can
# produce far more edges than nodes. Scaled off the node budget so one knob moves both.
_EDGE_BUDGET_FACTOR = 4

# Bounded read windows over the two inventory stores. Same values as `risk_service`, and
# each one, when hit, becomes a `missing_inputs` entry rather than a quiet partial answer.
_CATALOG_SCAN_LIMIT = 1000
_INSTALLATION_SCAN_LIMIT = 1000

# Whole-tenant reach pairs computed by `summary`. A tenant whose (agent, capability)
# reach relation exceeds this is reported as unknown rather than as a number produced by
# giving up half way through counting.
_SUMMARY_PAIR_BUDGET = 50_000

# The real graph's vocabulary for the same things, so the two surfaces agree.
# (`shared/graph/graph.py`: VertexType / EdgeType; emitted by
# `SilverGraphProjector._emit_agent_execution`.)
_VERTEX_TYPE_AGENT = "ExternalAgent"
_VERTEX_TYPE_SERVER = "MCPConnection"
_VERTEX_TYPE_TOOL = "AgentToolObserved"
_EDGE_TYPE_CONNECTED = "AGENT_CONNECTED_VIA_MCP"
_EDGE_TYPE_USED_TOOL = "AGENT_USED_TOOL_OBS"

_NEIGHBORHOOD_COUNT_KEYS = (
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
)

_SUMMARY_COUNT_KEYS = (
    "nodes",
    "edges",
    "agents",
    "servers",
    "capabilities",
    "edges_connects_to",
    "edges_exposes",
    "edges_authorized_for",
    "authorizations_active",
)


def agent_node_id(agent_id: str) -> str:
    return f"{NODE_AGENT}:{agent_id}"


def server_node_id(server_ref: str) -> str:
    return f"{NODE_SERVER}:{server_ref}"


def capability_node_id(capability_id: str) -> str:
    return f"{NODE_CAPABILITY}:{capability_id}"


def _matches_server_key(row: dict[str, Any], wanted: str) -> bool:
    """Whether a catalog/installation row is the server the caller named.

    Mirrors ``CapabilityAuthorityService._canonical_server_key``: an operator may name a
    server by either form the catalog shows (``server_name`` or ``server_url``), the
    comparison is case-insensitive, and the URL is compared in its sanitized (stored)
    form. Matched in memory over rows this request already read rather than through that
    method's own bounded catalog scan — one request, one read of each store.
    """
    name = str(row.get("server_name") or "").strip().lower()
    url = str(_sanitize_server_url(str(row.get("server_url") or "")) or "").strip().lower()
    return wanted in {v for v in (name, url) if v}


class _Bounds:
    """Resolved, clamped bounds for one neighborhood request, plus what they cost.

    Every field here ends up in the response: a caller must be able to see that the
    answer was shaped by a cap, and which one.
    """

    __slots__ = (
        "requested_depth",
        "depth",
        "requested_nodes",
        "nodes",
        "edges",
        "node_limit_hit",
        "edge_limit_hit",
    )

    def __init__(self, *, depth: int, limit: int) -> None:
        self.requested_depth = depth
        self.depth = min(depth, MAX_DEPTH)
        self.requested_nodes = limit
        self.nodes = min(limit, MAX_NODES)
        self.edges = self.nodes * _EDGE_BUDGET_FACTOR
        self.node_limit_hit = False
        self.edge_limit_hit = False

    @property
    def depth_capped(self) -> bool:
        return self.depth < self.requested_depth

    def as_dict(self) -> dict[str, Any]:
        return {
            "depth": {
                "requested": self.requested_depth,
                "applied": self.depth,
                "max_depth": MAX_DEPTH,
                "capped": self.depth_capped,
            },
            "limits": {
                "nodes_requested": self.requested_nodes,
                "nodes_applied": self.nodes,
                "max_nodes": MAX_NODES,
                "edges_applied": self.edges,
            },
        }


class CapabilityAccessGraphService:
    """Bounded, tenant-scoped access graph over the observed capability inventory."""

    # ------------------------------------------------------------------
    # Neighborhood
    # ------------------------------------------------------------------

    async def neighborhood(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        server_key: Optional[str] = None,
        depth: int = DEFAULT_DEPTH,
        limit: int = DEFAULT_NODES,
    ) -> dict[str, Any]:
        """The bounded neighborhood around exactly one anchor.

        Exactly one of ``agent_id`` / ``capability_id`` / ``server_key`` is required —
        the same rule, and the same failure mode, as ``risk_service.blast_radius``. Three
        anchors answer three questions ("what does this agent reach", "who reaches this
        capability", "what hangs off this server") and a request naming none or several
        has no single answer to give.
        """
        agent_id = (agent_id or "").strip() or None
        capability_id = (capability_id or "").strip() or None
        server_key = (server_key or "").strip() or None
        provided = [a for a in (agent_id, capability_id, server_key) if a]
        if len(provided) != 1:
            raise BadRequestError(
                "provide exactly one of agent_id (what this agent reaches), "
                "capability_id (who reaches this capability) or server_key "
                "(what is bound to this server)"
            )
        if int(depth) < 1:
            raise BadRequestError("depth must be at least 1")
        if int(limit) < 1:
            raise BadRequestError("limit must be at least 1")
        bounds = _Bounds(depth=int(depth), limit=int(limit))

        missing: list[str] = []
        if bounds.depth_capped:
            # The caller asked a wider question than this surface answers. The graph
            # returned is real, but it is not the neighborhood they asked for, so the
            # counts are not an answer to their question either.
            missing.append(f"graph:depth_capped_at_{MAX_DEPTH}")

        installations, catalog = await self._read_inventory(
            tenant_id, agent_id=agent_id, missing=missing
        )

        anchor, anchor_node_id, anchor_missing = await self._resolve_anchor(
            tenant_id,
            agent_id=agent_id,
            capability_id=capability_id,
            server_key=server_key,
            installations=installations,
            catalog=catalog,
        )
        missing.extend(anchor_missing)
        if not anchor_node_id:
            # THE case this surface exists for: an anchor nobody has observed (or another
            # tenant's) has an UNKNOWN neighborhood. Answering "no nodes, no edges" would
            # read as "this agent reaches nothing", which is a claim about the world that
            # no input supports. Fails closed and identically for absent / other-tenant.
            return self._unknown(
                anchor=anchor, bounds=bounds, missing=missing, nodes=[], edges=[]
            )

        index = _AccessIndex(tenant_id, installations=installations, catalog=catalog)
        missing.extend(index.missing)

        node_ids = self._walk(index, anchor_node_id, bounds)

        # Read ONCE per request, in a single bounded query, then matched in memory.
        # Delegates to the reader `risk_service` already fixed: a per-node `resolve()`
        # loop is both wrong (it inherits `active_for`'s 200-row newest-first window, so
        # older live grants fall out and the split reports 0 authorized) and expensive.
        active = await capability_risk_service._active_authorizations(
            tenant_id, agent_id=agent_id, missing=missing
        )
        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in active or []:
            by_agent[str(row.get("agent_id") or "")].append(row)

        edges = self._edges_for(index, node_ids, bounds, active=active, by_agent=by_agent)
        nodes = [index.node(node_id) for node_id in sorted(node_ids)]

        for node in nodes:
            if node["kind"] == NODE_CAPABILITY and not node["observed"]:
                missing.append(f"capability_catalog:capability_id={node['capability_id']}")
        if bounds.node_limit_hit:
            missing.append("graph:node_limit_reached")
        if bounds.edge_limit_hit:
            missing.append("graph:edge_limit_reached")

        if missing:
            return self._unknown(
                anchor=anchor, bounds=bounds, missing=missing, nodes=nodes, edges=edges
            )

        counts = self._count(nodes, edges)
        return {
            "anchor": anchor,
            "neighborhood_known": True,
            "missing_inputs": [],
            "basis": "observed_only",
            **bounds.as_dict(),
            "truncation": self._truncation(bounds, missing),
            "complete": True,
            "counts": counts,
            "counts_scope": "returned_neighborhood",
            "nodes": nodes,
            "edges": edges,
            "summary": (
                f"{anchor['kind'].capitalize()} {anchor['id']} sits in an observed "
                f"neighborhood of {counts['nodes']} node(s) and {counts['edges']} edge(s) "
                f"within {bounds.depth} hop(s): {counts['agents']} agent(s), "
                f"{counts['servers']} server(s), {counts['capabilities']} capability(ies). "
                f"{counts['edges_authorized']} of {counts['edges_authorized_for']} "
                "agent→capability reach relation(s) are covered by an active authorization. "
                "The graph is derived from observed installations and the tenant's "
                "capability catalog, bounded to "
                f"{bounds.nodes} node(s) and a maximum depth of {MAX_DEPTH} — it is what "
                "has been observed, not a proof of total reach."
            ),
        }

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    async def summary(self, tenant_id: str) -> dict[str, Any]:
        """Bounded counts by node kind and edge kind for the whole tenant.

        Same honesty rule as ``neighborhood``: if any read truncated, or the reach
        relation is too large to count exactly, every count is ``null``. A partial total
        is still a number a reader will treat as complete.
        """
        missing: list[str] = []
        installations, catalog = await self._read_inventory(
            tenant_id, agent_id=None, missing=missing
        )
        index = _AccessIndex(tenant_id, installations=installations, catalog=catalog)
        missing.extend(index.missing)
        # A tenant-wide total cannot be stated over capabilities we cannot describe.
        missing.extend(
            f"capability_catalog:capability_id={c}" for c in sorted(index.undescribed)
        )

        active = await capability_risk_service._active_authorizations(
            tenant_id, agent_id=None, missing=missing
        )

        reach_pairs = 0
        for agent, servers in index.agent_servers.items():
            reachable: set[str] = set(index.invoked_by_agent.get(agent) or ())
            for ref in servers:
                reachable |= index.server_capabilities.get(ref, set())
            reach_pairs += len(reachable)
            if reach_pairs > _SUMMARY_PAIR_BUDGET:
                missing.append("graph:reach_pair_budget_exceeded")
                break

        observed_any = bool(index.agents or index.servers or index.capabilities)

        if missing:
            deduped = _dedupe(missing)
            return {
                "tenant_id": tenant_id,
                "summary_known": False,
                "missing_inputs": deduped,
                "basis": "observed_only",
                "complete": False,
                "counts": {key: None for key in _SUMMARY_COUNT_KEYS},
                "limits": {
                    "catalog_scan_limit": _CATALOG_SCAN_LIMIT,
                    "installation_scan_limit": _INSTALLATION_SCAN_LIMIT,
                    "reach_pair_budget": _SUMMARY_PAIR_BUDGET,
                },
                "observed_any": observed_any,
                "summary": (
                    "Access graph totals for this tenant are UNKNOWN, not zero. Required "
                    f"input(s) absent: {', '.join(deduped)}. Every count is null because "
                    "it could not be computed — do not read this as no access."
                ),
            }

        counts = {
            "nodes": len(index.agents) + len(index.servers) + len(index.capabilities),
            "edges": len(index.connects_to) + len(index.exposes) + reach_pairs,
            "agents": len(index.agents),
            "servers": len(index.servers),
            "capabilities": len(index.capabilities),
            "edges_connects_to": len(index.connects_to),
            "edges_exposes": len(index.exposes),
            # Reach relations, not grants: how many (agent, capability) pairs the
            # `authorized_for` question can be asked about. `authorizations_active` is
            # the grant count. Conflating the two would let a reader take "8 authorized
            # edges" for "8 authorized capabilities".
            "edges_authorized_for": reach_pairs,
            "authorizations_active": len(active or []),
        }
        return {
            "tenant_id": tenant_id,
            "summary_known": True,
            "missing_inputs": [],
            "basis": "observed_only",
            "complete": True,
            "counts": counts,
            "limits": {
                "catalog_scan_limit": _CATALOG_SCAN_LIMIT,
                "installation_scan_limit": _INSTALLATION_SCAN_LIMIT,
                "reach_pair_budget": _SUMMARY_PAIR_BUDGET,
            },
            "observed_any": observed_any,
            "summary": (
                (
                    f"{counts['agents']} agent(s), {counts['servers']} server(s) and "
                    f"{counts['capabilities']} capability(ies) have been observed for this "
                    f"tenant, with {counts['edges_authorized_for']} agent→capability reach "
                    f"relation(s) and {counts['authorizations_active']} active capability "
                    "authorization(s). These are observed totals, not a proof of total reach."
                )
                if observed_any
                else (
                    "No capability observations have been recorded for this tenant. That is "
                    "an absence of observation, not evidence that its agents reach nothing."
                )
            ),
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def _read_inventory(
        self, tenant_id: str, *, agent_id: Optional[str], missing: list[str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The two inventory stores, each read once, each disclosing its window.

        Installations are filtered to the anchor agent when there is one: at depth ≤ 2 an
        agent anchor never needs another agent's rows, so the filter narrows the window
        instead of making truncation more likely for exactly the tenants with the most
        agents.
        """
        installations = await capability_catalog_service.list_installations(
            tenant_id, agent_id=agent_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            missing.append("capability_installations:scan_truncated")
        catalog = await capability_catalog_service.list_capabilities(
            tenant_id, limit=_CATALOG_SCAN_LIMIT
        )
        if len(catalog) >= _CATALOG_SCAN_LIMIT:
            missing.append("capability_catalog:scan_truncated")
        return installations, catalog

    async def _resolve_anchor(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str],
        capability_id: Optional[str],
        server_key: Optional[str],
        installations: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str, list[str]]:
        """``(anchor, node_id, missing)``.

        An empty ``node_id`` means the anchor could not be resolved at all — there is
        nothing to walk from, so the neighborhood is unknown. A resolved anchor may still
        contribute ``missing`` entries (an input it needs was absent); the walk still runs
        so the caller gets the evidence, but every count is withheld.
        """
        if agent_id:
            anchor = {
                "kind": NODE_AGENT,
                "id": agent_id,
                "node_id": agent_node_id(agent_id),
            }
            if not installations:
                return anchor, "", [f"capability_installations:agent_id={agent_id}"]
            return anchor, str(anchor["node_id"]), []

        if capability_id:
            anchor = {
                "kind": NODE_CAPABILITY,
                "id": capability_id,
                "node_id": capability_node_id(capability_id),
            }
            try:
                # Fail-closed single read: absent and another tenant's row raise the same
                # NotFoundError, so a capability id is never an existence oracle.
                capability = await capability_catalog_service.get_capability(
                    tenant_id, capability_id
                )
            except NotFoundError:
                return anchor, "", [f"capability_catalog:capability_id={capability_id}"]
            if not any(r.get("capability_id") == capability_id for r in catalog):
                # Real, but outside the bounded catalog window this request read. Include
                # it so the anchor is describable; the window truncation is already a
                # missing input, so no count will be claimed off a partial view.
                catalog.append(capability)
            missing: list[str] = []
            if not _server_key(capability):
                # Every `provider_action` — `_upsert_installation` only writes a row when
                # both an agent and a server key exist. With no server binding there is no
                # key to join reaching agents on, so who reaches it is unknown rather than
                # nobody. Same call `risk_service._capability_blast_radius` makes.
                missing.append(f"capability_server_binding:capability_id={capability_id}")
            return anchor, str(anchor["node_id"]), missing

        assert server_key is not None  # guarded by the exactly-one check in `neighborhood`
        wanted = str(_sanitize_server_url(server_key) or server_key).strip().lower()
        canonical: Optional[str] = None
        for row in list(catalog) + list(installations):
            if _matches_server_key(row, wanted):
                canonical = _server_key(row)
                if canonical:
                    break
        if not canonical:
            # Not observed for this tenant. Unknown, not empty — and identical to another
            # tenant's server, so the key is not an existence oracle either.
            return (
                {"kind": NODE_SERVER, "id": server_key, "node_id": None},
                "",
                [f"capability_catalog:server_key={server_key}"],
            )
        ref = server_ref_for(tenant_id, canonical)
        return (
            {
                "kind": NODE_SERVER,
                "id": server_key,
                "server_ref": ref,
                "server_key": _sanitize_server_url(canonical),
                "node_id": server_node_id(ref),
            },
            server_node_id(ref),
            [],
        )

    # ------------------------------------------------------------------
    # Walk + edge derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _walk(index: "_AccessIndex", anchor_node_id: str, bounds: _Bounds) -> set[str]:
        """Breadth-first over the structural adjacency, hard-capped by depth and nodes.

        The walk is undirected because the questions are: "who reaches this capability?"
        is the same edge read the other way round. Iteration is over sorted keys so the
        subgraph a budget truncates to is deterministic rather than dict-order-dependent.
        """
        seen = {anchor_node_id}
        frontier = {anchor_node_id}
        for _ in range(bounds.depth):
            nxt: set[str] = set()
            for node in sorted(frontier):
                for neighbor in sorted(index.adjacency.get(node, ())):
                    if neighbor in seen:
                        continue
                    if len(seen) >= bounds.nodes:
                        bounds.node_limit_hit = True
                        break
                    seen.add(neighbor)
                    nxt.add(neighbor)
                if bounds.node_limit_hit:
                    break
            if bounds.node_limit_hit or not nxt:
                break
            frontier = nxt
        return seen

    def _edges_for(
        self,
        index: "_AccessIndex",
        node_ids: set[str],
        bounds: _Bounds,
        *,
        active: Optional[list[dict[str, Any]]],
        by_agent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []

        def _room() -> bool:
            if len(edges) >= bounds.edges:
                bounds.edge_limit_hit = True
                return False
            return True

        for agent, ref in sorted(index.connects_to):
            src, dst = agent_node_id(agent), server_node_id(ref)
            if src not in node_ids or dst not in node_ids:
                continue
            if not _room():
                return edges
            edges.append({
                "kind": EDGE_CONNECTS_TO,
                "source": src,
                "target": dst,
                "basis": "observed_installation",
                # Tri-state, and scoped: this is whether a SERVER-wide grant covers the
                # whole connection. `false` here does not mean the agent may invoke
                # nothing on the server — per-capability grants show up on the
                # `authorized_for` edges, which is why the scope is stated.
                "authorization_scope": "server",
                "authorized": self._server_authorized(active, by_agent, agent, ref),
                "graph_edge_type": _EDGE_TYPE_CONNECTED,
            })

        for ref, capability in sorted(index.exposes):
            src, dst = server_node_id(ref), capability_node_id(capability)
            if src not in node_ids or dst not in node_ids:
                continue
            if not _room():
                return edges
            edges.append({
                "kind": EDGE_EXPOSES,
                "source": src,
                "target": dst,
                "basis": "catalog_server_binding",
                # Authorization is agent-relative and this edge has no agent. `null` here
                # means "not applicable", which is why the scope says so explicitly
                # rather than leaving a bare null to be misread as "unknown" or "denied".
                "authorization_scope": "not_applicable",
                "authorized": None,
                "graph_edge_type": None,
            })

        agents = sorted(n for n in node_ids if n.startswith(f"{NODE_AGENT}:"))
        capabilities = sorted(n for n in node_ids if n.startswith(f"{NODE_CAPABILITY}:"))
        for agent_id_node in agents:
            agent = agent_id_node.split(":", 1)[1]
            invoked = index.invoked_by_agent.get(agent) or set()
            servers = index.agent_servers.get(agent) or set()
            for capability_node in capabilities:
                capability = capability_node.split(":", 1)[1]
                is_invoked = capability in invoked
                if not is_invoked and not (servers & index.capability_servers.get(capability, set())):
                    continue
                if not _room():
                    return edges
                edges.append({
                    "kind": EDGE_AUTHORIZED_FOR,
                    "source": agent_id_node,
                    "target": capability_node,
                    # Same distinction `risk_service` draws: `invoked` means the agent was
                    # observed using it; `server_reachable` means it merely sits on a
                    # server the agent connects to. Both belong in an access graph, and
                    # conflating them lets a summary claim an agent was "observed reaching"
                    # 50 tools when it was observed invoking one.
                    "basis": "invoked" if is_invoked else "server_reachable",
                    "authorization_scope": "capability",
                    "authorized": self._capability_authorized(
                        index, active, by_agent, agent, capability
                    ),
                    "graph_edge_type": _EDGE_TYPE_USED_TOOL if is_invoked else None,
                })
        return edges

    @staticmethod
    def _server_authorized(
        active: Optional[list[dict[str, Any]]],
        by_agent: dict[str, list[dict[str, Any]]],
        agent: str,
        server_ref: str,
    ) -> Optional[bool]:
        if active is None:
            return None  # never False: the read failed, it did not come back empty.
        return any(
            str(row.get("server_ref") or "") == server_ref for row in by_agent.get(agent, ())
        )

    @staticmethod
    def _capability_authorized(
        index: "_AccessIndex",
        active: Optional[list[dict[str, Any]]],
        by_agent: dict[str, list[dict[str, Any]]],
        agent: str,
        capability_id: str,
    ) -> Optional[bool]:
        if active is None:
            return None  # never False — see the module docstring, invariant 3.
        refs = index.capability_servers.get(capability_id) or set()
        rows = by_agent.get(agent, ())
        for row in rows:
            if CapabilityRiskService._authorizes(row, capability_id, None):
                return True
            if any(CapabilityRiskService._authorizes(row, capability_id, ref) for ref in refs):
                return True
        return False

    # ------------------------------------------------------------------
    # Response shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _count(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        by_kind: dict[str, int] = defaultdict(int)
        for node in nodes:
            by_kind[str(node.get("kind"))] += 1
        by_edge: dict[str, int] = defaultdict(int)
        authorized = 0
        unauthorized = 0
        for edge in edges:
            by_edge[str(edge.get("kind"))] += 1
            if edge.get("kind") != EDGE_AUTHORIZED_FOR:
                continue
            if edge.get("authorized") is True:
                authorized += 1
            elif edge.get("authorized") is False:
                unauthorized += 1
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "agents": by_kind[NODE_AGENT],
            "servers": by_kind[NODE_SERVER],
            "capabilities": by_kind[NODE_CAPABILITY],
            "edges_connects_to": by_edge[EDGE_CONNECTS_TO],
            "edges_exposes": by_edge[EDGE_EXPOSES],
            "edges_authorized_for": by_edge[EDGE_AUTHORIZED_FOR],
            "edges_authorized": authorized,
            "edges_unauthorized": unauthorized,
        }

    @staticmethod
    def _truncation(bounds: _Bounds, missing: Iterable[str]) -> dict[str, Any]:
        entries = list(missing)
        return {
            "node_limit_reached": bounds.node_limit_hit,
            "edge_limit_reached": bounds.edge_limit_hit,
            "depth_capped": bounds.depth_capped,
            "catalog_truncated": any(
                e == "capability_catalog:scan_truncated" for e in entries
            ),
            "installations_truncated": any(
                e == "capability_installations:scan_truncated" for e in entries
            ),
            "authorizations_truncated": any(
                e == "capability_authorizations:scan_truncated" for e in entries
            ),
        }

    def _unknown(
        self,
        *,
        anchor: dict[str, Any],
        bounds: _Bounds,
        missing: list[str],
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Every count ``None``; whatever we do hold kept as a labelled list.

        ``nodes``/``edges`` are evidence, not totals — nothing in the response says they
        are complete, and emitting ``0`` for any count here would be an assertion about
        the world that no input supports.
        """
        deduped = _dedupe(missing)
        return {
            "anchor": anchor,
            "neighborhood_known": False,
            "missing_inputs": deduped,
            "basis": "observed_only",
            **bounds.as_dict(),
            "truncation": self._truncation(bounds, deduped),
            "complete": False,
            "counts": {key: None for key in _NEIGHBORHOOD_COUNT_KEYS},
            "counts_scope": "not_computed",
            "nodes": nodes,
            "edges": edges,
            "summary": (
                f"The access neighborhood for {anchor['kind']} {anchor['id']} is UNKNOWN, "
                f"not empty. Required input(s) absent: {', '.join(deduped)}. Every count "
                "is null because it could not be computed — do not read this as no access."
            ),
        }


class _AccessIndex:
    """One request's in-memory adjacency over the two inventory stores.

    Built once per request from rows already read. Nothing here issues a query: the
    per-node authorization lookup this package removed for issuing ~400 sequential
    round-trips on one read-gated GET does not get to come back as a per-node catalog
    lookup instead.
    """

    def __init__(
        self,
        tenant_id: str,
        *,
        installations: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
    ) -> None:
        self.tenant_id = tenant_id
        self.missing: list[str] = []
        self.undescribed: set[str] = set()
        self.by_capability: dict[str, dict[str, Any]] = {
            str(r.get("capability_id")): r for r in catalog if r.get("capability_id")
        }
        self.server_key_by_ref: dict[str, str] = {}
        self.agents: set[str] = set()
        self.servers: set[str] = set()
        self.capabilities: set[str] = set(self.by_capability)
        self.connects_to: set[tuple[str, str]] = set()
        self.exposes: set[tuple[str, str]] = set()
        self.agent_servers: dict[str, set[str]] = defaultdict(set)
        self.server_capabilities: dict[str, set[str]] = defaultdict(set)
        self.capability_servers: dict[str, set[str]] = defaultdict(set)
        self.invoked_by_agent: dict[str, set[str]] = defaultdict(set)
        self.adjacency: dict[str, set[str]] = defaultdict(set)

        for installation in installations:
            agent = str(installation.get("agent_id") or "").strip()
            key = _server_key(installation)
            if not agent:
                self.missing.append(
                    "capability_installation_agent:installation_id="
                    f"{installation.get('installation_id')}"
                )
                continue
            self.agents.add(agent)
            if not key:
                self.missing.append(
                    "capability_server_binding:installation_id="
                    f"{installation.get('installation_id')}"
                )
            else:
                ref = self._ref(key)
                self.servers.add(ref)
                self.connects_to.add((agent, ref))
                self.agent_servers[agent].add(ref)
                self._link(agent_node_id(agent), server_node_id(ref))
            for capability in installation.get("capability_ids") or []:
                capability = str(capability)
                self.capabilities.add(capability)
                self.invoked_by_agent[agent].add(capability)
                self._link(agent_node_id(agent), capability_node_id(capability))
                if capability not in self.by_capability:
                    # Recorded as reached but absent from the catalog window: we cannot
                    # describe it, so no total it belongs to is ours to state. Tracked
                    # separately from `missing` so a neighborhood only inherits it when
                    # the undescribed capability is actually IN that neighborhood — a
                    # tenant-wide gap must not make every unrelated anchor unknown.
                    self.undescribed.add(capability)

        for row in catalog:
            capability = str(row.get("capability_id") or "")
            key = _server_key(row)
            if not capability or not key:
                # A provider action with no server binding is a legitimate node with no
                # `exposes` edge — it reaches the graph through `invoked` instead. Not a
                # missing input: flagging every serverless capability would null the
                # counts for any tenant that has one.
                continue
            ref = self._ref(key)
            self.servers.add(ref)
            self.exposes.add((ref, capability))
            self.server_capabilities[ref].add(capability)
            self.capability_servers[capability].add(ref)
            self._link(server_node_id(ref), capability_node_id(capability))

    def _ref(self, server_key: str) -> str:
        ref = server_ref_for(self.tenant_id, server_key)
        self.server_key_by_ref.setdefault(ref, server_key)
        return ref

    def _link(self, left: str, right: str) -> None:
        self.adjacency[left].add(right)
        self.adjacency[right].add(left)

    # ── node payloads ─────────────────────────────────────────────────────────

    def node(self, node_id: str) -> dict[str, Any]:
        kind, _, value = node_id.partition(":")
        if kind == NODE_AGENT:
            return {
                "node_id": node_id,
                "kind": NODE_AGENT,
                "agent_id": value,
                "label": value,
                "graph_vertex_type": _VERTEX_TYPE_AGENT,
            }
        if kind == NODE_SERVER:
            key = self.server_key_by_ref.get(value)
            return {
                "node_id": node_id,
                "kind": NODE_SERVER,
                "server_ref": value,
                # Sanitized defensively: the catalog scrubs credentials out of a server
                # URL on write, and this is another durable read surface for that value.
                "server_key": _sanitize_server_url(key) if key else None,
                "label": _sanitize_server_url(key) if key else value,
                "graph_vertex_type": _VERTEX_TYPE_SERVER,
            }
        row = self.by_capability.get(value) or {}
        tool_name = row.get("tool_name")
        return {
            "node_id": node_id,
            "kind": NODE_CAPABILITY,
            "capability_id": value,
            "label": tool_name or row.get("provider") or value,
            "provider": row.get("provider"),
            "tool_name": tool_name,
            "capability_kind": row.get("capability_kind"),
            "server_key": _sanitize_server_url(_server_key(row)) if row else None,
            "latest_risk_level": row.get("latest_risk_level"),
            # False when the id was reached through an installation but is outside the
            # catalog window — the node is real, our description of it is not available.
            "observed": bool(row),
            "graph_vertex_type": _VERTEX_TYPE_TOOL if tool_name else None,
        }


def _dedupe(entries: Iterable[str]) -> list[str]:
    out: list[str] = []
    for entry in entries:
        if entry not in out:
            out.append(entry)
    return out


capability_access_graph_service = CapabilityAccessGraphService()
