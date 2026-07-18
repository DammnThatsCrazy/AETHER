"""
Aether Service — Agent Lifecycle Mapper

Routes canonical agent lifecycle events to graph mutations and repository
operations. Supports both new granular event types and legacy event names.

All vertex IDs are tenant-scoped: ``f"{tenant_id}:agent:{agent_id}"``
so that the same agent ID can exist in multiple tenants without collision
in the shared graph store.

Event coverage:
  agent_registered, agent_updated, agent_authorized, agent_deauthorized,
  agent_capability_granted, agent_capability_revoked,
  agent_task_created, agent_task_decomposed, agent_task_started,
  agent_task_completed, agent_task_failed,
  agent_tool_called, agent_resource_requested,
  agent_delegated_task, agent_subagent_spawned,
  agent_policy_evaluated, agent_handoff,
  agent_escalated_to_human, agent_outcome_recorded

Legacy aliases:
  agent_task         → agent_task_created / agent_task_completed / agent_task_failed
  agent_decision     → agent_policy_evaluated
  a2h_interaction    → agent_escalated_to_human or agent_handoff
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.repos import DelegationRepository, AgentExecutionRepository
from shared.common.common import utc_now
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent, vertex_intent
from shared.logger.logger import get_logger

logger = get_logger("aether.service.agent.lifecycle_mapper")


def _agent_vid(tenant_id: str, agent_id: str) -> str:
    """Return the tenant-scoped vertex ID for an agent."""
    return f"{tenant_id}:agent:{agent_id}"


def _task_vid(tenant_id: str, task_id: str) -> str:
    return f"{tenant_id}:task:{task_id}"


def _tool_vid(tenant_id: str, tool_id: str) -> str:
    return f"{tenant_id}:tool:{tool_id}"


def _policy_vid(tenant_id: str, policy_id: str) -> str:
    return f"{tenant_id}:policy:{policy_id}"


def _outcome_vid(tenant_id: str, outcome_id: str) -> str:
    return f"{tenant_id}:outcome:{outcome_id}"


def _resource_vid(tenant_id: str, resource_id: str) -> str:
    return f"{tenant_id}:resource:{resource_id}"


def _capability_vid(tenant_id: str, capability: str) -> str:
    return f"{tenant_id}:capability:{capability}"


def _user_vid(tenant_id: str, user_id: str) -> str:
    return f"{tenant_id}:user:{user_id}"


class AgentLifecycleMapper:
    """Routes agent lifecycle events to graph mutations.

    Uses tenant-scoped vertex IDs throughout so the same agent_id can
    exist across tenants without collision. Graph mutations are fire-and-forget
    within the handler; caller is responsible for durability guarantees at the
    event-consumer layer.
    """

    def __init__(
        self,
        graph_client: Optional[GraphClient] = None,
        delegations: Optional[DelegationRepository] = None,
        executions: Optional[AgentExecutionRepository] = None,
    ) -> None:
        self._graph = graph_client or GraphClient()
        self._gateway = GraphMutationGateway(graph_client=self._graph)
        self._delegations = delegations or DelegationRepository()
        self._executions = executions or AgentExecutionRepository()

    # ─────────────────────────────────────────────────────────────────────
    # Graph write helpers (route through the canonical mutation gateway)
    # ─────────────────────────────────────────────────────────────────────

    async def _put_vertex(self, v: Vertex) -> None:
        """Upsert a lifecycle vertex through the gateway (node_versioned).

        tenant_id flows from the vertex property (every lifecycle vertex is
        tenant-scoped); the mapper is the system actor projecting events.
        """
        await self._gateway.apply(vertex_intent(
            v, operation="node_versioned", actor_id="agent_lifecycle_mapper",
        ))

    async def _put_edge(self, e: Edge) -> None:
        """Add a lifecycle edge through the gateway (edge_created).

        tenant_id flows from the edge property (every lifecycle edge carries
        it); subject is the edge source vertex.
        """
        await self._gateway.apply(edge_intent(
            e, operation="edge_created", actor_id="agent_lifecycle_mapper",
            subject_id=e.from_vertex_id,
        ))

    # ─────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────

    async def handle_event(
        self, event_type: str, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Dispatch a single agent lifecycle event to the correct handler.

        Returns a dict describing the resulting graph/repository operation(s).
        """
        handlers = {
            # Identity
            "agent_registered": self._handle_agent_registered,
            "agent_updated": self._handle_agent_updated,
            "agent_authorized": self._handle_agent_authorized,
            "agent_deauthorized": self._handle_agent_deauthorized,
            # Capabilities
            "agent_capability_granted": self._handle_capability_granted,
            "agent_capability_revoked": self._handle_capability_revoked,
            # Task lifecycle
            "agent_task_created": self._handle_task_created,
            "agent_task_decomposed": self._handle_task_decomposed,
            "agent_task_started": self._handle_task_started,
            "agent_task_completed": self._handle_task_completed,
            "agent_task_failed": self._handle_task_failed,
            # Tool / resource
            "agent_tool_called": self._handle_tool_called,
            "agent_resource_requested": self._handle_resource_requested,
            # Delegation / subagent
            "agent_delegated_task": self._handle_delegated_task,
            "agent_subagent_spawned": self._handle_subagent_spawned,
            # Policy / outcome
            "agent_policy_evaluated": self._handle_policy_evaluated,
            "agent_handoff": self._handle_handoff,
            "agent_escalated_to_human": self._handle_escalated_to_human,
            "agent_outcome_recorded": self._handle_outcome_recorded,
            # Legacy aliases
            "agent_task": self._handle_legacy_agent_task,
            "agent_decision": self._handle_legacy_agent_decision,
            "a2h_interaction": self._handle_legacy_a2h_interaction,
        }
        handler = handlers.get(event_type)
        if handler is None:
            logger.warning(f"Unknown agent event type: {event_type!r}")
            return {"status": "ignored", "event_type": event_type}

        try:
            result = await handler(payload, tenant_id)
            logger.info(f"Agent lifecycle event handled: {event_type}", extra={"tenant_id": tenant_id})
            return result
        except Exception as exc:
            logger.error(
                f"Agent lifecycle event failed: {event_type}: {exc}",
                extra={"tenant_id": tenant_id},
                exc_info=True,
            )
            raise

    # ─────────────────────────────────────────────────────────────────────
    # Identity handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_agent_registered(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        agent_vid = _agent_vid(tenant_id, agent_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.AGENT,
            vertex_id=agent_vid,
            properties={
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "status": "registered",
                "registered_at": payload.get("timestamp", utc_now().isoformat()),
                **_pick(payload, "name", "description", "model", "version"),
            },
        ))

        edges = []
        # OWNS_AGENT from owner (user or org)
        owner_user_id = payload.get("owner_user_id")
        if owner_user_id:
            owner_vid = _user_vid(tenant_id, owner_user_id)
            await self._put_vertex(Vertex(
                vertex_type=VertexType.USER,
                vertex_id=owner_vid,
                properties={"user_id": owner_user_id, "tenant_id": tenant_id},
            ))
            await self._put_edge(Edge(
                edge_type=EdgeType.OWNS_AGENT,
                from_vertex_id=owner_vid,
                to_vertex_id=agent_vid,
                properties={"tenant_id": tenant_id, "registered_at": payload.get("timestamp", "")},
            ))
            edges.append({"type": EdgeType.OWNS_AGENT, "from": owner_vid, "to": agent_vid})

        return {"status": "registered", "agent_vid": agent_vid, "edges": edges}

    async def _handle_agent_updated(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        await self._put_vertex(Vertex(
            vertex_type=VertexType.AGENT,
            vertex_id=agent_vid,
            properties={
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "updated_at": payload.get("timestamp", utc_now().isoformat()),
                **_pick(payload, "name", "description", "model", "version", "status"),
            },
        ))
        return {"status": "updated", "agent_vid": agent_vid}

    async def _handle_agent_authorized(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        authorizer_id = payload.get("owner_user_id") or payload.get("beneficiary_actor_id")
        edges = []
        if authorizer_id:
            authorizer_vid = _user_vid(tenant_id, authorizer_id)
            await self._put_edge(Edge(
                edge_type=EdgeType.AUTHORIZED_AGENT,
                from_vertex_id=authorizer_vid,
                to_vertex_id=agent_vid,
                properties={
                    "authorization_id": payload.get("authorization_id", ""),
                    "tenant_id": tenant_id,
                    "authorized_at": payload.get("timestamp", ""),
                },
            ))
            edges.append({"type": EdgeType.AUTHORIZED_AGENT, "from": authorizer_vid, "to": agent_vid})
        return {"status": "authorized", "agent_vid": agent_vid, "edges": edges}

    async def _handle_agent_deauthorized(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        await self._put_vertex(Vertex(
            vertex_type=VertexType.AGENT,
            vertex_id=agent_vid,
            properties={
                "status": "deauthorized",
                "deauthorized_at": payload.get("timestamp", utc_now().isoformat()),
                "tenant_id": tenant_id,
            },
        ))
        return {"status": "deauthorized", "agent_vid": agent_vid}

    # ─────────────────────────────────────────────────────────────────────
    # Capability handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_capability_granted(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        capability = _require(payload, "capability")
        agent_vid = _agent_vid(tenant_id, agent_id)
        cap_vid = _capability_vid(tenant_id, capability)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.CAPABILITY,
            vertex_id=cap_vid,
            properties={"capability": capability, "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.HAS_CAPABILITY,
            from_vertex_id=agent_vid,
            to_vertex_id=cap_vid,
            properties={
                "granted_at": payload.get("timestamp", ""),
                "tenant_id": tenant_id,
                "authorization_id": payload.get("authorization_id", ""),
            },
        ))
        return {"status": "capability_granted", "capability_vid": cap_vid}

    async def _handle_capability_revoked(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        capability = _require(payload, "capability")
        agent_vid = _agent_vid(tenant_id, agent_id)
        cap_vid = _capability_vid(tenant_id, capability)

        await self._put_edge(Edge(
            edge_type=EdgeType.REVOKED_CAPABILITY,
            from_vertex_id=agent_vid,
            to_vertex_id=cap_vid,
            properties={
                "revoked_at": payload.get("timestamp", ""),
                "tenant_id": tenant_id,
            },
        ))
        return {"status": "capability_revoked", "capability_vid": cap_vid}

    # ─────────────────────────────────────────────────────────────────────
    # Task lifecycle handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_task_created(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        task_id = _require(payload, "task_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        task_vid = _task_vid(tenant_id, task_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.TASK,
            vertex_id=task_vid,
            properties={
                "task_id": task_id,
                "tenant_id": tenant_id,
                "status": "created",
                "created_at": payload.get("timestamp", utc_now().isoformat()),
                **_pick(payload, "parent_task_id", "description"),
            },
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.CREATED_TASK,
            from_vertex_id=agent_vid,
            to_vertex_id=task_vid,
            properties={"tenant_id": tenant_id, "created_at": payload.get("timestamp", "")},
        ))

        # Link to parent task if provided
        parent_task_id = payload.get("parent_task_id")
        if parent_task_id:
            parent_vid = _task_vid(tenant_id, parent_task_id)
            await self._put_edge(Edge(
                edge_type=EdgeType.DECOMPOSED_INTO,
                from_vertex_id=parent_vid,
                to_vertex_id=task_vid,
                properties={"tenant_id": tenant_id},
            ))

        return {"status": "task_created", "task_vid": task_vid}

    async def _handle_task_decomposed(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        root_task_id = _require(payload, "task_id")
        subtask_ids: list[str] = payload.get("subtask_ids") or []
        root_vid = _task_vid(tenant_id, root_task_id)

        # Record task decomposition in execution repo if execution_id present
        execution_id = payload.get("execution_id")
        if execution_id:
            await self._executions.record_task_decomposition(
                execution_id=execution_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                root_task_id=root_task_id,
                subtask_ids=subtask_ids,
                metadata=payload.get("metadata"),
            )

        edges = []
        for subtask_id in subtask_ids:
            subtask_vid = _task_vid(tenant_id, subtask_id)
            await self._put_vertex(Vertex(
                vertex_type=VertexType.TASK,
                vertex_id=subtask_vid,
                properties={
                    "task_id": subtask_id,
                    "parent_task_id": root_task_id,
                    "tenant_id": tenant_id,
                },
            ))
            await self._put_edge(Edge(
                edge_type=EdgeType.DECOMPOSED_INTO,
                from_vertex_id=root_vid,
                to_vertex_id=subtask_vid,
                properties={"tenant_id": tenant_id},
            ))
            edges.append({"type": EdgeType.DECOMPOSED_INTO, "from": root_vid, "to": subtask_vid})

        return {"status": "task_decomposed", "root_task_vid": root_vid, "subtask_count": len(subtask_ids), "edges": edges}

    async def _handle_task_started(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        task_id = _require(payload, "task_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        task_vid = _task_vid(tenant_id, task_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.TASK,
            vertex_id=task_vid,
            properties={"status": "running", "started_at": payload.get("timestamp", ""), "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.STARTED_TASK,
            from_vertex_id=agent_vid,
            to_vertex_id=task_vid,
            properties={"tenant_id": tenant_id, "started_at": payload.get("timestamp", "")},
        ))
        return {"status": "task_started", "task_vid": task_vid}

    async def _handle_task_completed(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        task_id = _require(payload, "task_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        task_vid = _task_vid(tenant_id, task_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.TASK,
            vertex_id=task_vid,
            properties={"status": "completed", "completed_at": payload.get("timestamp", ""), "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.COMPLETED_TASK,
            from_vertex_id=agent_vid,
            to_vertex_id=task_vid,
            properties={"tenant_id": tenant_id, "completed_at": payload.get("timestamp", "")},
        ))
        return {"status": "task_completed", "task_vid": task_vid}

    async def _handle_task_failed(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        task_id = _require(payload, "task_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        task_vid = _task_vid(tenant_id, task_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.TASK,
            vertex_id=task_vid,
            properties={
                "status": "failed",
                "failed_at": payload.get("timestamp", ""),
                "failure_reason": payload.get("failure_reason", ""),
                "tenant_id": tenant_id,
            },
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.FAILED_TASK,
            from_vertex_id=agent_vid,
            to_vertex_id=task_vid,
            properties={
                "tenant_id": tenant_id,
                "failure_reason": payload.get("failure_reason", ""),
            },
        ))
        return {"status": "task_failed", "task_vid": task_vid}

    # ─────────────────────────────────────────────────────────────────────
    # Tool / resource handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_tool_called(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        tool_id = _require(payload, "tool_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        tool_vid = _tool_vid(tenant_id, tool_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.TOOL,
            vertex_id=tool_vid,
            properties={"tool_id": tool_id, "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.CALLED_TOOL,
            from_vertex_id=agent_vid,
            to_vertex_id=tool_vid,
            properties={
                "tenant_id": tenant_id,
                "called_at": payload.get("timestamp", ""),
                "task_id": payload.get("task_id", ""),
                "execution_id": payload.get("execution_id", ""),
            },
        ))
        return {"status": "tool_called", "tool_vid": tool_vid}

    async def _handle_resource_requested(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        resource_id = _require(payload, "resource_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        resource_vid = _resource_vid(tenant_id, resource_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.ECONOMIC_RESOURCE,
            vertex_id=resource_vid,
            properties={"resource_id": resource_id, "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.REQUESTED_RESOURCE,
            from_vertex_id=agent_vid,
            to_vertex_id=resource_vid,
            properties={
                "tenant_id": tenant_id,
                "requested_at": payload.get("timestamp", ""),
                "capability_requested": payload.get("capability_requested", ""),
            },
        ))
        return {"status": "resource_requested", "resource_vid": resource_vid}

    # ─────────────────────────────────────────────────────────────────────
    # Delegation / subagent handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_delegated_task(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        delegate_agent_id = payload.get("parent_agent_id") or payload.get("beneficiary_actor_id", "")
        agent_vid = _agent_vid(tenant_id, agent_id)
        edges = []
        if delegate_agent_id:
            delegate_vid = _agent_vid(tenant_id, delegate_agent_id)
            await self._put_edge(Edge(
                edge_type=EdgeType.DELEGATED_TO,
                from_vertex_id=agent_vid,
                to_vertex_id=delegate_vid,
                properties={
                    "delegation_id": payload.get("delegation_id", ""),
                    "task_id": payload.get("task_id", ""),
                    "tenant_id": tenant_id,
                    "delegated_at": payload.get("timestamp", ""),
                },
            ))
            edges.append({"type": EdgeType.DELEGATED_TO, "from": agent_vid, "to": delegate_vid})
        return {"status": "task_delegated", "edges": edges}

    async def _handle_subagent_spawned(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        parent_agent_id = _require(payload, "agent_id")
        child_agent_id = payload.get("parent_agent_id") or payload.get("beneficiary_actor_id", "")
        parent_vid = _agent_vid(tenant_id, parent_agent_id)
        edges = []
        if child_agent_id:
            child_vid = _agent_vid(tenant_id, child_agent_id)
            await self._put_vertex(Vertex(
                vertex_type=VertexType.AGENT,
                vertex_id=child_vid,
                properties={
                    "agent_id": child_agent_id,
                    "parent_agent_id": parent_agent_id,
                    "tenant_id": tenant_id,
                    "spawned_at": payload.get("timestamp", ""),
                },
            ))
            await self._put_edge(Edge(
                edge_type=EdgeType.SPAWNED_SUBAGENT,
                from_vertex_id=parent_vid,
                to_vertex_id=child_vid,
                properties={"tenant_id": tenant_id, "spawned_at": payload.get("timestamp", "")},
            ))
            edges.append({"type": EdgeType.SPAWNED_SUBAGENT, "from": parent_vid, "to": child_vid})

            # Persist a delegation record so Profile360 and active_for() can
            # discover the relationship without querying graph edges directly.
            delegation_id = payload.get("delegation_id") or f"{tenant_id}:{parent_agent_id}:spawned:{child_agent_id}"
            existing = await self._delegations.find_by_id(delegation_id)
            if existing is None:
                await self._delegations.grant(
                    delegation_id=delegation_id,
                    tenant_id=tenant_id,
                    grantor_entity_id=parent_agent_id,
                    grantee_entity_id=child_agent_id,
                    scope={"type": "subagent", "task_id": payload.get("task_id", "")},
                    starts_at=payload.get("timestamp"),
                    metadata={"source": "agent_subagent_spawned"},
                )

        return {"status": "subagent_spawned", "edges": edges}

    # ─────────────────────────────────────────────────────────────────────
    # Policy / outcome handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_policy_evaluated(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        policy_id = _require(payload, "policy_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        policy_vid = _policy_vid(tenant_id, policy_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.POLICY,
            vertex_id=policy_vid,
            properties={"policy_id": policy_id, "tenant_id": tenant_id},
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.EVALUATED_BY_POLICY,
            from_vertex_id=agent_vid,
            to_vertex_id=policy_vid,
            properties={
                "decision": payload.get("decision", ""),
                "task_id": payload.get("task_id", ""),
                "tenant_id": tenant_id,
                "evaluated_at": payload.get("timestamp", ""),
            },
        ))
        return {"status": "policy_evaluated", "policy_vid": policy_vid}

    async def _handle_handoff(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        target_agent_id = payload.get("beneficiary_actor_id") or payload.get("parent_agent_id", "")
        agent_vid = _agent_vid(tenant_id, agent_id)
        edges = []
        if target_agent_id:
            target_vid = _agent_vid(tenant_id, target_agent_id)
            await self._put_edge(Edge(
                edge_type=EdgeType.HANDED_OFF_TO,
                from_vertex_id=agent_vid,
                to_vertex_id=target_vid,
                properties={
                    "task_id": payload.get("task_id", ""),
                    "tenant_id": tenant_id,
                    "handed_off_at": payload.get("timestamp", ""),
                },
            ))
            edges.append({"type": EdgeType.HANDED_OFF_TO, "from": agent_vid, "to": target_vid})
        return {"status": "handoff", "edges": edges}

    async def _handle_escalated_to_human(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        human_user_id = payload.get("owner_user_id") or payload.get("beneficiary_actor_id", "")
        agent_vid = _agent_vid(tenant_id, agent_id)
        edges = []
        if human_user_id:
            human_vid = _user_vid(tenant_id, human_user_id)
            await self._put_edge(Edge(
                edge_type=EdgeType.ESCALATED_TO_HUMAN,
                from_vertex_id=agent_vid,
                to_vertex_id=human_vid,
                properties={
                    "task_id": payload.get("task_id", ""),
                    "reason": payload.get("failure_reason", ""),
                    "tenant_id": tenant_id,
                    "escalated_at": payload.get("timestamp", ""),
                },
            ))
            edges.append({"type": EdgeType.ESCALATED_TO_HUMAN, "from": agent_vid, "to": human_vid})
        return {"status": "escalated_to_human", "edges": edges}

    async def _handle_outcome_recorded(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        agent_id = _require(payload, "agent_id")
        outcome_id = _require(payload, "outcome_id")
        agent_vid = _agent_vid(tenant_id, agent_id)
        outcome_vid = _outcome_vid(tenant_id, outcome_id)

        await self._put_vertex(Vertex(
            vertex_type=VertexType.OUTCOME,
            vertex_id=outcome_vid,
            properties={
                "outcome_id": outcome_id,
                "tenant_id": tenant_id,
                "status": payload.get("status", ""),
                "recorded_at": payload.get("timestamp", utc_now().isoformat()),
            },
        ))
        await self._put_edge(Edge(
            edge_type=EdgeType.RESULTED_IN_OUTCOME,
            from_vertex_id=agent_vid,
            to_vertex_id=outcome_vid,
            properties={
                "task_id": payload.get("task_id", ""),
                "tenant_id": tenant_id,
            },
        ))
        return {"status": "outcome_recorded", "outcome_vid": outcome_vid}

    # ─────────────────────────────────────────────────────────────────────
    # Legacy alias handlers
    # ─────────────────────────────────────────────────────────────────────

    async def _handle_legacy_agent_task(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Normalize legacy agent_task → task_created / task_completed / task_failed."""
        status = payload.get("status", "created")
        if status in ("completed", "success"):
            result = await self._handle_task_completed(payload, tenant_id)
        elif status in ("failed", "error"):
            result = await self._handle_task_failed(payload, tenant_id)
        else:
            result = await self._handle_task_created(payload, tenant_id)
        result["normalized_from"] = "agent_task"
        return result

    async def _handle_legacy_agent_decision(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Normalize legacy agent_decision → agent_policy_evaluated."""
        normalized = dict(payload)
        normalized.setdefault("policy_id", payload.get("decision_id", payload.get("agent_id", "") + ":policy"))
        normalized.setdefault("decision", payload.get("outcome", ""))
        result = await self._handle_policy_evaluated(normalized, tenant_id)
        result["normalized_from"] = "agent_decision"
        return result

    async def _handle_legacy_a2h_interaction(
        self, payload: dict[str, Any], tenant_id: str
    ) -> dict[str, Any]:
        """Normalize legacy a2h_interaction → escalated_to_human or handoff."""
        interaction_type = payload.get("interaction_type", "escalation")
        if interaction_type == "handoff":
            result = await self._handle_handoff(payload, tenant_id)
        else:
            result = await self._handle_escalated_to_human(payload, tenant_id)
        result["normalized_from"] = "a2h_interaction"
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _require(payload: dict[str, Any], key: str) -> str:
    """Extract a required field from payload; raise ValueError if missing."""
    value = payload.get(key)
    if not value:
        raise ValueError(f"Missing required field in agent lifecycle payload: {key!r}")
    return str(value)


def _pick(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Extract a subset of keys from payload, skipping missing ones."""
    return {k: str(payload[k]) for k in keys if payload.get(k) is not None}
