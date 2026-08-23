"""Dependency-aware capability readiness graph.

Additive alongside :mod:`shared.certification` and :mod:`services.capabilities`:

* :mod:`.graph` — the dependency-graph readiness engine
  (:class:`ReadinessGraphEngine`, :class:`ReadinessGraphResult`, canonical
  :class:`NodeStatus` / :class:`DependencyNode` vocabularies, default
  resolvers via :func:`build_default_engine`);
* :mod:`.revalidation_worker` — the supervised readiness-revalidation loop
  (:func:`build_readiness_revalidation_worker`);
* :mod:`.routes` — tenant + Kyber-operator readiness-graph routes.

Persisted per-(tenant, capability) readiness state is read through the
graph-local :class:`.graph.CapabilityReadinessAdapter`, which folds main's
canonical activation-state rows (:mod:`services.capabilities.activation_repository`
/ :mod:`services.capabilities.lifecycle`) into the graph's snapshot shape —
monotonic promote/demote, legal edges and the append-only audit history are
main's lifecycle contract, never re-implemented here.
"""

from __future__ import annotations

from services.readiness_graph.graph import (
    BLOCKING_STATUSES,
    CANONICAL_DEPENDENCY_NODES,
    CONFIG_NODES,
    WORKER_NODES,
    CredentialAuthorityResolver,
    DependencyNode,
    NodeResolution,
    NodeStatus,
    ReadinessGraphEngine,
    ReadinessGraphResult,
    ReadinessProbeResolver,
    build_default_engine,
    is_blocking,
    worst_blocking_status,
)
from services.readiness_graph.revalidation_worker import (
    ReadinessRevalidationConfig,
    build_readiness_revalidation_worker,
)

__all__ = [
    # graph
    "BLOCKING_STATUSES",
    "CANONICAL_DEPENDENCY_NODES",
    "CONFIG_NODES",
    "WORKER_NODES",
    "CredentialAuthorityResolver",
    "DependencyNode",
    "NodeResolution",
    "NodeStatus",
    "ReadinessGraphEngine",
    "ReadinessGraphResult",
    "ReadinessProbeResolver",
    "build_default_engine",
    "is_blocking",
    "worst_blocking_status",
    # revalidation worker
    "ReadinessRevalidationConfig",
    "build_readiness_revalidation_worker",
]
