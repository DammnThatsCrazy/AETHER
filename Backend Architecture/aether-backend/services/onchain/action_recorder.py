"""
Aether Service — On-Chain Action Recorder
Records on-chain actions, creates graph vertices/edges, runs bytecode risk scoring.
"""

from __future__ import annotations

import uuid
from typing import Optional

from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from shared.scoring.bytecode_risk import BytecodeRiskScorer
from repositories.repos import BaseRepository

from .models import ActionRecord, ActionType, ContractInfo

logger = get_logger("aether.service.onchain.recorder")


class ActionRecorder:
    """Records on-chain actions and builds the protocol subgraph."""

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        event_producer: Optional[EventProducer] = None,
        bytecode_scorer: Optional[BytecodeRiskScorer] = None,
    ):
        self._graph = graph_client or GraphClient()
        self._producer = event_producer or EventProducer()
        self._bytecode_scorer = bytecode_scorer or BytecodeRiskScorer()
        self._actions = BaseRepository("onchain_actions")

    async def record(self, action: ActionRecord) -> ActionRecord:
        """Record an on-chain action, create graph entities, and assess risk."""
        if not action.action_id:
            action.action_id = str(uuid.uuid4())

        # Score bytecode risk for DEPLOY actions
        if action.action_type == ActionType.DEPLOY and action.bytecode_hash:
            # Extract opcodes from metadata if available
            opcodes = action.metadata.get("bytecode_opcodes") if action.metadata else None
            risk_result = await self._bytecode_scorer.score(
                bytecode_hash=action.bytecode_hash,
                contract_address=action.contract_address or "",
                chain_id=action.chain_id,
                bytecode_opcodes=opcodes,
            )
            action.risk_score = risk_result.risk_score

        # Wrap graph operations in try/except so action is still recorded locally
        # even if graph mutations fail
        try:
            # Create ACTION_RECORD vertex
            action_vertex = Vertex(
                vertex_type=VertexType.ACTION_RECORD,
                vertex_id=action.action_id,
                properties={
                    "action_type": action.action_type,
                    "chain_id": action.chain_id,
                    "vm_type": action.vm_type,
                    "tx_hash": action.tx_hash or "",
                    "contract_address": action.contract_address or "",
                    "intent": action.intent_description,
                    "risk_score": str(action.risk_score),
                },
            )
            await self._graph.add_vertex(action_vertex)

            # Create PERFORMED_ACTION edge: agent -> action_record
            await self._graph.add_edge(Edge(
                edge_type=EdgeType.PERFORMED_ACTION,
                from_vertex_id=action.agent_id,
                to_vertex_id=action.action_id,
                properties={"confidence": "1.0"},
            ))

            # For DEPLOY actions, create/update CONTRACT vertex + DEPLOYED edge
            if action.action_type == ActionType.DEPLOY and action.contract_address:
                contract_vertex = Vertex(
                    vertex_type=VertexType.CONTRACT,
                    vertex_id=action.contract_address,
                    properties={
                        "chain_id": action.chain_id,
                        "vm_type": action.vm_type,
                        "deployer_agent_id": action.agent_id,
                        "bytecode_hash": action.bytecode_hash or "",
                        "risk_score": str(action.risk_score),
                    },
                )
                await self._graph.upsert_vertex(contract_vertex)
                await self._graph.add_edge(Edge(
                    edge_type=EdgeType.DEPLOYED,
                    from_vertex_id=action.agent_id,
                    to_vertex_id=action.contract_address,
                    properties={"tx_hash": action.tx_hash or "", "chain_id": action.chain_id},
                ))

            # For CALL actions, create CALLED edge
            if action.action_type == ActionType.CALL and action.contract_address:
                await self._graph.add_edge(Edge(
                    edge_type=EdgeType.CALLED,
                    from_vertex_id=action.agent_id,
                    to_vertex_id=action.contract_address,
                    properties={
                        "method": action.method_name or "",
                        "value": action.value_wei or "0",
                    },
                ))
        except Exception as e:
            logger.error(f"Graph operation failed for action {action.action_id}: {e}")
            # Still continue -- record the action locally even if graph fails

        # Determine event topic
        topic_map = {
            ActionType.DEPLOY: Topic.CONTRACT_DEPLOYED,
            ActionType.CALL: Topic.CONTRACT_CALLED,
        }
        topic = topic_map.get(action.action_type, Topic.ACTION_RECORDED)

        await self._producer.publish(Event(
            topic=topic,
            payload=action.model_dump(),
            source_service="onchain",
        ))

        existing = await self._actions.find_by_id(action.action_id)
        payload = action.model_dump()
        if existing:
            await self._actions.update(action.action_id, payload)
        else:
            await self._actions.insert(action.action_id, payload)
        metrics.increment("onchain_actions_recorded", labels={"type": action.action_type})
        logger.info(f"Action recorded: {action.action_id} ({action.action_type} on {action.chain_id})")
        return action

    async def get_agent_actions(self, agent_id: str) -> list[dict]:
        """Get all on-chain actions for an agent."""
        return await self._actions.find_many(filters={"agent_id": agent_id}, limit=10_000, sort_by="timestamp", sort_order="asc")

    async def get_contract_info(self, contract_address: str) -> Optional[ContractInfo]:
        """Get contract details from the graph."""
        vertex = await self._graph.get_vertex(contract_address)
        if not vertex or vertex.vertex_type != VertexType.CONTRACT:
            return None

        call_count = await self._actions.count(contract_address=contract_address, action_type=ActionType.CALL)

        return ContractInfo(
            address=contract_address,
            chain_id=vertex.properties.get("chain_id", ""),
            vm_type=vertex.properties.get("vm_type", "evm"),
            deployer_agent_id=vertex.properties.get("deployer_agent_id"),
            bytecode_hash=vertex.properties.get("bytecode_hash"),
            risk_score=float(vertex.properties.get("risk_score", "0.0")),
            deployed_at=vertex.created_at,
            call_count=call_count,
        )
