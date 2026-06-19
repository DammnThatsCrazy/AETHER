"""Identity graph writer — writes approved identity edges into the graph.

Rules:
1. Edges are tenant-scoped.
2. Edges are written only after policy approval.
3. Edges are idempotent: same (source, target, type) pair is not duplicated.
4. Revoked/split edges are marked revoked in the graph.
5. Campaign edges do not imply identity sameness.
6. Agent edges preserve agent/human separation.
7. Wallet ownership edges distinguish verified from observed.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.graph.graph import Edge
from shared.logger.logger import get_logger

from .models import (
    ConfidenceTier,
    EdgeType,
    MergeDecision,
    IdentityResolutionDecision,
)
from .repository import IdentityResolutionRepository
from .metrics import IdentityMetrics

logger = get_logger("aether.identity.graph_writer")


class IdentityGraphWriter:
    """
    Writes identity edges into the persistence-backed identity graph.

    In production this also writes to the Neptune graph via the shared
    GraphClient. In local/test mode the repository layer suffices.
    """

    def __init__(
        self,
        repo: IdentityResolutionRepository,
        metrics: IdentityMetrics,
        graph_client: Optional[Any] = None,
    ) -> None:
        self._repo = repo
        self._metrics = metrics
        self._graph = graph_client

    async def write_decision(
        self,
        decision: IdentityResolutionDecision,
        source_event_ids: list[str],
        consent_snapshot: Optional[dict] = None,
    ) -> list[str]:
        """
        Write graph edges for an approved identity resolution decision.

        Returns list of written edge IDs.
        """
        written: list[str] = []

        if decision.decision in (MergeDecision.BLOCKED, MergeDecision.REJECT, MergeDecision.NOOP):
            return written

        tenant_id = decision.tenant_id
        entity_id = decision.canonical_entity_id

        # ── same_as: deterministic / strong merge ─────────────────────────
        if decision.decision == MergeDecision.MERGE and decision.candidate_entity_ids:
            for candidate_id in decision.candidate_entity_ids:
                edge = await self._write_edge(
                    tenant_id, candidate_id, entity_id,
                    EdgeType.SAME_AS,
                    decision.confidence,
                    decision.confidence_tier,
                    decision.reason_codes,
                    source_event_ids,
                    consent_snapshot,
                )
                if edge:
                    written.append(edge["id"])

        # ── observed_as: anonymous visitor / session / device ─────────────
        if decision.decision in (MergeDecision.LINK, MergeDecision.CREATE):
            edge = await self._write_edge(
                tenant_id, entity_id, entity_id,
                EdgeType.OBSERVED_AS,
                decision.confidence,
                decision.confidence_tier,
                decision.reason_codes,
                source_event_ids,
                consent_snapshot,
            )
            # (self-loop for "observed" is a graph convention; skip if already there)

        self._metrics.record_graph_edge_writes(len(written))
        return written

    async def write_wallet_edge(
        self,
        tenant_id: str,
        human_entity_id: str,
        wallet_entity_id: str,
        is_verified: bool,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        consent_snapshot: Optional[dict] = None,
    ) -> Optional[dict]:
        edge_type = EdgeType.OWNS_WALLET if is_verified else EdgeType.CONTROLS_WALLET
        return await self._write_edge(
            tenant_id, human_entity_id, wallet_entity_id,
            edge_type, confidence, confidence_tier,
            reason_codes, source_event_ids, consent_snapshot,
        )

    async def write_session_edge(
        self,
        tenant_id: str,
        human_entity_id: str,
        session_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
    ) -> Optional[dict]:
        return await self._write_edge(
            tenant_id, human_entity_id, session_entity_id,
            EdgeType.LOGGED_IN_AS, confidence, confidence_tier,
            reason_codes, source_event_ids, None,
        )

    async def write_agent_delegation_edge(
        self,
        tenant_id: str,
        human_entity_id: str,
        agent_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
    ) -> Optional[dict]:
        return await self._write_edge(
            tenant_id, human_entity_id, agent_entity_id,
            EdgeType.DELEGATES_TO_AGENT, confidence, confidence_tier,
            reason_codes, source_event_ids, None,
        )

    async def write_org_membership_edge(
        self,
        tenant_id: str,
        human_entity_id: str,
        org_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
    ) -> Optional[dict]:
        return await self._write_edge(
            tenant_id, human_entity_id, org_entity_id,
            EdgeType.BELONGS_TO_ORG, confidence, confidence_tier,
            reason_codes, source_event_ids, None,
        )

    async def write_campaign_edge(
        self,
        tenant_id: str,
        entity_id: str,
        campaign_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
    ) -> Optional[dict]:
        # Campaign edges are attribution-only, never identity proof
        return await self._write_edge(
            tenant_id, entity_id, campaign_entity_id,
            EdgeType.CAME_FROM_CAMPAIGN, confidence, confidence_tier,
            reason_codes, source_event_ids, None,
        )

    async def write_journey_edge(
        self,
        tenant_id: str,
        entity_id: str,
        journey_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
    ) -> Optional[dict]:
        return await self._write_edge(
            tenant_id, entity_id, journey_id,
            EdgeType.PARTICIPATED_IN_JOURNEY, confidence, confidence_tier,
            reason_codes, source_event_ids, None,
        )

    async def revoke_edges_after_split(
        self,
        tenant_id: str,
        original_entity_id: str,
    ) -> list[str]:
        """Revoke all same_as edges involving the split entity."""
        revoked = await self._repo.revoke_edges_for_merge(
            tenant_id, original_entity_id, EdgeType.SAME_AS
        )
        self._metrics.record_graph_edge_writes(-len(revoked))
        return revoked

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _write_edge(
        self,
        tenant_id: str,
        source_entity_id: str,
        target_entity_id: str,
        edge_type: EdgeType,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        consent_snapshot: Optional[dict],
    ) -> Optional[dict]:
        try:
            edge = await self._repo.create_identity_edge(
                tenant_id=tenant_id,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                edge_type=edge_type,
                confidence=confidence,
                confidence_tier=confidence_tier,
                reason_codes=reason_codes,
                source_event_ids=source_event_ids,
                consent_snapshot=consent_snapshot,
            )
            # Mirror to Neptune graph when client is available (production path).
            # Failure is non-fatal: repo-backed edge is the source of truth.
            if edge and self._graph is not None:
                try:
                    graph_edge = Edge(
                        edge_type=edge_type.value,
                        from_vertex_id=source_entity_id,
                        to_vertex_id=target_entity_id,
                        properties={
                            "tenant_id": tenant_id,
                            "edge_id": edge["id"],
                            "confidence": str(confidence),
                            "confidence_tier": confidence_tier.value,
                            "reason_codes": ",".join(reason_codes or []),
                            "source_event_ids": ",".join(source_event_ids or []),
                        },
                    )
                    await self._graph.add_edge(graph_edge)
                except Exception as graph_exc:
                    logger.warning(
                        "Neptune mirror write failed (non-fatal): %s→%s: %s",
                        source_entity_id, target_entity_id, graph_exc,
                    )
            return edge
        except Exception as exc:
            logger.error(
                "graph_writer edge write failed: %s→%s type=%s: %s",
                source_entity_id, target_entity_id, edge_type.value, exc,
                exc_info=True,
            )
            self._metrics.record_graph_edge_error()
            return None
