"""Card-linked graph projection — idempotent, evidence-backed edges.

Projects catalog dimensions (CardProgram/CardIssuer/PaymentNetwork) and
flow facts (CardLinkedFlow) into the intelligence graph, connected to the
existing User/Wallet/Agent/Campaign/Journey/Chain/Token vertices.

Identity rule: card-linked edges are behavioral/economic/cluster evidence
only (all layer-EXCLUDED) — they are never deterministic identity-merge
or ownership proof.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from shared.logger.logger import get_logger

logger = get_logger("aether.card_linked.graph")

_PROVENANCE = "card_linked_payments"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _edge(edge_type: str, from_vid: str, to_vid: str, tenant_id: str,
          source_event_id: str, **extra: str) -> Edge:
    return Edge(
        edge_type=edge_type,
        from_vertex_id=from_vid,
        to_vertex_id=to_vid,
        properties=build_edge_properties(
            tenant_id=tenant_id,
            edge_type=edge_type,
            from_vertex_id=from_vid,
            to_vertex_id=to_vid,
            actor_kind="service",
            actor_id="card_linked_payments",
            provenance=_PROVENANCE,
            valid_from=_now(),
            source_event_id=source_event_id,
            **extra,
        ),
    )


def build_catalog_mutations(tenant_id: str, program: dict) -> tuple[list[Vertex], list[Edge]]:
    """CardProgram + its issuer/network dimension vertices and edges."""
    program_vid = f"card_program:{program['slug']}"
    vertices = [Vertex(
        vertex_id=program_vid,
        vertex_type=VertexType.CARD_PROGRAM,
        properties={
            "tenant_id": tenant_id,
            "display_name": program.get("display_name", program["slug"]),
            "source": program.get("source", "paymentscan"),
            "status": program.get("status", "active"),
        },
    )]
    edges: list[Edge] = []
    issuer = program.get("issuer_id")
    if issuer:
        issuer_vid = f"card_issuer:{issuer}"
        vertices.append(Vertex(
            vertex_id=issuer_vid, vertex_type=VertexType.CARD_ISSUER,
            properties={"tenant_id": tenant_id},
        ))
        edges.append(_edge(EdgeType.ISSUED_BY, program_vid, issuer_vid,
                           tenant_id, program["slug"]))
    network = program.get("payment_network")
    if network:
        network_vid = f"payment_network:{network}"
        vertices.append(Vertex(
            vertex_id=network_vid, vertex_type=VertexType.PAYMENT_NETWORK,
            properties={"tenant_id": tenant_id},
        ))
        edges.append(_edge(EdgeType.RUNS_ON, program_vid, network_vid,
                           tenant_id, program["slug"]))
    return vertices, edges


def build_flow_mutations(flow: dict) -> tuple[list[Vertex], list[Edge]]:
    """CardLinkedFlow vertex plus its evidence-backed edges.

    Benchmark-only rows are never projected — the graph carries observed
    activity, not PaymentScan market benchmarks.
    """
    if flow.get("basis") == "benchmark_only" or flow.get("reconciliation_state") == "benchmark_only":
        return [], []

    tenant_id = flow["tenant_id"]
    flow_vid = f"card_linked_flow:{flow['id']}"
    flow_id = flow["id"]
    vertices = [Vertex(
        vertex_id=flow_vid,
        vertex_type=VertexType.CARD_LINKED_FLOW,
        properties={
            "tenant_id": tenant_id,
            "basis": flow.get("basis", "unknown"),
            "source": flow.get("source", "unknown"),
            "confidence": flow.get("confidence", "weak"),
            "rail": flow.get("rail", "unknown"),
            "amount_bucket": flow.get("amount_bucket") or "unknown",
        },
    )]
    edges: list[Edge] = []

    program = flow.get("card_program_id")
    entity = flow.get("canonical_entity_id") or flow.get("user_id")
    if program:
        program_vid = f"card_program:{program}"
        vertices.append(Vertex(
            vertex_id=program_vid, vertex_type=VertexType.CARD_PROGRAM,
            properties={"tenant_id": tenant_id},
        ))
        if entity:
            edges.append(_edge(EdgeType.USED_PROVIDER, f"user:{entity}", program_vid,
                               tenant_id, flow_id, basis=flow.get("basis", "unknown"),
                               confidence=flow.get("confidence", "weak")))

    wallet = flow.get("wallet_address_hash")
    if wallet:
        edges.append(_edge(EdgeType.FUNDED, f"wallet:{wallet}", flow_vid,
                           tenant_id, flow_id, basis=flow.get("basis", "unknown")))

    campaign = flow.get("campaign_id")
    if campaign:
        # ATTRIBUTED_TO is an H2A edge — enforce-mode validation requires a
        # consent_purpose; "marketing" is the registry purpose whose data
        # categories cover attribution.
        edges.append(_edge(EdgeType.ATTRIBUTED_TO, flow_vid, f"campaign:{campaign}",
                           tenant_id, flow_id, consent_purpose="marketing"))
        if entity:
            edges.append(_edge(EdgeType.CAME_FROM, f"user:{entity}", f"campaign:{campaign}",
                               tenant_id, flow_id))

    journey = flow.get("journey_id")
    if journey and entity:
        edges.append(_edge(EdgeType.PARTICIPATED_IN, f"user:{entity}", f"journey:{journey}",
                           tenant_id, flow_id))

    chain = flow.get("chain")
    if chain:
        edges.append(_edge(EdgeType.OCCURRED_ON, flow_vid, f"chain:{chain}",
                           tenant_id, flow_id))

    asset = flow.get("asset")
    if asset:
        edges.append(_edge(EdgeType.USED_ASSET, flow_vid, f"token:{asset}",
                           tenant_id, flow_id))

    agent = flow.get("agent_id")
    if agent:
        edges.append(_edge(EdgeType.INITIATED_OR_INFLUENCED, f"agent:{agent}", flow_vid,
                           tenant_id, flow_id))

    return vertices, edges


def build_sequence_edge(tenant_id: str, earlier_flow_id: str, later_flow_id: str) -> Edge:
    """FOLLOWED_BY between two flows of the same entity (journey sequencing)."""
    return _edge(
        EdgeType.FOLLOWED_BY,
        f"card_linked_flow:{earlier_flow_id}",
        f"card_linked_flow:{later_flow_id}",
        tenant_id, later_flow_id,
    )
