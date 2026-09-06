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

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode
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
from services.fraud.evidence import (
    SIGNAL_TO_EVIDENCE_TYPE,
    normalize_persisted_evidence_refs,
)
from services.fraud.models import (
    FraudDecision,
    RiskAnnotation,
    decision_from_score,
    risk_tier_from_score,
)
from services.operational_intelligence.models import EvidenceRef
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

# ─────────────────────────────────────────────────────────────────────────────
# Signal weighting (uncalibrated heuristic — NOT a calibrated probability)
# ─────────────────────────────────────────────────────────────────────────────
#
# The composite risk_score below is a HANDCRAFTED heuristic: a bounded weighted
# sum of the *distinct detector signal types* that fired. It is not fit against
# real labeled fraud outcomes, so it must not be read as P(fraud) — only as a
# relative triage ordering. ``SIGNAL_WEIGHTS_VERSION`` versions this weight
# scheme and is persisted on every decision so a stored score is always
# traceable to the formula that produced it. Bump it whenever a weight, a
# family grouping, or the damping factor changes.
#
# v1.0.0 → naive ``len(distinct signal_types) * 10`` (+25 circular). Each
#          distinct type added weight independently, which double-counts
#          structurally-correlated signals (shared IP + shared device + shared
#          wallet all co-occur for a single household / NAT / device farm;
#          circular_transfer and split_merge are two views of one layering
#          topology).
# v1.1.0 → group signals into structural families and apply diminishing returns
#          to correlated siblings within a family, so correlated evidence is not
#          naively additively double-counted. Independent families still add.
SIGNAL_WEIGHTS_VERSION = "1.1.0"

# Points contributed by the first (strongest) signal in each structural family.
_SIGNAL_BASE_WEIGHT = 10.0

# Structurally-correlated signals share a family. Members of the same family
# tend to co-occur for a single underlying cause, so their contributions must
# not be summed at full weight.
_SIGNAL_FAMILIES: dict[str, str] = {
    # Shared-infrastructure / co-location: common in households, NAT gateways,
    # shared Wi-Fi, and device farms — structurally correlated, not independent.
    "shared_ip": "co_location",
    "shared_device": "co_location",
    "shared_wallet": "co_location",
    # Fund-layering topology: circular transfers and split/merge are two lenses
    # on the same movement pattern.
    "circular_transfer": "layering",
    "split_merge": "layering",
    # Coordinated multi-account behaviour.
    "reward_farming": "coordination",
    "agentic_delegation_abuse": "coordination",
    # Standalone.
    "commerce_abuse": "commerce",
}

# Weight multiplier applied to the 2nd, 3rd, … distinct signal *within the same
# family*. < 1.0 => correlated siblings contribute with diminishing returns
# instead of full additive weight.
_CORRELATED_SIGNAL_DAMPING = 0.4

# Extra weight for a confirmed circular-transfer topology (high-severity,
# genuinely distinct evidence of laundering intent).
_CIRCULAR_TRANSFER_BONUS = 25.0


def compute_signal_risk_score(signal_types: list[str]) -> float:
    """Composite risk score in [0, 100] from the distinct detector signal types.

    This is an UNCALIBRATED heuristic (see ``SIGNAL_WEIGHTS_VERSION``), not a
    probability. Signals are grouped into structural families; the first signal
    in a family contributes ``_SIGNAL_BASE_WEIGHT`` and each additional
    correlated sibling is damped by ``_CORRELATED_SIGNAL_DAMPING``. This stops
    structurally-correlated evidence (shared IP/device/wallet; circular +
    split_merge) from being naively additively double-counted, while genuinely
    independent families still add their full base weight.
    """
    distinct = set(signal_types)

    by_family: dict[str, int] = {}
    for signal in distinct:
        family = _SIGNAL_FAMILIES.get(signal, signal)
        by_family[family] = by_family.get(family, 0) + 1

    base = 0.0
    for count in by_family.values():
        # First (strongest) signal at full weight; correlated siblings damped.
        base += _SIGNAL_BASE_WEIGHT
        base += _SIGNAL_BASE_WEIGHT * _CORRELATED_SIGNAL_DAMPING * (count - 1)

    base = min(base, 100.0)
    circular_bonus = _CIRCULAR_TRANSFER_BONUS if "circular_transfer" in distinct else 0.0
    return round(min(base + circular_bonus, 100.0), 4)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evidence_uri(signal: str, detail: dict) -> str:
    """Encode one detector result into an internal (non-fetchable) aether:// ref.

    The canonical ``EvidenceRef`` has no free-form description/metadata slot, so
    the detector signal name and its detail payload are carried in the internal
    ``uri`` — the same convention ``services/fraud_networks/evidence.py`` uses —
    preserving traceability without re-introducing a fraud-local shape.
    """
    payload = json.dumps(detail, sort_keys=True, default=str, separators=(",", ":"))
    return "aether://fraud/decision/evidence?" + urlencode(
        {"signal": signal, "detail": payload}
    )


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
                        # One-way legacy compat: JSONB rows written before the
                        # EvidenceRef convergence may hold the old fraud-local
                        # shape (ref_id/ref_type/...), which the canonical
                        # EvidenceRef would reject. Normalize to canonical.
                        row = dict(existing)
                        if existing.get("evidence_refs"):
                            row["evidence_refs"] = normalize_persisted_evidence_refs(
                                existing["evidence_refs"]
                            )
                        return FraudDecision(**row)
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

        now = _utc_now()
        # Canonical EvidenceRef (id/type/source/observedAt/confidence/uri).
        # Detector outputs render per signal like fraud_networks/evidence.py;
        # the signal + detail payload ride in the internal uri.
        evidence_refs = [
            EvidenceRef(
                id=str(uuid4()),
                type=SIGNAL_TO_EVIDENCE_TYPE.get(signal, "model_output"),
                source="fraud_evaluator",
                observedAt=now,
                uri=_evidence_uri(signal, detail),
            )
            for signal, _, detail in all_results
        ]

        # Composite risk score (UNCALIBRATED heuristic, versioned by
        # SIGNAL_WEIGHTS_VERSION): structurally-correlated signal families are
        # damped so shared IP/device/wallet and circular/split_merge are not
        # naively additively double-counted. See compute_signal_risk_score.
        risk_score = compute_signal_risk_score(signal_types)

        risk_tier = risk_tier_from_score(risk_score)
        outcome = decision_from_score(risk_score)
        review_required = risk_tier in ("high", "critical")

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
            model_versions={"signal_weights": SIGNAL_WEIGHTS_VERSION},
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
                # Traceability: which weight scheme produced this risk_score, and
                # a truthful note that the score is not a calibrated probability.
                "signal_weights_version": SIGNAL_WEIGHTS_VERSION,
                "risk_score_kind": "uncalibrated_heuristic",
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
            # Fail CLOSED: an evaluation failure must NOT silently become a
            # benign/cleared outcome. Route to human review with an elevated
            # (undetermined) tier rather than defaulting to monitor+low+score 0,
            # which read as "clear". risk_score is not a computed assessment here.
            decision="review",
            risk_score=0.0,
            risk_tier="medium",
            review_state="required",
            evaluation_state="failed",
            evaluated_at=now,
            valid_from=now,
            machine_explanation=(
                "Evaluation failed; fail-closed to human review (not cleared). "
                "risk_score is not a computed assessment."
            ),
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
