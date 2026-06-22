"""
Aether Shared — @aether/graph/relationship_layers
Classifies graph edges into four relationship layers:
  H2H (Human-to-Human)  — existing behavioral analytics
  H2A (Human-to-Agent)   — delegation, attribution, reward passthrough
  A2H (Agent-to-Human)   — notifications, recommendations, deliveries, escalations
  A2A (Agent-to-Agent)    — orchestration, hiring, payments, protocol composition

  EXCLUDED is a fifth non-canonical bucket for edges that are intentionally
  outside the four-layer analytics graph (pure graph-topology or metadata edges).
  Edges classified as EXCLUDED are never counted in the four operational layers.

Used by: Analytics, Agent, Commerce, On-Chain services.
"""

from __future__ import annotations

import os
from enum import Enum

from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger

logger = get_logger("aether.graph.layers")


# ═══════════════════════════════════════════════════════════════════════════
# RELATIONSHIP LAYERS
# ═══════════════════════════════════════════════════════════════════════════

class RelationshipLayer(str, Enum):
    H2H = "H2H"         # Human-to-Human
    H2A = "H2A"         # Human-to-Agent
    A2H = "A2H"         # Agent-to-Human
    A2A = "A2A"         # Agent-to-Agent
    EXCLUDED = "EXCLUDED"  # Intentionally outside the four operational layers


# ═══════════════════════════════════════════════════════════════════════════
# UNKNOWN EDGE TYPE ERROR
# ═══════════════════════════════════════════════════════════════════════════

class UnknownEdgeTypeError(ValueError):
    """Raised when an EdgeType has no layer classification in staging/production."""


# ═══════════════════════════════════════════════════════════════════════════
# ENVIRONMENT GATE
# ═══════════════════════════════════════════════════════════════════════════

def _is_strict() -> bool:
    """Return True in staging/production — unknown edges raise instead of defaulting."""
    return os.getenv("AETHER_ENV", "local").lower() not in ("local", "test", "")


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CLASSIFICATION MAP
# Every EdgeType constant MUST have an entry here. Unmapped edges raise
# UnknownEdgeTypeError in staging/production. Only EXCLUDED edges are
# intentionally outside the four operational layers.
# ═══════════════════════════════════════════════════════════════════════════

_EDGE_LAYER_MAP: dict[str, RelationshipLayer] = {
    # ── H2H — Behavioral analytics / identity graph ──────────────────────
    EdgeType.HAS_SESSION: RelationshipLayer.H2H,
    EdgeType.VIEWED_PAGE: RelationshipLayer.H2H,
    EdgeType.TRIGGERED_EVENT: RelationshipLayer.H2H,
    EdgeType.USED_DEVICE: RelationshipLayer.H2H,
    EdgeType.BELONGS_TO: RelationshipLayer.H2H,
    EdgeType.RESOLVED_AS: RelationshipLayer.H2H,
    EdgeType.ENRICHED_BY: RelationshipLayer.H2H,
    EdgeType.HAS_FINGERPRINT: RelationshipLayer.H2H,
    EdgeType.SEEN_FROM_IP: RelationshipLayer.H2H,
    EdgeType.LOCATED_IN: RelationshipLayer.H2H,
    EdgeType.HAS_EMAIL: RelationshipLayer.H2H,
    EdgeType.HAS_PHONE: RelationshipLayer.H2H,
    EdgeType.OWNS_WALLET: RelationshipLayer.H2H,
    EdgeType.MEMBER_OF_CLUSTER: RelationshipLayer.H2H,
    EdgeType.SIMILAR_TO: RelationshipLayer.H2H,
    EdgeType.IP_MAPS_TO: RelationshipLayer.H2H,

    # ── H2A — Human-to-Agent (delegation, ownership, authorization) ───────
    EdgeType.LAUNCHED_BY: RelationshipLayer.H2A,
    EdgeType.DELEGATES: RelationshipLayer.H2A,
    EdgeType.INTERACTS_WITH: RelationshipLayer.H2A,
    EdgeType.ATTRIBUTED_TO: RelationshipLayer.H2A,

    # ── A2H — Agent-to-Human (delivery, notification, escalation) ─────────
    EdgeType.NOTIFIES: RelationshipLayer.A2H,
    EdgeType.RECOMMENDS: RelationshipLayer.A2H,
    EdgeType.DELIVERS_TO: RelationshipLayer.A2H,
    EdgeType.ESCALATES_TO: RelationshipLayer.A2H,
    EdgeType.HAS_RECOMMENDATION: RelationshipLayer.A2H,
    EdgeType.SUPPORTED_BY: RelationshipLayer.A2H,
    EdgeType.SELECTED_BY: RelationshipLayer.A2H,

    # ── A2A — Agent-to-Agent / protocol orchestration ─────────────────────
    EdgeType.PAYS: RelationshipLayer.A2A,
    EdgeType.CONSUMES: RelationshipLayer.A2A,
    EdgeType.HIRED: RelationshipLayer.A2A,
    EdgeType.DEPLOYED: RelationshipLayer.A2A,
    EdgeType.CALLED: RelationshipLayer.A2A,
    EdgeType.COMPOSED_WITH: RelationshipLayer.A2A,
    EdgeType.UPGRADED: RelationshipLayer.A2A,
    EdgeType.GOVERNED_BY: RelationshipLayer.A2A,
    EdgeType.DEPENDS_ON: RelationshipLayer.A2A,
    EdgeType.PERFORMED_ACTION: RelationshipLayer.A2A,
    EdgeType.EXECUTED_AS: RelationshipLayer.A2A,
    EdgeType.PRODUCED: RelationshipLayer.A2A,
    EdgeType.UPDATES_CONFIDENCE_FOR: RelationshipLayer.A2A,

    # ── Profile 360 — generic relationship edges ───────────────────────────
    EdgeType.OWNS: RelationshipLayer.H2A,           # Entity → Agent/Wallet/Asset ownership
    EdgeType.MEMBER_OF: RelationshipLayer.H2H,      # Entity → Organization
    EdgeType.GRANTED_BY: RelationshipLayer.H2A,     # Delegation → grantor Entity
    EdgeType.GRANTED_TO: RelationshipLayer.H2A,     # Delegation → grantee Entity/Agent
    EdgeType.EXECUTED: RelationshipLayer.A2A,       # Agent → AgentExecution record
    EdgeType.TRANSFERRED: RelationshipLayer.H2H,    # Entity → Entity (financial flow)

    # ── Web3 — Wallet ↔ Entity / Protocol edges ───────────────────────────
    EdgeType.USES_PROTOCOL: RelationshipLayer.H2H,
    EdgeType.USES_APP: RelationshipLayer.H2H,
    EdgeType.TOUCHES_DOMAIN: RelationshipLayer.H2H,
    EdgeType.HOLDS_TOKEN: RelationshipLayer.H2H,
    EdgeType.BRIDGES_VIA: RelationshipLayer.H2H,
    EdgeType.PARTICIPATES_IN: RelationshipLayer.H2H,
    EdgeType.VOTES_ON: RelationshipLayer.H2H,
    EdgeType.DELEGATES_TO: RelationshipLayer.H2H,   # Wallet → Wallet governance
    EdgeType.LINKED_TO_SOCIAL: RelationshipLayer.H2H,
    EdgeType.TRADED_ON: RelationshipLayer.H2H,
    EdgeType.EXPOSED_TO: RelationshipLayer.H2H,

    # ── Web3 — Contract/Protocol topology ─────────────────────────────────
    EdgeType.INSTANCE_OF: RelationshipLayer.H2H,
    EdgeType.PART_OF_SYSTEM: RelationshipLayer.H2H,
    EdgeType.SUCCESSOR_OF: RelationshipLayer.H2H,
    EdgeType.MIGRATED_TO: RelationshipLayer.H2H,
    EdgeType.CONTROLS: RelationshipLayer.H2H,
    EdgeType.DEPLOYED_ON: RelationshipLayer.H2H,
    EdgeType.FRONTS_PROTOCOL: RelationshipLayer.H2H,
    EdgeType.ASSOCIATED_WITH: RelationshipLayer.H2H,
    EdgeType.SERVED_BY: RelationshipLayer.H2H,
    EdgeType.TOKEN_OF: RelationshipLayer.H2H,
    EdgeType.TRADED_ON_VENUE: RelationshipLayer.H2H,
    EdgeType.POOL_FOR: RelationshipLayer.H2H,
    EdgeType.GOVERNED_BY_SPACE: RelationshipLayer.H2H,
    EdgeType.LATER_CLASSIFIED_AS: RelationshipLayer.H2H,

    # ── Cross-Domain — Entity ↔ Account / Instrument ──────────────────────
    EdgeType.OWNS_ACCOUNT: RelationshipLayer.H2H,
    EdgeType.BENEFICIAL_OF: RelationshipLayer.H2H,
    EdgeType.AUTHORIZED_ON: RelationshipLayer.H2H,
    EdgeType.ADVISES: RelationshipLayer.H2H,
    EdgeType.PARENT_OF: RelationshipLayer.H2H,
    EdgeType.MEMBER_OF_HOUSEHOLD: RelationshipLayer.H2H,
    EdgeType.HOLDS_POSITION: RelationshipLayer.H2H,
    EdgeType.PLACED_ORDER: RelationshipLayer.H2H,
    EdgeType.ORDER_FOR: RelationshipLayer.H2H,
    EdgeType.TRADED_AT_VENUE: RelationshipLayer.H2H,
    EdgeType.CASH_FLOW: RelationshipLayer.H2H,
    EdgeType.FUNDED_BY: RelationshipLayer.H2H,

    # ── Cross-Domain — Institution / Business ─────────────────────────────
    EdgeType.SERVICES_ACCOUNT: RelationshipLayer.H2H,
    EdgeType.ISSUES: RelationshipLayer.H2H,
    EdgeType.CUSTODIES: RelationshipLayer.H2H,
    EdgeType.MARKETS_TO: RelationshipLayer.H2H,
    EdgeType.OPERATES: RelationshipLayer.H2H,
    EdgeType.OFFERS_PRODUCT: RelationshipLayer.H2H,

    # ── Cross-Domain — Instrument topology ────────────────────────────────
    EdgeType.ISSUED_BY: RelationshipLayer.H2H,
    EdgeType.IN_SECTOR: RelationshipLayer.H2H,
    EdgeType.UNDERLYING_OF: RelationshipLayer.H2H,
    EdgeType.TOKENIZED_AS: RelationshipLayer.H2H,
    EdgeType.CORRELATED_WITH: RelationshipLayer.H2H,

    # ── Cross-Domain — Compliance / Risk ──────────────────────────────────
    EdgeType.RESTRICTED_ON: RelationshipLayer.H2H,
    EdgeType.COMPLIANCE_ACTED_ON: RelationshipLayer.H2H,
    EdgeType.KYC_FOR: RelationshipLayer.H2H,

    # ── Cross-Domain — Behavioral / Pre-trade ─────────────────────────────
    EdgeType.RESEARCHED: RelationshipLayer.H2H,
    EdgeType.WATCHLISTED: RelationshipLayer.H2H,
    EdgeType.INQUIRED_ABOUT: RelationshipLayer.H2H,
    EdgeType.VISITED: RelationshipLayer.H2H,

    # ── Cross-Domain — Identity fusion ────────────────────────────────────
    EdgeType.OVERLAPS_WITH: RelationshipLayer.H2H,
    EdgeType.LINKED_VIA: RelationshipLayer.H2H,

    # ── Economic Graph Layer — Agent economies ────────────────────────────
    EdgeType.PAYS_FOR: RelationshipLayer.A2A,
    EdgeType.PURCHASES_EXECUTION_FROM: RelationshipLayer.A2A,
    EdgeType.SETTLED_VIA: RelationshipLayer.A2A,
    EdgeType.REQUESTED_QUOTE_FROM: RelationshipLayer.A2A,
    EdgeType.ABANDONED_DUE_TO_COST: RelationshipLayer.A2A,
    EdgeType.RELIES_ON_PROVIDER: RelationshipLayer.A2A,
    EdgeType.USES_APPLICATION: RelationshipLayer.A2A,
    EdgeType.USES_EMAIL_SERVICE: RelationshipLayer.A2A,
    EdgeType.SPECIALIZES_IN: RelationshipLayer.A2A,
    EdgeType.COMMUNICATES_WITH: RelationshipLayer.A2A,
    EdgeType.EXECUTED_ON: RelationshipLayer.A2A,
    EdgeType.ECONOMICALLY_IDENTIFIED_AS: RelationshipLayer.A2A,
    EdgeType.PROFILED_AS: RelationshipLayer.A2A,
    EdgeType.QUOTED_AS: RelationshipLayer.A2A,
    EdgeType.EVALUATED_AS: RelationshipLayer.A2A,
    EdgeType.SETTLED_AS: RelationshipLayer.A2A,
    EdgeType.RESULTED_IN_EXECUTION: RelationshipLayer.A2A,
    EdgeType.RESULTED_IN_OUTCOME: RelationshipLayer.A2A,

    # ── Agentic Commerce — Control Plane ──────────────────────────────────
    EdgeType.REQUIRES_PAYMENT: RelationshipLayer.A2A,
    EdgeType.OFFERS_PAYMENT_OPTION: RelationshipLayer.A2A,
    EdgeType.AUTHORIZED_BY: RelationshipLayer.A2A,
    EdgeType.VERIFIED_BY: RelationshipLayer.A2A,
    EdgeType.SETTLED_BY: RelationshipLayer.A2A,
    EdgeType.GRANTS_ACCESS_TO: RelationshipLayer.A2A,
    EdgeType.FULFILLED_BY: RelationshipLayer.A2A,
    EdgeType.PRICES_IN: RelationshipLayer.A2A,
    EdgeType.ACCEPTS_ASSET: RelationshipLayer.A2A,
    EdgeType.PREFERS_NETWORK: RelationshipLayer.A2A,
    EdgeType.CONSTRAINED_BY: RelationshipLayer.H2A,       # User/Agent → BudgetPolicy
    EdgeType.SUBSCRIBES_TO: RelationshipLayer.H2A,        # User/Agent → ServicePlan
    EdgeType.REUSES_ENTITLEMENT: RelationshipLayer.A2A,
    EdgeType.RETRIED_AS: RelationshipLayer.A2A,
    EdgeType.ESCALATES_PAYMENT_TO: RelationshipLayer.A2H, # ApprovalRequest → User
    EdgeType.GUARDED_BY_POLICY: RelationshipLayer.A2A,
    EdgeType.ROUTES_VIA: RelationshipLayer.A2A,
    EdgeType.APPROVED_BY: RelationshipLayer.A2H,          # ApprovalDecision → User
    EdgeType.REJECTED_BY: RelationshipLayer.A2H,          # ApprovalDecision → User
    EdgeType.REQUESTS_APPROVAL_FROM: RelationshipLayer.A2H,  # Agent → User
    EdgeType.GOVERNED_BY_POLICY: RelationshipLayer.A2A,
    EdgeType.FUNDED_FROM_TREASURY: RelationshipLayer.A2A,

    # ── Agent Lifecycle — Ownership / Identity ────────────────────────────
    EdgeType.OWNS_AGENT: RelationshipLayer.H2A,
    EdgeType.AUTHORIZED_AGENT: RelationshipLayer.H2A,
    EdgeType.HAS_CAPABILITY: RelationshipLayer.A2A,
    EdgeType.REVOKED_CAPABILITY: RelationshipLayer.A2A,
    EdgeType.ACTED_FOR: RelationshipLayer.A2H,           # Agent acted on behalf of User

    # ── Agent Lifecycle — Task control-flow ───────────────────────────────
    EdgeType.CREATED_TASK: RelationshipLayer.A2A,
    EdgeType.DECOMPOSED_INTO: RelationshipLayer.A2A,
    EdgeType.STARTED_TASK: RelationshipLayer.A2A,
    EdgeType.COMPLETED_TASK: RelationshipLayer.A2A,
    EdgeType.FAILED_TASK: RelationshipLayer.A2A,
    EdgeType.CALLED_TOOL: RelationshipLayer.A2A,
    EdgeType.REQUESTED_RESOURCE: RelationshipLayer.A2A,
    EdgeType.DELEGATED_TO: RelationshipLayer.A2A,
    EdgeType.SPAWNED_SUBAGENT: RelationshipLayer.A2A,
    EdgeType.EVALUATED_BY_POLICY: RelationshipLayer.A2A,
    EdgeType.HANDED_OFF_TO: RelationshipLayer.A2A,
    EdgeType.ESCALATED_TO_HUMAN: RelationshipLayer.A2H,

    # ── Tier ──────────────────────────────────────────────────────────────
    EdgeType.IN_TIER_GROUP: RelationshipLayer.H2H,

    # ── Behavioral signals ────────────────────────────────────────────────
    EdgeType.HAS_BEHAVIORAL_SIGNAL: RelationshipLayer.H2H,

    # ── Social ────────────────────────────────────────────────────────────
    EdgeType.HAS_SOCIAL_PROFILE: RelationshipLayer.H2H,
    EdgeType.FOLLOWS_SOCIAL: RelationshipLayer.H2H,

    # ── Location ──────────────────────────────────────────────────────────
    EdgeType.PRIMARY_LOCATION: RelationshipLayer.H2H,
    EdgeType.SECONDARY_LOCATION: RelationshipLayer.H2H,
    EdgeType.ACCESSED_FROM: RelationshipLayer.H2H,

    # ── Unified entity specialization ─────────────────────────────────────
    EdgeType.IS_GOVERNANCE_ORG: RelationshipLayer.H2H,
    EdgeType.IS_BRAND: RelationshipLayer.H2H,
    EdgeType.IS_MARKETPLACE: RelationshipLayer.H2H,
    EdgeType.IS_MEDIA_ENTITY: RelationshipLayer.H2H,
    EdgeType.IS_YIELD_PLATFORM: RelationshipLayer.H2H,
    EdgeType.IS_DAO: RelationshipLayer.H2H,
    EdgeType.IS_DEX: RelationshipLayer.H2H,

    # ── External integration ──────────────────────────────────────────────
    EdgeType.HAS_PLAID_ACCOUNT: RelationshipLayer.H2H,
    EdgeType.HAS_CREDIT_PROFILE: RelationshipLayer.H2H,
    EdgeType.HAS_TRADFI_POSITION: RelationshipLayer.H2H,

    # ── Campaign intelligence ─────────────────────────────────────────────
    EdgeType.TARGETED_BY_CAMPAIGN: RelationshipLayer.H2H,
    EdgeType.HAS_RETARGET_RECOMMENDATION: RelationshipLayer.A2H,

    # ── Entity → Protocol / Onchain ───────────────────────────────────────
    EdgeType.TRADES_ON_PROTOCOL: RelationshipLayer.H2H,
    EdgeType.STAKES_IN: RelationshipLayer.H2H,
    EdgeType.DEPLOYS_CONTRACT_FROM: RelationshipLayer.H2H,

    # ── Entity → Entity (universal relationship graph) ────────────────────
    EdgeType.CO_INVESTS_WITH: RelationshipLayer.H2H,
    EdgeType.LISTED_ON: RelationshipLayer.H2H,
    EdgeType.DISTRIBUTES_VIA: RelationshipLayer.H2H,
    EdgeType.CONTENT_ON: RelationshipLayer.H2H,
    EdgeType.COMPETES_WITH: RelationshipLayer.H2H,
    EdgeType.REVIEWS: RelationshipLayer.H2H,
    EdgeType.SELLS_ON: RelationshipLayer.H2H,
    EdgeType.OPERATES_CHANNEL: RelationshipLayer.H2H,

    # ── Human → Business / Org ────────────────────────────────────────────
    EdgeType.EMPLOYEE_OF: RelationshipLayer.H2H,
    EdgeType.FOUNDER_OF: RelationshipLayer.H2H,
    EdgeType.CUSTOMER_OF: RelationshipLayer.H2H,
    EdgeType.INVESTOR_IN: RelationshipLayer.H2H,
    EdgeType.CONTRACTOR_FOR: RelationshipLayer.H2H,

    # ── H2A — human/org delegation to agent (agentic observability wave) ──
    EdgeType.HUMAN_DELEGATED_TO_AGENT: RelationshipLayer.H2A,
    EdgeType.ORG_DELEGATED_TO_AGENT: RelationshipLayer.H2A,

    # ── A2H — agent signals/notifications delivered to humans ─────────────
    EdgeType.AGENT_PRODUCED_RISK_SIGNAL: RelationshipLayer.A2H,
    EdgeType.EXTERNAL_ACCOUNT_EMITTED_NOTIFICATION: RelationshipLayer.A2H,
    EdgeType.INTERACTION_FLAGGED_REPLAY_RISK: RelationshipLayer.A2H,

    # ── A2A — agentic observability: MCP, inbox, x402, external accounts ──
    EdgeType.AGENT_ACTED_ON_BEHALF_OF: RelationshipLayer.A2A,
    EdgeType.AGENT_CONNECTED_VIA_MCP: RelationshipLayer.A2A,
    EdgeType.AGENT_GENERATED_TRADE_INTENT: RelationshipLayer.A2A,
    EdgeType.AGENT_HAS_INBOX: RelationshipLayer.A2A,
    EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT: RelationshipLayer.A2A,
    EdgeType.AGENT_REQUESTED_RESOURCE_OBS: RelationshipLayer.A2A,
    EdgeType.AGENT_TRIGGERED_ACTIVITY: RelationshipLayer.A2A,
    EdgeType.AGENT_USED_TOOL_OBS: RelationshipLayer.A2A,
    EdgeType.CHALLENGE_HAS_PAYMENT_REQUIREMENT: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_DISCONNECTED: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_EMITTED_ACTIVITY: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_HAS_BUDGET_OBSERVED: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_HAS_PERMISSION_OBSERVED: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_OBSERVED_FILL: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_OBSERVED_ORDER: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_OBSERVED_PORTFOLIO: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_OBSERVED_POSITION: RelationshipLayer.A2A,
    EdgeType.EXTERNAL_ACCOUNT_OBSERVED_REJECTION: RelationshipLayer.A2A,
    EdgeType.INBOX_CONTAINS_THREAD: RelationshipLayer.A2A,
    EdgeType.INBOX_HAS_EMAIL_ADDRESS: RelationshipLayer.A2A,
    EdgeType.INTERACTION_HAS_RESOURCE_ACCESS_OUTCOME: RelationshipLayer.A2A,
    EdgeType.INTERACTION_HAS_SETTLEMENT_OBSERVED: RelationshipLayer.A2A,
    EdgeType.INTERACTION_HAS_SIGNATURE_OBSERVED: RelationshipLayer.A2A,
    EdgeType.INTERACTION_HAS_VERIFICATION_OBSERVED: RelationshipLayer.A2A,
    EdgeType.MESSAGE_EXTRACTED_ENTITY: RelationshipLayer.A2A,
    EdgeType.MESSAGE_HAS_ATTACHMENT: RelationshipLayer.A2A,
    EdgeType.MESSAGE_REFERENCES_INVOICE: RelationshipLayer.A2A,
    EdgeType.MESSAGE_REFERENCES_SUPPORT_CASE: RelationshipLayer.A2A,
    EdgeType.PROTOCOL_OBSERVED_FROM_PROVIDER: RelationshipLayer.A2A,
    EdgeType.RESOURCE_PROVIDED_BY: RelationshipLayer.A2A,
    EdgeType.RESOURCE_RETURNED_X402_CHALLENGE: RelationshipLayer.A2A,
    EdgeType.STRATEGY_PRODUCED_INTENT: RelationshipLayer.A2A,
    EdgeType.THREAD_CONTAINS_MESSAGE: RelationshipLayer.A2A,

    # ── Fraud Network Intelligence ─────────────────────────────────────────
    EdgeType.MEMBER_OF_FRAUD_NETWORK: RelationshipLayer.H2H,
    EdgeType.HAS_RISK_ROLE: RelationshipLayer.H2H,
    EdgeType.SCORED_AS_RISKY: RelationshipLayer.H2H,
    EdgeType.SUPPORTED_BY_EVIDENCE: RelationshipLayer.H2H,
    EdgeType.PART_OF_FLOW_TRACE: RelationshipLayer.H2H,
    EdgeType.FLOW_PATH_NEXT: RelationshipLayer.H2H,
    EdgeType.HAS_SOURCE: RelationshipLayer.H2H,
    EdgeType.HAS_SINK: RelationshipLayer.H2H,
    EdgeType.HAS_CONTROLLER: RelationshipLayer.H2H,
    EdgeType.USES_MULE: RelationshipLayer.H2H,
    EdgeType.LINKED_BY_DEVICE: RelationshipLayer.H2H,
    EdgeType.LINKED_BY_IP: RelationshipLayer.H2H,
    EdgeType.LINKED_BY_WALLET: RelationshipLayer.H2H,
    EdgeType.LINKED_BY_AGENT: RelationshipLayer.A2A,
    EdgeType.LINKED_BY_DELEGATION: RelationshipLayer.H2A,
    EdgeType.ATTACHED_TO_CASE: RelationshipLayer.H2H,
}


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

def classify_edge(edge: Edge) -> RelationshipLayer:
    """Classify an edge into its relationship layer (H2H, H2A, A2H, or A2A).

    In staging/production (AETHER_ENV not in local/test), an unknown edge type
    raises UnknownEdgeTypeError (fail-closed). In local/test it logs a warning
    and returns H2H for backward compatibility.
    """
    layer = _EDGE_LAYER_MAP.get(edge.edge_type)
    if layer is None:
        if _is_strict():
            raise UnknownEdgeTypeError(
                f"EdgeType {edge.edge_type!r} has no layer classification. "
                "Add it to _EDGE_LAYER_MAP in relationship_layers.py."
            )
        logger.warning("Unknown edge type for layer classification: %s", edge.edge_type)
        return RelationshipLayer.H2H
    return layer


def classify_edge_type(edge_type: str) -> RelationshipLayer:
    """Classify an edge type string into its relationship layer.

    In staging/production, unknown types raise UnknownEdgeTypeError.
    """
    layer = _EDGE_LAYER_MAP.get(edge_type)
    if layer is None:
        if _is_strict():
            raise UnknownEdgeTypeError(
                f"EdgeType {edge_type!r} has no layer classification. "
                "Add it to _EDGE_LAYER_MAP in relationship_layers.py."
            )
        logger.warning("Unknown edge type: %s", edge_type)
        return RelationshipLayer.H2H
    return layer


# ═══════════════════════════════════════════════════════════════════════════
# LAYER VERTEX SETS
# ═══════════════════════════════════════════════════════════════════════════

H2H_VERTEX_TYPES = frozenset({
    VertexType.USER, VertexType.SESSION, VertexType.DEVICE,
    VertexType.PAGE_VIEW, VertexType.EVENT, VertexType.COMPANY,
    VertexType.EMAIL, VertexType.PHONE, VertexType.WALLET,
    VertexType.DEVICE_FINGERPRINT, VertexType.IP_ADDRESS,
    VertexType.LOCATION, VertexType.IDENTITY_CLUSTER,
})

H2A_VERTEX_TYPES = frozenset({
    VertexType.USER, VertexType.AGENT, VertexType.SERVICE,
    VertexType.CAMPAIGN,
})

A2H_VERTEX_TYPES = frozenset({
    VertexType.AGENT, VertexType.USER, VertexType.SERVICE,
})

A2A_VERTEX_TYPES = frozenset({
    VertexType.AGENT, VertexType.SERVICE, VertexType.CONTRACT,
    VertexType.PROTOCOL, VertexType.PAYMENT, VertexType.ACTION_RECORD,
})


# ═══════════════════════════════════════════════════════════════════════════
# QUERY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

async def get_layer_subgraph(
    graph_client: GraphClient,
    user_id: str,
    layer: RelationshipLayer,
    tenant_id: str = "",
    max_hops: int = 2,
    max_results: int = 200,
) -> dict:
    """
    Get the subgraph for a specific relationship layer starting from a user vertex.
    Returns dict with 'vertices' and 'edges' lists.

    max_hops limits BFS depth (default 2). max_results caps total vertex count.
    """
    allowed_vertex_types = {
        RelationshipLayer.H2H: H2H_VERTEX_TYPES,
        RelationshipLayer.H2A: H2A_VERTEX_TYPES,
        RelationshipLayer.A2H: A2H_VERTEX_TYPES,
        RelationshipLayer.A2A: A2A_VERTEX_TYPES,
        RelationshipLayer.EXCLUDED: frozenset(),
    }[layer]

    allowed_edge_types = {
        et for et, el in _EDGE_LAYER_MAP.items() if el == layer
    }

    vertices: list[Vertex] = []
    visited: set[str] = {user_id}
    frontier: list[str] = [user_id]

    for _ in range(max_hops):
        if not frontier or len(vertices) >= max_results:
            break
        next_frontier: list[str] = []
        for vid in frontier:
            if len(vertices) >= max_results:
                break
            neighbors = await graph_client.get_neighbors(vid, direction="both")
            for neighbor in neighbors:
                if neighbor.vertex_id in visited:
                    continue
                if neighbor.vertex_type not in allowed_vertex_types:
                    continue
                if tenant_id and neighbor.properties.get("tenant_id", tenant_id) != tenant_id:
                    continue
                visited.add(neighbor.vertex_id)
                vertices.append(neighbor)
                next_frontier.append(neighbor.vertex_id)
                if len(vertices) >= max_results:
                    break
        frontier = next_frontier

    return {
        "layer": layer.value,
        "root_user_id": user_id,
        "vertices": [
            {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
            for v in vertices
        ],
        "vertex_count": len(vertices),
        "edge_types": sorted(allowed_edge_types),
    }


async def get_cross_layer_paths(
    graph_client: GraphClient,
    user_id: str,
    tenant_id: str = "",
    max_depth: int = 3,
) -> list[dict]:
    """
    Find cross-layer paths: Human → Agent → Agent and Agent → Human chains.
    Traces H2A delegation into A2A orchestration and A2H delivery back to humans.

    max_depth limits the H2A→A2A hop chain (default 3).
    """
    paths: list[dict] = []

    # Step 1: Find agents launched/delegated by user (H2A layer)
    agents = await graph_client.get_neighbors(
        user_id, edge_type=EdgeType.DELEGATES, direction="out"
    )
    launched = await graph_client.get_neighbors(
        user_id, edge_type=EdgeType.LAUNCHED_BY, direction="in"
    )
    all_agents = {a.vertex_id: a for a in agents + launched}

    # Step 2: For each agent, find A2A and A2H connections up to max_depth
    for depth, (agent_id, agent) in enumerate(all_agents.items()):
        if depth >= max_depth:
            break

        hired = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.HIRED, direction="out"
        )
        consumed = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.CONSUMES, direction="out"
        )
        deployed = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.DEPLOYED, direction="out"
        )

        # A2H: agent-initiated interactions back to humans
        notified = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.NOTIFIES, direction="out"
        )
        delivered = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.DELIVERS_TO, direction="out"
        )
        escalated = await graph_client.get_neighbors(
            agent_id, edge_type=EdgeType.ESCALATES_TO, direction="out"
        )

        if hired or consumed or deployed or notified or delivered or escalated:
            path_entry: dict = {
                "user_id": user_id,
                "agent_id": agent_id,
                "agent_type": agent.properties.get("model_name", "unknown"),
                "h2a_edge": "DELEGATES",
                "a2a_connections": {
                    "hired_agents": [h.vertex_id for h in hired],
                    "consumed_services": [c.vertex_id for c in consumed],
                    "deployed_contracts": [d.vertex_id for d in deployed],
                },
                "a2h_connections": {
                    "notified_users": [n.vertex_id for n in notified],
                    "delivered_to_users": [d.vertex_id for d in delivered],
                    "escalated_to_users": [e.vertex_id for e in escalated],
                },
            }
            paths.append(path_entry)

    return paths


def get_layer_stats(edges: list[Edge]) -> dict[str, int]:
    """Count edges by relationship layer. Unclassified edges counted under 'unknown'."""
    counts: dict[str, int] = {layer.value: 0 for layer in RelationshipLayer}
    counts["unknown"] = 0
    for edge in edges:
        layer = _EDGE_LAYER_MAP.get(edge.edge_type)
        if layer is None:
            counts["unknown"] += 1
        else:
            counts[layer.value] += 1
    return counts
