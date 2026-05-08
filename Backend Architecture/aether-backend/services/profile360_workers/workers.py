"""
Profile 360 — derived data workers.

Stateless event handlers attached to the shared EventConsumer. They populate
the new behavior_profiles, journey_chains, and graph projections without
disturbing any existing service logic.

Wired up via attach_profile360_workers(consumer); a no-op until called.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from shared.events.events import Event, EventConsumer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from repositories.repos import (
    AgentExecutionRepository,
    BehaviorProfileRepository,
    DelegationRepository,
    JourneyChainRepository,
)

logger = get_logger("aether.profile360.workers")

# ── Tiny in-process state for rolling computations ─────────────────────
# Per-entity counters reset by the first event of a new window. Enough for
# automation_ratio / decision_latency snapshots; the persisted snapshot row
# is the source of truth for clients.

_action_counts: dict[str, Counter] = defaultdict(Counter)
_last_event_at: dict[str, datetime] = {}
_session_chain: dict[str, list[str]] = defaultdict(list)


def _entity_from_event(event: Event) -> Optional[str]:
    p = event.payload or {}
    for key in ("entity_id", "agent_id", "user_id", "owner_entity_id", "grantee_entity_id"):
        v = p.get(key)
        if isinstance(v, str) and v:
            return v
    if event.envelope and isinstance(event.envelope.actor, dict):
        v = event.envelope.actor.get("entity_id")
        if isinstance(v, str) and v:
            return v
    return None


def _actor_kind(event: Event) -> str:
    """Best-effort label of who acted: 'agent' if topic comes from the agent
    execution layer or the actor is typed as agent, else 'human'."""
    if event.topic in (
        Topic.AGENT_EXECUTION_STARTED,
        Topic.AGENT_EXECUTION_COMPLETED,
        Topic.AGENT_EXECUTION_FAILED,
        Topic.AGENT_EXECUTION_RECOVERED,
    ):
        return "agent"
    if event.envelope and isinstance(event.envelope.actor, dict):
        if event.envelope.actor.get("entity_type") == "agent":
            return "agent"
    return "human"


# ── BehaviorScorer ─────────────────────────────────────────────────────

class BehaviorScorer:
    def __init__(self, repo: Optional[BehaviorProfileRepository] = None) -> None:
        self._repo = repo or BehaviorProfileRepository()

    async def handle(self, event: Event) -> None:
        entity_id = _entity_from_event(event)
        if not entity_id or not event.tenant_id:
            return
        kind = _actor_kind(event)
        _action_counts[entity_id][kind] += 1
        _action_counts[entity_id]["total"] += 1

        now = datetime.now(timezone.utc)
        prev = _last_event_at.get(entity_id)
        latency_ms = int((now - prev).total_seconds() * 1000) if prev else 0
        _last_event_at[entity_id] = now

        c = _action_counts[entity_id]
        total = c["total"] or 1
        automation_ratio = c["agent"] / total

        await self._repo.upsert_snapshot(
            entity_id=entity_id,
            tenant_id=event.tenant_id,
            window_start=(now - timedelta(days=7)).isoformat(),
            window_end=now.isoformat(),
            automation_ratio=round(automation_ratio, 4),
            decision_latency_ms=latency_ms,
        )
        metrics.increment("profile360_behavior_scored")


# ── RiskScorer ─────────────────────────────────────────────────────────

class RiskScorer:
    """Bumps the per-entity risk_score on failed or revoked executions."""

    def __init__(self, repo: Optional[BehaviorProfileRepository] = None) -> None:
        self._repo = repo or BehaviorProfileRepository()

    async def handle(self, event: Event) -> None:
        entity_id = _entity_from_event(event)
        if not entity_id or not event.tenant_id:
            return

        existing = await self._repo.find_by_id(entity_id) or {}
        current = float(existing.get("risk_score") or 0.0)
        bump = 0.05 if event.topic == Topic.AGENT_EXECUTION_FAILED else 0.0
        if event.topic == Topic.DELEGATION_REJECTED:
            bump = 0.02
        new_score = max(0.0, min(1.0, current * 0.95 + bump))

        now = datetime.now(timezone.utc)
        await self._repo.upsert_snapshot(
            entity_id=entity_id,
            tenant_id=event.tenant_id,
            window_start=existing.get("window_start") or now.isoformat(),
            window_end=now.isoformat(),
            automation_ratio=float(existing.get("automation_ratio") or 0.0),
            decision_latency_ms=int(existing.get("decision_latency_ms") or 0),
            top_patterns=existing.get("top_patterns"),
            anomaly_flags=existing.get("anomaly_flags"),
            risk_score=round(new_score, 4),
            predicted_next=existing.get("predicted_next"),
        )
        metrics.increment("profile360_risk_scored")


# ── IntentInferrer ─────────────────────────────────────────────────────

class IntentInferrer:
    """Lightweight rule-based intent labeling. ML-backed inference can replace
    this without changing the surface; the snapshot's predicted_next is the
    contract for clients."""

    KEYWORDS = {
        "convert":  ("checkout", "purchase", "subscribe", "payment"),
        "explore":  ("browse", "search", "view"),
        "abandon":  ("cancel", "exit", "back"),
    }

    def __init__(self, repo: Optional[BehaviorProfileRepository] = None) -> None:
        self._repo = repo or BehaviorProfileRepository()

    async def handle(self, event: Event) -> None:
        entity_id = _entity_from_event(event)
        if not entity_id or not event.tenant_id:
            return
        text = " ".join(str(v) for v in (event.payload or {}).values()).lower()
        intent = "unknown"
        for label, words in self.KEYWORDS.items():
            if any(w in text for w in words):
                intent = label
                break
        existing = await self._repo.find_by_id(entity_id) or {}
        await self._repo.upsert_snapshot(
            entity_id=entity_id,
            tenant_id=event.tenant_id,
            window_start=existing.get("window_start") or datetime.now(timezone.utc).isoformat(),
            window_end=datetime.now(timezone.utc).isoformat(),
            automation_ratio=float(existing.get("automation_ratio") or 0.0),
            decision_latency_ms=int(existing.get("decision_latency_ms") or 0),
            top_patterns=existing.get("top_patterns"),
            anomaly_flags=existing.get("anomaly_flags"),
            risk_score=float(existing.get("risk_score") or 0.0),
            predicted_next={"action": intent, "confidence": 0.4, "model_version": "rules-v1"},
        )
        metrics.increment("profile360_intent_inferred", labels={"intent": intent})


# ── JourneyChainLinker ─────────────────────────────────────────────────

class JourneyChainLinker:
    """Stitches per-entity sessions into a chain id that survives across
    sessions; persisted to journey_chains."""

    WINDOW_DAYS = 90

    def __init__(self, repo: Optional[JourneyChainRepository] = None) -> None:
        self._repo = repo or JourneyChainRepository()

    async def handle(self, event: Event) -> None:
        entity_id = _entity_from_event(event)
        if not entity_id or not event.tenant_id:
            return
        session_id = (event.payload or {}).get("session_id") or event.event_id
        chain = _session_chain[entity_id]
        if session_id not in chain:
            chain.append(session_id)

        chain_id = f"chain:{entity_id}"
        await self._repo.upsert_chain(
            chain_id=chain_id,
            entity_id=entity_id,
            tenant_id=event.tenant_id,
            first_journey_id=chain[0],
            last_journey_id=chain[-1],
            journey_count=len(chain),
            spans_started_at=datetime.now(timezone.utc).isoformat(),
            spans_last_seen_at=datetime.now(timezone.utc).isoformat(),
        )
        metrics.increment("profile360_journey_chain_linked")


# ── DelegationProjector ────────────────────────────────────────────────

class DelegationProjector:
    """Mirrors authoritative delegations into the graph as DELEGATES edges.

    Listens to DELEGATION_CREATED / DELEGATION_REVOKED and adds (or marks
    revoked) the corresponding edge. Authoritative store is unchanged.
    """

    def __init__(
        self,
        graph: GraphClient,
        repo: Optional[DelegationRepository] = None,
    ) -> None:
        self._graph = graph
        self._repo = repo or DelegationRepository()

    async def handle(self, event: Event) -> None:
        delegation_id = (event.payload or {}).get("delegation_id")
        if not delegation_id:
            return
        record = await self._repo.find_by_id(delegation_id)
        if record is None:
            return
        try:
            await self._graph.add_edge(Edge(
                edge_type=EdgeType.DELEGATES,
                from_vertex_id=record["grantor_entity_id"],
                to_vertex_id=record["grantee_entity_id"],
                properties={
                    "tenant_id": record.get("tenant_id", ""),
                    "delegation_id": delegation_id,
                    "valid_from": record.get("starts_at", ""),
                    "valid_to": record.get("ends_at") or "",
                    "revoked_at": record.get("revoked_at") or "",
                },
            ))
            metrics.increment("profile360_delegation_projected")
        except Exception as e:  # pragma: no cover
            logger.warning(f"DelegationProjector failed for {delegation_id}: {e}")


# ── AnomalyFlagger ─────────────────────────────────────────────────────

class AnomalyFlagger:
    """Lightweight z-style outlier flag on decision_latency_ms."""

    def __init__(self, repo: Optional[BehaviorProfileRepository] = None) -> None:
        self._repo = repo or BehaviorProfileRepository()

    async def handle(self, event: Event) -> None:
        entity_id = _entity_from_event(event)
        if not entity_id or not event.tenant_id:
            return
        existing = await self._repo.find_by_id(entity_id) or {}
        latency = int(existing.get("decision_latency_ms") or 0)
        flags = list(existing.get("anomaly_flags") or [])
        # Heuristic threshold; replaceable by ML.
        if latency > 5_000 and "high_latency" not in flags:
            flags.append("high_latency")
        await self._repo.upsert_snapshot(
            entity_id=entity_id,
            tenant_id=event.tenant_id,
            window_start=existing.get("window_start") or datetime.now(timezone.utc).isoformat(),
            window_end=datetime.now(timezone.utc).isoformat(),
            automation_ratio=float(existing.get("automation_ratio") or 0.0),
            decision_latency_ms=latency,
            top_patterns=existing.get("top_patterns"),
            anomaly_flags=flags,
            risk_score=float(existing.get("risk_score") or 0.0),
            predicted_next=existing.get("predicted_next"),
        )


# ── Wiring ─────────────────────────────────────────────────────────────

def attach_profile360_workers(consumer: EventConsumer, graph: GraphClient) -> None:
    """Subscribe Profile 360 workers to the shared EventConsumer."""
    behavior = BehaviorScorer()
    risk = RiskScorer()
    intent = IntentInferrer()
    chain = JourneyChainLinker()
    projector = DelegationProjector(graph=graph)
    anomaly = AnomalyFlagger()

    # BehaviorScorer + JourneyChainLinker + IntentInferrer listen broadly.
    broad_topics = (
        Topic.PROFILE_UPDATED,
        Topic.AGENT_EXECUTION_STARTED,
        Topic.AGENT_EXECUTION_COMPLETED,
        Topic.AGENT_EXECUTION_FAILED,
        Topic.FLOW_TRANSFER,
        Topic.ENTITY_UPDATED,
        Topic.DELEGATION_VALIDATED,
    )
    for t in broad_topics:
        consumer.subscribe(t, behavior.handle)
        consumer.subscribe(t, intent.handle)
        consumer.subscribe(t, chain.handle)

    # RiskScorer reacts to failures.
    for t in (Topic.AGENT_EXECUTION_FAILED, Topic.DELEGATION_REJECTED):
        consumer.subscribe(t, risk.handle)

    # DelegationProjector tracks delegation lifecycle.
    for t in (Topic.DELEGATION_CREATED, Topic.DELEGATION_REVOKED):
        consumer.subscribe(t, projector.handle)

    # AnomalyFlagger samples broadly on the same broad set.
    for t in broad_topics:
        consumer.subscribe(t, anomaly.handle)

    logger.info("Profile 360 workers attached to consumer")
