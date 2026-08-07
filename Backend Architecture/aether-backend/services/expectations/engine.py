"""
Expectation Engine — core detection logic.

Computes baselines from existing subsystems and detects:
- missing expected behaviors (absence)
- contradictory evidence (identity, graph, source, temporal)
- broken sequences
- peer/self/graph deviation
- source silence vs true behavioral silence
"""

from __future__ import annotations

from typing import Optional

from datetime import timedelta

from repositories.repos import BaseRepository, AnalyticsRepository
from repositories.lake import silver_identity, silver_onchain, silver_social
from shared.graph.graph import GraphClient, VertexType
from shared.cache.cache import CacheClient
from shared.logger.logger import get_logger, metrics
from shared.common.common import utc_now
from shared.temporal import ensure_aware_utc, parse_instant_strict

# Dynamic freshness SLA — source silence is judged against the CURRENT time, not
# a hardcoded calendar date.
SOURCE_FRESHNESS_SLA_DAYS = 45


def _is_source_stale(
    last_update_iso: Optional[str], *, sla_days: int = SOURCE_FRESHNESS_SLA_DAYS
) -> Optional[bool]:
    """True when ``last_update`` is older than the SLA; None when absent/unparseable."""
    if not last_update_iso:
        return None
    try:
        ts = ensure_aware_utc(parse_instant_strict(last_update_iso))
    except Exception:
        return None
    return (utc_now() - ts) > timedelta(days=sla_days)
from services.expectations.models import (
    SignalType, SignalSeverity, BaselineSource, make_signal_record,
)

logger = get_logger("aether.expectations.engine")


class SignalRepository(BaseRepository):
    """Stores expectation signals (absence, contradiction, deviation)."""

    def __init__(self) -> None:
        super().__init__("expectation_signals")

    async def get_signals_for_entity(
        self, entity_id: str, signal_type: Optional[str] = None, limit: int = 50,
    ) -> list[dict]:
        filters: dict = {"entity_id": entity_id}
        if signal_type:
            filters["signal_type"] = signal_type
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")

    async def get_signals_for_population(
        self, population_id: str, limit: int = 100,
    ) -> list[dict]:
        return await self.find_many(filters={"population_id": population_id}, limit=limit)

    async def get_signals_by_type(
        self, signal_type: str, tenant_id: str, limit: int = 100,
    ) -> list[dict]:
        return await self.find_many(filters={"signal_type": signal_type, "tenant_id": tenant_id}, limit=limit)


signal_repo = SignalRepository()


class ExpectationEngine:
    """
    Core detection engine. Computes baselines and detects signals.
    Composes from existing subsystems — does NOT duplicate their logic.
    """

    def __init__(
        self,
        graph: GraphClient,
        cache: CacheClient,
        analytics: Optional[AnalyticsRepository] = None,
    ) -> None:
        self._graph = graph
        self._cache = cache
        self._analytics = analytics or AnalyticsRepository(cache)

    # ── Identity Contradiction Detection ──────────────────────────

    async def detect_identity_contradictions(
        self, entity_id: str, tenant_id: str = "",
    ) -> list[dict]:
        """Detect contradictory identity evidence from multiple sources."""
        signals = []
        identity_records = await silver_identity.get_entity(entity_id, "wallet")

        # Check for conflicting source claims about the same entity
        sources_seen: dict[str, list[dict]] = {}
        for rec in identity_records:
            source = rec.get("source", "")
            sources_seen.setdefault(source, []).append(rec)

        # If multiple sources claim different properties for same entity
        if len(sources_seen) > 1:
            source_names = list(sources_seen.keys())
            for i, s1 in enumerate(source_names):
                for s2 in source_names[i + 1:]:
                    recs1, recs2 = sources_seen[s1], sources_seen[s2]
                    conflicts = self._find_field_conflicts(recs1[0], recs2[0])
                    if conflicts:
                        signal = make_signal_record(
                            entity_id=entity_id,
                            entity_type="wallet",
                            signal_type=SignalType.IDENTITY_CONTRADICTION,
                            severity=SignalSeverity.HIGH,
                            expected=f"Consistent identity from {s1} and {s2}",
                            observed=f"Conflicting fields: {conflicts}",
                            baseline_source=BaselineSource.SOURCE_NORM,
                            confidence=0.7,
                            explanation=f"Sources {s1} and {s2} disagree on: {', '.join(conflicts)}",
                            tenant_id=tenant_id,
                        )
                        await signal_repo.insert(signal["id"], signal)
                        signals.append(signal)

        metrics.increment("expectation_contradictions_detected", labels={"type": "identity"})
        return signals

    # ── Missing Expected Actions ──────────────────────────────────

    async def detect_missing_actions(
        self, entity_id: str, tenant_id: str = "", window_days: int = 7,
    ) -> list[dict]:
        """Detect expected actions that did not occur based on self-history."""
        signals = []

        # Get recent events for the entity
        events = await self._analytics.query_events(
            tenant_id, {"user_id": entity_id}, limit=200
        )
        if not events:
            return signals

        # Build action frequency baseline from history
        action_counts: dict[str, int] = {}
        for e in events:
            et = e.get("event_type", "")
            if et:
                action_counts[et] = action_counts.get(et, 0) + 1

        # Check for actions that were frequent but stopped
        total = len(events)
        for action, count in action_counts.items():
            frequency = count / max(total, 1)
            if frequency > 0.1 and count > 3:
                # This was a regular action — check if it's still happening
                recent = [e for e in events[:20] if e.get("event_type") == action]
                if not recent:
                    signal = make_signal_record(
                        entity_id=entity_id,
                        entity_type="user",
                        signal_type=SignalType.MISSING_EXPECTED_ACTION,
                        severity=SignalSeverity.MEDIUM,
                        expected=f"Action '{action}' expected (historical frequency: {frequency:.0%})",
                        observed=f"No recent '{action}' events in last window",
                        baseline_source=BaselineSource.SELF_HISTORY,
                        confidence=min(frequency * 2, 0.9),
                        explanation=f"Entity performed '{action}' {count} times historically but stopped recently",
                        tenant_id=tenant_id,
                    )
                    await signal_repo.insert(signal["id"], signal)
                    signals.append(signal)

        metrics.increment("expectation_missing_actions_detected")
        return signals

    # ── Missing Expected Edges ────────────────────────────────────

    async def detect_missing_edges(
        self, entity_id: str, tenant_id: str = "",
    ) -> list[dict]:
        """Detect expected graph relationships that are missing."""
        signals = []
        neighbors = await self._graph.get_neighbors(entity_id, direction="both")

        # Check if peer entities have connections this entity lacks
        for neighbor in neighbors[:10]:
            peer_neighbors = await self._graph.get_neighbors(neighbor.vertex_id, direction="both")
            peer_types = {n.vertex_type for n in peer_neighbors}
            my_types = {n.vertex_type for n in neighbors}

            missing_types = peer_types - my_types - {VertexType.USER}
            for mt in missing_types:
                signal = make_signal_record(
                    entity_id=entity_id,
                    entity_type="user",
                    signal_type=SignalType.MISSING_EXPECTED_EDGE,
                    severity=SignalSeverity.LOW,
                    expected=f"Edge to {mt} type (peer {neighbor.vertex_id} has one)",
                    observed="No such edge exists",
                    baseline_source=BaselineSource.GRAPH_NEIGHBOR,
                    confidence=0.3,
                    explanation=f"Graph neighbor {neighbor.vertex_id} has {mt} connection but this entity does not",
                    tenant_id=tenant_id,
                )
                await signal_repo.insert(signal["id"], signal)
                signals.append(signal)
                if len(signals) >= 5:
                    break
            if len(signals) >= 5:
                break

        metrics.increment("expectation_missing_edges_detected")
        return signals

    # ── Source Silence Detection ───────────────────────────────────

    async def detect_source_silence(
        self, entity_id: str, tenant_id: str = "",
    ) -> list[dict]:
        """Differentiate true missing behavior from source/ingestion silence."""
        signals = []

        # Check each lake domain for recency
        for domain_name, repo in [
            ("identity", silver_identity),
            ("onchain", silver_onchain),
            ("social", silver_social),
        ]:
            records = await repo.get_entity(entity_id, "wallet")
            if not records:
                continue

            # Check last update time
            latest = max(records, key=lambda r: r.get("updated_at", ""))
            last_update = latest.get("updated_at", "")

            # If last update is old, this might be source silence
            if _is_source_stale(last_update) is True:  # dynamic freshness SLA
                signal = make_signal_record(
                    entity_id=entity_id,
                    entity_type="wallet",
                    signal_type=SignalType.SOURCE_SILENCE,
                    severity=SignalSeverity.INFO,
                    expected=f"Recent data from {domain_name} source",
                    observed=f"Last update: {last_update}",
                    baseline_source=BaselineSource.SOURCE_NORM,
                    confidence=0.4,
                    explanation=f"No recent data from {domain_name} — may be source silence rather than true behavior change",
                    is_source_silence=True,
                    tenant_id=tenant_id,
                )
                await signal_repo.insert(signal["id"], signal)
                signals.append(signal)

        metrics.increment("expectation_source_silence_detected")
        return signals

    # ── Full Scan ─────────────────────────────────────────────────

    async def run_full_scan(
        self, entity_id: str, tenant_id: str = "",
    ) -> dict:
        """Run all detection engines for an entity. Returns all signals."""
        contradictions = await self.detect_identity_contradictions(entity_id, tenant_id)
        missing_actions = await self.detect_missing_actions(entity_id, tenant_id)
        missing_edges = await self.detect_missing_edges(entity_id, tenant_id)
        source_silence = await self.detect_source_silence(entity_id, tenant_id)

        all_signals = contradictions + missing_actions + missing_edges + source_silence

        return {
            "entity_id": entity_id,
            "total_signals": len(all_signals),
            "by_type": {
                "identity_contradiction": len(contradictions),
                "missing_expected_action": len(missing_actions),
                "missing_expected_edge": len(missing_edges),
                "source_silence": len(source_silence),
            },
            "signals": all_signals,
            "scanned_at": utc_now().isoformat(),
        }

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _find_field_conflicts(rec1: dict, rec2: dict) -> list[str]:
        """Find fields where two records disagree."""
        conflicts = []
        skip = {"id", "source", "source_tag", "created_at", "updated_at", "tenant_id", "bronze_id"}
        for key in set(rec1.keys()) & set(rec2.keys()) - skip:
            v1, v2 = rec1.get(key), rec2.get(key)
            if v1 and v2 and v1 != v2:
                conflicts.append(key)
        return conflicts
