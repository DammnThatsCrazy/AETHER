"""Platform topology derived from what the repository already declares.

A hand-maintained list of services and surfaces rots silently: a worker role
added to ``services/runtime/roles.py`` or a surface added to the capability
registry would simply be missing from the operational graph, and nothing would
say so. An operator would then read a blast-radius answer that quietly excluded
the new component — the failure mode is a confident wrong answer, which is worse
than an error.

So topology is *derived*:

* :func:`service_nodes` from :data:`services.runtime.roles.WORKER_ROLES` plus
  ``api`` — the set of deployable process classes.
* :func:`worker_role_nodes` / :func:`worker_role_edges` from
  :data:`services.runtime.roles.ROLE_TO_SPEC_NAMES` — which supervised loop each
  role owns.
* :func:`feature_surface_nodes` from
  ``packages/shared/contracts/surface-capability-registry.json`` — the same
  contract the frontend and the capability gates read.

What cannot be derived is *reported, never invented*. :func:`sync_topology`
returns a ``missing_inputs`` list naming each gap (service dependency edges,
releases and deployments, the surface→service mapping, the stream consumer
specs). A named gap is actionable; a fabricated node is a lie that survives
review because it looks like data.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from services.kyber.graph.contracts import KyberGraphEdge, KyberGraphNode
from services.kyber.graph.repository import KyberGraphStore
from services.runtime.roles import ROLE_TO_SPEC_NAMES, WORKER_ROLES
from shared.logger.logger import get_logger

logger = get_logger("aether.kyber.graph.topology")

#: The pure request-serving process. Not a worker role, but a service node.
API_SERVICE_ROLE = "api"

_REGISTRY_RELATIVE = Path("packages/shared/contracts/surface-capability-registry.json")

#: Gaps this module cannot close from repository sources. Reported by
#: :func:`sync_topology` so the graph's incompleteness is visible in its own
#: output rather than inferred from an empty result.
UNDERIVABLE_INPUTS: tuple[tuple[str, str], ...] = (
    (
        "service_dependency_edges",
        "No declared service-to-service dependency source exists in the repo; "
        "DEPENDS_ON edges must come from a runtime dependency feed, not a "
        "hand-written list here.",
    ),
    (
        "release_and_deployment_nodes",
        "Release/Deployment nodes describe what is deployed where, which only "
        "the deploy pipeline knows. Deriving them from source would assert "
        "deployments that may not exist.",
    ),
    (
        "surface_to_service_edges",
        "The capability registry names surfaces and roles.py names services, "
        "but nothing declares which service serves which surface, so "
        "EXPOSES_FEATURE / SERVED_BY edges cannot be derived.",
    ),
    (
        "stream_consumer_specs",
        "Roles whose ROLE_TO_SPEC_NAMES entry is empty (identity-worker, "
        "graph-writer, measurement-worker, semantic-worker) own stream "
        "consumers declared in services/runtime/consumer_specs.py, which is not "
        "a pure declaration this module can read without importing the "
        "consumer runtime.",
    ),
)


def _registry_path() -> Optional[Path]:
    """Locate the surface capability registry by walking up to the repo root.

    Walking beats a fixed ``parents[n]`` hop: the backend is nested under a
    directory with a space in its name and has been re-rooted before, and a
    silently wrong constant would turn into an empty surface list.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _REGISTRY_RELATIVE
        if candidate.is_file():
            return candidate
    return None


def service_nodes() -> list[KyberGraphNode]:
    """One ``Service`` node per deployable process class.

    ``AETHER_ROLE`` selects which slice of the platform a process runs, so the
    role set *is* the service inventory: ``api`` plus every worker role.
    """
    roles = sorted(WORKER_ROLES | {API_SERVICE_ROLE})
    return [
        KyberGraphNode(
            node_key=f"service:{role}",
            node_type="Service",
            display_name=role,
            properties={
                "runtime_role": role,
                "serves_requests": role in (API_SERVICE_ROLE, "all"),
                "derived_from": "services/runtime/roles.py",
            },
        )
        for role in roles
    ]


def worker_role_nodes() -> list[KyberGraphNode]:
    """One ``WorkerRole`` node per supervised loop a runtime role owns.

    Edge targets must exist for a traversal to reach them, so the spec nodes are
    derived from the same mapping as :func:`worker_role_edges` rather than being
    assumed to have been created elsewhere.
    """
    nodes: list[KyberGraphNode] = []
    for role, specs in sorted(ROLE_TO_SPEC_NAMES.items()):
        for spec in sorted(specs):
            nodes.append(
                KyberGraphNode(
                    node_key=f"worker_role:{spec}",
                    node_type="WorkerRole",
                    display_name=spec,
                    properties={
                        "spec_name": spec,
                        "runtime_role": role,
                        "derived_from": "services/runtime/roles.py:ROLE_TO_SPEC_NAMES",
                    },
                )
            )
    return nodes


def feature_surface_nodes() -> list[KyberGraphNode]:
    """One ``FeatureSurface`` node per surface in the capability registry.

    Properties carry the surface's declared *capabilities* — views, temporal
    modes, export support. These are contract facts shared with the frontend,
    not tenant data.
    """
    path = _registry_path()
    if path is None:
        logger.warning(
            "kyber topology: surface capability registry not found; "
            "FeatureSurface nodes cannot be derived"
        )
        return []
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.error(f"kyber topology: surface capability registry unreadable: {exc}")
        return []

    nodes: list[KyberGraphNode] = []
    for surface in registry.get("surfaces", []):
        surface_id = surface.get("surfaceId")
        if not surface_id:
            continue
        nodes.append(
            KyberGraphNode(
                node_key=f"feature_surface:{surface_id}",
                node_type="FeatureSurface",
                display_name=surface_id,
                properties={
                    "surface_id": surface_id,
                    "supported_views": surface.get("supportedViews", []),
                    "supported_temporal_modes": surface.get("supportedTemporalModes", []),
                    "supported_field_categories": surface.get(
                        "supportedFieldCategories", []
                    ),
                    "supports_export": bool(surface.get("supportsExport", False)),
                    "supports_comparison": bool(surface.get("supportsComparison", False)),
                    "contract_version": registry.get("contractVersion"),
                    "derived_from": str(_REGISTRY_RELATIVE),
                },
            )
        )
    return nodes


def worker_role_edges() -> list[KyberGraphEdge]:
    """``service:<role> RUNS worker_role:<spec>`` for every declared spec."""
    edges: list[KyberGraphEdge] = []
    for role, specs in sorted(ROLE_TO_SPEC_NAMES.items()):
        for spec in sorted(specs):
            edges.append(
                KyberGraphEdge(
                    source_node_key=f"service:{role}",
                    target_node_key=f"worker_role:{spec}",
                    relationship_type="RUNS",
                    properties={"derived_from": "services/runtime/roles.py"},
                )
            )
    return edges


async def sync_topology(store: KyberGraphStore, *, environment: str) -> dict[str, Any]:
    """Upsert derived platform topology into ``environment``.

    Idempotent by construction: every node and edge carries a stable natural
    key, so running this on every boot converges rather than accumulating.

    Returns counts plus ``missing_inputs`` — the topology this function knows it
    is not producing. The return type is ``dict[str, Any]`` rather than
    ``dict[str, int]`` for exactly that reason: the honest report is part of the
    result, not a log line a caller never sees.
    """
    # Environment is stamped here rather than inside the derivation helpers so
    # they stay pure. It matters: PostgreSQL treats NULLs as distinct in a
    # unique index, so an environment-less node would not be deduped by
    # ux_kyber_graph_nodes_key.
    nodes = [
        node.model_copy(update={"environment": environment})
        for node in (*service_nodes(), *worker_role_nodes(), *feature_surface_nodes())
    ]
    edges = [
        edge.model_copy(update={"environment": environment})
        for edge in worker_role_edges()
    ]

    for node in nodes:
        await store.upsert_node(node)
    for edge in edges:
        await store.upsert_edge(edge)

    missing = [name for name, _ in UNDERIVABLE_INPUTS]
    if not feature_surface_nodes():
        missing.append("surface_capability_registry")

    report: dict[str, Any] = {
        "environment": environment,
        "nodes_upserted": len(nodes),
        "edges_upserted": len(edges),
        "service_nodes": len(service_nodes()),
        "worker_role_nodes": len(worker_role_nodes()),
        "feature_surface_nodes": len(feature_surface_nodes()),
        "missing_inputs": missing,
    }
    logger.info(
        f"kyber topology sync: env={environment} nodes={report['nodes_upserted']} "
        f"edges={report['edges_upserted']} missing_inputs={len(missing)}"
    )
    return report


__all__ = [
    "API_SERVICE_ROLE",
    "UNDERIVABLE_INPUTS",
    "feature_surface_nodes",
    "service_nodes",
    "sync_topology",
    "worker_role_edges",
    "worker_role_nodes",
]
