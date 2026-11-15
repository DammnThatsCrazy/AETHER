"""Project proven correlation verdicts into the graph.

Only ``linked`` verdicts (proof-class evidence) are projected. Candidates stay
in the verdict store and the chain view, never in the graph, so a timing or
actor match can never appear as a proven relationship.

Each observation becomes an ``ActionRecord`` vertex; the verdict becomes one
``CORRELATED_ACROSS_SOURCES`` edge carrying the evidence class, the join key,
both roles, and the verdict ID as its source event. Writes go through the
graph mutation gateway via the agentic observability persistence helper.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Awaitable, Callable, Optional

from shared.graph.edge_properties import build_edge_properties, build_lineage_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from shared.integration_contracts.correlation import CorrelationObservation, CorrelationVerdict

_RESOLUTION_METHOD = {
    "DETERMINISTIC_BINDING": "deterministic",
    "CRYPTOGRAPHICALLY_ATTESTED": "attested",
    "VERIFIED_AUTHORITY": "authority_record",
}

Persist = Callable[..., Awaitable[Any]]


def action_record_id(tenant_id: str, observation_id: str) -> str:
    material = json.dumps([tenant_id, observation_id], ensure_ascii=False, separators=(",", ":"))
    return "action_record_corr_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _vertex(obs: CorrelationObservation) -> Vertex:
    return Vertex(
        vertex_type=VertexType.ACTION_RECORD,
        vertex_id=action_record_id(obs.tenant_id, obs.observation_id),
        properties={
            "tenant_id": obs.tenant_id,
            "observation_id": obs.observation_id,
            "source_role": obs.source_role,
            "provider_family": obs.provider_family,
            "occurred_at": obs.occurred_at.isoformat(),
            "record_origin": "agent_correlation",
        },
    )


def build_link_mutations(
    left: CorrelationObservation,
    right: CorrelationObservation,
    verdict: CorrelationVerdict,
    verdict_id: str,
) -> list[Any]:
    """Vertices and edge for one linked verdict; [] for anything else."""
    if verdict.status != "linked" or not verdict.proves_link:
        return []
    method = _RESOLUTION_METHOD.get(verdict.evidence_class)
    if method is None:
        return []
    # Edges run from the earlier observation to the later one.
    first, second = sorted((left, right), key=lambda o: (o.occurred_at, o.observation_id))
    from_id = action_record_id(first.tenant_id, first.observation_id)
    to_id = action_record_id(second.tenant_id, second.observation_id)
    valid_from = second.occurred_at.isoformat()
    properties = build_edge_properties(
        tenant_id=first.tenant_id,
        edge_type=EdgeType.CORRELATED_ACROSS_SOURCES,
        from_vertex_id=from_id,
        to_vertex_id=to_id,
        actor_kind="system",
        actor_id="agent_correlation_engine",
        provenance="agent_correlation",
        provenance_class="silver",
        valid_from=valid_from,
        source_event_id=verdict_id,
        confidence=1.0,
        evidence_class=verdict.evidence_class,
        join_key=verdict.key_kind or "",
        supporting_keys=",".join(verdict.supporting_keys),
        from_role=first.source_role,
        to_role=second.source_role,
        verdict_id=verdict_id,
        policy_version=verdict.contract_version,
        **build_lineage_edge_properties(
            evidence_refs=[first.observation_id, second.observation_id, verdict_id],
            resolution_method=method,
            relationship_status="active",
            observed_at=valid_from,
        ),
    )
    return [
        _vertex(first),
        _vertex(second),
        Edge(edge_type=EdgeType.CORRELATED_ACROSS_SOURCES, from_vertex_id=from_id, to_vertex_id=to_id, properties=properties),
    ]


class GraphProjector:
    def __init__(self, persist: Optional[Persist] = None) -> None:
        self._persist = persist

    async def project(
        self,
        left: CorrelationObservation,
        right: CorrelationObservation,
        verdict: CorrelationVerdict,
        verdict_id: str,
    ) -> dict[str, Any]:
        mutations = build_link_mutations(left, right, verdict, verdict_id)
        if not mutations:
            return {"graph_projection_status": "not_applicable", "graph_mutations_persisted": 0}
        if self._persist is not None:
            result = await self._persist(mutations, tenant_id=left.tenant_id, trace_id=verdict_id)
        else:
            from actions.agentic_observability.foundation import persist_mutations

            result = await persist_mutations(mutations, tenant_id=left.tenant_id, trace_id=verdict_id)
        return {
            "graph_projection_status": getattr(result, "graph_projection_status", "unknown"),
            "graph_mutations_persisted": getattr(result, "graph_mutations_persisted", 0),
        }
