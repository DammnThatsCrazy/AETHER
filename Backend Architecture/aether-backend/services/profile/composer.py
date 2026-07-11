"""
Profile Composer — Assembles holistic profile from existing subsystems.

This is the core "Profile 360" aggregator. It does NOT duplicate data or logic.
It calls existing repositories and services to compose a unified view.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from shared.common.common import utc_now
from shared.graph.graph import GraphClient
from shared.cache.cache import CacheClient
from shared.scoring.trust_score import TrustScoreComposite
from shared.logger.logger import get_logger, metrics
from repositories.repos import IdentityRepository, AnalyticsRepository, ConsentRepository
from repositories.lake import (
    gold_identity, gold_market, gold_onchain, gold_social,
    silver_identity, silver_onchain, silver_social,
)
from services.profile.resolver import ProfileResolver
from services.profile.economic import AgentProfile360EconomicComposer

logger = get_logger("aether.profile.composer")


def _tenant_matches(properties: dict[str, Any], tenant_id: str) -> bool:
    """Return True only for current-tenant or legacy unscoped graph rows."""
    graph_tenant = properties.get("tenant_id")
    return graph_tenant in (None, "", tenant_id)


def _vertex_to_node(vertex: Any) -> dict:
    properties = dict(getattr(vertex, "properties", {}) or {})
    vertex_id = getattr(vertex, "vertex_id", properties.get("id", ""))
    vertex_type = getattr(vertex, "vertex_type", properties.get("type", "external"))
    display_label = (
        properties.get("display_name")
        or properties.get("name")
        or properties.get("label")
        or vertex_id
    )
    return {
        "id": vertex_id,
        "type": vertex_type,
        "label": display_label,
        "trustScore": properties.get("trust_score"),
        "riskScore": properties.get("risk_score"),
        "anomalyScore": properties.get("anomaly_score"),
        "metadata": properties,
        # Profile 360 preview fields — used by the frontend to open a preview
        # card or full profile view directly from a graph node selection.
        "profile_id": vertex_id,
        "entity_type": vertex_type,
        "display_label": display_label,
        "profile_links": {
            "summary": f"/v1/profile/{vertex_id}/summary",
            "full": f"/v1/profile360/{vertex_type}/{vertex_id}",
            "drill": None,
        },
    }


def _timeline_event(event: dict, fallback_id: str) -> dict:
    properties = event.get("properties") or event.get("metadata") or {}
    return {
        "id": str(event.get("id") or event.get("event_id") or fallback_id),
        "timestamp": str(event.get("timestamp") or event.get("created_at") or ""),
        "type": str(event.get("event_type") or event.get("type") or "event"),
        "title": str(event.get("title") or event.get("event_type") or event.get("type") or "Profile event"),
        "description": str(event.get("description") or event.get("summary") or "Profile360 timeline event"),
        "severity": str(event.get("severity") or "info"),
        "entityId": event.get("entity_id") or event.get("user_id"),
        "traceId": event.get("trace_id"),
        "causalityId": event.get("causality_id"),
        "parentEventId": event.get("parent_event_id"),
        "metadata": properties if isinstance(properties, dict) else {},
    }


class ProfileComposer:
    """Composes a full profile view from existing subsystems."""

    def __init__(
        self,
        identity_repo: IdentityRepository,
        analytics_repo: AnalyticsRepository,
        consent_repo: ConsentRepository,
        graph: GraphClient,
        cache: CacheClient,
        resolver: ProfileResolver,
    ) -> None:
        self._identity = identity_repo
        self._analytics = analytics_repo
        self._consent = consent_repo
        self._graph = graph
        self._cache = cache
        self._resolver = resolver
        self._scorer = TrustScoreComposite()
        self._agent_economic = AgentProfile360EconomicComposer()

    async def get_full_profile(
        self,
        user_id: str,
        tenant_id: str,
        include_timeline: bool = True,
        include_graph: bool = True,
        include_intelligence: bool = True,
        include_lake: bool = True,
        include_agent_economic: bool = False,
        timeline_limit: int = 50,
        graph_depth: int = 1,
    ) -> dict:
        """Assemble a complete profile view from all subsystems.

        Each dimension is composed under isolation: a single subsystem raising
        degrades only its own dimension (to a typed default) instead of 500-ing
        the whole profile, and the failure is surfaced in an additive
        ``readiness`` block rather than silently erased.
        """
        now = utc_now().isoformat()

        async def _core() -> dict:
            profile = await self._identity.get_profile(tenant_id, user_id)
            return profile or {"user_id": user_id, "tenant_id": tenant_id, "status": "unknown"}

        unknown_core = {"user_id": user_id, "tenant_id": tenant_id, "status": "unknown"}
        # (key, coroutine factory, default-on-error, enabled)
        specs: list[tuple[str, Any, Any, bool]] = [
            ("core", _core, unknown_core, True),
            ("identifiers",
             lambda: self._resolver.get_all_identifiers(user_id, tenant_id=tenant_id), [], True),
            ("consent", lambda: self._consent.get_consent(tenant_id, user_id), None, True),
            ("timeline",
             lambda: self._compose_timeline(tenant_id, user_id, limit=timeline_limit),
             [], include_timeline),
            ("graph",
             lambda: self._compose_graph(user_id, tenant_id=tenant_id, depth=graph_depth),
             {}, include_graph),
            ("intelligence",
             lambda: self._compose_intelligence(user_id, tenant_id), {}, include_intelligence),
            ("lake", lambda: self._compose_lake_data(user_id), {}, include_lake),
            # Agent economic Profile360 telemetry (opt-in/additive) — human/user
            # profile responses are unchanged unless an agent route enables it.
            ("agent_economic",
             lambda: self._agent_economic.compose(
                 agent_id=user_id, tenant_id=tenant_id, limit=timeline_limit),
             {}, include_agent_economic),
        ]

        active = [(k, f, d) for (k, f, d, en) in specs if en]
        results = await asyncio.gather(
            *[factory() for (_k, factory, _d) in active], return_exceptions=True
        )

        values: dict[str, Any] = {}
        degraded: list[dict] = []
        for (key, _factory, default), res in zip(active, results):
            if isinstance(res, Exception):
                logger.warning(
                    "profile360_dimension_failed",
                    extra={"dimension": key, "error": str(res)},
                )
                metrics.increment("profile_360_dimension_failed", labels={"dimension": key})
                values[key] = default
                degraded.append(
                    {"dimension": key, "state": "error", "reason": type(res).__name__}
                )
            else:
                values[key] = res
        # Disabled dimensions carry their default (not queried, not degraded).
        for (key, _factory, default, enabled) in specs:
            values.setdefault(key, default)

        metrics.increment("profile_360_composed")
        return {
            "profile_id": user_id,
            "tenant_id": tenant_id,
            "core": values["core"],
            "identifiers": values["identifiers"],
            "consent": values["consent"] or {"status": "no_record"},
            "timeline": values["timeline"],
            "graph": values["graph"],
            "intelligence": values["intelligence"],
            "lake": values["lake"],
            "agent_economic": values["agent_economic"],
            "computed_at": now,
            "readiness": {
                "state": "degraded" if degraded else "ready",
                "degraded_dimensions": degraded,
            },
            "provenance": {
                "source": "profile_360_composer",
                "subsystems_queried": [
                    "identity", "graph", "analytics", "consent",
                    "lake_gold", "trust_scorer", "agent_economic",
                ],
            },
        }

    async def _compose_timeline(
        self, tenant_id: str, user_id: str, limit: int = 50
    ) -> list[dict]:
        """Assemble time-ordered events from analytics."""
        events = await self._analytics.query_events(
            tenant_id, {"user_id": user_id}, limit=limit
        )
        return [
            {
                "event_id": e.get("id", ""),
                "event_type": e.get("event_type", ""),
                "timestamp": e.get("created_at", ""),
                "properties": e.get("properties", {}),
                "source": "analytics",
            }
            for e in events
        ]

    async def _compose_graph(self, user_id: str, tenant_id: str, depth: int = 1, limit: int = 50) -> dict:
        """Load tenant-scoped graph context around the user.

        Kyber is an internal operator surface and can inspect all Profile360
        dimensions, but every graph read remains constrained to the active
        client/tenant. Legacy vertices without tenant metadata are surfaced and
        flagged in the alignment audit so operators can backfill them.
        """
        root = await self._graph.get_vertex(user_id)
        root_properties = dict(getattr(root, "properties", {}) or {}) if root else {"tenant_id": tenant_id}
        if root and not _tenant_matches(root_properties, tenant_id):
            logger.warning(
                "profile360_graph_root_cross_tenant",
                extra={"user_id": user_id, "tenant_id": tenant_id, "vertex_tenant": root_properties.get("tenant_id")},
            )
            return {"neighbor_count": 0, "neighbors": [], "nodes": [], "edges": [], "alignment_audit": {"cross_tenant_neighbors_excluded": 0, "legacy_unscoped_neighbors": 0}}

        neighbors = await self._graph.get_neighbors(user_id, direction="both")
        scoped_neighbors = []
        cross_tenant = 0
        legacy_unscoped = 0
        for vertex in neighbors:
            props = dict(getattr(vertex, "properties", {}) or {})
            if not _tenant_matches(props, tenant_id):
                cross_tenant += 1
                continue
            if not props.get("tenant_id"):
                legacy_unscoped += 1
            scoped_neighbors.append(vertex)

        limited = scoped_neighbors[:limit]
        root_node = _vertex_to_node(root) if root else {
            "id": user_id,
            "type": "human",
            "label": user_id,
            "metadata": {"tenant_id": tenant_id},
            "profile_id": user_id,
            "entity_type": "human",
            "display_label": user_id,
            "profile_links": {
                "summary": f"/v1/profile/{user_id}/summary",
                "full": f"/v1/profile360/human/{user_id}",
                "drill": None,
            },
        }
        nodes = [root_node, *[_vertex_to_node(v) for v in limited]]
        edges = [
            {
                "id": f"{user_id}-{v.vertex_id}-{index}",
                "source": user_id,
                "target": v.vertex_id,
                "type": "RELATED_TO",
                "weight": 1,
                "label": "related",
                "metadata": {"tenant_id": tenant_id, "profile360_inferred": True},
            }
            for index, v in enumerate(limited)
        ]
        return {
            "neighbor_count": len(scoped_neighbors),
            "neighbors": [
                {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
                for v in limited
            ],
            "nodes": nodes,
            "edges": edges,
            "alignment_audit": {
                "cross_tenant_neighbors_excluded": cross_tenant,
                "legacy_unscoped_neighbors": legacy_unscoped,
                "tenant_id": tenant_id,
                "depth": depth,
            },
        }

    async def _compose_intelligence(self, user_id: str, tenant_id: str) -> dict:
        """Aggregate risk scores and model outputs."""
        # Trust score
        score = await self._scorer.compute(entity_id=user_id, entity_type="human")

        # Gold-tier identity features
        gold_features = await gold_identity.get_metrics(user_id, entity_type="wallet")
        features = gold_features[0].get("value", {}) if gold_features else {}

        return {
            "risk_score": score.to_dict(),
            "features": features,
        }

    async def _compose_lake_data(self, user_id: str) -> dict:
        """Gather Gold-tier data across all lake domains."""
        result: dict[str, Any] = {}
        for domain_name, repo in [
            ("identity", gold_identity),
            ("market", gold_market),
            ("onchain", gold_onchain),
            ("social", gold_social),
        ]:
            records = await repo.get_metrics(user_id)
            if records:
                result[domain_name] = [r.get("value", {}) for r in records]
        return result

    async def get_profile360_surface(
        self,
        entity_type: str,
        entity_id: str,
        tenant_id: str,
        include: Optional[list[str]] = None,
        timeline_limit: int = 250,
        graph_limit: int = 750,
    ) -> dict:
        """Return the normalized internal Kyber Profile360 surface.

        The response is intentionally broader than any future end-user profile
        surface: Kyber receives all tenant-scoped identity, system, financial,
        graph, timeline, analytics, and debug data plus an alignment audit.
        """
        include_set = set(include or [
            "identity", "system", "financial", "graph", "timeline", "analytics", "debug",
        ])
        full = await self.get_full_profile(
            user_id=entity_id,
            tenant_id=tenant_id,
            include_timeline="timeline" in include_set,
            include_graph="graph" in include_set,
            include_intelligence="analytics" in include_set or "identity" in include_set,
            include_lake="financial" in include_set or "analytics" in include_set,
            timeline_limit=timeline_limit,
        )
        graph = full.get("graph") if isinstance(full.get("graph"), dict) else {}
        if "graph" in include_set and graph_limit != 50:
            graph = await self._compose_graph(entity_id, tenant_id=tenant_id, limit=graph_limit)

        timeline = [_timeline_event(e, f"{entity_id}-evt-{idx}") for idx, e in enumerate(full.get("timeline") or [])]
        core = full.get("core") or {}
        intelligence = full.get("intelligence") or {}
        lake = full.get("lake") or {}
        entity = {
            "id": entity_id,
            "type": entity_type,
            "name": core.get("name") or core.get("display_name") or entity_id,
            "displayLabel": core.get("display_name") or core.get("name") or entity_id,
            "createdAt": core.get("created_at") or full.get("computed_at"),
            "updatedAt": core.get("updated_at") or full.get("computed_at"),
            "health": {"status": core.get("status", "unknown"), "lastChecked": full.get("computed_at")},
            "trustScore": core.get("trust_score", 0),
            "riskScore": core.get("risk_score", 0),
            "anomalyScore": core.get("anomaly_score", 0),
            "needsHelp": bool(core.get("needs_help", False)),
            "tags": core.get("tags", []),
            "metadata": core,
        }
        sections = {
            "identity": [{"id": "identity", "title": "Identity and consent", "data": {"core": core, "identifiers": full.get("identifiers"), "consent": full.get("consent")}}],
            "system": [{"id": "system", "title": "System and automation context", "data": {"agents": full.get("agents", []), "behavior": full.get("behavior", {})}}],
            "financial": [{"id": "financial", "title": "Financial and lake context", "data": lake}],
            "analytics": [{"id": "analytics", "title": "Intelligence and behavioral analytics", "data": intelligence}],
            "debug": [{"id": "alignment", "title": "Tenant and graph alignment audit", "data": {"tenant_id": tenant_id, "surface": "kyber_internal", "graph": graph.get("alignment_audit", {})}}],
        }
        return {
            "entity": entity,
            "tenant_id": tenant_id,
            "surface": "kyber_internal",
            "visibility": "internal_full",
            "sections": {key: value for key, value in sections.items() if key in include_set},
            "timeline": timeline if "timeline" in include_set else [],
            "graph": {"nodes": graph.get("nodes", []), "edges": graph.get("edges", [])} if "graph" in include_set else {"nodes": [], "edges": []},
            "raw": full,
            "alignment_audit": {
                "tenant_id": tenant_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "kyber_internal_full_surface": True,
                "end_user_surface_requires_redaction": True,
                "graph": graph.get("alignment_audit", {}),
                "sections_returned": sorted(include_set),
            },
        }


    async def get_timeline(
        self,
        user_id: str,
        tenant_id: str,
        limit: int = 100,
        offset: int = 0,
        event_type: Optional[str] = None,
    ) -> list[dict]:
        """Get paginated timeline for a user."""
        filters: dict = {"user_id": user_id}
        if event_type:
            filters["event_type"] = event_type
        return await self._analytics.query_events(tenant_id, filters, limit=limit)

    async def get_provenance(
        self, user_id: str, field: str = ""
    ) -> dict:
        """Get provenance info for a profile field or entity."""
        # Lake Silver records show source/source_tag for each data point
        identity_records = await silver_identity.get_entity(user_id, "wallet")
        onchain_records = await silver_onchain.get_entity(user_id, "wallet")
        social_records = await silver_social.get_entity(user_id, "wallet")

        return {
            "entity_id": user_id,
            "sources": {
                "identity": [
                    {"source": r.get("source", ""), "source_tag": r.get("source_tag", ""), "updated_at": r.get("updated_at", "")}
                    for r in identity_records
                ],
                "onchain": [
                    {"source": r.get("source", ""), "source_tag": r.get("source_tag", ""), "updated_at": r.get("updated_at", "")}
                    for r in onchain_records
                ],
                "social": [
                    {"source": r.get("source", ""), "source_tag": r.get("source_tag", ""), "updated_at": r.get("updated_at", "")}
                    for r in social_records
                ],
            },
        }
