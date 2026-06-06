"""Graph-native natural-language intelligence orchestration for Noesis."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from shared.auth.auth import Role, TenantContext
from shared.common.common import BadRequestError, ForbiddenError, RateLimitedError, ServiceUnavailableError
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
    WalletRepository,
)

from .conversation import NoesisConversationStore
from .flags import NoesisFlags
from .models import (
    INJECTION_PATTERNS,
    MAX_LIMIT,
    SUPPORTED_FILTERS,
    SUPPORTED_INTENTS,
    WRITE_LIKE_KEYWORDS,
    NoesisAction,
    NoesisAuditEntry,
    NoesisGraph,
    NoesisQueryRequest,
    NoesisResponse,
    QueryPlan,
)
from .provider import NoesisPlanProvider, ProductionNoesisPlanProvider
from .rate_limiter import NoesisRateLimiter, RateLimitState

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
        rate_limiter: Optional[NoesisRateLimiter] = None,
        conversation_store: Optional[NoesisConversationStore] = None,
        flags: Optional[NoesisFlags] = None,
    ) -> None:
        self.graph = graph
        self.analytics = analytics
        self.provider = provider or ProductionNoesisPlanProvider()
        self.rate_limiter = rate_limiter or NoesisRateLimiter()
        self.conversation_store = conversation_store or NoesisConversationStore()
        self.flags = flags or NoesisFlags()
        self._rate_limit_state: RateLimitState | None = None
        self.entities = EntityRepository()
        self.alerts = AlertRepository()
        self.tenants = AdminRepository()
        self.campaigns = CampaignRepository()
        self.rewards = BaseRepository("rewards")
        self.agents = AgentConfigRepository()
        self.agent_executions = AgentExecutionRepository()
        self.providers = ProvidersRepository()
        self.wallets = WalletRepository()

    async def query(self, body: NoesisQueryRequest, tenant: TenantContext, *, request_id: str | None = None) -> NoesisResponse:
        request_id = request_id or str(uuid.uuid4())

        # Master kill-switch
        if not self.flags.noesis_enabled:
            raise ServiceUnavailableError("Noesis")

        # Canary gating — block before scope resolution to avoid leaking tenant state
        if not self.flags.is_tenant_allowed(tenant.tenant_id):
            logger.info("Noesis canary gate blocked", extra={"tenant_id": tenant.tenant_id})
            metrics.increment("noesis_canary_blocked")
            raise ForbiddenError("Noesis is not yet available for this tenant")

        scope = self._resolve_scope(body, tenant)

        # Safety: reject write-like and injection prompts
        safety_response = self._check_safety(body, scope, request_id)
        if safety_response is not None:
            return safety_response

        # Real rate limiting — increments counters, raises RateLimitedError if exceeded
        await self._check_rate_limit(scope)

        # Conversation history for multi-turn continuity
        history: list[dict] = []
        if body.conversation_id:
            history = await self.conversation_store.get_recent(
                body.conversation_id, scope.effective_tenant_id
            )

        plan = self._classify(body, scope, history)
        mode = "deterministic"
        warnings: list[str] = []
        fallback_triggered = False
        provider_used: str | None = None

        if plan.intent == "unsupported":
            llm_plan = await self.provider.plan(body, scope.effective_tenant_id, history or None)
            provider_used = getattr(self.provider, "provider_name", None) or type(self.provider).__name__
            if llm_plan is not None:
                plan = self._validate_plan(llm_plan, scope)
                mode = "llm_text_to_query"
            else:
                fallback_triggered = True
                resp = self._unsupported_response(body, warnings)
                self._audit_log(NoesisAuditEntry(
                    request_id=request_id, tenant_id=tenant.tenant_id,
                    effective_tenant_id=scope.effective_tenant_id,
                    requested_tenant_id=body.tenant_id,
                    surface=body.surface, role=tenant.role.value if hasattr(tenant.role, "value") else str(tenant.role),
                    permissions=list(tenant.permissions), intent="unsupported", mode="fallback",
                    result_count=0, debug_returned=False, fallback_triggered=True,
                    provider_used=provider_used,
                ))
                return resp

        # Read-only guard before dispatch
        self._assert_read_only(plan)

        response = await self._dispatch(plan, scope, body)
        response.mode = mode  # type: ignore[assignment]
        response.warnings.extend(warnings)
        if not scope.debug_allowed:
            response.query_debug = None
        metrics.increment("noesis_query", labels={"surface": body.surface, "intent": response.intent, "mode": response.mode})
        logger.info(
            "Noesis query routed",
            extra={"surface": body.surface, "intent": response.intent, "mode": response.mode, "tenant_id": scope.effective_tenant_id, "cross_tenant": scope.cross_tenant},
        )
        self._audit_log(NoesisAuditEntry(
            request_id=request_id, tenant_id=tenant.tenant_id,
            effective_tenant_id=scope.effective_tenant_id,
            requested_tenant_id=body.tenant_id,
            surface=body.surface, role=tenant.role.value if hasattr(tenant.role, "value") else str(tenant.role),
            permissions=list(tenant.permissions), intent=response.intent, mode=response.mode,
            result_count=len(response.results), debug_returned=response.query_debug is not None,
            fallback_triggered=fallback_triggered, provider_used=provider_used,
        ))

        # Persist the turn to conversation store for multi-turn continuity
        if body.conversation_id and response.intent not in ("rejected", "unsupported"):
            await self.conversation_store.append(
                body.conversation_id,
                scope.effective_tenant_id,
                body.message,
                response.intent,
                response.mode,
                response.answer,
            )

        return response

    async def query_stream(
        self,
        body: NoesisQueryRequest,
        tenant: TenantContext,
        *,
        request_id: str | None = None,
    ):
        """Async generator that yields SSE event dicts as query phases complete.

        Phases:
          1. {"type": "intent", "intent": "...", "confidence": 0.xx}  — after classification
          2. {"type": "results", "count": N}                           — after data fetch
          3. {"type": "complete", ...full NoesisResponse fields...}    — final answer
          4. {"type": "error", "error": "...", "code": "..."}          — on any error
        """
        import json as _json

        request_id = request_id or str(uuid.uuid4())

        def _sse(data: dict) -> str:
            return f"data: {_json.dumps(data)}\n\n"

        try:
            # Kill-switch + canary gate
            if not self.flags.noesis_enabled:
                yield _sse({"type": "error", "error": "Noesis unavailable", "code": "service_unavailable"})
                return
            if not self.flags.is_tenant_allowed(tenant.tenant_id):
                yield _sse({"type": "error", "error": "Noesis not yet available for this tenant", "code": "forbidden"})
                return

            scope = self._resolve_scope(body, tenant)

            safety_response = self._check_safety(body, scope, request_id)
            if safety_response is not None:
                yield _sse({"type": "complete", **safety_response.model_dump(exclude_none=True)})
                return

            await self._check_rate_limit(scope)

            history: list[dict] = []
            if body.conversation_id:
                history = await self.conversation_store.get_recent(
                    body.conversation_id, scope.effective_tenant_id
                )

            plan = self._classify(body, scope, history)
            mode = "deterministic"

            yield _sse({"type": "intent", "intent": plan.intent, "confidence": plan.confidence})

            if plan.intent == "unsupported":
                llm_plan = await self.provider.plan(body, scope.effective_tenant_id, history or None)
                if llm_plan is not None:
                    plan = self._validate_plan(llm_plan, scope)
                    mode = "llm_text_to_query"
                else:
                    resp = self._unsupported_response(body, [])
                    yield _sse({"type": "complete", **resp.model_dump(exclude_none=True)})
                    return

            self._assert_read_only(plan)

            response = await self._dispatch(plan, scope, body)
            response.mode = mode  # type: ignore[assignment]
            if not scope.debug_allowed:
                response.query_debug = None

            yield _sse({"type": "results", "count": len(response.results)})

            if body.conversation_id and response.intent not in ("rejected", "unsupported"):
                await self.conversation_store.append(
                    body.conversation_id,
                    scope.effective_tenant_id,
                    body.message,
                    response.intent,
                    response.mode,
                    response.answer,
                )

            yield _sse({"type": "complete", **response.model_dump(exclude_none=True)})

        except (ForbiddenError, BadRequestError, RateLimitedError, ServiceUnavailableError) as exc:
            yield _sse({"type": "error", "error": str(exc), "code": type(exc).__name__.lower().replace("error", "")})
        except Exception as exc:
            logger.error("Noesis stream unexpected error", extra={"request_id": request_id, "error": str(exc)})
            yield _sse({"type": "error", "error": "Internal Noesis error", "code": "internal_error"})

    # ─── Safety & guards ──────────────────────────────────────────────────

    def _check_safety(self, body: NoesisQueryRequest, scope: Scope, request_id: str) -> NoesisResponse | None:
        """Reject write-like and injection prompts. Returns a safe response or None."""
        low = body.message.lower()

        # Injection pattern check
        for pattern in INJECTION_PATTERNS:
            if pattern in low:
                logger.warning("Noesis injection pattern detected", extra={"pattern": pattern, "request_id": request_id})
                metrics.increment("noesis_safety_reject", labels={"reason": "injection"})
                return NoesisResponse(
                    answer="I can only answer read-only intelligence questions. This request was not processed.",
                    mode="fallback", intent="rejected", confidence=1.0,
                    error={"code": "safety_rejection", "message": "Prompt matched an injection pattern.", "details": {}},
                )

        # Write-like keyword check — only flag if the keyword is the main verb
        # "show deleted alerts" is fine; "delete this user" is not
        sentences = re.split(r"[.!?\n]+", low)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            words = sentence.split()
            if not words:
                continue
            # Check first word or second word (after "please", "can you", etc.)
            lead_words = words[:3]
            for word in lead_words:
                if word in WRITE_LIKE_KEYWORDS:
                    # Allow passive/adjective usage like "show deleted", "find removed"
                    if len(words) > 1 and words[0] in ("show", "find", "list", "get", "display", "search", "what", "which", "how"):
                        break
                    logger.warning("Noesis write-like prompt rejected", extra={"keyword": word, "request_id": request_id})
                    metrics.increment("noesis_safety_reject", labels={"reason": "write_keyword"})
                    return NoesisResponse(
                        answer="Noesis is a read-only intelligence layer. Write, mutation, and administrative operations are not supported.",
                        mode="fallback", intent="rejected", confidence=1.0,
                        error={"code": "safety_rejection", "message": "Prompt contains a write-like instruction.", "details": {}},
                    )
        return None

    async def _check_rate_limit(self, scope: Scope) -> None:
        """Enforce per-tenant QPM and daily quota via NoesisRateLimiter."""
        self._rate_limit_state = await self.rate_limiter.check_and_increment(scope.effective_tenant_id)

    def _assert_read_only(self, plan: QueryPlan) -> None:
        """Verify plan is for a supported read-only intent."""
        if plan.intent not in SUPPORTED_INTENTS:
            raise BadRequestError(f"Noesis does not support intent '{plan.intent}'")
        # Check for mutation keywords in filter values
        for v in plan.filters.values():
            if isinstance(v, str) and any(kw in v.lower() for kw in WRITE_LIKE_KEYWORDS):
                raise BadRequestError("Noesis plan contains mutation-like filter values")

    def _audit_log(self, entry: NoesisAuditEntry) -> None:
        """Structured audit log for every Noesis query."""
        from shared.common.common import utc_now
        entry.timestamp = entry.timestamp or utc_now()
        logger.info("Noesis audit", extra=entry.model_dump())
        metrics.increment("noesis_audit", labels={"intent": entry.intent, "mode": entry.mode, "surface": entry.surface})
        if entry.rejected:
            metrics.increment("noesis_rejected", labels={"reason": entry.rejection_reason or "unknown"})

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
            low_msg = body.message.lower()
            wants_all_tenants = not requested and any(token in low_msg for token in ("all tenants", "across tenants", "across all tenants", "tenants with", "show tenants", "list tenants"))
            return Scope(body.surface, requested or ("" if wants_all_tenants else tenant.tenant_id), wants_all_tenants or bool(requested and requested != tenant.tenant_id), is_operator)
        raise BadRequestError("Unsupported Noesis surface")

    def _classify(
        self,
        body: NoesisQueryRequest,
        scope: Scope,
        history: list[dict] | None = None,
    ) -> QueryPlan:
        text = body.message.strip()
        low = text.lower()
        target = self._extract_target(text) or body.context.selected_entity_id
        time_range = body.context.time_range or self._extract_time_range(low)
        limit = 10
        if "all" in low and len(low) < 80:
            limit = 25

        # Prior intent from conversation history — used to carry forward when ambiguous
        prior_intent: str | None = None
        if history:
            last = history[-1]
            if last.get("intent") in SUPPORTED_INTENTS:
                prior_intent = last["intent"]

        # Collect candidate intents for ambiguity detection
        candidates: list[tuple[str, float]] = []

        if any(k in low for k in ("sdk", "telemetry", "health", "drift", "failing", "unhealthy", "diagnostics", "provider status", "system status", "uptime")):
            candidates.append(("health_lookup", 0.82))
        if any(k in low for k in ("alert", "unresolved", "incident", "open issues", "warnings", "critical")):
            candidates.append(("alert_lookup", 0.86))
        if any(k in low for k in ("tenant", "customers")) and any(k in low for k in ("summary", "status", "lookup", "show", "overview", "report")):
            candidates.append(("tenant_summary", 0.8))
        if any(k in low for k in ("connected", "neighbors", "graph", "what is connected", "traversal", "linked", "relationships", "edges", "adjacent")):
            candidates.append(("graph_lookup", 0.84))
        if any(k in low for k in ("campaign", "reward", "spending", "valuable", "loyalty", "incentive")):
            candidates.append(("campaign_reward_lookup", 0.78))
        if any(k in low for k in ("risk", "cluster", "abnormal", "fraud", "risky", "suspicious", "anomaly", "anomalies")):
            candidates.append(("risk_cluster_lookup", 0.76))
        if "wallet" in low or _WALLET_RE.search(text):
            candidates.append(("wallet_lookup", 0.84))
        if "agent" in low:
            candidates.append(("agent_lookup", 0.8))
        if any(k in low for k in ("profile", "user", "identity", "person", "member", "customer")):
            candidates.append(("profile_lookup", 0.78))
        if any(k in low for k in ("find", "search", "show me", "take me", "list", "display", "look up")):
            candidates.append(("entity_search", 0.64))

        if not candidates:
            # If conversation history provides a prior intent, carry it forward with low confidence
            if prior_intent:
                return QueryPlan(
                    intent=prior_intent, target=target, tenant_id=scope.effective_tenant_id,
                    time_range=time_range, confidence=0.4, limit=limit,
                )
            return QueryPlan(intent="unsupported", target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.2)

        # Ambiguity: if multiple strong candidates, ask for clarification
        strong = [(i, c) for i, c in candidates if c >= 0.7]
        if len(strong) > 1:
            # If there's a clear winner (highest confidence), use it
            strong.sort(key=lambda x: x[1], reverse=True)
            if strong[0][1] - strong[1][1] < 0.05:
                # Too close — ambiguous
                return QueryPlan(intent=strong[0][0], target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=0.45, limit=limit)

        best_intent, best_conf = candidates[0]

        # Build the plan for the best match
        if best_intent == "wallet_lookup":
            return QueryPlan(intent="wallet_lookup", target=target or self._extract_wallet(text), entity_type="wallet", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=best_conf, limit=limit)
        if best_intent == "agent_lookup":
            return QueryPlan(intent="agent_lookup", target=target, entity_type="agent", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=best_conf, limit=limit)
        if best_intent == "profile_lookup":
            return QueryPlan(intent="profile_lookup", target=target, entity_type="human", tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=best_conf, limit=limit)
        if best_intent == "entity_search":
            return QueryPlan(intent="entity_search", target=target or self._search_terms(text), tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=best_conf, limit=limit)
        return QueryPlan(intent=best_intent, target=target, tenant_id=scope.effective_tenant_id, time_range=time_range, confidence=best_conf, limit=limit)

    def _validate_plan(self, plan: QueryPlan, scope: Scope) -> QueryPlan:
        if plan.intent == "unsupported":
            logger.warning("LLM plan returned unsupported intent", extra={"intent": plan.intent})
            raise BadRequestError("LLM plan did not map to a supported Noesis intent")
        if plan.intent not in SUPPORTED_INTENTS:
            logger.warning("LLM plan returned non-allowlisted intent", extra={"intent": plan.intent})
            raise BadRequestError(f"LLM plan intent '{plan.intent}' is not allowlisted")
        if plan.tenant_id and plan.tenant_id != scope.effective_tenant_id:
            logger.warning("LLM plan attempted tenant override", extra={"plan_tenant": plan.tenant_id, "effective": scope.effective_tenant_id})
            raise ForbiddenError("Generated Noesis plan attempted to change tenant scope")
        # Reject cross-tenant from Aether surface
        if scope.surface == "aether" and plan.tenant_id and plan.tenant_id != scope.effective_tenant_id:
            logger.warning("LLM plan cross-tenant from aether blocked")
            raise ForbiddenError("Cross-tenant queries are not allowed from Aether surface")
        # Reject unsupported filters
        for key in plan.filters:
            if key not in SUPPORTED_FILTERS:
                logger.warning("LLM plan unsupported filter rejected", extra={"filter": key})
                raise BadRequestError(f"LLM plan filter '{key}' is not supported")
        # Reject mutation-like filter values
        for v in plan.filters.values():
            if isinstance(v, str) and any(kw in v.lower() for kw in WRITE_LIKE_KEYWORDS):
                logger.warning("LLM plan mutation filter value rejected")
                raise BadRequestError("LLM plan contains mutation-like filter values")
        # Reject unsafe date ranges (>90 days)
        tr = plan.time_range or ""
        if tr:
            day_match = re.search(r"(\d+)\s*d", tr)
            if day_match and int(day_match.group(1)) > 90:
                logger.warning("LLM plan unsafe date range rejected", extra={"time_range": tr})
                raise BadRequestError("LLM plan time range exceeds 90-day maximum")
        plan.tenant_id = scope.effective_tenant_id
        plan.limit = min(max(plan.limit, 1), MAX_LIMIT)
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
        needle = (plan.target or "").lower()
        fetch_limit = max(plan.limit * 10, 200) if needle else plan.limit
        rows = await self.entities.find_many(filters=self._tenant_filter(scope), limit=fetch_limit)
        if needle:
            rows = [r for r in rows if needle in str(r.get("entity_id", r.get("id", ""))).lower() or needle in str(r.get("display_name", "")).lower() or needle in str(r.get("entity_type", "")).lower()]
        rows = rows[: plan.limit]
        return self._response(plan, f"Found {len(rows)} tenant-scoped entities matching your request.", rows, self._entity_actions(rows, scope))

    async def _graph_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        if not plan.target:
            return self._ambiguous(plan, "Which graph node or entity should I inspect?")
        vertex = await self.graph.get_vertex(plan.target)
        if vertex:
            vtid = vertex.properties.get("tenant_id")
            if scope.cross_tenant and not scope.effective_tenant_id:
                pass
            elif vtid not in (scope.effective_tenant_id, None, ""):
                vertex = None
        neighbors = await self.graph.get_neighbors(plan.target, direction="both") if vertex else []
        if scope.cross_tenant and not scope.effective_tenant_id:
            safe_neighbors = list(neighbors)
        else:
            safe_neighbors = [v for v in neighbors if v.properties.get("tenant_id") in (scope.effective_tenant_id, None, "")]
        edges = await self.graph.get_edges(plan.target, direction="both") if vertex else []
        visible_node_ids = {v.vertex_id for v in ([vertex] if vertex else []) + safe_neighbors}
        nodes = [self._vertex_to_node(v) for v in ([vertex] if vertex else []) + safe_neighbors]
        graph_edges = [self._edge_to_dict(e) for e in edges if e.from_vertex_id in visible_node_ids and e.to_vertex_id in visible_node_ids]
        actions = [NoesisAction(type="highlight_graph", label="Highlight graph neighborhood", node_ids=[n["id"] for n in nodes], edge_ids=[e["id"] for e in graph_edges])]
        if vertex:
            actions.append(NoesisAction(type="open_inspector", label="Open inspector", entity_id=vertex.vertex_id, entity_type=str(vertex.vertex_type)))
            actions.append(NoesisAction(type="navigate", label="Open graph workspace", href=f"/graph?entity={vertex.vertex_id}"))
        answer = f"{plan.target} has {len(safe_neighbors)} visible neighboring nodes in this tenant scope."
        return self._response(plan, answer, nodes, actions, NoesisGraph(nodes=nodes, edges=graph_edges, highlights=[plan.target]))

    async def _alert_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        fetch_limit = max(plan.limit * 10, 200)
        rows = await self.alerts.find_many(filters=self._tenant_filter(scope), limit=fetch_limit)
        unresolved = [r for r in rows if str(r.get("status", "open")).lower() not in ("resolved", "closed")][: plan.limit]
        actions = [NoesisAction(type="navigate", label="Open alerts", href="/review")]
        return self._response(plan, f"Found {len(unresolved)} unresolved alert records in scope.", unresolved, actions)

    async def _tenant_summary(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        if scope.surface != "kyber":
            raise ForbiddenError("Tenant summaries are Kyber-only")
        # Prefer scope's effective tenant; only use plan.target if it looks like a
        # tenant ID (not a keyword accidentally captured by _extract_target).
        target_tid = scope.effective_tenant_id
        if plan.target and scope.cross_tenant and plan.target != scope.effective_tenant_id:
            candidate = await self.tenants.find_by_id(plan.target)
            if candidate is not None:
                target_tid = plan.target
        tenant = await self.tenants.find_by_id(target_tid) if target_tid else None
        summary = await self.analytics.dashboard_summary(target_tid) if target_tid else {"period": "all", "total_events": 0, "total_sessions": 0}
        target_filter = {"tenant_id": target_tid} if target_tid else None
        alerts = await self.alerts.count(filters=target_filter)
        entities = await self.entities.count(filters=target_filter)
        result = {"tenant": tenant or {"tenant_id": target_tid or "all-authorized-tenants"}, "analytics": summary, "alerts": alerts, "entities": entities}
        label = target_tid or "authorized tenants"
        href = f"/tenants/{target_tid}" if target_tid else "/tenants"
        return self._response(plan, f"Tenant scope {label} has {entities} entities, {alerts} alert records, and {summary.get('total_events', 0)} tracked events.", [result], [NoesisAction(type="navigate", label="Open tenants", href=href)])

    async def _typed_lookup(self, plan: QueryPlan, scope: Scope) -> NoesisResponse:
        if plan.intent == "wallet_lookup":
            fetch_limit = max(plan.limit * 10, 200)
            rows = await self.wallets.find_many(filters=self._tenant_filter(scope), limit=fetch_limit)
            needle = (plan.target or "").lower()
            if needle:
                rows = [r for r in rows if needle in str(r).lower()]
            rows = rows[: plan.limit]
            return self._response(plan, f"Found {len(rows)} wallet records in the authorized tenant scope.", rows, self._entity_actions(rows, scope))
        filters: dict[str, Any] = self._tenant_filter(scope) or {}
        if plan.entity_type:
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
        provider_rows = [self._redact_deep(r) for r in await self.providers.find_many(filters=self._tenant_filter(scope), limit=plan.limit)]
        failed_agents = (await self.agent_executions.find_many(filters={"status": "failed"}, limit=plan.limit)) if scope.cross_tenant and not scope.effective_tenant_id else await self.agent_executions.list_failed(scope.effective_tenant_id, limit=plan.limit)
        if scope.cross_tenant and not scope.effective_tenant_id:
            summary = await self.analytics.dashboard_summary(None)
        else:
            summary = await self.analytics.dashboard_summary(scope.effective_tenant_id)
        result = {"sdk_or_provider_records": provider_rows, "failed_agent_executions": [self._redact_deep(r) for r in failed_agents], "analytics_summary": summary}
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
        return self._redact_deep(row)

    def _redact_deep(self, value: Any) -> Any:
        blocked = {
            "key_hash", "api_key", "secret", "token", "password", "credentials",
            "authorization", "session_token", "refresh_token", "private_key",
            "connection_string", "oauth_token", "webhook_secret", "x_api_key",
        }
        if isinstance(value, dict):
            return {k: ("[redacted]" if k.lower() in blocked else self._redact_deep(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_deep(item) for item in value]
        return value

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
