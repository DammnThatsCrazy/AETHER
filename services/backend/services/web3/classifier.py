"""
Aether Web3 Coverage — Classification Engine

Three-phase classification pipeline:
  Phase 1 — Raw observability (ingest everything, create raw graph objects)
  Phase 2 — Typed semantic decoding (classify contracts, map protocols, normalize actions)
  Phase 3 — Risk/intelligence scoring (confidence bands, graph expansion)

Supports:
  - Contract → protocol mapping via registry lookup
  - Method selector → canonical action mapping
  - Frontend domain → app/protocol attribution
  - Unknown contract handling with later reclassification
  - Protocol migration detection
"""

from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.graph.graph import GraphClient, Vertex, Edge, VertexType, EdgeType
from shared.logger.logger import get_logger

from services.web3.registries import (
    ProtocolRegistry,
    ContractInstanceRegistry,
    AppRegistry,
    FrontendDomainRegistry,
)

logger = get_logger("aether.web3.classifier")


# ═══════════════════════════════════════════════════════════════════════════
# METHOD SELECTOR → CANONICAL ACTION MAPPING
# ═══════════════════════════════════════════════════════════════════════════

# Common EVM method selectors mapped to canonical action families.
# This is the initial seed — extend dynamically from Dune decoded traces.
METHOD_SELECTOR_MAP: dict[str, str] = {
    # ERC20
    "0xa9059cbb": "transfer",        # transfer(address,uint256)
    "0x23b872dd": "transfer",        # transferFrom(address,address,uint256)
    "0x095ea7b3": "approve",         # approve(address,uint256)

    # Uniswap V2
    "0x38ed1739": "swap",            # swapExactTokensForTokens
    "0x7ff36ab5": "swap",            # swapExactETHForTokens
    "0x18cbafe5": "swap",            # swapExactTokensForETH
    "0xe8e33700": "add_liquidity",   # addLiquidity
    "0xf305d719": "add_liquidity",   # addLiquidityETH
    "0xbaa2abde": "remove_liquidity", # removeLiquidity
    "0x02751cec": "remove_liquidity", # removeLiquidityETH

    # Uniswap V3
    "0x414bf389": "swap",            # exactInputSingle
    "0xc04b8d59": "swap",            # exactInput
    "0x5023b4df": "swap",            # exactOutputSingle
    "0x88316456": "create_position", # mint (position)
    "0x0c49ccbe": "close_position",  # decreaseLiquidity
    "0xfc6f7865": "claim",           # collect (fees)

    # Aave V3
    "0xe8eda9df": "lend",            # deposit (supply)
    "0x69328dec": "withdraw",        # withdraw
    "0xa415bcad": "borrow",          # borrow
    "0x573ade81": "repay",           # repay

    # Compound V3
    "0xf2b9fdb8": "lend",            # supply
    "0xf3fef3a3": "withdraw",        # withdraw

    # Lido
    "0xa1903eab": "stake",           # submit (stake ETH)
    "0xccc143b8": "unstake",         # requestWithdrawals

    # EigenLayer
    "0xf7a30806": "stake",           # depositIntoStrategy
    "0xd9caed12": "unstake",         # queueWithdrawal

    # Bridge (common patterns)
    "0x0100d9f0": "bridge",          # Across deposit
    "0x9fbf10fc": "bridge",          # Stargate swap
    "0x3ccfd60b": "withdraw",        # Generic withdraw

    # Governance
    "0xda95691a": "vote",            # castVote (Governor)
    "0x56781388": "vote",            # castVote (Snapshot relay)
    "0x5c19a95c": "delegate",        # delegate(address)

    # NFT
    "0x42842e0e": "transfer",        # safeTransferFrom (ERC721)
    "0x1249c58b": "mint",            # mint()
    "0xa22cb465": "approve",         # setApprovalForAll

    # Wrapped tokens
    "0xd0e30db0": "wrap",            # deposit (WETH)
    "0x2e1a7d4d": "unwrap",          # withdraw (WETH)

    # General
    "0x3593564c": "swap",            # execute (Universal Router)
    "0x5ae401dc": "call_contract",   # multicall
}


def classify_method_selector(selector: str) -> str:
    """Map a method selector (4 bytes hex) to a canonical action."""
    return METHOD_SELECTOR_MAP.get(selector.lower()[:10], "unknown")


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════


async def classify_contract(
    chain_id: str,
    address: str,
    contract_reg: ContractInstanceRegistry,
    protocol_reg: ProtocolRegistry,
) -> dict:
    """
    Classify a contract address.

    Returns:
      {
        "address": str,
        "chain_id": str,
        "protocol_id": str (or ""),
        "system_id": str (or ""),
        "role": str,
        "classification_confidence": float,
        "completeness": str,
        "is_new": bool,
      }
    """
    # Check if we already know this contract
    existing = await contract_reg.get_by_address(chain_id, address.lower())
    if existing and existing.get("protocol_id"):
        return {
            "address": address,
            "chain_id": chain_id,
            "protocol_id": existing.get("protocol_id", ""),
            "system_id": existing.get("system_id", ""),
            "role": existing.get("role", "unknown"),
            "classification_confidence": existing.get("classification_confidence", 0.0),
            "completeness": existing.get("completeness", "raw_observed"),
            "is_new": False,
        }

    # Unknown contract — register as raw_observed
    if not existing:
        await contract_reg.register({
            "address": address.lower(),
            "chain_id": chain_id,
            "completeness": "raw_observed",
            "classification_confidence": 0.0,
            "status": "active",
            "source": "auto_classify",
        })

    return {
        "address": address,
        "chain_id": chain_id,
        "protocol_id": "",
        "system_id": "",
        "role": "unknown",
        "classification_confidence": 0.0,
        "completeness": "raw_observed",
        "is_new": True,
    }


# ═══════════════════════════════════════════════════════════════════════════
# DOMAIN ATTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════


async def attribute_domain(
    domain: str,
    domain_reg: FrontendDomainRegistry,
    app_reg: AppRegistry,
) -> dict:
    """
    Attribute a frontend domain to an app and protocol(s).

    Returns:
      {
        "domain": str,
        "app_id": str (or ""),
        "protocol_ids": list[str],
        "verified": bool,
        "is_new": bool,
      }
    """
    existing = await domain_reg.get_by_domain(domain)
    if existing:
        return {
            "domain": domain,
            "app_id": existing.get("app_id", ""),
            "protocol_ids": existing.get("protocol_ids", []),
            "verified": existing.get("verified", False),
            "is_new": False,
        }

    # Check if any registered app claims this domain
    app = await app_reg.get_by_domain(domain)
    if app:
        await domain_reg.register({
            "domain": domain,
            "app_id": app.get("app_id", ""),
            "protocol_ids": app.get("protocols", []),
            "verified": True,
            "first_seen": utc_now(),
            "source": "app_registry_match",
        })
        return {
            "domain": domain,
            "app_id": app.get("app_id", ""),
            "protocol_ids": app.get("protocols", []),
            "verified": True,
            "is_new": True,
        }

    # Unknown domain — register as raw
    await domain_reg.register({
        "domain": domain,
        "app_id": "",
        "protocol_ids": [],
        "verified": False,
        "first_seen": utc_now(),
        "source": "auto_discovery",
    })
    return {
        "domain": domain,
        "app_id": "",
        "protocol_ids": [],
        "verified": False,
        "is_new": True,
    }


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVATION → GRAPH BUILDER
# ═══════════════════════════════════════════════════════════════════════════


async def build_graph_from_observation(
    observation: dict,
    graph: GraphClient,
    contract_reg: ContractInstanceRegistry,
    protocol_reg: ProtocolRegistry,
    domain_reg: FrontendDomainRegistry,
    app_reg: AppRegistry,
) -> dict:
    """
    Build graph vertices and edges from a single Web3 observation.

    This is the heart of Layer 4 — the Internal Ontology + Graph Expansion.
    Every observation creates at minimum a WALLET vertex and an edge to the
    contract/protocol/app/domain it touched. Unknown objects get raw vertices
    with confidence=0 that can be enriched later.

    Returns: {"vertices_created": int, "edges_created": int}
    """
    vertices = 0
    edges = 0
    now = utc_now()

    chain_id = observation.get("chain_id", "")
    from_address = observation.get("from_address", "")
    to_address = observation.get("to_address", "")
    contract_address = observation.get("contract_address", "") or to_address
    canonical_action = observation.get("canonical_action", "unknown")
    protocol_id = observation.get("protocol_id", "")
    app_id = observation.get("app_id", "")
    domain = observation.get("domain", "")
    provenance = observation.get("provenance", {})
    source = provenance.get("source", "unknown") if isinstance(provenance, dict) else "unknown"

    # 1. Create/upsert WALLET vertex for from_address
    if from_address:
        graph.upsert_vertex(Vertex(
            vertex_type=VertexType.WALLET,
            vertex_id=f"wallet:{from_address.lower()}",
            properties={
                "address": from_address.lower(),
                "chain_id": chain_id,
                "last_seen": now,
                "source": source,
            },
        ))
        vertices += 1

    # 2. Classify and graph the contract
    if contract_address:
        classification = await classify_contract(
            chain_id, contract_address, contract_reg, protocol_reg,
        )
        protocol_id = protocol_id or classification.get("protocol_id", "")

        if classification.get("completeness") == "raw_observed" and not protocol_id:
            # Unknown contract → create UNKNOWN_CONTRACT vertex
            graph.upsert_vertex(Vertex(
                vertex_type=VertexType.UNKNOWN_CONTRACT,
                vertex_id=f"contract:{chain_id}:{contract_address.lower()}",
                properties={
                    "address": contract_address.lower(),
                    "chain_id": chain_id,
                    "classification_confidence": 0.0,
                    "completeness": "raw_observed",
                    "first_seen": now,
                    "source": source,
                },
            ))
        else:
            graph.upsert_vertex(Vertex(
                vertex_type=VertexType.CONTRACT,
                vertex_id=f"contract:{chain_id}:{contract_address.lower()}",
                properties={
                    "address": contract_address.lower(),
                    "chain_id": chain_id,
                    "protocol_id": protocol_id,
                    "role": classification.get("role", "unknown"),
                    "classification_confidence": classification.get("classification_confidence", 0.0),
                    "source": source,
                },
            ))
        vertices += 1

        # Edge: wallet → contract
        if from_address:
            graph.add_edge(Edge(
                edge_type=EdgeType.CALLED,
                source_id=f"wallet:{from_address.lower()}",
                target_id=f"contract:{chain_id}:{contract_address.lower()}",
                properties={
                    "canonical_action": canonical_action,
                    "chain_id": chain_id,
                    "observed_at": now,
                    "source": source,
                },
            ))
            edges += 1

    # 3. Create protocol vertex + wallet→protocol edge
    if protocol_id and from_address:
        graph.upsert_vertex(Vertex(
            vertex_type=VertexType.PROTOCOL,
            vertex_id=f"protocol:{protocol_id}",
            properties={"protocol_id": protocol_id, "source": source},
        ))
        vertices += 1

        graph.add_edge(Edge(
            edge_type=EdgeType.USES_PROTOCOL,
            source_id=f"wallet:{from_address.lower()}",
            target_id=f"protocol:{protocol_id}",
            properties={
                "canonical_action": canonical_action,
                "chain_id": chain_id,
                "observed_at": now,
                "source": source,
            },
        ))
        edges += 1

    # 4. Create app vertex + wallet→app edge
    if app_id and from_address:
        graph.upsert_vertex(Vertex(
            vertex_type=VertexType.APP,
            vertex_id=f"app:{app_id}",
            properties={"app_id": app_id, "source": source},
        ))
        vertices += 1

        graph.add_edge(Edge(
            edge_type=EdgeType.USES_APP,
            source_id=f"wallet:{from_address.lower()}",
            target_id=f"app:{app_id}",
            properties={"observed_at": now, "source": source},
        ))
        edges += 1

    # 5. Domain attribution
    if domain and from_address:
        attribution = await attribute_domain(domain, domain_reg, app_reg)

        graph.upsert_vertex(Vertex(
            vertex_type=VertexType.FRONTEND_DOMAIN,
            vertex_id=f"domain:{domain.lower()}",
            properties={
                "domain": domain.lower(),
                "app_id": attribution.get("app_id", ""),
                "verified": attribution.get("verified", False),
                "source": source,
            },
        ))
        vertices += 1

        graph.add_edge(Edge(
            edge_type=EdgeType.TOUCHES_DOMAIN,
            source_id=f"wallet:{from_address.lower()}",
            target_id=f"domain:{domain.lower()}",
            properties={"observed_at": now, "source": source},
        ))
        edges += 1

        # Domain → Protocol edges
        for pid in attribution.get("protocol_ids", []):
            graph.add_edge(Edge(
                edge_type=EdgeType.FRONTS_PROTOCOL,
                source_id=f"domain:{domain.lower()}",
                target_id=f"protocol:{pid}",
                properties={"source": source},
            ))
            edges += 1

    # 6. Chain vertex
    if chain_id:
        graph.upsert_vertex(Vertex(
            vertex_type=VertexType.CHAIN,
            vertex_id=f"chain:{chain_id}",
            properties={"chain_id": chain_id, "source": source},
        ))
        vertices += 1

    return {"vertices_created": vertices, "edges_created": edges}


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATION DETECTOR
# ═══════════════════════════════════════════════════════════════════════════


async def detect_migration(
    protocol_id: str,
    new_contract_address: str,
    chain_id: str,
    contract_reg: ContractInstanceRegistry,
    protocol_reg: ProtocolRegistry,
    graph: GraphClient,
) -> Optional[dict]:
    """
    Detect if a new contract deployment is a migration of an existing protocol.

    Checks if the deployer address matches a known protocol deployer.
    If so, creates MIGRATED_TO edges and returns migration metadata.
    """
    protocol = await protocol_reg.get_by_protocol_id(protocol_id)
    if not protocol:
        return None

    # Get existing contracts for this protocol on this chain
    existing = await contract_reg.list_by_protocol(protocol_id)
    same_chain = [c for c in existing if c.get("chain_id") == chain_id and c.get("status") == "active"]

    if not same_chain:
        return None

    # Check if any existing active contract should be marked as migrated
    new_instance = await contract_reg.get_by_address(chain_id, new_contract_address)
    if not new_instance:
        return None

    new_deployer = new_instance.get("deployed_by", "")
    now = utc_now()

    for old in same_chain:
        old_deployer = old.get("deployed_by", "")
        if old_deployer and new_deployer and old_deployer.lower() == new_deployer.lower():
            old_address = old.get("address", "")
            # Same deployer → potential migration
            graph.add_edge(Edge(
                edge_type=EdgeType.MIGRATED_TO,
                source_id=f"contract:{chain_id}:{old_address}",
                target_id=f"contract:{chain_id}:{new_contract_address.lower()}",
                properties={
                    "migration_type": "redeploy",
                    "detected_at": now,
                    "same_deployer": True,
                },
            ))

            return {
                "protocol_id": protocol_id,
                "chain_id": chain_id,
                "from_contract": old_address,
                "to_contract": new_contract_address,
                "migration_type": "redeploy",
                "detected_at": now,
                "same_deployer": True,
            }

    return None
