"""
Profile Composer — Assembles holistic profile from existing subsystems.

This is the core "Profile 360" aggregator. It does NOT duplicate data or logic.
It calls existing repositories and services to compose a unified view.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now
from shared.graph.graph import GraphClient
from shared.cache.cache import CacheClient, TTL
from shared.scoring.trust_score import TrustScoreComposite
from shared.logger.logger import get_logger, metrics
from repositories.repos import IdentityRepository, AnalyticsRepository, ConsentRepository
from repositories.lake import (
    gold_identity, gold_market, gold_onchain, gold_social,
    silver_identity, silver_onchain, silver_social,
)
from services.profile.resolver import ProfileResolver

logger = get_logger("aether.profile.composer")


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

    async def get_full_profile(
        self,
        user_id: str,
        tenant_id: str,
        include_timeline: bool = True,
        include_graph: bool = True,
        include_intelligence: bool = True,
        include_lake: bool = True,
        timeline_limit: int = 50,
        graph_depth: int = 1,
    ) -> dict:
        """Assemble a complete profile view from all subsystems."""
        now = utc_now().isoformat()

        # 1. Core identity
        profile = await self._identity.get_profile(tenant_id, user_id)
        if not profile:
            profile = {"user_id": user_id, "tenant_id": tenant_id, "status": "unknown"}

        # 2. All linked identifiers
        identifiers = await self._resolver.get_all_identifiers(user_id)

        # 3. Consent status
        consent = await self._consent.get_consent(tenant_id, user_id)

        # 4. Timeline (events + actions)
        timeline = []
        if include_timeline:
            timeline = await self._compose_timeline(tenant_id, user_id, limit=timeline_limit)

        # 5. Graph context
        graph_context = {}
        if include_graph:
            graph_context = await self._compose_graph(user_id, depth=graph_depth)

        # 6. Intelligence (risk, features, model outputs)
        intelligence = {}
        if include_intelligence:
            intelligence = await self._compose_intelligence(user_id, tenant_id)

        # 7. Lake data (Gold-tier features and metrics)
        lake_data = {}
        if include_lake:
            lake_data = await self._compose_lake_data(user_id)

        metrics.increment("profile_360_composed")
        return {
            "profile_id": user_id,
            "tenant_id": tenant_id,
            "core": profile,
            "identifiers": identifiers,
            "consent": consent or {"status": "no_record"},
            "timeline": timeline,
            "graph": graph_context,
            "intelligence": intelligence,
            "lake": lake_data,
            "computed_at": now,
            "provenance": {
                "source": "profile_360_composer",
                "subsystems_queried": [
                    "identity", "graph", "analytics", "consent",
                    "lake_gold", "trust_scorer",
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

    async def _compose_graph(self, user_id: str, depth: int = 1) -> dict:
        """Load graph context around the user."""
        neighbors = await self._graph.get_neighbors(user_id, direction="both")
        return {
            "neighbor_count": len(neighbors),
            "neighbors": [
                {
                    "id": v.vertex_id,
                    "type": v.vertex_type,
                    "properties": v.properties,
                }
                for v in neighbors[:50]
            ],
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
