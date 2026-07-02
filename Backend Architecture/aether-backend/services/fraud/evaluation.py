"""Fraud Evaluation Service — automatic, idempotent, event-driven.

This module provides:

  FraudEvaluationService.evaluate_subject()
      Core evaluation: assembles features from real data, runs detectors,
      produces a durable FraudDecision, and writes risk annotations back
      to canonical_activity and journey_steps.

  evaluate_on_canonical_activity()
      Entry point for activity-ingestion events.

  evaluate_on_entity_event()
      Entry point for identity/wallet/delegation events.

  evaluate_on_commerce_event()
      Entry point for order/refund/reward events.

Design:
  - Idempotent: same subject evaluated within TTL returns existing decision.
  - Primary ingestion does NOT wait for evaluation (caller fires-and-forgets).
  - Evaluation failure is isolated: never silently becomes a 'clear' outcome.
  - Tenant isolation enforced at every data-fetch boundary.
  - Infinite event cycles prevented via recursion depth guard.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from repositories.repos import (
    DelegationRepository,
    FraudDecisionRepository,
    OrderRepository,
    RefundRepository,
    RewardEventRepository,
    SessionRepository,
    TransferRepository,
    WalletRepository,
)
from services.fraud.models import (
    EvidenceRef,
    FraudDecision,
    RiskAnnotation,
    decision_from_score,
    risk_tier_from_score,
)
from services.fraud_networks.detectors import (
    detect_agentic_delegation_abuse,
    detect_circular_transfers,
    detect_commerce_abuse,
    detect_reward_farming,
    detect_shared_device,
    detect_shared_ip,
    detect_split_merge,
    detect_wallet_cluster,
)
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.fraud.evaluation")

_EVALUATION_TTL_SECONDS = 300  # re-evaluate subjects changed within 5 min
_MAX_RECURSION_DEPTH = 1       # prevent evaluation loops

DETECTOR_VERSION = "1.0.0"
POLICY_VERSION = "v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_annotation_from_decision(decision: FraudDecision) -> RiskAnnotation:
    return RiskAnnotation(
        risk_score=decision.risk_score,
        risk_tier=decision.risk_tier,
        fraud_status="evaluated",
        fraud_disposition=decision.decision,
        fraud_decision_id=decision.decision_id,
        fraud_network_ids=decision.fraud_network_ids,
        fraud_signal_types=decision.signal_types,
        fraud_evidence_refs=[e.model_dump() for e in decision.evidence_refs],
        risk_evaluated_at=decision.evaluated_at,
        risk_model_version=DETECTOR_VERSION,
        risk_policy_version=POLICY_VERSION,
        risk_explanation=decision.machine_explanation,
        risk_evaluation_state="evaluated",
    )


def _build_annotation_failed() -> RiskAnnotation:
    return RiskAnnotation(
        fraud_status="evaluation_failed",
        risk_evaluation_state="failed",
        risk_evaluated_at=_utc_now(),
    )


class FraudEvaluationService:
    """Core fraud evaluation service.

    Fetches real feature data for the subject, runs all detectors,
    computes a composite risk score, persists a durable FraudDecision,
    and writes risk annotations back to canonical_activity / journey_steps.
    """

    def __init__(self) -> None:
        self._decisions = FraudDecisionRepository()
        self._transfers = TransferRepository()
        self._wallets = WalletRepository()
        self._sessions = SessionRepository()
        self._delegations = DelegationRepository()
        self._rewards = RewardEventRepository()
        self._orders = OrderRepository()
        self._refunds = RefundRepository()

    async def evaluate_subject(
        self,
        *,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        entity_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        cluster_id: Optional[str] = None,
        wallet_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        activity_id: Optional[str] = None,
        journey_id: Optional[str] = None,
        journey_version_id: Optional[str] = None,
        force: bool = False,
        _depth: int = 0,
    ) -> FraudDecision:
        """Evaluate a subject and return a durable FraudDecision.

        Args:
            force: bypass TTL-based deduplication and re-evaluate.
            _depth: internal recursion guard — do not set externally.
        """
        if _depth > _MAX_RECURSION_DEPTH:
            logger.warning(
                "fraud_evaluation_max_recursion",
                extra={"tenant_id": tenant_id, "subject_id": subject_id},
            )
            return self._failed_decision(tenant_id, subject_type, subject_id)

        if not force:
            existing = await self._decisions.get_current_for_subject(
                tenant_id, subject_type, subject_id
            )
            if existing:
                evaluated_at = existing.get("evaluated_at", "")
                try:
                    age = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
                    ).total_seconds()
                    if age < _EVALUATION_TTL_SECONDS:
                        return FraudDecision(**existing)
                except (ValueError, TypeError):
                    pass

        try:
            decision = await self._run_evaluation(
                tenant_id=tenant_id,
                subject_type=subject_type,
                subject_id=subject_id,
                entity_id=entity_id,
                profile_id=profile_id,
                cluster_id=cluster_id,
                wallet_id=wallet_id,
                agent_id=agent_id,
                activity_id=activity_id,
                journey_id=journey_id,
                journey_version_id=journey_version_id,
            )
        except Exception as exc:
            logger.error(
                "fraud_evaluation_failed",
                extra={"tenant_id": tenant_id, "subject_id": subject_id, "error": str(exc)},
            )
            metrics.increment("fraud_evaluation_failures_total", labels={"tenant_id": tenant_id})
            return self._failed_decision(tenant_id, subject_type, subject_id)

        # Persist — supersede any prior active decision
        prior = await self._decisions.get_current_for_subject(
            tenant_id, subject_type, subject_id
        )
        await self._decisions.create(decision.model_dump())
        if prior:
            await self._decisions.supersede(
                prior["decision_id"], decision.decision_id, tenant_id
            )

        # Write risk annotations back
        if activity_id:
            await self._annotate_activity(tenant_id, activity_id, decision)
        if journey_id:
            await self._annotate_journey_steps(tenant_id, journey_id, decision)

        metrics.increment(
            "fraud_evaluations_total",
            labels={"tenant_id": tenant_id, "decision": decision.decision, "risk_tier": decision.risk_tier},
        )
        logger.info(
            "fraud_evaluation_complete",
            extra={
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "decision": decision.decision,
                "risk_score": decision.risk_score,
                "risk_tier": decision.risk_tier,
                "signal_count": len(decision.signal_types),
            },
        )
        return decision

    async def _run_evaluation(
        self,
        *,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
        entity_id: Optional[str],
        profile_id: Optional[str],
        cluster_id: Optional[str],
        wallet_id: Optional[str],
        agent_id: Optional[str],
        activity_id: Optional[str],
        journey_id: Optional[str],
        journey_version_id: Optional[str],
    ) -> FraudDecision:
        # Gather the set of entity IDs to fetch features for
        entity_ids: list[str] = []
        if entity_id:
            entity_ids.append(entity_id)
        if subject_type == "entity" and subject_id not in entity_ids:
            entity_ids.append(subject_id)

        # Fetch real feature data
        sessions = await self._sessions.list_for_entities(entity_ids, tenant_id)
        wallet_links: list[dict] = []
        for eid in entity_ids:
            rows = await self._wallets.find_many(
                filters={"owner_entity_id": eid, "tenant_id": tenant_id}, limit=50
            )
            for w in rows:
                wallet_links.append({
                    "entity_id": eid,
                    "wallet_address": w.get("address", ""),
                    "chain": w.get("chain", "unknown"),
                })

        transfers: list[dict] = []
        for eid in entity_ids:
            out = await self._transfers.find_many(
                filters={"from_entity_id": eid, "tenant_id": tenant_id}, limit=200
            )
            inp = await self._transfers.find_many(
                filters={"to_entity_id": eid, "tenant_id": tenant_id}, limit=200
            )
            transfers.extend(out + inp)

        delegations: list[dict] = []
        for eid in entity_ids:
            rows = await self._delegations.find_many(
                filters={"principal_id": eid, "tenant_id": tenant_id}, limit=100
            )
            delegations.extend(rows)
            rows2 = await self._delegations.find_many(
                filters={"agent_id": eid, "tenant_id": tenant_id}, limit=100
            )
            delegations.extend(rows2)

        reward_events = await self._rewards.list_for_entities(entity_ids, tenant_id)
        orders = await self._orders.list_for_entities(entity_ids, tenant_id)
        refunds = await self._refunds.list_for_entities(entity_ids, tenant_id)

        # Run detectors
        all_results = (
            detect_shared_device(sessions)
            + detect_shared_ip(sessions)
            + detect_wallet_cluster(wallet_links)
            + detect_circular_transfers(transfers, max_depth=4)
            + detect_split_merge(transfers)
            + detect_reward_farming(reward_events)
            + detect_agentic_delegation_abuse(delegations, transfers)
            + detect_commerce_abuse(orders, refunds)
        )

        signal_types = list({r[0] for r in all_results})
        reason_codes = self._signal_to_reason_codes(signal_types)
        evidence_refs = [
            EvidenceRef(
                ref_type=signal,
                ref_source="fraud_evaluator",
                description=str(detail),
                metadata=detail,
            )
            for signal, _, detail in all_results
        ]

        # Score: 10 pts per signal, capped at 100; circular transfer adds 25
        base = min(len(signal_types) * 10.0, 100.0)
        circular_bonus = 25.0 if "circular_transfer" in signal_types else 0.0
        risk_score = min(base + circular_bonus, 100.0)

        risk_tier = risk_tier_from_score(risk_score)
        outcome = decision_from_score(risk_score)
        review_required = risk_tier in ("high", "critical")

        now = _utc_now()
        explanation = (
            f"Detected {len(signal_types)} signal(s): {', '.join(signal_types) or 'none'}. "
            f"Risk score: {risk_score:.1f}/{100}."
        )

        return FraudDecision(
            decision_id=str(uuid4()),
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            entity_id=entity_id,
            profile_id=profile_id,
            cluster_id=cluster_id,
            wallet_id=wallet_id,
            agent_id=agent_id,
            activity_id=activity_id,
            journey_id=journey_id,
            journey_version_id=journey_version_id,
            fraud_network_ids=[],
            flow_trace_ids=[],
            decision=outcome,
            risk_score=risk_score,
            risk_tier=risk_tier,
            signal_types=signal_types,
            reason_codes=reason_codes,
            evidence_refs=evidence_refs,
            machine_explanation=explanation,
            detector_versions={"all_detectors": DETECTOR_VERSION},
            model_versions={},
            policy_version=POLICY_VERSION,
            evaluation_state="evaluated",
            evaluated_at=now,
            valid_from=now,
            valid_until=None,
            status="active",
            review_state="required" if review_required else "not_required",
            metadata={
                "session_count": len(sessions),
                "transfer_count": len(transfers),
                "wallet_count": len(wallet_links),
                "delegation_count": len(delegations),
                "reward_event_count": len(reward_events),
                "order_count": len(orders),
                "refund_count": len(refunds),
            },
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _signal_to_reason_codes(signal_types: list[str]) -> list[str]:
        mapping = {
            "shared_device": "SHARED_DEVICE_FINGERPRINT",
            "shared_ip": "SHARED_IP_ADDRESS",
            "shared_wallet": "SHARED_WALLET_ADDRESS",
            "circular_transfer": "CIRCULAR_FUND_MOVEMENT",
            "split_merge": "SPLIT_MERGE_LAYERING",
            "reward_farming": "COORDINATED_REWARD_FARMING",
            "agentic_delegation_abuse": "AGENT_DELEGATION_FAN_OUT",
            "commerce_abuse": "HIGH_REFUND_RATE",
        }
        return [mapping.get(s, s.upper()) for s in signal_types]

    def _failed_decision(
        self,
        tenant_id: str,
        subject_type: str,
        subject_id: str,
    ) -> FraudDecision:
        now = _utc_now()
        return FraudDecision(
            decision_id=str(uuid4()),
            tenant_id=tenant_id,
            subject_type=subject_type,
            subject_id=subject_id,
            decision="monitor",
            risk_score=0.0,
            risk_tier="low",
            evaluation_state="failed",
            evaluated_at=now,
            valid_from=now,
            machine_explanation="Evaluation failed; defaulting to monitor pending retry.",
            created_at=now,
            updated_at=now,
        )

    async def _annotate_activity(
        self,
        tenant_id: str,
        activity_id: str,
        decision: FraudDecision,
    ) -> None:
        from services.measurement.repositories.activity_repo import ActivityRepository
        repo = ActivityRepository()
        annotation = _build_annotation_from_decision(decision)
        try:
            await repo.update_risk_annotation(tenant_id, activity_id, annotation.model_dump())
        except Exception as exc:
            logger.warning(
                "fraud_annotation_activity_failed",
                extra={"activity_id": activity_id, "error": str(exc)},
            )

    async def _annotate_journey_steps(
        self,
        tenant_id: str,
        journey_id: str,
        decision: FraudDecision,
    ) -> None:
        from services.measurement.repositories.journey_step_repo import JourneyStepRepository
        repo = JourneyStepRepository()
        annotation = _build_annotation_from_decision(decision)
        try:
            await repo.update_risk_annotation_for_journey(
                tenant_id, journey_id, annotation.model_dump()
            )
        except Exception as exc:
            logger.warning(
                "fraud_annotation_journey_failed",
                extra={"journey_id": journey_id, "error": str(exc)},
            )


# ═══════════════════════════════════════════════════════════════════════════
# EVENT-DRIVEN ENTRY POINTS
# ═══════════════════════════════════════════════════════════════════════════

_evaluator = FraudEvaluationService()


async def evaluate_on_canonical_activity(activity: dict) -> None:
    """Trigger fraud evaluation when a canonical activity is ingested.

    Called fire-and-forget from the ingestion pipeline; never raises.
    """
    tenant_id = activity.get("tenant_id", "")
    activity_id = activity.get("activity_id")
    entity_id = activity.get("profile_id") or activity.get("anonymous_id")
    if not tenant_id or not entity_id:
        return
    try:
        await _evaluator.evaluate_subject(
            tenant_id=tenant_id,
            subject_type="entity",
            subject_id=entity_id,
            entity_id=entity_id,
            activity_id=str(activity_id) if activity_id else None,
        )
    except Exception as exc:
        logger.error(
            "evaluate_on_canonical_activity_error",
            extra={"tenant_id": tenant_id, "activity_id": str(activity_id), "error": str(exc)},
        )


async def evaluate_on_entity_event(
    tenant_id: str,
    entity_id: str,
    wallet_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> None:
    """Trigger fraud evaluation on identity/wallet/delegation events."""
    if not tenant_id or not entity_id:
        return
    try:
        await _evaluator.evaluate_subject(
            tenant_id=tenant_id,
            subject_type="entity",
            subject_id=entity_id,
            entity_id=entity_id,
            wallet_id=wallet_id,
            agent_id=agent_id,
        )
    except Exception as exc:
        logger.error(
            "evaluate_on_entity_event_error",
            extra={"tenant_id": tenant_id, "entity_id": entity_id, "error": str(exc)},
        )


async def evaluate_on_commerce_event(
    tenant_id: str,
    entity_id: str,
    activity_id: Optional[str] = None,
) -> None:
    """Trigger fraud evaluation on order/refund/reward events."""
    if not tenant_id or not entity_id:
        return
    try:
        await _evaluator.evaluate_subject(
            tenant_id=tenant_id,
            subject_type="entity",
            subject_id=entity_id,
            entity_id=entity_id,
            activity_id=activity_id,
            force=True,  # commerce events always warrant a fresh evaluation
        )
    except Exception as exc:
        logger.error(
            "evaluate_on_commerce_event_error",
            extra={"tenant_id": tenant_id, "entity_id": entity_id, "error": str(exc)},
        )
