"""Blast radius over the Kyber Graph — what a change can reach.

Before an operator pauses a connector, rolls back a release or redeploys a
service, the question is "what else does this touch?". This module answers it by
walking the Kyber Graph outward from the subject node to the services that
depend on it, the feature surfaces those serve, the tenants entitled to those
features, and the graph domains underneath.

Three commitments, each of which is a defect this module is written to not
repeat.

**It does not reimplement the agent-access answer.**
``services/agent_access_intelligence/risk_service.py::blast_radius`` already
answers the agent and capability form of this question from *observed*
installations, and it is already hardened around the case that matters — an
agent nobody has observed has an unknown reach, not an empty one. Agent and
capability subjects are delegated there through a lazy import declared in
``services/kyber/seams.py``, and that call's ``missing_inputs`` are merged into
this result rather than dropped.

**It is not a fleet-wide rollup.**
``services/agent_access_intelligence/kyber_ops_routes.py`` states the reason
directly: a blast radius is a per-subject exposure answer whose honesty depends
on every input for that subject being present, so "summing it over tenants would
produce a number no operator can act on and would hide exactly the tenants whose
inputs were missing". There is deliberately no ``for_fleet``.

**It is cycle- and budget-safe, and says when a budget bound.**
``DEPENDS_ON`` cycles exist in real topology (two services that each read the
other's projection), so the walk carries a visited set. Depth and node budgets
are hard, and when either binds the result is marked ``truncated`` with a lower
``confidence`` — a truncated reach reported at full confidence is how an
operator concludes a change is safe when the walk simply stopped early.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from shared.logger.logger import get_logger, metrics

from .contracts import BlastRadiusResult
from .scoped_gateway import get_store

logger = get_logger("aether.kyber.graph.blast_radius")

#: Hard traversal ceilings. Depth 3 reaches service → feature → tenant, which is
#: the shape of every question this surface is asked.
MAX_DEPTH = 3
MAX_NODES = 400

#: Per-node edge fan-out bound, so one hub node cannot consume the whole budget.
MAX_EDGES_PER_NODE = 200

#: Subject types this module walks itself.
GRAPH_SUBJECT_PREFIXES: dict[str, str] = {
    "service": "service",
    "workerrole": "worker",
    "release": "release",
    "deployment": "deployment",
    "feature": "feature",
    "featuresurface": "feature",
    "featureentitlement": "entitlement",
    "modeldeployment": "model",
    "projection": "projection",
    "tenant": "tenant",
    "graphdomain": "domain",
}

#: Subject types owned by the agent-access plane. Delegated, never duplicated.
DELEGATED_SUBJECTS: frozenset[str] = frozenset({"agent", "capability"})

#: Node type → the bucket it lands in on the result.
_SERVICE_TYPES: frozenset[str] = frozenset({"Service", "WorkerRole", "ModelDeployment"})
_FEATURE_TYPES: frozenset[str] = frozenset({"FeatureSurface", "FeatureEntitlement"})
_TENANT_TYPES: frozenset[str] = frozenset({"Tenant"})
_DOMAIN_TYPES: frozenset[str] = frozenset({"GraphDomain", "TenantGraph"})

#: Relationships worth following. Restricting the walk keeps a blast radius
#: about *propagation* — an audit event attached to a service does not widen
#: what a change to it can break.
PROPAGATING_EDGES: frozenset[str] = frozenset({
    "DEPENDS_ON", "SERVED_BY", "PRODUCED_BY", "RUNS", "HOSTS", "DEPLOYED_TO",
    "CHANGED", "EXPOSES_FEATURE", "ENTITLED_TO", "OWNS_GRAPH",
    "CONTAINS_DOMAIN", "PROJECTS_TO", "INGESTS_FROM", "AFFECTS", "DEGRADED",
})

_CONFIDENCE_COMPLETE = 0.9
_CONFIDENCE_TRUNCATED = 0.45
_CONFIDENCE_PARTIAL = 0.35


def node_key_for(subject_type: str, subject_id: str) -> str:
    """The Kyber Graph node key for one subject.

    A caller that already holds a node key (``service:identity-worker``) may
    pass it straight through; anything else is prefixed from the subject type.
    Node keys are the natural keys edges reference, so getting this wrong would
    silently resolve to "no such node" — which is why an unresolved anchor sets
    ``exposure_known: false`` rather than returning an empty reach.
    """
    subject_id = str(subject_id or "").strip()
    if ":" in subject_id:
        return subject_id
    prefix = GRAPH_SUBJECT_PREFIXES.get(str(subject_type or "").strip().lower())
    return f"{prefix}:{subject_id}" if prefix else subject_id


class KyberBlastRadiusService:
    """One bounded blast-radius review for one subject.

    The store is injectable and defaults to the package provider; ``None``
    denies the answer rather than returning an empty reach.
    """

    def __init__(
        self,
        *,
        store: Optional[Any] = None,
        max_depth: int = MAX_DEPTH,
        max_nodes: int = MAX_NODES,
    ) -> None:
        self._store = store
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))

    def _resolve_store(self) -> Optional[Any]:
        return self._store if self._store is not None else get_store()

    async def for_subject(
        self,
        *,
        subject_type: str,
        subject_id: str,
        environment: Optional[str] = None,
        max_depth: int = MAX_DEPTH,
        tenant_id: Optional[str] = None,
    ) -> BlastRadiusResult:
        """What a change to this subject can reach.

        Args:
            subject_type: ``Service``, ``Release``, ``Deployment``,
                ``FeatureSurface`` … or ``Agent`` / ``Capability``, which are
                delegated to the agent-access plane.
            subject_id: A node key, or a bare id to be prefixed by type.
            environment: Restricts the walk to one environment's topology.
            max_depth: Requested depth, clamped to :data:`MAX_DEPTH`.
            tenant_id: Required only for a delegated agent/capability subject —
                that answer is per tenant by design and cannot be summed.

        Returns:
            A :class:`~services.kyber.graph.contracts.BlastRadiusResult`.
            ``exposure_known`` is ``False`` whenever an input was missing or a
            budget bound, and ``missing_inputs`` names what was absent.
        """
        depth = min(max(1, int(max_depth)), self.max_depth)
        kind = str(subject_type or "").strip().lower()
        result = BlastRadiusResult(
            subject_type=str(subject_type or "unknown"),
            subject_id=str(subject_id or ""),
            environment=environment,
        )

        store = self._resolve_store()
        if store is None:
            result.missing_inputs = ["kyber_graph_store:unavailable"]
            result.exposure_known = False
            result.confidence = 0.0
            metrics.increment(
                "kyber_blast_radius_reviews_total",
                labels={"subject": kind or "unknown", "exposure_known": "false"},
            )
            return result

        missing: list[str] = []
        # A delegated subject has no Kyber Graph node and never will: agents and
        # capabilities are owned by the agent-access plane, and
        # GRAPH_SUBJECT_PREFIXES deliberately has no entry for them. Walking the
        # graph for one anyway anchors on a bare id that cannot resolve, which
        # charges the answer a missing input that was never supposed to exist
        # and pins confidence at 0.0 — so the one number telling an operator how
        # much of the answer to trust carries no information on exactly the
        # surface where the delegated plane does know. Delegated, never
        # duplicated: skip the walk and let the owning plane answer.
        delegated_subject = kind in DELEGATED_SUBJECTS
        if delegated_subject:
            walk = _empty_walk()
        else:
            anchor_key = node_key_for(subject_type, subject_id)
            walk = await self._walk(store, anchor_key, environment=environment, depth=depth)
        missing.extend(walk["missing_inputs"])

        result.affected_services = sorted(walk["services"])
        result.affected_features = sorted(walk["features"])
        result.affected_tenants = sorted(walk["tenants"])
        result.affected_graph_domains = sorted(walk["domains"])
        result.evidence_references = sorted(walk["evidence"])
        result.traversal_depth = int(walk["depth_reached"])
        result.truncated = bool(walk["truncated"])

        if kind in DELEGATED_SUBJECTS:
            delegated = await self._delegate(kind, subject_id, tenant_id)
            missing.extend(delegated["missing_inputs"])
            if delegated["tenant_id"]:
                result.affected_tenants = sorted(
                    set(result.affected_tenants) | {delegated["tenant_id"]}
                )
            result.affected_services = sorted(
                set(result.affected_services) | set(delegated["servers"])
            )
            result.affected_features = sorted(
                set(result.affected_features) | set(delegated["capabilities"])
            )
            if not delegated["exposure_known"]:
                # The delegated plane says it does not know. Neither do we.
                result.truncated = result.truncated or bool(delegated["missing_inputs"])

        result.customer_visible = bool(result.affected_tenants or result.affected_features)
        result.missing_inputs = _dedupe(missing)
        result.exposure_known = not result.truncated and not result.missing_inputs
        result.confidence = _confidence(
            anchor_resolved=bool(walk["anchor_resolved"]),
            truncated=result.truncated,
            missing=result.missing_inputs,
        )

        metrics.increment(
            "kyber_blast_radius_reviews_total",
            labels={
                "subject": kind or "unknown",
                "exposure_known": str(result.exposure_known).lower(),
            },
        )
        return result

    # ── Traversal ────────────────────────────────────────────────────────────

    async def _walk(
        self,
        store: Any,
        anchor_key: str,
        *,
        environment: Optional[str],
        depth: int,
    ) -> dict[str, Any]:
        """Breadth-first outward from the anchor, cycle- and budget-safe.

        ``visited`` is what makes this terminate on a cyclic topology, and it is
        keyed on ``node_key`` — the natural key edges reference — so the same
        node reached by two paths is charged to the budget once.
        """
        buckets: dict[str, set[str]] = {
            "services": set(),
            "features": set(),
            "tenants": set(),
            "domains": set(),
            "evidence": set(),
        }
        missing: list[str] = []

        anchor = await self._get_node(store, anchor_key, environment, missing)
        if anchor is None:
            missing.append(f"kyber_graph_node:node_key={anchor_key}")
            return {
                **buckets,
                "anchor_resolved": False,
                "truncated": False,
                "depth_reached": 0,
                "missing_inputs": missing,
            }
        self._classify(anchor, buckets)

        visited: set[str] = {anchor_key}
        frontier: list[str] = [anchor_key]
        truncated = False
        depth_reached = 0

        for hop in range(depth):
            next_frontier: list[str] = []
            for key in frontier:
                neighbors = await self._neighbors(store, key, environment, missing)
                for neighbor_key in neighbors:
                    if neighbor_key in visited:
                        continue
                    if len(visited) >= self.max_nodes:
                        truncated = True
                        break
                    visited.add(neighbor_key)
                    node = await self._get_node(store, neighbor_key, environment, missing)
                    if node is None:
                        # An edge pointing at a node we cannot read is a real
                        # gap, not an absence of reach.
                        missing.append(f"kyber_graph_node:node_key={neighbor_key}")
                        continue
                    self._classify(node, buckets)
                    next_frontier.append(neighbor_key)
                if truncated:
                    break
            depth_reached = hop + 1
            if truncated or not next_frontier:
                break
            frontier = next_frontier
        else:
            # Every requested hop ran and nodes were still being discovered, so
            # there are boundary nodes whose onward edges were never read. That
            # is a missing input, not a truncated result: the nodes we found are
            # all reported. `truncated` stays reserved for the node budget,
            # which is the only bound that makes us DROP something we saw.
            if frontier:
                missing.append(f"kyber_graph_walk:depth_bound_reached:depth={depth}")

        return {
            **buckets,
            "anchor_resolved": True,
            "truncated": truncated,
            "depth_reached": depth_reached,
            "missing_inputs": missing,
        }

    async def _get_node(
        self, store: Any, node_key: str, environment: Optional[str], missing: list[str]
    ) -> Optional[Any]:
        try:
            return await store.get_node(node_key, environment=environment)
        except Exception as exc:
            logger.warning(f"kyber: blast radius node lookup failed for {node_key}: {exc}")
            missing.append(f"kyber_graph_node:lookup_failed:{node_key}")
            return None

    async def _neighbors(
        self, store: Any, node_key: str, environment: Optional[str], missing: list[str]
    ) -> list[str]:
        """Propagating neighbours in both directions, deduplicated and ordered.

        Both directions, because "what breaks if this service goes down?" and
        "what does this deployment change?" are the same edges read the two
        ways round.
        """
        keys: list[str] = []
        seen: set[str] = set()
        for direction, reader in (("out", "edges_from"), ("in", "edges_to")):
            method = getattr(store, reader, None)
            if method is None:
                missing.append(f"kyber_graph_store:{reader}_unavailable")
                continue
            try:
                edges = await method(node_key, environment=environment, limit=MAX_EDGES_PER_NODE)
            except Exception as exc:
                logger.warning(f"kyber: blast radius {reader}({node_key}) failed: {exc}")
                missing.append(f"kyber_graph_edges:{reader}_failed:{node_key}")
                continue
            edges = list(edges or ())
            if len(edges) >= MAX_EDGES_PER_NODE:
                missing.append(f"kyber_graph_edges:fanout_truncated:{node_key}")
            for edge in edges:
                relationship = getattr(edge, "relationship_type", None)
                if relationship not in PROPAGATING_EDGES:
                    continue
                other = (
                    getattr(edge, "target_node_key", None)
                    if direction == "out"
                    else getattr(edge, "source_node_key", None)
                )
                if not other or other in seen:
                    continue
                seen.add(str(other))
                keys.append(str(other))
        return sorted(keys)

    @staticmethod
    def _classify(node: Any, buckets: dict[str, set[str]]) -> None:
        """Drop one node into its bucket and harvest its evidence reference."""
        node_type = getattr(node, "node_type", None)
        key = str(getattr(node, "node_key", "") or "")
        if not key:
            return
        if node_type in _SERVICE_TYPES:
            buckets["services"].add(key)
        elif node_type in _FEATURE_TYPES:
            buckets["features"].add(key)
        elif node_type in _TENANT_TYPES:
            buckets["tenants"].add(str(getattr(node, "tenant_id", None) or key))
        elif node_type in _DOMAIN_TYPES:
            buckets["domains"].add(key)
        reference = getattr(node, "evidence_reference", None)
        if reference:
            buckets["evidence"].add(str(reference))

    # ── Delegation ───────────────────────────────────────────────────────────

    async def _delegate(
        self, kind: str, subject_id: str, tenant_id: Optional[str]
    ) -> dict[str, Any]:
        """Hand an agent or capability subject to the agent-access plane.

        That plane owns the observed-installation model this answer depends on.
        Its ``exposure_known`` / ``missing_inputs`` convention is the one this
        module reports in, so merging is a union rather than a translation.

        A delegated review needs a tenant, because the agent-access blast radius
        is bounded to one tenant's observed inventory *by design* — see the
        note in ``kyber_ops_routes.py``. Without one we report the missing input
        instead of aggregating across tenants.
        """
        blank: dict[str, Any] = {
            "exposure_known": False,
            "missing_inputs": [],
            "servers": [],
            "capabilities": [],
            "tenant_id": tenant_id,
        }
        if not tenant_id:
            blank["missing_inputs"] = [f"blast_radius_tenant_id_required:subject={kind}"]
            return blank

        try:
            from services.agent_access_intelligence.risk_service import capability_risk_service
        except ImportError as exc:  # pragma: no cover - plane unavailable
            logger.error(f"kyber: agent-access risk service unavailable: {exc}")
            blank["missing_inputs"] = ["agent_access_risk_service:unavailable"]
            return blank

        kwargs = {"agent_id": subject_id} if kind == "agent" else {"capability_id": subject_id}
        try:
            delegated = await capability_risk_service.blast_radius(tenant_id, **kwargs)
        except Exception as exc:
            logger.warning(f"kyber: delegated blast radius failed for {kind}={subject_id}: {exc}")
            blank["missing_inputs"] = [
                f"agent_access_blast_radius:failed:{type(exc).__name__}"
            ]
            return blank

        payload = delegated if isinstance(delegated, dict) else {}
        return {
            "exposure_known": bool(payload.get("exposure_known")),
            "missing_inputs": [str(m) for m in (payload.get("missing_inputs") or ())],
            "servers": [str(s) for s in _ids(payload.get("servers"))],
            "capabilities": [str(c) for c in _ids(payload.get("capabilities"))],
            "tenant_id": tenant_id,
        }


def _ids(values: Any) -> list[str]:
    """Ids out of a list of strings or of ``{"id": …}`` / ``{"key": …}`` dicts."""
    out: list[str] = []
    for value in values or ():
        if isinstance(value, dict):
            candidate = value.get("id") or value.get("key") or value.get("name")
            if candidate:
                out.append(str(candidate))
        elif value:
            out.append(str(value))
    return out


def _dedupe(values: Iterable[str]) -> list[str]:
    """Stable, sorted, deduplicated ``missing_inputs``."""
    return sorted({str(v) for v in values if v})


def _empty_walk() -> dict[str, Any]:
    """The walk result for a subject the Kyber Graph does not own.

    ``anchor_resolved: True`` is not a claim that a node was found — it is the
    statement that no Kyber Graph anchor was *required*. The distinction matters
    because ``_confidence`` treats an unresolved anchor as "we could not start",
    which is the right reading for a service or a release and the wrong one for
    an agent, whose reach the agent-access plane answers in full.
    """
    return {
        "services": set(),
        "features": set(),
        "tenants": set(),
        "domains": set(),
        "evidence": set(),
        "anchor_resolved": True,
        "truncated": False,
        "depth_reached": 0,
        "missing_inputs": [],
    }


def _confidence(*, anchor_resolved: bool, truncated: bool, missing: list[str]) -> float:
    """How much of this answer an operator should act on.

    An unresolved anchor is zero, not "no reach found". A truncated walk and a
    partial input set both drop the number, because both mean the reach shown is
    a lower bound.
    """
    if not anchor_resolved:
        return 0.0
    if truncated:
        return _CONFIDENCE_TRUNCATED
    if missing:
        return _CONFIDENCE_PARTIAL
    return _CONFIDENCE_COMPLETE


#: Process-wide service over the package's store provider.
kyber_blast_radius_service = KyberBlastRadiusService()


__all__ = [
    "DELEGATED_SUBJECTS",
    "GRAPH_SUBJECT_PREFIXES",
    "MAX_DEPTH",
    "MAX_EDGES_PER_NODE",
    "MAX_NODES",
    "PROPAGATING_EDGES",
    "KyberBlastRadiusService",
    "kyber_blast_radius_service",
    "node_key_for",
]
