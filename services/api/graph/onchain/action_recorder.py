"""On-chain action recording through the canonical graph mutation gateway."""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from shared.common.common import BadRequestError, ConflictError, ServiceUnavailableError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.edge_properties import build_edge_properties
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger, metrics
from shared.scoring.bytecode_risk import BytecodeRiskScorer

from .models import ActionRecord, ActionType, ContractInfo

logger = get_logger("aether.service.onchain.recorder")
_GRAPH_ACTOR_ID = "onchain.action_recorder"
_MAX_TENANT_READ = 1000


def _tenant_id(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("tenant_id is required for on-chain operations")
    return value.strip()


def _tenant_vertex_id(tenant_id: str, vertex_id: str) -> str:
    return f"{tenant_id}:{vertex_id}"


def _source_event_id(action: ActionRecord) -> Optional[str]:
    tx_hash = (action.tx_hash or "").strip().lower()
    if not tx_hash:
        return f"onchain:action:{action.action_id}"
    # The transaction is the external source identity; action_id distinguishes
    # multiple observed actions in one transaction when callers provide it.
    return f"onchain:{action.chain_id}:{tx_hash}:{action.action_id}"


def _check_outcome(outcome, *, operation: str) -> None:
    if outcome.deduplicated:
        return
    if outcome.applied:
        return
    details = "; ".join(outcome.violations) or "gateway did not apply the mutation"
    raise ConflictError(f"On-chain graph mutation {operation} was rejected: {details}")


class ActionRecorder:
    """Records on-chain actions and builds the tenant-scoped protocol subgraph."""

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        event_producer: Optional[EventProducer] = None,
        bytecode_scorer: Optional[BytecodeRiskScorer] = None,
        mutation_gateway: Optional[GraphMutationGateway] = None,
    ):
        self._graph = graph_client or GraphClient()
        self._gateway = mutation_gateway or GraphMutationGateway(graph_client=self._graph)
        self._producer = event_producer or EventProducer()
        self._bytecode_scorer = bytecode_scorer or BytecodeRiskScorer()

    async def record(self, action: ActionRecord, *, tenant_id: str) -> ActionRecord:
        """Record an action and mutate graph facts for an authenticated tenant.

        ActionRecord has no log index. Omitted IDs therefore assume one action
        per tenant/chain/transaction; callers must provide distinct stable IDs
        to represent multiple actions from the same transaction.
        """
        tenant_id = _tenant_id(tenant_id)
        if not action.action_id:
            tx_hash = (action.tx_hash or "").strip().lower()
            if not tx_hash:
                raise BadRequestError("action_id or tx_hash is required for on-chain action identity")
            action.action_id = hashlib.sha256(
                f"{tenant_id}:{action.chain_id}:{tx_hash}".encode()
            ).hexdigest()

        if action.action_type == ActionType.DEPLOY and action.bytecode_hash:
            opcodes = action.metadata.get("bytecode_opcodes") if action.metadata else None
            risk_result = await self._bytecode_scorer.score(
                bytecode_hash=action.bytecode_hash,
                contract_address=action.contract_address or "",
                chain_id=action.chain_id,
                bytecode_opcodes=opcodes,
            )
            action.risk_score = risk_result.risk_score

        source_event_id = _source_event_id(action)
        agent_id = _tenant_vertex_id(tenant_id, action.agent_id)
        action_id = _tenant_vertex_id(tenant_id, action.action_id)
        action_properties = {
            **action.model_dump(),
            "tenantId": tenant_id,
        }
        action_vertex = Vertex(
            vertex_type=VertexType.ACTION_RECORD,
            vertex_id=action_id,
            properties=action_properties,
        )
        stable_properties = {
            key: value
            for key, value in action_properties.items()
            if key not in {"timestamp", "metadata"}
        }
        stable_properties["tx_hash"] = (action.tx_hash or "").strip().lower()
        payload_hash = hashlib.sha256(
            json.dumps(stable_properties, sort_keys=True, default=str).encode()
        ).hexdigest()
        outcome = await self._gateway.apply(vertex_intent(
            action_vertex,
            operation="node_versioned",
            tenant_id=tenant_id,
            actor_kind="service",
            actor_id=_GRAPH_ACTOR_ID,
            source_event_id=source_event_id,
            idempotency_key=hashlib.sha256(
                f"{tenant_id}:{action_id}:{source_event_id or action.action_id}:{payload_hash}".encode()
            ).hexdigest(),
            causality_class="observed_sequence",
        ))
        _check_outcome(outcome, operation="action record")

        await self._apply_edge(
            Edge(
                edge_type=EdgeType.PERFORMED_ACTION,
                from_vertex_id=agent_id,
                to_vertex_id=action_id,
                properties={"tenant_id": tenant_id, "confidence": "1.0"},
            ),
            tenant_id=tenant_id,
            source_event_id=source_event_id,
            valid_from=action.timestamp,
        )

        contract_id = None
        if action.contract_address:
            contract_id = _tenant_vertex_id(
                tenant_id, f"contract:{action.chain_id}:{action.contract_address.lower()}"
            )
        if action.action_type == ActionType.DEPLOY and contract_id:
            contract_vertex = Vertex(
                vertex_type=VertexType.CONTRACT,
                vertex_id=contract_id,
                properties={
                    "tenantId": tenant_id,
                    "address": action.contract_address,
                    "chain_id": action.chain_id,
                    "vm_type": action.vm_type,
                    "deployer_agent_id": action.agent_id,
                    "bytecode_hash": action.bytecode_hash or "",
                    "risk_score": str(action.risk_score),
                },
            )
            outcome = await self._gateway.apply(vertex_intent(
                contract_vertex,
                operation="node_versioned",
                tenant_id=tenant_id,
                actor_kind="service",
                actor_id=_GRAPH_ACTOR_ID,
                source_event_id=source_event_id,
                idempotency_key=hashlib.sha256(
                    f"{tenant_id}:{contract_id}:{source_event_id or action.action_id}:"
                    f"{action.bytecode_hash or ''}:{action.risk_score}".encode()
                ).hexdigest(),
            ))
            _check_outcome(outcome, operation="contract record")
            await self._apply_edge(
                Edge(
                    edge_type=EdgeType.DEPLOYED,
                    from_vertex_id=agent_id,
                    to_vertex_id=contract_id,
                    properties={"tenant_id": tenant_id, "tx_hash": action.tx_hash or "", "chain_id": action.chain_id},
                ),
                tenant_id=tenant_id,
                source_event_id=source_event_id,
                valid_from=action.timestamp,
            )
        elif action.action_type == ActionType.CALL and contract_id:
            await self._apply_edge(
                Edge(
                    edge_type=EdgeType.CALLED,
                    from_vertex_id=agent_id,
                    to_vertex_id=contract_id,
                    properties={
                        "tenant_id": tenant_id,
                        "method": action.method_name or "",
                        "value": action.value_wei or "0",
                    },
                ),
                tenant_id=tenant_id,
                source_event_id=source_event_id,
                valid_from=action.timestamp,
            )

        topic = {
            ActionType.DEPLOY: Topic.CONTRACT_DEPLOYED,
            ActionType.CALL: Topic.CONTRACT_CALLED,
        }.get(action.action_type, Topic.ACTION_RECORDED)
        await self._producer.publish(Event(
            topic=topic,
            payload=action.model_dump(),
            tenant_id=tenant_id,
            source_service="onchain",
        ))
        metrics.increment("onchain_actions_recorded", labels={"type": action.action_type})
        logger.info(f"Action recorded: {action.action_id} ({action.action_type} on {action.chain_id})")
        return action

    async def _apply_edge(
        self,
        edge: Edge,
        *,
        tenant_id: str,
        source_event_id: Optional[str],
        valid_from: str,
    ) -> None:
        edge.properties.update(build_edge_properties(
            tenant_id=tenant_id,
            edge_type=edge.edge_type,
            from_vertex_id=edge.from_vertex_id,
            to_vertex_id=edge.to_vertex_id,
            actor_kind="service",
            actor_id=_GRAPH_ACTOR_ID,
            provenance="onchain:action_recorder",
            valid_from=valid_from,
            confidence=1.0,
            source_event_id=source_event_id or "",
        ))
        outcome = await self._gateway.apply(edge_intent(
            edge,
            operation="edge_created",
            tenant_id=tenant_id,
            actor_kind="service",
            actor_id=_GRAPH_ACTOR_ID,
            source_event_id=source_event_id,
            causality_class="observed_sequence",
            valid_from=valid_from,
        ))
        _check_outcome(outcome, operation=f"{edge.edge_type} edge")

    async def get_agent_actions(self, agent_id: str, *, tenant_id: str) -> list[dict]:
        """Read only action records owned by the authenticated tenant and agent."""
        tenant_id = _tenant_id(tenant_id)
        vertices = await self._bounded_tenant_vertices(tenant_id, VertexType.ACTION_RECORD)
        return [
            {
                key: value
                for key, value in vertex.properties.items()
                if key in ActionRecord.model_fields
            }
            for vertex in vertices
            if vertex.properties.get("agent_id") == agent_id
        ]

    async def get_contract_info(
        self, contract_address: str, *, tenant_id: str, chain_id: Optional[str] = None
    ) -> Optional[ContractInfo]:
        """Find a contract by address within the authenticated tenant only."""
        tenant_id = _tenant_id(tenant_id)
        vertices = await self._bounded_tenant_vertices(tenant_id, VertexType.CONTRACT)
        matches = [
            item for item in vertices
            if item.properties.get("address", "").lower() == contract_address.lower()
            and (chain_id is None or item.properties.get("chain_id") == chain_id)
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise ConflictError(
                f"Contract address {contract_address} exists on multiple chains; provide chain_id"
            )
        vertex = matches[0]
        props = vertex.properties
        actions = await self._bounded_tenant_vertices(tenant_id, VertexType.ACTION_RECORD)
        call_count = sum(
            1 for item in actions
            if (item.properties.get("contract_address") or "").lower() == contract_address.lower()
            and item.properties.get("action_type") == ActionType.CALL
            and item.properties.get("chain_id") == props.get("chain_id")
        )
        return ContractInfo(
            address=contract_address,
            chain_id=props.get("chain_id", ""),
            vm_type=props.get("vm_type", "evm"),
            deployer_agent_id=props.get("deployer_agent_id"),
            bytecode_hash=props.get("bytecode_hash"),
            risk_score=float(props.get("risk_score", "0.0")),
            deployed_at=vertex.created_at,
            call_count=call_count,
        )

    async def _bounded_tenant_vertices(self, tenant_id: str, vertex_type: str) -> list[Vertex]:
        """Refuse an incomplete read until indexed on-chain queries are available."""
        vertices = await self._graph.get_vertices_for_tenant(
            tenant_id, limit=_MAX_TENANT_READ + 1, vertex_type=vertex_type
        )
        if len(vertices) > _MAX_TENANT_READ:
            raise ServiceUnavailableError("indexed on-chain tenant graph read")
        return vertices
