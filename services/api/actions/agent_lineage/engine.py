"""Bulk, cycle-safe resolver for the principal <-> agent lineage projection.

Silver execution facts, authority records and principal bindings fold into one
tenant's lineage state. ``resolve()`` then derives every agent's canonical
parent, root, depth, status and principal links and returns the row-level delta
for the read model. Nothing here is authoritative: dropping the engine and
folding the same evidence again reproduces the same rows, in any arrival order,
and that property is what makes the projection rebuildable and replay safe.

Rules enforced here:

  * A reported principal is a claim. It yields a link only through a binding;
    an unbound claim stays unresolved under the ``unattributed`` bucket.
  * An edge an agent reports about *itself* (a child naming its parent) carries
    no principal attribution, so an impostor cannot attach itself to a verified
    fleet. A link is only as strong as the weakest hop in its chain.
  * Weak evidence never reaches ``verified``, and a non-proof link that a proof
    link contradicts is demoted to ``unresolved`` rather than dropped.
  * Each agent has one canonical parent, so the topology is a functional graph:
    traversal is iterative and cycles are cut at a deterministic anchor, marked
    ``cyclic``, and never inflate counts or hide their members.
  * ``as_of`` comes from the evidence, never the wall clock, so a rebuild of the
    same evidence is byte-identical.
  * A count the evidence cannot support is ``None``, not ``0``.
"""
from __future__ import annotations

from bisect import insort
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple, Optional

from shared.agent_lineage import vocabulary as vocab

from ._common import (
    EVIDENCE_RANK,
    LINK_CONFIDENCE,
    PATH_SEP,
    UNATTRIBUTED,
    attribution_for,
    class_of,
    digest_int,
    epoch,
    iso,
    is_proof_class,
    ref,
    stable_hash,
)
from .config import DEFAULT_CONFIG, PROJECTION_VERSION, LineageConfig
from .evidence import AuthorityRecord, PrincipalBinding

SPAWN_EVENT = "agent_subagent_spawned"
DELEGATION_EVENTS = frozenset({"agent_delegated_task", "agent_handoff_observed"})
TERMINAL_EVENTS = frozenset({"agent_terminated", "agent_instance_terminated"})
DENIED_DECISIONS = frozenset({"deny", "denied", "block", "blocked", "rejected"})
HIGH_RISK_LEVELS = frozenset({"high", "critical"})
VERIFIED_STATES = frozenset({"deployment_verified", "attested", "reconciled"})
EFFECT_PROOF_STATES = frozenset({"attested", "reconciled"})
ECONOMIC_REF_FIELDS = ("payment_intent_ref", "settlement_event_ref", "external_order_id")
COMMUNICATION_MARKERS = ("agent_comm", "communication", "message")

_RANK_VERIFIED = EVIDENCE_RANK["VERIFIED_AUTHORITY"]
_RANK_DETERMINISTIC = EVIDENCE_RANK["DETERMINISTIC_BINDING"]
_RANK_PROVIDER = EVIDENCE_RANK["PROVIDER_ASSERTED"]
_RANK_DECLARED = EVIDENCE_RANK["TENANT_DECLARED"]
_RANK_BEHAVIORAL = EVIDENCE_RANK["BEHAVIORALLY_INFERRED"]
_RANK_INFRA = EVIDENCE_RANK["INFRASTRUCTURE_CORRELATED"]
_RANK_UNKNOWN = EVIDENCE_RANK["UNKNOWN"]

#: Fields whose change is a restatement of what the projection claims (as
#: opposed to ordinary activity counters advancing).
_RESTATED_FIELDS = (
    "attribution_class", "evidence_class", "relationship_status", "parent_agent_id",
    "root_agent_id", "depth", "lineage_status", "authority_resolution_status",
)
_INSTANCE_SHORTLIVED_RUNS = 1


class Edge(NamedTuple):
    rank: int
    first: float
    relationship: str


class Link(NamedTuple):
    """One principal link for one agent, carried down the delegation chain."""

    principal: str
    rank: int
    relationship: str
    depth: int
    authority_status: Optional[str] = None
    authority_ref: Optional[str] = None
    authority_type: Optional[str] = None
    delegation_allowed: Optional[bool] = None
    #: Deepest level the authority permits, absolute (``None`` = no stated limit).
    depth_limit: Optional[int] = None
    revoked_at: Optional[float] = None
    refs: tuple[str, ...] = ()


class Resolution(NamedTuple):
    parent: Optional[str]
    root: str
    depth: int
    status: str
    path: str
    hard: tuple[Link, ...]


class _Node:
    """Fold of every fact about one agent. Commutative, so arrival order is moot."""

    __slots__ = (
        "agent_id", "first", "last", "events", "digest", "samples", "instances",
        "definitions", "runs", "root_runs", "parent_runs", "tools", "services",
        "claims", "fact_authority", "deployments", "operators", "namespaces",
        "protocols", "edges", "self_edge", "observed", "terminated", "economic",
        "communication", "risk_seen", "risk_count", "denied", "wallets",
        "transactions", "providers", "effects_verified", "effects_reported",
        "outcomes", "verification",
    )

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.first: Optional[float] = None
        self.last: Optional[float] = None
        self.events = 0
        self.digest = 0
        self.samples: list[str] = []
        self.instances: set[str] = set()
        self.definitions: set[str] = set()
        self.runs: set[str] = set()
        self.root_runs: set[str] = set()
        self.parent_runs: set[str] = set()
        self.tools: set[str] = set()
        self.services: set[str] = set()
        self.claims: set[tuple[str, str]] = set()
        self.fact_authority: set[tuple[str, str]] = set()
        self.deployments: set[str] = set()
        self.operators: set[str] = set()
        self.namespaces: set[str] = set()
        self.protocols: set[str] = set()
        self.edges: dict[str, Edge] = {}
        self.self_edge = False
        self.observed = False
        self.terminated = False
        self.economic = False
        self.communication = False
        self.risk_seen = False
        self.risk_count = 0
        self.denied = 0
        self.wallets: set[str] = set()
        self.transactions: set[str] = set()
        self.providers: set[str] = set()
        self.effects_verified: set[str] = set()
        self.effects_reported: set[str] = set()
        self.outcomes: set[str] = set()
        self.verification: set[str] = set()


@dataclass
class ResolveResult:
    """Row-level delta from one ``resolve()`` pass."""

    tenant_id: str
    as_of: Optional[str]
    rows_upserted: list[dict[str, Any]] = field(default_factory=list)
    rows_removed: list[tuple[str, str]] = field(default_factory=list)
    nodes_upserted: list[dict[str, Any]] = field(default_factory=list)
    nodes_removed: list[str] = field(default_factory=list)
    summaries: list[dict[str, Any]] = field(default_factory=list)
    clusters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    summaries_removed: list[str] = field(default_factory=list)
    restatements: list[dict[str, Any]] = field(default_factory=list)
    restatements_dropped: int = 0
    stats: dict[str, int] = field(default_factory=dict)


def _status_for_row(link: Link, node: _Node) -> str:
    if link.authority_status == "revoked":
        return "revoked"
    if link.authority_status == "expired":
        return "expired"
    if node.terminated:
        return "terminated"
    return "active" if node.last is not None else "unknown"


class LineageEngine:
    """One tenant's lineage state. Not safe for concurrent mutation."""

    def __init__(self, tenant_id: str, config: LineageConfig = DEFAULT_CONFIG) -> None:
        if not ref(tenant_id):
            raise ValueError("lineage engine requires a tenant_id")
        self.tenant_id = tenant_id
        self.config = config
        self._nodes: dict[str, _Node] = {}
        self._seen: set[str] = set()
        self._dirty: set[str] = set()
        self._parent: dict[str, Optional[str]] = {}
        self._parent_conflicts: dict[str, int] = {}
        self._children: dict[str, set[str]] = defaultdict(set)
        self._edge_children: dict[str, set[str]] = defaultdict(set)
        self._principal_refs: dict[str, set[str]] = defaultdict(set)
        self._last_counts: dict[str, tuple] = {}
        self._res: dict[str, Resolution] = {}
        self._cycle: dict[str, str] = {}
        self._cycle_cut: set[str] = set()
        self._soft: dict[str, tuple[Link, ...]] = {}
        self._group_candidate: dict[str, tuple[str, ...]] = {}
        self._infra: dict[str, set[str]] = defaultdict(set)
        self._authority: dict[str, AuthorityRecord] = {}
        self._auth_by_grantee: dict[str, set[str]] = defaultdict(set)
        self._auth_by_grantor: dict[str, set[str]] = defaultdict(set)
        self._bindings: dict[tuple, PrincipalBinding] = {}
        self._claim_agents: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._agent_principals: dict[str, set[str]] = defaultdict(set)
        self._principal_agents: dict[str, set[str]] = defaultdict(set)
        self._risk_flags: dict[str, int] = {}
        self._risk_input_seen = False
        self._source_truncation: list[str] = []
        self._pass_disclosures: list[str] = []
        self._persisted_summaries: set[str] = set()
        self.duplicates_ignored = 0
        self.cross_tenant_rejected = 0

    # ── evidence intake ───────────────────────────────────────────────────

    def ingest(self, rows: Iterable[dict[str, Any]]) -> int:
        """Fold Silver facts; a replayed event id is ignored. Returns rows applied."""
        applied = 0
        for row in rows:
            if row.get("tenant_id") != self.tenant_id:
                self.cross_tenant_rejected += 1
                continue
            event_id = ref(row.get("source_event_id")) or ref(row.get("fact_id")) or stable_hash(
                row.get("agent_id"), row.get("source_event_type"), row.get("occurred_at"),
                row.get("child_agent_ref"), row.get("trace_id"), row.get("span_id"),
            )
            if event_id in self._seen:
                self.duplicates_ignored += 1
                continue
            self._seen.add(event_id)
            self._apply(row, event_id)
            applied += 1
        return applied

    def _node(self, agent_id: str) -> _Node:
        node = self._nodes.get(agent_id)
        if node is None:
            node = self._nodes[agent_id] = _Node(agent_id)
            # Grants naming this id as grantor were treated as principal-issued
            # while it was unobserved; a newly observed agent changes that.
            for key in self._auth_by_grantor.get(agent_id, ()):
                self._dirty.add(self._authority[key].grantee_entity_id)
            # Parent selection prefers observed parents, and an id named as a
            # principal stops being one once it is observed as an agent.
            self._dirty.update(self._edge_children.get(agent_id, ()))
            self._dirty.update(self._principal_refs.get(agent_id, ()))
        self._dirty.add(agent_id)
        return node

    def _apply(self, row: dict[str, Any], event_id: str) -> None:
        name = str(row.get("source_event_type") or row.get("event_name") or row.get("event_type") or "")
        agent = ref(row.get("agent_id"))
        occurred = epoch(row.get("occurred_at"))
        state = ref(row.get("execution_verification_state"))

        if name == SPAWN_EVENT or name in DELEGATION_EVENTS:
            parent = ref(row.get("parent_agent_ref")) or agent
            namespace = ref(row.get("delegated_to_namespace"))
            child = ref(row.get("child_agent_ref"))
            if child is None and (namespace is None or namespace == "agent"):
                child = ref(row.get("delegated_to_ref"))
            relationship = "SPAWNED" if name == SPAWN_EVENT else "DELEGATED_TO"
            if parent and child:
                self._add_edge(parent, child, agent, occurred, state, relationship)
        elif agent and ref(row.get("parent_agent_ref")):
            self._add_edge(ref(row.get("parent_agent_ref")), agent, agent, occurred, state, "SPAWNED")

        if agent is None:
            return
        node = self._node(agent)
        node.observed = True
        node.events += 1
        node.digest ^= digest_int(event_id)
        samples = node.samples
        if len(samples) < self.config.evidence_ref_sample:
            insort(samples, event_id)
        elif event_id < samples[-1]:
            insort(samples, event_id)
            samples.pop()
        if occurred is not None:
            node.first = occurred if node.first is None or occurred < node.first else node.first
            node.last = occurred if node.last is None or occurred > node.last else node.last
        for target, column in (
            (node.instances, "agent_instance_id"), (node.definitions, "agent_definition_id"),
            (node.root_runs, "root_run_id"), (node.parent_runs, "parent_run_id"),
            (node.tools, "tool_name"), (node.services, "server_name"),
            (node.providers, "provider"), (node.operators, "operator_entity_id"),
            (node.protocols, "protocol"),
        ):
            value = ref(row.get(column))
            if value:
                target.add(value)
        # A trace is not a run: only a source-reported run id counts as a run.
        run = ref(row.get("source_run_id")) or ref(row.get("canonical_run_id"))
        if run is None and row.get("run_correlation_source") == "run_id":
            run = ref(row.get("run_id"))
        if run:
            node.runs.add(run)
        namespace = ref(row.get("reported_principal_namespace")) or ""
        claim = ref(row.get("reported_principal_ref"))
        if claim:
            node.claims.add((namespace, claim))
            self._claim_agents[(namespace, claim)].add(agent)
        authority_ref = ref(row.get("authority_ref"))
        if authority_ref:
            node.fact_authority.add((authority_ref, ref(row.get("authority_type")) or "unknown"))
        deployment = ref(row.get("deployment_id"))
        if deployment and deployment not in node.deployments:
            node.deployments.add(deployment)
            self._infra[deployment].add(agent)
        source_namespace = ref(row.get("source_namespace"))
        if source_namespace or deployment:
            node.namespaces.add(source_namespace or deployment)
        if state:
            node.verification.add(state)
        if name in TERMINAL_EVENTS:
            node.terminated = True
        if any(ref(row.get(column)) for column in ECONOMIC_REF_FIELDS):
            node.economic = True
            node.transactions.update(
                value for column in ECONOMIC_REF_FIELDS if (value := ref(row.get(column)))
            )
        if any(marker in name for marker in COMMUNICATION_MARKERS):
            node.communication = True
        if ref(row.get("object_type")) == "wallet" and ref(row.get("object_id")):
            node.wallets.add(ref(row.get("object_id")))
        risk_level = ref(row.get("risk_level"))
        if risk_level:
            node.risk_seen = True
            self._risk_input_seen = True
            if risk_level.lower() in HIGH_RISK_LEVELS:
                node.risk_count += 1
        decision = str(row.get("policy_decision") or row.get("status") or "").lower()
        if decision in DENIED_DECISIONS:
            node.denied += 1
        effect = ref(row.get("external_effect_ref"))
        if effect:
            (node.effects_verified if state in EFFECT_PROOF_STATES else node.effects_reported).add(effect)
        outcome = ref(row.get("outcome_ref"))
        if outcome:
            node.outcomes.add(outcome)

    def _add_edge(
        self, parent: str, child: str, reporter: Optional[str], occurred: Optional[float],
        state: Optional[str], relationship: str,
    ) -> None:
        if parent == child:
            node = self._node(child)
            node.self_edge = True
            return
        if reporter == parent:
            rank = _RANK_DETERMINISTIC if state in VERIFIED_STATES else _RANK_PROVIDER
        elif reporter == child or reporter is None:
            # A child's own statement about its parent is topology, not attribution.
            rank = _RANK_UNKNOWN
        else:
            rank = _RANK_DECLARED
        node = self._node(child)
        when = occurred if occurred is not None else float("inf")
        existing = node.edges.get(parent)
        if existing is None:
            node.edges[parent] = Edge(rank, when, relationship)
        else:
            # Commutative merge: strongest rank, earliest time, stable type.
            node.edges[parent] = Edge(
                min(existing.rank, rank), min(existing.first, when),
                min(existing.relationship, relationship),
            )
        self._edge_children[parent].add(child)
        if occurred is not None and (node.first is None or occurred < node.first):
            node.first = occurred

    def upsert_authority(self, record: AuthorityRecord) -> bool:
        """Apply one authority record; lower versions are ignored. True if applied."""
        if record.tenant_id != self.tenant_id:
            self.cross_tenant_rejected += 1
            return False
        key = record.authority_ref
        current = self._authority.get(key)
        if current is not None:
            if _version_key(record) <= _version_key(current):
                return False
            self._auth_by_grantee[current.grantee_entity_id].discard(key)
            self._auth_by_grantor[current.grantor_entity_id].discard(key)
            self._dirty.add(current.grantee_entity_id)
        self._authority[key] = record
        self._auth_by_grantee[record.grantee_entity_id].add(key)
        self._auth_by_grantor[record.grantor_entity_id].add(key)
        self._node(record.grantee_entity_id)
        return True

    def upsert_binding(self, binding: PrincipalBinding) -> bool:
        if binding.tenant_id != self.tenant_id:
            self.cross_tenant_rejected += 1
            return False
        current = self._bindings.get(binding.key)
        if current is not None and _version_key(binding) <= _version_key(current):
            return False
        self._bindings[binding.key] = binding
        if binding.kind == "agent":
            self._node(binding.agent_entity_id)
        else:
            self._dirty.update(self._claim_agents.get((binding.namespace or "", binding.claim_ref), ()))
        return True

    def set_risk_flags(self, flags: dict[str, int]) -> None:
        """Risk-signal counts per agent from the risk plane (input, never derived here)."""
        self._risk_input_seen = True
        current = {agent: int(count) for agent, count in flags.items()}
        for agent in set(self._risk_flags) | set(current):
            if self._risk_flags.get(agent) != current.get(agent) and agent in self._nodes:
                self._dirty.add(agent)
        self._risk_flags = current

    def set_pass_disclosures(self, reasons: Iterable[str]) -> None:
        """Reasons true of this pass only. Source truncation stays until a clean rebuild."""
        self._pass_disclosures = list(reasons)

    def disclose_source_truncation(self, reason: str) -> None:
        if reason not in self._source_truncation:
            self._source_truncation.append(reason)

    # ── resolution ────────────────────────────────────────────────────────

    def _grantor_is_agent(self, record: AuthorityRecord) -> bool:
        if record.grantor_kind:
            return record.grantor_kind == "agent"
        return record.grantor_entity_id in self._nodes

    def _select_parent(self, node: _Node) -> None:
        agent = node.agent_id
        candidates: dict[str, Edge] = dict(node.edges)
        for key in self._auth_by_grantee.get(agent, ()):
            record = self._authority[key]
            if not self._grantor_is_agent(record) or record.grantor_entity_id == agent:
                continue
            rank = _RANK_VERIFIED if record.verified else _RANK_DECLARED
            when = record.valid_from if record.valid_from is not None else float("inf")
            prior = candidates.get(record.grantor_entity_id)
            if prior is None or rank < prior.rank:
                candidates[record.grantor_entity_id] = Edge(rank, when, "DELEGATED_TO")
        chosen = None
        if candidates:
            chosen = min(
                candidates,
                key=lambda p: (p not in self._nodes, candidates[p].rank, candidates[p].first, p),
            )
        previous = self._parent.get(agent)
        if previous != chosen:
            if previous is not None:
                self._children[previous].discard(agent)
            if chosen is not None:
                self._children[chosen].add(agent)
            self._parent[agent] = chosen
        self._parent_conflicts[agent] = max(0, len(candidates) - 1)

    def _edge(self, parent: str, child: str) -> tuple[Edge, Optional[AuthorityRecord]]:
        node = self._nodes[child]
        edge = node.edges.get(parent)
        best: Optional[AuthorityRecord] = None
        for key in self._auth_by_grantee.get(child, ()):
            record = self._authority[key]
            if record.grantor_entity_id != parent or not self._grantor_is_agent(record):
                continue
            if best is None or _version_key(record) > _version_key(best):
                best = record
        if best is not None:
            rank = _RANK_VERIFIED if best.verified else _RANK_DECLARED
            if edge is None or rank < edge.rank:
                edge = Edge(rank, best.valid_from or float("inf"), "DELEGATED_TO")
        if edge is None:
            edge = Edge(_RANK_UNKNOWN, float("inf"), "SPAWNED")
        return edge, best

    def _authority_status(self, record: AuthorityRecord, node: _Node) -> str:
        if record.revoked_at is not None:
            return "revoked"
        # Expiry is judged against the agent's own activity, not the wall clock.
        if record.valid_until is not None and node.last is not None and node.last > record.valid_until:
            return "expired"
        return "verified" if record.verified else "declared"

    def _own_links(self, node: _Node) -> dict[str, Link]:
        agent = node.agent_id
        links: dict[str, Link] = {}

        def offer(link: Link) -> None:
            self._principal_refs[link.principal].add(agent)
            if link.principal == agent or link.principal in self._nodes:
                # A principal is never an agent: identity and relationship stay
                # separate, and an agent id named as principal is not attribution.
                return
            current = links.get(link.principal)
            if current is None or _link_key(link) < _link_key(current):
                links[link.principal] = link

        for key in self._auth_by_grantee.get(agent, ()):
            record = self._authority[key]
            if self._grantor_is_agent(record):
                continue
            offer(Link(
                principal=record.grantor_entity_id,
                rank=_RANK_VERIFIED if record.verified else _RANK_DECLARED,
                relationship="AUTHORIZED",
                depth=1,
                authority_status=self._authority_status(record, node),
                authority_ref=record.authority_ref,
                authority_type=record.authority_type,
                delegation_allowed=record.delegation_allowed,
                depth_limit=(
                    None if record.maximum_delegation_depth is None
                    else 1 + record.maximum_delegation_depth
                ),
                revoked_at=record.revoked_at,
                refs=record.evidence_refs,
            ))
        binding = self._bindings.get(("agent", agent))
        if binding is not None:
            offer(Link(
                principal=binding.principal_entity_id,
                rank=EVIDENCE_RANK[binding.evidence_class],
                relationship="PRINCIPAL_OF",
                depth=1,
                refs=binding.evidence_refs,
            ))
        for namespace, claim in node.claims:
            bound = self._bindings.get(("claim", namespace, claim))
            if bound is not None:
                offer(Link(
                    principal=bound.principal_entity_id,
                    rank=EVIDENCE_RANK[bound.evidence_class],
                    relationship="ACTED_ON_BEHALF_OF",
                    depth=1,
                    refs=bound.evidence_refs,
                ))
        return links

    def _extend(
        self, link: Link, edge: Edge, record: Optional[AuthorityRecord], depth: int,
        child: _Node, weaken_to: Optional[int],
    ) -> Link:
        rank = max(link.rank, edge.rank)
        if weaken_to is not None:
            rank = max(rank, weaken_to)
        status = link.authority_status
        allowed = link.delegation_allowed
        limit = link.depth_limit
        authority_ref = link.authority_ref
        authority_type = link.authority_type
        revoked_at = link.revoked_at
        if status not in ("revoked", "expired"):
            if allowed is False or (limit is not None and depth > limit):
                status = "out_of_scope"
        if record is not None:
            edge_status = self._authority_status(record, child)
            if edge_status in ("revoked", "expired"):
                status = edge_status
                revoked_at = record.revoked_at if record.revoked_at is not None else revoked_at
            elif status not in ("revoked", "expired", "out_of_scope"):
                status = edge_status
            authority_ref = record.authority_ref
            authority_type = record.authority_type
            allowed = record.delegation_allowed if record.delegation_allowed is not None else allowed
            if record.maximum_delegation_depth is not None:
                bound = depth + record.maximum_delegation_depth
                limit = bound if limit is None else min(limit, bound)
        return link._replace(
            rank=rank, relationship=edge.relationship, depth=depth, authority_status=status,
            authority_ref=authority_ref, authority_type=authority_type,
            delegation_allowed=allowed, depth_limit=limit, revoked_at=revoked_at,
        )

    def _resolve_node(self, agent: str, parent: Optional[str]) -> None:
        node = self._nodes[agent]
        own = self._own_links(node)
        cfg = self.config
        status = "complete"
        if parent is None:
            depth, root, path = 1, agent, agent
            raw_parent = self._parent.get(agent)
            if raw_parent is not None and raw_parent not in self._nodes:
                status = "unresolved_parent"
            links = dict(own)
        else:
            parent_res = self._res[parent]
            depth = parent_res.depth + 1
            root = parent_res.root
            path = parent_res.path + PATH_SEP + agent if depth <= cfg.max_depth else parent_res.path
            edge, record = self._edge(parent, agent)
            if parent_res.status in ("cyclic", "partial", "unresolved_parent"):
                status = "partial"
            elif parent_res.status == "depth_limited":
                status = "depth_limited"
            weaken = _RANK_BEHAVIORAL if agent in self._cycle or parent_res.status == "cyclic" else None
            if depth > cfg.max_depth:
                status = "depth_limited"
            links = dict(own)
            for inherited in parent_res.hard:
                extended = self._extend(inherited, edge, record, depth, node, weaken)
                if status == "depth_limited":
                    # Beyond the processed depth the chain is not walked: the agent
                    # stays visible as an unresolved candidate, never verified.
                    extended = extended._replace(rank=_RANK_UNKNOWN)
                current = links.get(extended.principal)
                if current is None or _link_key(extended) < _link_key(current):
                    links[extended.principal] = extended
        if agent in self._cycle or node.self_edge:
            status = "cyclic"
        elif status == "complete" and self._parent_conflicts.get(agent):
            status = "partial"
        hard = tuple(sorted(links.values(), key=lambda link: link.principal))
        self._res[agent] = Resolution(parent, root, depth, status, path, hard)

    def _order(self, members: set[str]) -> list[tuple[str, Optional[str]]]:
        """Topological order over ``members``; cycles are cut at a stable anchor."""
        order: list[tuple[str, Optional[str]]] = []
        visited: set[str] = set()

        def effective(agent: str) -> Optional[str]:
            parent = self._parent.get(agent)
            return parent if parent in self._nodes else None

        queue: deque[str] = deque(
            agent for agent in sorted(members)
            if (parent := effective(agent)) is None or parent not in members
        )
        while queue:
            agent = queue.popleft()
            if agent in visited:
                continue
            visited.add(agent)
            order.append((agent, effective(agent)))
            for child in self._children.get(agent, ()):
                if child in members and child not in visited:
                    queue.append(child)
        leftover = members - visited
        if not leftover:
            return order
        # Everything left is on a cycle or hanging off one. Each node has one
        # parent, so walking parent pointers finds each cycle exactly once.
        state: dict[str, int] = {}
        anchors: list[str] = []
        for start in sorted(leftover):
            walk: list[str] = []
            cursor: Optional[str] = start
            while cursor is not None and cursor in leftover and cursor not in state:
                state[cursor] = 1
                walk.append(cursor)
                cursor = effective(cursor)
            if cursor is not None and state.get(cursor) == 1 and cursor in walk:
                cycle = walk[walk.index(cursor):]
                anchor = min(cycle, key=lambda a: (self._best_own_rank(a), a))
                cycle_id = stable_hash(self.tenant_id, sorted(cycle))
                for member in cycle:
                    self._cycle[member] = cycle_id
                self._cycle_cut.add(anchor)
                anchors.append(anchor)
            for agent in walk:
                state[agent] = 2
        queue = deque(sorted(anchors))
        while queue:
            agent = queue.popleft()
            if agent in visited:
                continue
            visited.add(agent)
            order.append((agent, None if agent in self._cycle_cut else effective(agent)))
            for child in self._children.get(agent, ()):
                if child in leftover and child not in visited:
                    queue.append(child)
        return order

    def _best_own_rank(self, agent: str) -> int:
        links = self._own_links(self._nodes[agent])
        return min((link.rank for link in links.values()), default=_RANK_UNKNOWN + 1)

    def _closure(self, seeds: Iterable[str]) -> set[str]:
        seen: set[str] = set()
        stack = list(seeds)
        while stack:
            agent = stack.pop()
            if agent in seen:
                continue
            if agent in self._nodes:
                seen.add(agent)
            stack.extend(child for child in self._children.get(agent, ()) if child not in seen)
        return seen

    def _prune(self) -> list[str]:
        removed = []
        for agent in list(self._dirty):
            node = self._nodes.get(agent)
            if node is None or node.observed or node.edges or node.self_edge:
                continue
            if self._auth_by_grantee.get(agent) or ("agent", agent) in self._bindings:
                continue
            removed.append(agent)
        for agent in removed:
            node = self._nodes.pop(agent)
            for deployment in node.deployments:
                self._infra[deployment].discard(agent)
            parent = self._parent.pop(agent, None)
            if parent is not None:
                self._children[parent].discard(agent)
            self._res.pop(agent, None)
            self._soft.pop(agent, None)
            self._cycle.pop(agent, None)
            self._cycle_cut.discard(agent)
            self._last_counts.pop(agent, None)
            self._dirty.update(self._edge_children.get(agent, ()))
            self._dirty.update(self._principal_refs.get(agent, ()))
            for key in self._auth_by_grantor.get(agent, ()):
                self._dirty.add(self._authority[key].grantee_entity_id)
        return removed

    def resolve(self) -> ResolveResult:
        """Re-derive what changed and return the row delta for the read model."""
        removed = self._prune()
        dirty = set(self._dirty)
        for agent in dirty:
            node = self._nodes.get(agent)
            if node is not None:
                self._select_parent(node)
        seeds = set(dirty)
        for agent in removed:
            seeds.update(self._children.get(agent, ()))
        self._dirty = set()
        affected = self._closure(seeds)

        for agent in affected:
            self._cycle.pop(agent, None)
            self._cycle_cut.discard(agent)
        for agent, parent in self._order(affected):
            self._resolve_node(agent, parent)

        soft_affected = self._resolve_soft(affected)
        rebuilt = affected | soft_affected

        result = ResolveResult(tenant_id=self.tenant_id, as_of=None)
        changed: set[tuple[str, str]] = set()
        as_of = self._as_of()
        result.as_of = iso(as_of)
        for agent in removed:
            for principal in self._agent_principals.pop(agent, set()):
                self._rows.pop((principal, agent), None)
                self._principal_agents[principal].discard(agent)
                result.rows_removed.append((principal, agent))
            result.nodes_removed.append(agent)
        for agent in rebuilt:
            self._rebuild_rows(agent, as_of, result, changed)
        counts = self._rollup(as_of, changed)
        clusters = self._clusters(changed)
        result.clusters = clusters
        for key in changed:
            row = self._rows.get(key)
            if row is not None:
                result.rows_upserted.append(row)
        result.rows_upserted.sort(key=lambda r: (r["principal_entity_id"], r["agent_entity_id"]))
        result.rows_removed.sort()
        moved = set()
        for agent, count in counts.items():
            fingerprint = tuple(count.values())
            if self._last_counts.get(agent) != fingerprint:
                self._last_counts[agent] = fingerprint
                moved.add(agent)
        result.nodes_upserted = [self._node_record(agent, counts) for agent in sorted(rebuilt | moved)]
        result.nodes_removed.sort()
        live_principals = {p for p, agents in self._principal_agents.items() if agents}
        result.summaries = [
            self._summary(principal, as_of, clusters.get(principal, []))
            for principal in sorted(live_principals)
        ]
        result.summaries_removed = sorted(self._persisted_summaries - live_principals)
        self._persisted_summaries = live_principals
        result.stats = {
            "agents": len(self._nodes),
            "rows": len(self._rows),
            "dirty": len(dirty),
            "affected": len(rebuilt),
            "rows_changed": len(changed),
            "duplicates_ignored": self.duplicates_ignored,
            "cross_tenant_rejected": self.cross_tenant_rejected,
        }
        return result

    def _as_of(self) -> Optional[float]:
        latest = None
        for node in self._nodes.values():
            if node.last is not None and (latest is None or node.last > latest):
                latest = node.last
        return latest

    def _group_links(self, deployment: str) -> tuple[str, ...]:
        """The principal a shared deployment *suggests*, gated hard on share and count."""
        tally: Counter[str] = Counter()
        linked = 0
        for member in self._infra.get(deployment, ()):
            res = self._res.get(member)
            principals = {link.principal for link in res.hard if link.rank < _RANK_UNKNOWN} if res else set()
            if principals:
                linked += 1
                tally.update(principals)
        if linked < self.config.prob_min_linked or not tally:
            return ()
        principal, top = min(tally.items(), key=lambda item: (-item[1], item[0]))
        if top / linked < self.config.prob_min_share:
            return ()
        return (principal,)

    def _resolve_soft(self, affected: set[str]) -> set[str]:
        """Probabilistic association, kept apart from hard links; never verified."""
        groups: set[str] = set()
        for agent in affected:
            groups.update(self._nodes[agent].deployments)
        seeds: set[str] = set(affected)
        for group in groups:
            candidate = self._group_links(group)
            if self._group_candidate.get(group) != candidate:
                self._group_candidate[group] = candidate
                seeds.update(self._infra.get(group, ()))
        members = self._closure(seeds)
        children: dict[str, list[str]] = defaultdict(list)
        roots = []
        for agent in members:
            parent = self._res[agent].parent
            if parent is None or parent not in members:
                roots.append(agent)
            else:
                children[parent].append(agent)
        stack = roots
        while stack:
            agent = stack.pop()
            stack.extend(children.get(agent, ()))
            res = self._res[agent]
            hard_principals = {link.principal for link in res.hard if link.rank < _RANK_UNKNOWN}
            if hard_principals:
                self._soft.pop(agent, None)
                continue
            soft: dict[str, Link] = {}
            if res.parent is not None:
                for link in self._soft.get(res.parent, ()):
                    soft[link.principal] = link._replace(
                        depth=res.depth, relationship=self._nodes[agent].edges.get(res.parent, Edge(0, 0, "SPAWNED")).relationship,
                    )
            for group in sorted(self._nodes[agent].deployments):
                for principal in self._group_candidate.get(group, ()):
                    soft.setdefault(principal, Link(
                        principal=principal, rank=_RANK_INFRA, relationship="ACTED_ON_BEHALF_OF",
                        depth=1, refs=(),
                    ))
            if soft:
                self._soft[agent] = tuple(sorted(soft.values(), key=lambda link: link.principal))
            else:
                self._soft.pop(agent, None)
        return members

    def _effective_links(self, agent: str) -> tuple[Link, ...]:
        res = self._res[agent]
        soft = self._soft.get(agent, ())
        if not soft:
            return res.hard
        merged = {link.principal: link for link in res.hard}
        for link in soft:
            current = merged.get(link.principal)
            if current is None or link.rank < current.rank:
                merged[link.principal] = link
        return tuple(sorted(merged.values(), key=lambda link: link.principal))

    def _rebuild_rows(
        self, agent: str, as_of: Optional[float], result: ResolveResult, changed: set[tuple[str, str]],
    ) -> None:
        links = self._effective_links(agent)
        node = self._nodes[agent]
        res = self._res[agent]
        new_keys: dict[str, dict[str, Any]] = {}
        has_proof = any(is_proof_class(class_of(link.rank)) for link in links)
        competing = sorted(link.principal for link in links) if len(links) > 1 else []
        for link in links:
            demoted = has_proof and not is_proof_class(class_of(link.rank))
            new_keys[link.principal] = self._row(node, res, link, demoted, competing, as_of)
        if not links:
            placeholder = Link(UNATTRIBUTED, _RANK_UNKNOWN, "ACTED_ON_BEHALF_OF", res.depth)
            new_keys[UNATTRIBUTED] = self._row(node, res, placeholder, False, [], as_of)
        for principal in list(self._agent_principals.get(agent, ())):
            if principal not in new_keys:
                old = self._rows.pop((principal, agent), None)
                self._principal_agents[principal].discard(agent)
                self._agent_principals[agent].discard(principal)
                result.rows_removed.append((principal, agent))
                if old is not None:
                    self._log_restatement(result, old, None)
        for principal, row in new_keys.items():
            old = self._rows.get((principal, agent))
            if old is not None:
                row["cluster_ids"] = old.get("cluster_ids", [])
            if old != row:
                self._rows[(principal, agent)] = row
                changed.add((principal, agent))
                self._log_restatement(result, old, row)
            self._agent_principals[agent].add(principal)
            self._principal_agents[principal].add(agent)

    def _log_restatement(
        self, result: ResolveResult, old: Optional[dict[str, Any]], new: Optional[dict[str, Any]],
    ) -> None:
        if old is None:
            return
        if new is not None and all(old.get(f) == new.get(f) for f in _RESTATED_FIELDS):
            return
        if len(result.restatements) >= self.config.restatement_row_log_cap:
            result.restatements_dropped += 1
            return
        before = {f: old.get(f) for f in _RESTATED_FIELDS}
        after = {f: new.get(f) for f in _RESTATED_FIELDS} if new is not None else None
        result.restatements.append({
            "tenant_id": self.tenant_id,
            "principal_entity_id": old["principal_entity_id"],
            "agent_entity_id": old["agent_entity_id"],
            "before": before,
            "after": after,
            "change_kind": "removed" if new is None else "restated",
        })

    def _row(
        self, node: _Node, res: Resolution, link: Link, demoted: bool, competing: list[str],
        as_of: Optional[float],
    ) -> dict[str, Any]:
        evidence_class = class_of(link.rank)
        attribution = "unresolved" if demoted else attribution_for(evidence_class)
        refs = sorted({*node.samples, *link.refs})[: self.config.evidence_ref_sample]
        indirect = link.depth > 1
        verification = node.verification
        source_quality = (
            0.9 if verification & EFFECT_PROOF_STATES
            else 0.7 if "deployment_verified" in verification
            else 0.4 if verification else None
        )
        relationship_status = _status_for_row(link, node)
        return {
            "tenant_id": self.tenant_id,
            "principal_entity_id": link.principal,
            "agent_entity_id": node.agent_id,
            "agent_definition_id": min(node.definitions) if node.definitions else None,
            "agent_instance_id": next(iter(node.instances)) if len(node.instances) == 1 else None,
            "agent_deployment_id": min(node.deployments) if node.deployments else None,
            "operator_entity_id": min(node.operators) if node.operators else None,
            "root_agent_id": res.root,
            "parent_agent_id": res.parent,
            "root_run_id": min(node.root_runs) if node.root_runs else None,
            "parent_run_id": min(node.parent_runs) if node.parent_runs else None,
            "relationship_type": link.relationship,
            "relationship_status": relationship_status,
            "depth": link.depth,
            "direct_or_indirect": "indirect" if indirect else "direct",
            "authority_ref": link.authority_ref or (min(a for a, _ in node.fact_authority) if node.fact_authority else None),
            "authority_type": link.authority_type or (min(t for _, t in node.fact_authority) if node.fact_authority else None),
            "authority_resolution_status": link.authority_status,
            "attribution_class": attribution,
            "evidence_class": evidence_class,
            "lineage_status": res.status,
            "first_seen": iso(node.first),
            "last_seen": iso(node.last),
            "active_state": self._active_state(node, relationship_status, as_of),
            "confidence": {
                "agent_identity_confidence": None,
                "instance_binding_confidence": None,
                "principal_link_confidence": LINK_CONFIDENCE[evidence_class],
                "operator_link_confidence": None,
                "delegation_confidence": LINK_CONFIDENCE[evidence_class] if indirect else None,
                "authority_confidence": (
                    0.99 if link.authority_status == "verified"
                    else 0.5 if link.authority_status == "declared" else None
                ),
                "execution_link_confidence": None,
                "source_quality": source_quality,
                "external_effect_confidence": 0.9 if node.effects_verified else (0.3 if node.effects_reported else None),
                "outcome_confidence": 0.5 if node.outcomes else None,
            },
            "evidence_count": node.events,
            "evidence_refs": refs,
            "evidence_digest": f"{node.digest:016x}" if node.events else None,
            "source_namespaces": sorted(node.namespaces),
            "agent_instance_count": len(node.instances),
            "agent_run_count": len(node.runs),
            "competing_principal_ids": competing,
            "cluster_ids": [],
            "risk_signal_count": self._risk_count(node),
            # Not observing activity is not evidence of absence.
            "economic_activity_present": True if node.economic else None,
            "communication_activity_present": True if node.communication else None,
            "last_reconciled_at": iso(as_of),
            "projection_version": PROJECTION_VERSION,
        }

    def _risk_count(self, node: _Node) -> Optional[int]:
        external = self._risk_flags.get(node.agent_id)
        if external is None and not node.risk_seen:
            return None
        return (external or 0) + node.risk_count

    def _active_state(self, node: _Node, relationship_status: str, as_of: Optional[float]) -> str:
        if relationship_status in ("revoked", "terminated"):
            return relationship_status
        if node.last is None or as_of is None:
            return "unknown"
        return "active" if as_of - node.last <= self.config.active_window_seconds else "inactive"

    def _rollup(self, as_of: Optional[float], changed: set[tuple[str, str]]) -> dict[str, dict[str, Any]]:
        """Activity windows move with ``as_of``; descendant counts roll up leaf-first."""
        iso_as_of = iso(as_of)
        for key, row in self._rows.items():
            node = self._nodes[key[1]]
            state = self._active_state(node, row["relationship_status"], as_of)
            if row["active_state"] != state:
                row["active_state"] = state
                changed.add(key)
            row["last_reconciled_at"] = iso_as_of

        counts: dict[str, dict[str, Any]] = {
            agent: {"direct": 0, "total": 0, "active": 0, "risk": None, "max_depth": 0}
            for agent in self._nodes
        }
        order = sorted(self._nodes, key=lambda agent: -self._res[agent].depth)
        for agent in order:
            parent = self._res[agent].parent
            if parent is None:
                continue
            mine = counts[agent]
            theirs = counts[parent]
            node = self._nodes[agent]
            theirs["direct"] += 1
            theirs["total"] += mine["total"] + 1
            active = node.last is not None and as_of is not None and (
                as_of - node.last <= self.config.active_window_seconds
            )
            theirs["active"] += mine["active"] + (1 if active else 0)
            own_risk = self._risk_count(node)
            if own_risk is not None or mine["risk"] is not None:
                flagged = (mine["risk"] or 0) + (1 if own_risk else 0)
                theirs["risk"] = (theirs["risk"] or 0) + flagged
            theirs["max_depth"] = max(theirs["max_depth"], mine["max_depth"] + 1)
        return counts

    def _clusters(self, changed: set[tuple[str, str]]) -> dict[str, list[dict[str, Any]]]:
        """Derived analytic groupings. Each one states why its members are grouped."""
        cfg = self.config
        out: dict[str, list[dict[str, Any]]] = {}
        membership: dict[tuple[str, str], list[str]] = defaultdict(list)
        for principal, agents in self._principal_agents.items():
            if not agents:
                continue
            groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
            for agent in agents:
                node = self._nodes[agent]
                res = self._res[agent]
                if res.parent is not None or self._children.get(agent):
                    groups[("delegation_cluster", "shared_delegation_root", res.root)].append(agent)
                for deployment in node.deployments:
                    kind = "infrastructure_cluster" if principal == UNATTRIBUTED else "agent_fleet"
                    basis = "shared_infrastructure" if principal == UNATTRIBUTED else "shared_deployment"
                    groups[(kind, basis, deployment)].append(agent)
                for operator in node.operators:
                    groups[("agent_fleet", "shared_operator", operator)].append(agent)
                if node.tools:
                    groups[("execution_cluster", "shared_tool_patterns", stable_hash(sorted(node.tools)))].append(agent)
                if node.first is not None:
                    bucket = int(node.first // cfg.swarm_bucket_seconds)
                    groups[("agent_swarm", "temporal_coordination", str(bucket))].append(agent)
            emitted = []
            ranked = sorted(
                (item for item in groups.items() if len(item[1]) >= cfg.min_cluster_size),
                key=lambda item: (-len(item[1]), item[0]),
            )
            for (kind, basis, key), members in ranked[: cfg.max_clusters_per_principal]:
                cluster_id = "lc_" + stable_hash(self.tenant_id, principal, kind, basis, key)
                emitted.append(self._cluster(principal, cluster_id, kind, basis, key, members))
                for agent in members:
                    membership[(principal, agent)].append(cluster_id)
            out[principal] = emitted
        for key, row in self._rows.items():
            ids = sorted(membership.get(key, ()))
            if row.get("cluster_ids") != ids:
                row["cluster_ids"] = ids
                changed.add(key)
        return out

    def _cluster(
        self, principal: str, cluster_id: str, kind: str, basis: str, key: str, members: list[str],
    ) -> dict[str, Any]:
        cfg = self.config
        ordered = sorted(members)
        classes = {self._rows[(principal, agent)]["attribution_class"] for agent in members}
        weak = basis in vocab.WEAK_CLUSTER_BASES
        if principal == UNATTRIBUTED or weak:
            attribution = "suspected_cluster"
        elif classes == {"verified"}:
            attribution = "verified"
        elif classes <= {"verified", "inferred"}:
            attribution = "inferred"
        else:
            attribution = "suspected_cluster"
        active = sum(1 for agent in members if self._rows[(principal, agent)]["active_state"] == "active")
        risk_values = [self._rows[(principal, agent)]["risk_signal_count"] for agent in members]
        risk_flagged = (
            None if all(value is None for value in risk_values)
            else sum(1 for value in risk_values if value)
        )
        return {
            "tenant_id": self.tenant_id,
            "principal_entity_id": principal,
            "cluster_id": cluster_id,
            "kind": kind,
            "label": f"{basis}:{key}",
            "member_count": len(members),
            "active_count": active,
            "risk_flagged_count": risk_flagged,
            "bases": [{"basis": basis, "detail": key, "evidence_refs": []}],
            "attribution_class": attribution,
            # Only an all-verified, non-weak grouping says anything about control.
            "implies_common_control": attribution == "verified",
            "sample_agent_ids": ordered[: cfg.sample_ids],
            "next_cursor": None,
        }

    def _summary(self, principal: str, as_of: Optional[float], clusters: list[dict[str, Any]]) -> dict[str, Any]:
        agents = self._principal_agents[principal]
        rows = [self._rows[(principal, agent)] for agent in agents]
        by_attr = Counter(row["attribution_class"] for row in rows)
        attributed = [row for row in rows if row["attribution_class"] in ("verified", "inferred")]
        direct = sum(1 for row in attributed if row["direct_or_indirect"] == "direct")
        active = sum(1 for row in rows if row["active_state"] == "active")
        unknown_state = sum(1 for row in rows if row["active_state"] == "unknown")
        nodes = [self._nodes[agent] for agent in agents]
        definitions: set[str] = set()
        no_definition = 0
        instances: set[str] = set()
        runs: set[str] = set()
        tools: set[str] = set()
        services: set[str] = set()
        first = last = None
        for node in nodes:
            if node.definitions:
                definitions |= node.definitions
            else:
                no_definition += 1
            instances |= node.instances
            runs |= node.runs
            tools |= node.tools
            services |= node.services
            if node.first is not None and (first is None or node.first < first):
                first = node.first
            if node.last is not None and (last is None or node.last > last):
                last = node.last
        statuses = Counter(row["lineage_status"] for row in rows)
        reasons = [*self._source_truncation, *self._pass_disclosures]
        if statuses.get("depth_limited"):
            reasons.append(f"depth_limited:{statuses['depth_limited']}")
        partial_reasons = [
            f"{status}:{statuses[status]}"
            for status in ("cyclic", "unresolved_parent", "partial") if statuses.get(status)
        ]
        completeness = "truncated" if reasons else ("partial" if partial_reasons else "complete")
        risk_values = [row["risk_signal_count"] for row in rows]
        return {
            "tenant_id": self.tenant_id,
            "principal_entity_id": principal,
            # An agent with no reported definition is its own logical identity.
            "unique_agent_definitions": len(definitions) + no_definition,
            "agent_instances": len(instances) if instances else None,
            "agent_runs": len(runs) if runs else None,
            "active_agents": active,
            "historical_agents": len(rows) - active - unknown_state,
            "direct_agents": direct,
            "indirect_agents": len(attributed) - direct,
            "probabilistic_agents": by_attr.get("suspected_cluster", 0),
            "unresolved_agents": by_attr.get("unresolved", 0),
            "revoked_agents": sum(1 for row in rows if row["relationship_status"] == "revoked"),
            "out_of_scope_agents": sum(1 for row in rows if row["authority_resolution_status"] == "out_of_scope"),
            "unknown_state_agents": unknown_state,
            "risk_flagged_agents": (
                None if all(value is None for value in risk_values)
                else sum(1 for value in risk_values if value)
            ),
            "max_delegation_depth": max((row["depth"] for row in rows), default=None),
            "cyclic_agents": statuses.get("cyclic", 0),
            "tools_used": len(tools) if tools else None,
            "services_used": len(services) if services else None,
            "verified_links": by_attr.get("verified", 0),
            "inferred_links": by_attr.get("inferred", 0),
            "disclosure": {
                "as_of": iso(as_of),
                "computed_at": iso(as_of),
                "evidence_window_start": iso(first),
                "evidence_window_end": iso(last),
                "projection_version": PROJECTION_VERSION,
                "completeness": completeness,
                "truncated": bool(reasons),
                "truncation_reasons": reasons + partial_reasons,
            },
            "activity": self._activity(principal, nodes, rows, clusters, as_of),
        }

    def _activity(
        self, principal: str, nodes: list[_Node], rows: list[dict[str, Any]],
        clusters: list[dict[str, Any]], as_of: Optional[float],
    ) -> dict[str, Any]:
        """Neutral activity counters; Risk360 owns any classification of them."""
        timeline: Counter[int] = Counter()
        for node in nodes:
            if node.first is not None:
                timeline[int(node.first // self.config.swarm_bucket_seconds)] += 1
        wallets: set[str] = set()
        transactions: set[str] = set()
        providers: set[str] = set()
        tools: set[str] = set()
        effects_verified: set[str] = set()
        effects_reported: set[str] = set()
        outcomes: set[str] = set()
        events = denied = ephemeral = instance_total = run_total = revoked_active = high_risk = terminated = 0
        for node in nodes:
            wallets |= node.wallets
            transactions |= node.transactions
            providers |= node.providers
            tools |= node.tools
            effects_verified |= node.effects_verified
            effects_reported |= node.effects_reported
            outcomes |= node.outcomes
            events += node.events
            denied += node.denied
            instance_total += len(node.instances)
            run_total += len(node.runs)
            high_risk += node.risk_count
            terminated += 1 if node.terminated else 0
            if len(node.runs) <= _INSTANCE_SHORTLIVED_RUNS and node.first is not None and node.first == node.last:
                ephemeral += 1
        for row in rows:
            if row["relationship_status"] == "revoked" and row["active_state"] == "revoked":
                node = self._nodes[row["agent_entity_id"]]
                link = next((li for li in self._effective_links(node.agent_id) if li.principal == principal), None)
                if link and link.revoked_at is not None and node.last is not None and node.last > link.revoked_at:
                    revoked_active += 1
        direct_children = Counter(row["parent_agent_id"] for row in rows if row["parent_agent_id"])
        ordered_buckets = sorted(timeline.items())[-1440:]
        return {
            "agent_count": len(nodes),
            "event_count": events,
            "denied_event_count": denied,
            "high_risk_event_count": high_risk,
            "ephemeral_agents": ephemeral,
            "terminated_agents": terminated,
            "instance_total": instance_total,
            "run_total": run_total,
            "wallet_count": len(wallets),
            "transaction_count": len(transactions),
            "provider_count": len(providers),
            "tool_count": len(tools),
            "verified_effect_count": len(effects_verified),
            "reported_effect_count": len(effects_reported),
            "outcome_count": len(outcomes),
            "revoked_agent_activity": revoked_active,
            "max_direct_fanout": max(direct_children.values(), default=0),
            "shared_infra_largest_share": max(
                (c["member_count"] for c in clusters if c["kind"] in ("infrastructure_cluster", "agent_fleet")),
                default=0,
            ),
            "spawn_timeline": [[bucket * self.config.swarm_bucket_seconds, count] for bucket, count in ordered_buckets],
            "spawn_timeline_truncated": len(timeline) > 1440,
            "bucket_seconds": self.config.swarm_bucket_seconds,
            "tool_sample": sorted(tools)[:20],
            "provider_sample": sorted(providers)[:20],
            "wallet_sample": sorted(wallets)[:20],
        }

    def _node_record(self, agent: str, counts: dict[str, dict[str, Any]]) -> dict[str, Any]:
        node = self._nodes[agent]
        res = self._res[agent]
        count = counts[agent]
        return {
            "tenant_id": self.tenant_id,
            "agent_entity_id": agent,
            "parent_agent_id": res.parent,
            "reported_parent_agent_id": self._parent.get(agent),
            "root_agent_id": res.root,
            "depth": res.depth,
            "path": res.path,
            "lineage_status": res.status,
            "cycle_id": self._cycle.get(agent),
            "principal_entity_ids": sorted(self._agent_principals.get(agent, ())),
            "agent_definition_ids": sorted(node.definitions)[:20],
            "agent_deployment_ids": sorted(node.deployments)[:20],
            "operator_entity_ids": sorted(node.operators)[:20],
            "agent_instance_count": len(node.instances),
            "agent_instance_sample": sorted(node.instances)[:self.config.sample_ids],
            "agent_run_count": len(node.runs),
            "agent_run_sample": sorted(node.runs)[:self.config.sample_ids],
            "tool_sample": sorted(node.tools)[:20],
            "service_sample": sorted(node.services)[:20],
            "verified_effects": sorted(node.effects_verified)[:20],
            "reported_effects": sorted(node.effects_reported)[:20],
            "outcome_refs": sorted(node.outcomes)[:20],
            "authority_refs": sorted({a for a, _ in node.fact_authority} | {
                self._authority[key].authority_ref for key in self._auth_by_grantee.get(agent, ())
            })[:20],
            "first_seen": iso(node.first),
            "last_seen": iso(node.last),
            "evidence_refs": list(node.samples),
            "direct_child_count": count["direct"],
            "recursive_descendant_count": count["total"],
            "active_descendant_count": count["active"],
            "risk_descendant_count": count["risk"],
            "max_descendant_depth": count["max_depth"],
            "projection_version": PROJECTION_VERSION,
        }

    # ── accessors used by rebuild comparison and the scale proof ──────────

    def rows(self) -> dict[tuple[str, str], dict[str, Any]]:
        return self._rows

    def agent_count(self) -> int:
        return len(self._nodes)


def compare_rows(
    prior: dict[tuple[str, str], dict[str, Any]],
    current: dict[tuple[str, str], dict[str, Any]],
    *,
    cap: int = DEFAULT_CONFIG.restatement_row_log_cap,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]], int]:
    """Diff a stored projection against a full rebuild: removed keys, restatements, dropped."""
    removed = sorted(key for key in prior if key not in current)
    restatements: list[dict[str, Any]] = []
    dropped = 0
    for key, old in prior.items():
        new = current.get(key)
        if new is not None and all(old.get(f) == new.get(f) for f in _RESTATED_FIELDS):
            continue
        if len(restatements) >= cap:
            dropped += 1
            continue
        restatements.append({
            "tenant_id": old["tenant_id"],
            "principal_entity_id": old["principal_entity_id"],
            "agent_entity_id": old["agent_entity_id"],
            "before": {f: old.get(f) for f in _RESTATED_FIELDS},
            "after": {f: new.get(f) for f in _RESTATED_FIELDS} if new is not None else None,
            "change_kind": "removed" if new is None else "restated",
        })
    return removed, restatements, dropped


def _version_key(item: Any) -> tuple[int, str]:
    """Version, then a content hash so an equal-version conflict folds deterministically."""
    return (item.version, stable_hash(repr(item)))


def _link_key(link: Link) -> tuple[int, int, str]:
    return (link.rank, link.depth, link.authority_ref or "")
