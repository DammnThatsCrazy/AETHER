"""Graph-native natural-language intelligence orchestration for Noesis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from shared.auth.auth import Role, TenantContext
from shared.common.common import BadRequestError, ForbiddenError
from shared.graph.graph import GraphClient, Vertex
from shared.logger.logger import get_logger, metrics
from repositories.repos import (
    BaseRepository,
    AdminRepository,
    AgentConfigRepository,
    AgentExecutionRepository,
    AlertRepository,
    AnalyticsRepository,
    CampaignRepository,
    EntityRepository,
    ProvidersRepository,
)

from .conversations import NoesisConversationStore
from .models import NoesisAction, NoesisGraph, NoesisQueryRequest, NoesisResponse, QueryPlan
from .provider import EnvironmentNoesisPlanProvider, NoesisPlanProvider

logger = get_logger("aether.service.noesis")

_ID_RE = re.compile(r"(?:wallet|agent|tenant|profile|user|entity|cluster|alert)\s+([A-Za-z0-9_.:\-]{3,})", re.I)
_WALLET_RE = re.compile(r"\b(0x[a-fA-F0-9]{8,}|[1-9A-HJ-NP-Za-km-z]{32,44})\b")
@dataclass(frozen=True)
class Scope:
    surface: str
    effective_tenant_id: str
    cross_tenant: bool
    debug_allowed: bool


class NoesisService:
    def __init__(
        self,
        graph: GraphClient,
        analytics: AnalyticsRepository,
        provider: Optional[NoesisPlanProvider] = None,
        conversation_store: Optional[NoesisConversationStore] = None,
    ) -> None:
        self.graph = graph
        self.analytics = analytics
        self.provider = provider or EnvironmentNoesisPlanProvider()
        self.entities = EntityRepository()
        self.alerts = AlertRepository()
        self.tenants = AdminRepository()
        self.campaigns = CampaignRepository()
        self.rewards = BaseRepository("rewards")
        self.agents = AgentConfigRepository()
        self.agent_executions = AgentExecutionRepository()
        self.providers = ProvidersRepository()
        self.conversations = conversation_store or NoesisConversationStore()

    async def query(self, body: NoesisQueryRequest, tenant: TenantContext) -> NoesisResponse:
        scope = self._resolve_scope(body, tenant)
        plan = self._classify(body, scope)
        mode = "deterministic"
        warnings: list[str] = []

        if plan.intent == "unsupported":
            llm_plan = await self.provider.plan(body, scope.effective_tenant_id)
            if llm_plan is not None:
                plan = self._validate_plan(llm_plan, scope)
                mode = "llm_text_to_query"
            else:
                response = self._unsupported_response(body, warnings)
                conversation_id = await self.conversations.record_turn(body, response, scope.effective_tenant_id)
                response.conversation_id = conversation_id
                return response

        response = await self._dispatch(plan, scope, body)
        response.mode = mode  # type: ignore[assignment]
        response.warnings.extend(warnings)
        conversation_id = await self.conversations.record_turn(body, response, scope.effective_tenant_id)
        response.conversation_id = conversation_id
        if not scope.debug_allowed:
            response.query_debug = None
        metrics.increment("noesis_query", labels={"surface": body.surface, "intent": response.intent, "mode": response.mode})
        logger.info(
            "Noesis query routed",
            extra={"surface": body.surface, "intent": response.intent, "mode": response.mode, "tenant_id": scope.effective_tenant_id, "cross_tenant": scope.cross_tenant},
        )
        return response

    def _resolve_scope(self, body: NoesisQueryRequest, tenant: TenantContext) -> Scope:
        tenant.require_permission("read")
        requested = (body.tenant_id or "").strip()
        is_operator = tenant.role == Role.ADMIN or tenant.has_permission("admin") or tenant.has_permission("kyber:read")
        if body.surface == "aether":
            if requested and requested != tenant.tenant_id:
                raise ForbiddenError("Aether Noesis cannot query another tenant")
            return Scope(body.surface, tenant.tenant_id, False, False)
        if body.surface == "kyber":
            if requested and requested != tenant.tenant_id and not is_operator:
                raise ForbiddenError("Kyber cross-tenant Noesis requires operator permission")
            if not requested and not is_operator:
                return Scope(body.surface, tenant.tenant_id, False, False)
            wants_all_tenants = not requested and any(token in body.message.lower() for token in ("all tenants", "across tenants", "across all tenants"))
            return Scope(body.surface, requested or ("" if wants_all_tenants else tenant.tenant_id), wants_all_tenants or bool(requested and requested != tenant.tenant_id), is_operator)
        raise BadRequestError("Unsupported Noesis surface")

    def _classify(self, body: NoesisQueryRequest, scope: Scope) -> QueryPlan:
        text = body.message.strip()
        low = text.lower()
        target = self._extract_target(text) or body.context.selected_entity_id
        time_range = body.context.time_range or self._extract_time_range(low)
        limit = 10
        if "all" in low and len(low) < 80:
            limit = 25
        if any(k in low for k in ("sdk", "telemetry", "health", "drift", "failing", "unhealthy")):
            return QueryPlan(intent="health_lookup", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.82, limit=limit)
        if any(k in low for k in ("alert", "unresolved", "incident")):
            return QueryPlan(intent="alert_lookup", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.86, limit=limit)
        if any(k in low for k in ("tenant", "customers")) and any(k in low for k in ("summary", "status", "lookup", "show")):
            return QueryPlan(intent="tenant_summary", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.8, limit=limit)
        if any(k in low for k in ("connected", "neighbors", "graph", "what is connected", "traversal")):
            return QueryPlan(intent="graph_lookup", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.84, limit=limit)
        if any(k in low for k in ("campaign", "reward", "spending", "valuable")):
            return QueryPlan(intent="campaign_reward_lookup", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.78, limit=limit)
        if any(k in low for k in ("risk", "cluster", "abnormal", "fraud")):
            return QueryPlan(intent="risk_cluster_lookup", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.76, limit=limit)
        if "wallet" in low or _WALLET_RE.search(text):
            return QueryPlan(intent="wallet_lookup", target=target or self._extract_wallet(text), entity_type="wallet", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.84, limit=limit)
        if "agent" in low:
            return QueryPlan(intent="agent_lookup", target=target, entity_type="agent", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.8, limit=limit)
        if any(k in low for k in ("profile", "user", "identity")):
            return QueryPlan(intent="profile_lookup", target=target, entity_type="human", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.78, limit=limit)
        if any(k in low for k in ("find", "search", "show me", "take me")):
            return QueryPlan(intent="entity_search", target=target or self._search_terms(text), tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.64, limit=limit)
        return QueryPlan(intent="unsupported", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.2)

    def _validate_plan(self, plan: QueryPlan, scope: Scope) -> QueryPlan:
        if plan.intent == "unsupported":
            raise BadRequestError("LLM plan did not map to a supported Noesis intent")
        if plan.tenant_id and plan.tenant_id != scope.effective_tenant_id:
            raise ForbiddenError("Generated Noesis plan attempted to change tenant scope")
        plan.tenant_id = scope.effective_tenant_id
        plan.limit = min(max(plan.limit, 1), 50)
        plan.source = "llm"
        return plan

    async def _dispatch(self, plan: QueryPlan, scope: Scope, body: NoesisQueryRequest) -> NoesisResponse:
        if plan.intent == "entity_search":
            return await self._entity_search(plan, scope)
        if plan.intent == "graph_lookup":
            return await self._graph_lookup(plan, scope)
        if plan.intent == "alert_lookup":
            return await self._alert_lookup(plan, scope)
        if plan.intent == "tenant_summary":
            return await self._tenant_summary(plan, scope)
        if plan.intent in ("profile_lookup", "wallet_lookup", "agent_lookup"):
            return await self._typed_lookup(plan, scope)
        if plan.intent == "health_lookup":
            return await self._health_lookup(plan, scope)
        if plan.intent == "campaign_reward_lookup":
            return await self._campaign_reward_lookup(plan, scope)
        if plan.intent == "risk_cluster_lookup":
            return await self._risk_cluster_lookup(plan, scope)
        return self._unsupported_response(body, [])

    def _tenant_filter(self, scope: Scope) -> Optional[dict[str, Any]]:
        if scope.cross_tenant and not scope.effective_tenant_id:
            return None
        return {"tenant_id": scope.effective_tenant_id}

    async def _entity_search(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        rows = await self.entities.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
        needle = (plan.target or "").lower()
        if needle:
            rows = [r for r in rows if needle in str(r.get("entity_id", r.get("id", ""))).lower() or needle in str(r.get("display_name", "")).lower() or needle in str(r.get("entity_type", "")).lower()]
        return self._response(plan, f"Found {len(rows)} tenant-scoped entities matching your request.", rows, self._entity_actions(rows, scope))

    async def _graph_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        if not plan.target:
            return self._ambiguous(plan, "Which graph node or entity should I inspect?")
        vertex = await self.graph.get_vertex(plan.target)
        if vertex and vertex.properties.get("tenant_id") not in (scope.effective_tenant_id, None, ""):
            vertex = None
        neighbors = await self.graph.get_neighbors(plan.target, direction="both") if vertex else []
        safe_neighbors = [v for v in neighbors if v.properties.get("tenant_id") in (scope.effective_tenant_id, None, "")]
        edges = await self.graph.get_edges(plan.target, direction="both") if vertex else []
        nodes = [self._vertex_to_node(v) for v in ([vertex] if vertex else []) + safe_neighbors]
        graph_edges = [self._edge_to_dict(e) for e in edges if e.properties.get("tenant_id") in (scope.effective_tenant_id, None, "")]
        actions = [NoesisAction(type="highlight_graph", label="Highlight graph neighborhood", node_ids=[n["id"] for n in nodes], edge_ids=[e["id"] for e in graph_edges])]
        if vertex:
            actions.append(NoesisAction(type="open_inspector", label="Open inspector", entity_id=vertex.vertex_id, entity_type=str(vertex.vertex_type)))
            graph_href = f"/noesis/graph?focus={vertex.vertex_id}" if scope.surface == "kyber" else f"/graph?entity={vertex.vertex_id}"
            actions.append(NoesisAction(type="navigate", label="Open graph workspace", href=graph_href))
        answer = f"{plan.target} has {len(safe_neighbors)} visible neighboring nodes in this tenant scope."
        return self._response(plan, answer, nodes, actions, NoesisGraph(nodes=nodes, edges=graph_edges, highlights=[plan.target]))

    async def _alert_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        rows = await self.alerts.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
        unresolved = [r for r in rows if str(r.get("status", "open")).lower() not in ("resolved", "closed")]
        actions = [NoesisAction(type="navigate", label="Open alerts", href="/review")]
        return self._response(plan, f"Found {len(unresolved)} unresolved alert records in scope.", unresolved, actions)

    async def _tenant_summary(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        if scope.surface != "kyber":
            raise ForbiddenError("Tenant summaries are Kyber-only")
        tenant = await self.tenants.find_by_id(scope.effective_tenant_id) if scope.effective_tenant_id else None
        summary = await self.analytics.dashboard_summary(scope.effective_tenant_id) if scope.effective_tenant_id else {"period": "all", "total_events": 0, "total_sessions": 0}
        alerts = await self.alerts.count(filters=self._tenant_filter(scope))
        entities = await self.entities.count(filters=self._tenant_filter(scope))
        result = {"tenant": tenant or {"tenant_id": scope.effective_tenant_id or "all-authorized-tenants"}, "analytics": summary, "alerts": alerts, "entities": entities}
        label = scope.effective_tenant_id or "authorized tenants"
        href = f"/tenants/{scope.effective_tenant_id}" if scope.effective_tenant_id else "/tenants"
        return self._response(plan, f"Tenant scope {label} has {entities} entities, {alerts} alert records, and {summary.get('total_events', 0)} tracked events.", [result], [NoesisAction(type="navigate", label="Open tenants", href=href)])

    async def _typed_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        filters: dict[str, Any] = self._tenant_filter(scope) or {}
        if plan.entity_type and plan.intent != "wallet_lookup":
            filters["entity_type"] = plan.entity_type
        rows = await self.entities.find_many(filters=filters, limit=plan.limit)
        if plan.intent == "agent_lookup":
            agent_rows = await self.agents.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
            rows.extend(agent_rows)
        needle = (plan.target or "").lower()
        if needle:
            rows = [r for r in rows if needle in str(r).lower()]
        kind = plan.intent.replace("_lookup", "")
        return self._response(plan, f"Found {len(rows)} {kind} records in the authorized tenant scope.", rows, self._entity_actions(rows, scope))

    async def _health_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        provider_rows = await self.providers.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
        failed_agents = (await self.agent_executions.find_many(filters={"status": "failed"}, limit=plan.limit)) if scope.cross_tenant and not scope.effective_tenant_id else await self.agent_executions.list_failed(scope.effective_tenant_id, limit=plan.limit)
        summary = await self.analytics.dashboard_summary(scope.effective_tenant_id)
        result = {"sdk_or_provider_records": provider_rows, "failed_agent_executions": failed_agents, "analytics_summary": summary}
        return self._response(plan, f"Health summary: {len(provider_rows)} provider/SDK records, {len(failed_agents)} failed agent executions, and {summary.get('total_events', 0)} events in the dashboard summary.", [result], [NoesisAction(type="navigate", label="Open diagnostics", href="/diagnostics"), NoesisAction(type="navigate", label="Open system status", href="/system-status")])

    async def _campaign_reward_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        campaigns = await self.campaigns.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
        rewards = await self.rewards.find_many(filters=self._tenant_filter(scope), limit=plan.limit)
        rows = [{"type": "campaign", **r} for r in campaigns] + [{"type": "reward", **r} for r in rewards]
        return self._response(plan, f"Found {len(campaigns)} campaigns and {len(rewards)} rewards in scope.", rows, [NoesisAction(type="navigate", label="Open campaigns", href="/campaigns")])

    async def _risk_cluster_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        rows = await self.entities.find_many(filters=self._tenant_filter(scope), limit=50)
        risky = sorted(rows, key=lambda r: float(r.get("risk_score") or r.get("metadata", {}).get("risk_score") or 0), reverse=True)[: plan.limit]
        return self._response(plan, f"Found {len(risky)} tenant-scoped entities sorted by available risk score.", risky, self._entity_actions(risky, scope))

    def _response(self, plan: QueryPlan, answer: str, results: list[dict[str, Any]], actions: list[NoesisAction], graph: Optional[NoesisGraph] = None) -> NoesisResponse:
        entities = [self._redact(r) for r in results if isinstance(r, dict)]
        return NoesisResponse(
            answer=answer,
            mode="deterministic",
            intent=plan.intent,
            confidence=plan.confidence,
            entities=entities[:10],
            results=[self._redact(r) for r in results],
            graph=graph or NoesisGraph(),
            actions=actions,
            query_debug={"plan": plan.model_dump(), "read_only": True, "validated": True},
        )

    def _unsupported_response(self, body: NoesisQueryRequest, warnings: list[str]) -> NoesisResponse:
        return NoesisResponse(
            answer="I can answer graph, entity, alert, tenant, health, campaign, reward, wallet, profile, and agent lookup questions. Please narrow the request or include a specific entity.",
            mode="fallback",
            intent="unsupported",
            confidence=0.2,
            actions=[NoesisAction(type="refine_query", prompt="Ask about a tenant-scoped graph entity, alert, wallet, campaign, reward, SDK health, or agent.")],
            warnings=warnings,
            error={"code": "unsupported_intent", "message": "Noesis could not safely map this request to a read-only graph query.", "details": {"surface": body.surface}},
        )

    def _ambiguous(self, plan: QueryPlan, prompt: str) -> NoesisResponse:
        return NoesisResponse(answer=prompt, mode="fallback", intent=plan.intent, confidence=0.4, actions=[NoesisAction(type="refine_query", prompt=prompt)], query_debug={"plan": plan.model_dump(), "validated": True})

    def _entity_actions(self, rows: Iterable[dict[str, Any]], scope: Scope) -> list[NoesisAction]:
        actions: list[NoesisAction] = []
        for row in list(rows)[:3]:
            entity_id = str(row.get("entity_id") or row.get("agent_id") or row.get("user_id") or row.get("id") or "")
            entity_type = str(row.get("entity_type") or row.get("type") or "entity")
            if entity_id:
                href = f"/profile360/{entity_type}/{entity_id}" if scope.surface == "kyber" else f"/graph?entity={entity_id}"
                actions.append(NoesisAction(type="navigate", label=f"Open {entity_type} {entity_id}", href=href, entity_id=entity_id, entity_type=entity_type))
                actions.append(NoesisAction(type="open_inspector", label="Open inspector", entity_id=entity_id, entity_type=entity_type))
        return actions

    def _vertex_to_node(self, vertex: Vertex) -> dict[str, Any]:
        return {"id": vertex.vertex_id, "type": str(vertex.vertex_type), "label": vertex.properties.get("display_name") or vertex.vertex_id, "properties": self._redact(vertex.properties)}

    def _edge_to_dict(self, edge: Any) -> dict[str, Any]:
        edge_id = f"{edge.from_vertex_id}:{edge.edge_type}:{edge.to_vertex_id}"
        return {"id": edge_id, "source": edge.from_vertex_id, "target": edge.to_vertex_id, "type": edge.edge_type, "properties": self._redact(edge.properties)}

    def _redact(self, row: dict[str, Any]) -> dict[str, Any]:
        blocked = {"key_hash", "api_key", "secret", "token", "password"}
        return {k: ("[redacted]" if k.lower() in blocked else v) for k, v in row.items()}

    def _search_terms(self, text: str) -> str:
        return re.sub(r"^(find|search|show me|take me to)\s+", "", text.strip(), flags=re.I)

    def _extract_target(self, text: str) -> Optional[str]:
        match = _ID_RE.search(text)
        return match.group(1).strip("?.!,") if match else None

    def _extract_wallet(self, text: str) -> Optional[str]:
        match = _WALLET_RE.search(text)
        return match.group(1) if match else None

    def _extract_time_range(self, low: str) -> Optional[str]:
        for token in ("24 hours", "24h", "7 days", "7d", "week", "30 days", "30d"):
            if token in low:
                return {"24 hours": "24h", "7 days": "7d", "week": "7d", "30 days": "30d"}.get(token, token)
        return None
