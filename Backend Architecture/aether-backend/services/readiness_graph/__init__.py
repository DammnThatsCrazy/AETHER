"""Dependency-aware capability readiness graph.

Additive alongside :mod:`shared.certification` and :mod:`services.capabilities`:

* :mod:`.graph` — the dependency-graph readiness engine
  (:class:`ReadinessGraphEngine`, :class:`ReadinessGraphResult`, canonical
  :class:`NodeStatus` / :class:`DependencyNode` vocabularies, default
  resolvers via :func:`build_default_engine`);
* :mod:`.revalidation_worker` — the supervised readiness-revalidation loop
  (:func:`build_readiness_revalidation_worker`);
* :mod:`.routes` — tenant + Kyber-operator readiness-graph routes.

Persisted per-(tenant, capability) readiness state and its audit trail live in
:mod:`services.capabilities.readiness_repo` (:class:`CapabilityReadinessService`),
which enforces monotonic promote/demote and writes every change to the
canonical security-audit ledger.
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
