"""
Aether Service — Identity Explainability API

Explainability surfaces for the identity continuity subsystem (blueprint §13.2).
Returns why a profile exists, which sources contributed, which evidence matched
/ was ignored / blocked the decision, the current graph version, and a natural-
language resolution decision summary.

Endpoints are tenant-scoped and gated by feature flags.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.logger.logger import get_logger

from .decision_evidence import DecisionType, IdentityDecisionEvidenceService
from .exceptions import IdentityError
from .graph_versioner import GraphVersioner as _GraphVersioner
from .models import ConfidenceTier, MergeDecision
from .repository import IdentityResolutionRepository
from .merge_ledger import MergeLedger
from .resolver import IdentityResolutionService
from .schemas import (
    AdminIdentityMergeRequest,
    AdminIdentityMergeResponse,
    AdminIdentityReviewQueueResponse,
    AdminIdentitySplitRequest,
    AdminIdentitySplitResponse,
    AdminIdentityReconcileRequest,
    AdminIdentityReconcileResponse,
    ReviewQueueEntry,
)

logger = get_logger("aether.service.identity.explainability")


class _ConfidenceBand:
    """Map a ConfidenceTier + veto state to a blueprint §8.2 confidence band."""

    BAND_THRESHOLDS = [
        ("very_high", 0.97),
        ("high", 0.90),
        ("medium", 0.70),
        ("low", 0.30),
    ]

    @classmethod
    def for_tier(cls, tier: ConfidenceTier, blocked: bool = False) -> str:
        if blocked:
            return "blocked"
        value = cls._tier_center(tier)
        for band, threshold in cls.BAND_THRESHOLDS:
            if value >= threshold:
                return band
        return "low"

    @staticmethod
    def _tier_center(tier: ConfidenceTier) -> float:
        centers = {
            ConfidenceTier.DETERMINISTIC: 1.0,
            ConfidenceTier.STRONG: 0.95,
            ConfidenceTier.PROBABLE: 0.80,
            ConfidenceTier.WEAK: 0.50,
            ConfidenceTier.BLOCKED: 0.0,
        }
        return centers.get(tier, 0.0)


def _confidence_band_from_decision(decision: dict) -> str:
    """Resolve the confidence_band that the explainability response exposes."""
    if decision.get("decision_type") in (
        DecisionType.REJECT.value,
        DecisionType.CONFLICT.value,
    ):
        return "blocked"
    tier = decision.get("confidence_tier", "")
    return _ConfidenceBand.for_tier(
        ConfidenceTier(tier) if tier else ConfidenceTier.WEAK,
        blocked=False,
    )


# ── Explainability service ─────────────────────────────────────────────────────


class IdentityExplainabilityService:
    """Build explainability payloads for a canonical entity / decision.

    Uses the existing decision-evidence store (IdentityDecisionEvidenceService)
    and the identity resolution repository to assemble the §13.2 response shape
    without re-implementing resolution logic.
    """

    def __init__(
        self,
        repo: Optional[IdentityResolutionRepository] = None,
        evidence_service: Optional[IdentityDecisionEvidenceService] = None,
        resolver: Optional[IdentityResolutionService] = None,
    ) -> None:
        self._repo = repo or IdentityResolutionRepository()
        self._evidence = evidence_service or IdentityDecisionEvidenceService()
        self._resolver = resolver

    # ── Profile identity explanation ──────────────────────────────────────────

    async def get_profile_identity_explanation(
        self,
        profile_id: str,
        tenant_id: str,
    ) -> dict:
        """Return the §13.2 explainability payload for a canonical profile.

        ``profile_id`` is the canonical entity id the caller wants explained.
        The response mirrors blueprint §13.2 exactly:

        - canonical_entity_id
        - confidence
        - confidence_band
        - source_identities
        - positive_evidence
        - negative_evidence
        - ignored_evidence
        - graph_version
        - resolution_decision_summary
        """
        decisions = await self._evidence.list_for_entity(
            tenant_id=tenant_id, entity_id=profile_id, limit=200
        )
        decision = self._most_recent_decision(decisions, profile_id)

        # ── Confidence / band ────────────────────────────────────────────────
        confidence = float(decision.get("confidence_score", 0.0)) if decision else 0.0
        band: str
        if decision:
            tier = decision.get("confidence_tier", "")
            blocked = decision.get("decision_type") in (
                DecisionType.REJECT.value,
                DecisionType.CONFLICT.value,
            )
            band = _ConfidenceBand.for_tier(
                ConfidenceTier(tier) if tier else ConfidenceTier.WEAK,
                blocked=blocked,
            )
        else:
            band = "low"

        # ── Source identities contributing to this profile ───────────────────
        source_identities = await self._source_identities_for_entity(
            tenant_id, profile_id
        )

        # ── Evidence buckets (positive / negative / ignored) ─────────────────
        positive_evidence: list[dict] = []
        negative_evidence: list[dict] = []
        ignored_evidence: list[dict] = []

        if decision:
            signals_used = decision.get("signals_used") or []
            signals_excluded = decision.get("signals_excluded") or []
            source_events = decision.get("source_events") or []
            source_connectors = decision.get("source_connectors") or []
            decision_type = decision.get("decision_type", "")
            reason_codes = decision.get("reason_codes") or []

            for sig in signals_used:
                positive_evidence.append(
                    self._evidence_entry(
                        signal=sig,
                        status="admitted",
                        reason_codes=reason_codes,
                        source_events=source_events,
                        source_connectors=source_connectors,
                        decision_type=decision_type,
                    )
                )

            for sig in signals_excluded:
                negative_evidence.append(
                    self._evidence_entry(
                        signal=sig,
                        status="excluded",
                        reason_codes=reason_codes,
                        source_events=source_events,
                        source_connectors=source_connectors,
                        decision_type=decision_type,
                    )
                )

            if decision_type in (
                DecisionType.REJECT.value,
                DecisionType.CONFLICT.value,
            ):
                negative_evidence.append(
                    self._evidence_entry(
                        signal="decision",
                        status="rejected",
                        reason_codes=reason_codes,
                        source_events=source_events,
                        source_connectors=source_connectors,
                        decision_type=decision_type,
                    )
                )

            ignored_evidence = await self._ignored_evidence_for_entity(
                tenant_id, profile_id, decision
            )

        # ── Graph version ────────────────────────────────────────────────────
        graph_version = await self._current_graph_version(tenant_id, profile_id)

        # ── Resolution decision summary ───────────────────────────────────────
        summary = self._resolution_decision_summary(
            decision=decision,
            entity_id=profile_id,
            tenant_id=tenant_id,
            source_identities=source_identities,
            positive=len(positive_evidence),
            negative=len(negative_evidence),
            ignored=len(ignored_evidence),
        )

        return {
            "canonical_entity_id": profile_id,
            "confidence": round(confidence, 4),
            "confidence_band": band,
            "source_identities": source_identities,
            "positive_evidence": positive_evidence,
            "negative_evidence": negative_evidence,
            "ignored_evidence": ignored_evidence,
            "graph_version": graph_version,
            "resolution_decision_summary": summary,
        }

    # ── Decision details ──────────────────────────────────────────────────────

    async def get_decision_details(
        self,
        decision_id: str,
        tenant_id: str,
    ) -> dict:
        """Return the full decision record with evidence for a decision_id."""
        record = await self._evidence._repo.get_for_tenant(tenant_id, decision_id)
        if record is None:
            return {
                "decision_id": decision_id,
                "found": False,
                "tenant_id": tenant_id,
            }

        return {
            "decision_id": decision_id,
            "found": True,
            "tenant_id": tenant_id,
            "entity_id": record.get("entity_id", ""),
            "subject_entity_id": record.get("subject_entity_id", ""),
            "decision_type": record.get("decision_type", ""),
            "signals_used": record.get("signals_used", []),
            "signals_excluded": record.get("signals_excluded", []),
            "source_events": record.get("source_events", []),
            "source_connectors": record.get("source_connectors", []),
            "consent_snapshot_hash": record.get("consent_snapshot_hash", ""),
            "policy_decision_id": record.get("policy_decision_id"),
            "confidence_score": record.get("confidence_score", 0.0),
            "confidence_tier": record.get("confidence_tier", ""),
            "merge_policy_version": record.get("merge_policy_version", ""),
            "operator_id": record.get("operator_id", ""),
            "review_status": record.get("review_status", ""),
            "created_at": record.get("created_at", ""),
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _most_recent_decision(
        decisions: list[dict], entity_id: str
    ) -> Optional[dict]:
        if not decisions:
            return None
        sorted_decisions = sorted(
            decisions,
            key=lambda d: d.get("created_at", ""),
            reverse=True,
        )
        for d in sorted_decisions:
            if d.get("entity_id") == entity_id or d.get("subject_entity_id") == entity_id:
                return d
        return sorted_decisions[0]

    async def _source_identities_for_entity(
        self, tenant_id: str, entity_id: str
    ) -> list[dict]:
        """List source-identity-like contributors to this canonical entity."""
        aliases = await self._repo.get_entity_aliases(tenant_id, entity_id)
        seen: set[str] = set()
        out: list[dict] = []
        for a in aliases:
            key = a.get("id") or ""
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "source_identity_id": a.get("id", ""),
                    "source": a.get("source", ""),
                    "source_platform": a.get("source_platform", ""),
                    "source_event_id": a.get("source_event_id", ""),
                    "alias_type": a.get("alias_type", ""),
                    "confidence": a.get("confidence", 0.0),
                    "first_seen_at": a.get("first_seen_at", ""),
                    "last_seen_at": a.get("last_seen_at", ""),
                    "alias_display_value_redacted": a.get(
                        "alias_display_value_redacted", ""
                    ),
                }
            )
        return out

    async def _ignored_evidence_for_entity(
        self,
        tenant_id: str,
        entity_id: str,
        decision: Optional[dict],
    ) -> list[dict]:
        """Evidence that was observed but did not sway the outcome."""
        if decision is None:
            return []

        used = set(decision.get("signals_used") or [])
        excluded = set(decision.get("signals_excluded") or [])
        known = used | excluded

        observations = await self._repo.get_observations_for_entity(
            tenant_id, entity_id, limit=200
        )
        ignored: list[dict] = []
        seen: set[str] = set()
        for obs in observations:
            obs_id = obs.get("id") or ""
            if obs_id in seen:
                continue
            seen.add(obs_id)
            sig_ref = obs.get("id", "")
            if sig_ref in known:
                continue
            ignored.append(
                {
                    "observation_id": obs.get("id", ""),
                    "signal_type": obs.get("signal_type", ""),
                    "source_platform": obs.get("source_platform", ""),
                    "source_event_id": obs.get("source_event_id", ""),
                    "observed_at": obs.get("observed_at", ""),
                    "reason": "insufficient_evidence",
                    "reason_codes": ["insufficient_evidence"],
                }
            )
        return ignored

    async def _current_graph_version(
        self, tenant_id: str, entity_id: str
    ) -> str:
        """Best-effort current graph version for the entity."""
        try:
            versioner = _GraphVersioner()
            version = await versioner.get_current_version(tenant_id)
            if version is not None:
                return str(version.version_number)
        except Exception:
            logger.debug(
                "graph_version unavailable for tenant=%s entity=%s",
                tenant_id,
                entity_id,
            )
        return "unknown"

    @staticmethod
    def _resolution_decision_summary(
        *,
        decision: Optional[dict],
        entity_id: str,
        tenant_id: str,
        source_identities: list[dict],
        positive: int,
        negative: int,
        ignored: int,
    ) -> str:
        if decision is None:
            return (
                f"No identity decision record found for entity {entity_id} in "
                f"tenant {tenant_id}. The profile may exist from a source that "
                f"has not yet emitted a resolution decision, or the decision "
                f"evidence store is unavailable for this tenant."
            )

        dtype = decision.get("decision_type", "")
        reason_codes = decision.get("reason_codes") or []
        confidence = decision.get("confidence_score", 0.0)
        operator_id = decision.get("operator_id", "")

        parts: list[str] = []
        parts.append(
            f"Entity {entity_id} in tenant {tenant_id} was resolved as "
            f"'{dtype}' with confidence {confidence:.2f}."
        )

        if operator_id:
            parts.append(f"The decision was made or approved by operator {operator_id}.")

        if reason_codes:
            parts.append("Reason codes: " + ", ".join(reason_codes) + ".")

        if source_identities:
            sources = ", ".join(
                s.get("source", "unknown") or "unknown"
                for s in source_identities[:5]
            )
            if len(source_identities) > 5:
                sources += f" (+{len(source_identities) - 5} more)"
            parts.append(
                f"Contributed by {len(source_identities)} source identity/"
                f"alias records ({sources})."
            )

        parts.append(
            f"Evidence breakdown: {positive} signal(s) admitted, "
            f"{negative} signal(s) excluded / blocked, "
            f"{ignored} signal(s) observed but ignored."
        )

        return " ".join(parts)

    @staticmethod
    def _evidence_entry(
        *,
        signal: str,
        status: str,
        reason_codes: list[str],
        source_events: list[str],
        source_connectors: list[str],
        decision_type: str,
    ) -> dict:
        return {
            "signal": signal,
            "status": status,
            "reason_codes": list(reason_codes),
            "source_events": list(source_events),
            "source_connectors": list(source_connectors),
            "decision_type": decision_type,
        }


class AdminIdentityService:
    """Thin service layer for admin identity operations (PR 8 admin endpoints).

    Wraps the existing resolver, merge ledger, split execution, and resolution
    replay so the route layer stays thin and provenance/flag checks stay in one
    place.
    """

    def __init__(
        self,
        resolver: Optional[IdentityResolutionService] = None,
        merge_ledger: Optional[MergeLedger] = None,
        graph_versioner: Optional[_GraphVersioner] = None,
        repo: Optional[IdentityResolutionRepository] = None,
    ) -> None:
        self._resolver = resolver
        self._merge_ledger = merge_ledger
        self._graph_versioner = graph_versioner or _GraphVersioner()
        self._repo = repo or IdentityResolutionRepository()

    async def manual_merge(
        self,
        tenant_id: str,
        source_entity_id: str,
        canonical_entity_id: str,
        reason: str,
        operator_id: str,
        confirmation_token: str,
        expected_graph_version: str,
    ) -> dict:
        """Execute a manual merge with stale-version rejection."""
        current = await self._graph_versioner.get_current_version(tenant_id)
        current_version = str(current.version_number) if current is not None else "0"

        if current_version != expected_graph_version:
            return {
                "merged": False,
                "canonical_entity_id": None,
                "graph_version_after": current_version,
                "decision_id": None,
                "rejection_reason": (
                    f"Stale graph version: expected {expected_graph_version}, "
                    f"current {current_version}."
                ),
                "error": None,
            }

        # Delegate to the resolver's operator_merge path (existing PR 4 seam).
        resolver = self._resolver
        if resolver is None:
            return {
                "merged": False,
                "canonical_entity_id": None,
                "graph_version_after": current_version,
                "decision_id": None,
                "rejection_reason": "Identity resolver unavailable.",
                "error": "unavailable",
            }

        decision = await resolver.operator_merge(
            tenant_id=tenant_id,
            primary_entity_id=canonical_entity_id,
            secondary_entity_id=source_entity_id,
            actor_id=operator_id,
            actor_type="operator",
            reason=reason,
        )

        return {
            "merged": True,
            "canonical_entity_id": decision.canonical_entity_id,
            "graph_version_after": current_version,
            "decision_id": decision.audit_id,
            "rejection_reason": None,
            "error": None,
        }

    async def manual_split(
        self,
        tenant_id: str,
        source_canonical_profile: str,
        target_split_plan: dict,
        source_identities_to_move: list[str],
        reason: str,
        operator_id: str,
        confirmation_token: str,
        expected_graph_version: str,
    ) -> dict:
        """Execute a manual split with stale-version rejection."""
        current = await self._graph_versioner.get_current_version(tenant_id)
        current_version = str(current.version_number) if current is not None else "0"

        if current_version != expected_graph_version:
            return {
                "split": False,
                "resulting_entity_ids": [],
                "split_event_id": None,
                "graph_version_after": current_version,
                "rejection_reason": (
                    f"Stale graph version: expected {expected_graph_version}, "
                    f"current {current_version}."
                ),
                "error": None,
            }

        resolver = self._resolver
        if resolver is None:
            return {
                "split": False,
                "resulting_entity_ids": [],
                "split_event_id": None,
                "graph_version_after": current_version,
                "rejection_reason": "Identity resolver unavailable.",
                "error": "unavailable",
            }

        mode = target_split_plan.get("mode", "create_new_entity")
        target_id = target_split_plan.get("target_entity_id")
        source_merge_event_id = target_split_plan.get("source_merge_event_id")

        result = await resolver.fragment_split(
            tenant_id=tenant_id,
            entity_id=source_canonical_profile,
            fragments={
                "alias_ids": source_identities_to_move,
                "observation_ids": [],
            },
            mode=mode,
            actor_id=operator_id,
            actor_type="operator",
            reason=reason,
            target_entity_id=target_id,
            source_merge_event_id=source_merge_event_id,
        )

        if not result.get("allowed"):
            return {
                "split": False,
                "resulting_entity_ids": [],
                "split_event_id": None,
                "graph_version_after": current_version,
                "rejection_reason": result.get("rejection_reason") or "split not allowed",
                "error": result.get("error"),
            }

        return {
            "split": True,
            "resulting_entity_ids": [result.get("resulting_entity_id")] if result.get("resulting_entity_id") else [],
            "split_event_id": result.get("split_event_id"),
            "graph_version_after": current_version,
            "rejection_reason": None,
            "error": None,
        }

    async def reconcile(
        self,
        tenant_id: str,
        trigger_type: str,
        trigger_id: str,
        identifier_type: Optional[str],
        identifier_hash: Optional[str],
        entity_id: Optional[str],
        reason: str,
    ) -> dict:
        """Re-run resolution for a tenant (resolution replay seam)."""
        from .resolution_replay import ResolutionReplayService

        replay = ResolutionReplayService(
            resolver=self._resolver,
            repo=self._repo,
        )

        result = await replay.request_replay(
            tenant_id=tenant_id,
            identifier_type=identifier_type or "",
            identifier_hash=identifier_hash or "",
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            policy_version="1.0.0",
        )

        return {
            "status": result.get("status", "unknown"),
            "tenant_id": tenant_id,
            "trigger_type": trigger_type,
            "trigger_id": trigger_id,
            "affected_entity_ids": result.get("affected", []),
            "decisions": [],
            "error": result.get("error"),
        }

    async def review_queue(self, tenant_id: str, limit: int = 50) -> list[dict]:
        """Return open conflicts/reviews for the tenant."""
        conflicts = await self._repo.get_conflicts(tenant_id, status="open", limit=limit)
        queue: list[dict] = []
        for c in conflicts:
            candidate_ids = c.get("candidate_entity_ids") or []
            candidate_a = candidate_ids[0] if len(candidate_ids) > 0 else ""
            candidate_b = candidate_ids[1] if len(candidate_ids) > 1 else ""
            queue.append(
                {
                    "conflict_id": c.get("id", ""),
                    "tenant_id": tenant_id,
                    "candidate_a": {"entity_id": candidate_a},
                    "candidate_b": {"entity_id": candidate_b},
                    "matching_evidence": [],
                    "conflicting_evidence": [],
                    "recommended_action": "review",
                    "confidence": c.get("confidence", 0.0),
                    "risk_level": "medium",
                    "affected_projections": ["profile_360", "journeys", "campaigns"],
                    "created_at": c.get("created_at", ""),
                    "status": c.get("status", "open"),
                }
            )
        return queue

    async def activation_status(self, tenant_id: str) -> dict:
        """Tenant activation dashboard data."""
        health = await self._repo.get_identity_health(tenant_id)
        return {
            "tenant_id": tenant_id,
            "historical_data_status": "available" if health.get("total_subjects", 0) > 0 else "empty",
            "sdk_status": "connected" if health.get("total_aliases", 0) > 0 else "not_connected",
            "resolution_counts": {
                "total_entities": health.get("total_subjects", 0),
                "total_aliases": health.get("total_aliases", 0),
                "total_clusters": health.get("total_clusters", 0),
                "recent_merges": health.get("recent_merges", 0),
                "recent_splits": health.get("recent_splits", 0),
            },
            "conflict_counts": {
                "open": health.get("open_conflicts", 0),
                "resolved": 0,
                "dismissed": 0,
            },
            "projection_restatement_status": "active",
            "computed_at": uuid.uuid4().hex,
        }
