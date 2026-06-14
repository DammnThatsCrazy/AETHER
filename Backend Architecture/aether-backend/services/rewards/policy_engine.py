"""
Aether Backend — Reward Policy Engine

Evaluates reward eligibility by applying a sequence of gates to an event.
Every denial includes an explicit reason; no silent failures.

Architecture:
    RewardPolicyEngine.evaluate() is called with pre-resolved attribution,
    fraud, consent, and identity inputs. It queries durable campaign/rule
    repositories, applies gates in order, and returns a PolicyDecision.

Gate evaluation order:
    1. Campaign active + time window
    2. Rule active + event type match + channel + properties
    3. Consent
    4. Identity confidence
    5. Wallet binding confidence
    6. Fraud decision
    7. Attribution weight + confidence
    8. Cooldown
    9. Per-user cap
    10. Total uses cap
    11. Budget policy (observational)
    12. Idempotency (return existing if duplicate key)

The engine never holds, transfers, or distributes rewards.
See docs/source-of-truth/REWARD_NO_CUSTODY_MODEL.md.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from services.rewards.repositories import (
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardRuleRepository,
)
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.policy_engine")


# ═══════════════════════════════════════════════════════════════════════════
# INPUT MODELS
# ═══════════════════════════════════════════════════════════════════════════

class AttributionResultInput(BaseModel):
    attribution_result_id: str
    model: str = "unknown"
    attribution_weight: float = 0.0
    confidence: float = 0.0
    journey_id: Optional[str] = None
    campaign_id: Optional[str] = None
    channel: Optional[str] = None
    source: Optional[str] = None
    medium: Optional[str] = None
    referrer: Optional[str] = None


class FraudDecisionInput(BaseModel):
    fraud_decision_id: str
    score: float = 0.0
    decision: str = "approve"   # approve | review | reject | block
    signals: dict = Field(default_factory=dict)
    model_version: Optional[str] = None


class ConsentSnapshotInput(BaseModel):
    consent_snapshot_id: str
    purposes_granted: list[str] = Field(default_factory=list)
    purposes_denied: list[str] = Field(default_factory=list)


class IdentityInput(BaseModel):
    user_id: Optional[str] = None
    account_ref: Optional[str] = None
    wallet_address: Optional[str] = None
    identity_cluster_id: Optional[str] = None
    actor_id: Optional[str] = None
    journey_id: Optional[str] = None
    identity_confidence: float = 1.0
    wallet_binding_confidence: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════
# DECISION OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

class PolicyDecision(BaseModel):
    eligible: bool
    decision: str
    decision_reason: Optional[str] = None
    denial_reason: Optional[str] = None
    campaign_id: Optional[str] = None
    rule_id: Optional[str] = None
    rule: Optional[dict] = None
    campaign: Optional[dict] = None
    execution_mode: Optional[str] = None
    rail: Optional[str] = None
    attribution: Optional[dict] = None
    fraud: Optional[dict] = None
    identity: Optional[dict] = None
    next_action: Optional[dict] = None
    reward: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════════════════
# POLICY ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class RewardPolicyEngine:
    """
    Stateless policy engine: takes pre-resolved inputs, queries repositories,
    and returns an explainable PolicyDecision.
    """

    # Fraud decision → policy outcome
    _FRAUD_DECISION_MAP = {
        "approve": "continue",
        "review": "needs_review",
        "reject": "blocked_fraud",
        "block": "blocked_fraud",
    }

    async def evaluate(
        self,
        *,
        tenant_id: str,
        project_id: Optional[str],
        event_type: str,
        event_channel: Optional[str],
        event_properties: dict,
        attribution: Optional[AttributionResultInput],
        fraud: Optional[FraudDecisionInput],
        consent: Optional[ConsentSnapshotInput],
        identity: IdentityInput,
        idempotency_key: Optional[str],
        recommend_only_without_attribution: bool = False,
        campaign_repo: RewardCampaignRepository,
        rule_repo: RewardRuleRepository,
        decision_repo: RewardDecisionRepository,
    ) -> PolicyDecision:
        env = os.getenv("AETHER_ENV", "local").lower()
        is_local = env in ("local", "test")

        # ── Idempotency check ────────────────────────────────────────────
        if idempotency_key:
            existing = await decision_repo.get_by_idempotency_key(tenant_id, idempotency_key)
            if existing:
                logger.info(f"Idempotent decision returned: key={idempotency_key} tenant={tenant_id}")
                metrics.increment("rewards_duplicate_idempotency_total", labels={"tenant_id": tenant_id})
                return self._decision_from_record(existing)

        # ── Collect active campaigns ─────────────────────────────────────
        campaigns = await campaign_repo.get_active_for_event(tenant_id, project_id)
        if not campaigns:
            return PolicyDecision(
                eligible=False,
                decision="no_matching_rule",
                denial_reason="No active reward campaigns configured for this tenant",
            )

        # ── Evaluate each campaign in order ──────────────────────────────
        for campaign in campaigns:
            rules = await rule_repo.list_for_campaign(campaign["id"], tenant_id)
            for rule in rules:
                decision = await self._evaluate_rule(
                    rule=rule,
                    campaign=campaign,
                    event_type=event_type,
                    event_channel=event_channel,
                    event_properties=event_properties,
                    attribution=attribution,
                    fraud=fraud,
                    consent=consent,
                    identity=identity,
                    decision_repo=decision_repo,
                    is_local=is_local,
                    recommend_only_without_attribution=recommend_only_without_attribution,
                )
                if decision is not None:
                    metrics.increment(
                        "rewards_evaluations_total",
                        labels={"tenant_id": tenant_id, "decision": decision.decision},
                    )
                    if decision.eligible:
                        metrics.increment("rewards_eligible_total", labels={"tenant_id": tenant_id})
                    else:
                        metrics.increment("rewards_ineligible_total", labels={"tenant_id": tenant_id, "reason": decision.decision})
                    return decision

        return PolicyDecision(
            eligible=False,
            decision="no_matching_rule",
            denial_reason=f"No rule matched event_type={event_type!r} in any active campaign",
        )

    # ── Rule-level evaluation ────────────────────────────────────────────

    async def _evaluate_rule(
        self,
        *,
        rule: dict,
        campaign: dict,
        event_type: str,
        event_channel: Optional[str],
        event_properties: dict,
        attribution: Optional[AttributionResultInput],
        fraud: Optional[FraudDecisionInput],
        consent: Optional[ConsentSnapshotInput],
        identity: IdentityInput,
        decision_repo: RewardDecisionRepository,
        is_local: bool,
        recommend_only_without_attribution: bool,
    ) -> Optional[PolicyDecision]:
        """
        Evaluate a single rule. Returns None if the rule is irrelevant
        (event type mismatch), or a PolicyDecision for any other outcome.
        """
        if not rule.get("active", True):
            return None

        event_types = rule.get("event_types", [])
        if event_type not in event_types:
            return None

        campaign_id = campaign["id"]
        rule_id = rule["id"]
        tenant_id = campaign["tenant_id"]
        execution_mode = rule.get("execution_mode") or campaign.get("default_execution_mode", "recommend_only")
        rail = rule.get("rail") or campaign.get("default_rail", "recommend_only")

        def _deny(decision: str, reason: str) -> PolicyDecision:
            return PolicyDecision(
                eligible=False,
                decision=decision,
                denial_reason=reason,
                campaign_id=campaign_id,
                rule_id=rule_id,
                execution_mode=execution_mode,
                rail=rail,
                attribution=self._attr_summary(attribution),
                fraud=self._fraud_summary(fraud),
                identity=self._identity_summary(identity),
            )

        # ── 1. Campaign time window ──────────────────────────────────────
        now = datetime.now(timezone.utc)
        start = campaign.get("start_time")
        end = campaign.get("end_time")
        if start and now.isoformat() < start:
            return None  # Campaign not yet active; skip silently
        if end and now.isoformat() > end:
            return None  # Campaign expired; skip silently

        # ── 2. Required channel ──────────────────────────────────────────
        required_channel = rule.get("required_channel")
        if required_channel and event_channel != required_channel:
            return _deny("ineligible", f"Channel mismatch: required={required_channel!r} got={event_channel!r}")

        # ── 3. Required properties ───────────────────────────────────────
        req_props = rule.get("required_properties") or {}
        for key, expected in req_props.items():
            if event_properties.get(key) != expected:
                return _deny("ineligible", f"Property {key!r} required={expected!r} got={event_properties.get(key)!r}")

        # ── 4. Consent ───────────────────────────────────────────────────
        required_purposes = rule.get("requires_consent_purposes") or []
        if required_purposes:
            if consent is None:
                if not is_local:
                    return _deny("blocked_consent", f"Consent snapshot required for purposes: {required_purposes}")
            else:
                missing = [p for p in required_purposes if p not in consent.purposes_granted]
                if missing:
                    metrics.increment("rewards_blocked_consent_total", labels={"tenant_id": tenant_id})
                    return _deny("blocked_consent", f"Required consent purposes not granted: {missing}")

        # ── 5. Identity confidence ───────────────────────────────────────
        identity_conf_min = float(rule.get("identity_confidence_min", 0.0))
        if identity.identity_confidence < identity_conf_min:
            return _deny("blocked_identity", f"Identity confidence {identity.identity_confidence:.3f} below minimum {identity_conf_min:.3f}")

        # ── 6. Wallet binding confidence ─────────────────────────────────
        requires_wallet = rule.get("requires_wallet", False)
        wallet_conf_min = float(rule.get("wallet_binding_confidence_min", 0.0))
        if requires_wallet:
            if not identity.wallet_address:
                return _deny("blocked_wallet_binding", "Wallet address required but not provided")
            if identity.wallet_binding_confidence < wallet_conf_min:
                return _deny(
                    "blocked_wallet_binding",
                    f"Wallet binding confidence {identity.wallet_binding_confidence:.3f} below minimum {wallet_conf_min:.3f}",
                )

        # ── 7. Fraud decision ────────────────────────────────────────────
        if fraud is None:
            if not is_local:
                return _deny("needs_review", "Fraud decision required in non-local environments")
        else:
            max_fraud = float(rule.get("max_fraud_score", 40.0))
            fraud_outcome = self._FRAUD_DECISION_MAP.get(fraud.decision, "needs_review")
            if fraud_outcome == "blocked_fraud":
                metrics.increment("rewards_blocked_fraud_total", labels={"tenant_id": tenant_id})
                return _deny("blocked_fraud", f"Fraud decision={fraud.decision!r} score={fraud.score:.1f}")
            if fraud_outcome == "needs_review" or fraud.score > max_fraud:
                return _deny("needs_review", f"Fraud review required: decision={fraud.decision!r} score={fraud.score:.1f} max={max_fraud:.1f}")

        # ── 8. Attribution weight + confidence ───────────────────────────
        if attribution is None:
            if not is_local and not recommend_only_without_attribution:
                return _deny("ineligible", "Attribution result required (or set recommend_only_without_attribution=true)")
        else:
            min_weight = float(rule.get("min_attribution_weight", 0.0))
            min_conf = float(rule.get("min_attribution_confidence", 0.0))
            if attribution.attribution_weight < min_weight:
                return _deny(
                    "ineligible",
                    f"Attribution weight {attribution.attribution_weight:.4f} below minimum {min_weight:.4f}",
                )
            if attribution.confidence < min_conf:
                return _deny(
                    "ineligible",
                    f"Attribution confidence {attribution.confidence:.4f} below minimum {min_conf:.4f}",
                )

        # ── 9. Cooldown ──────────────────────────────────────────────────
        cooldown_seconds = int(rule.get("cooldown_seconds", 86400))
        if cooldown_seconds > 0:
            last_at = await decision_repo.get_last_eligible_at(
                tenant_id, campaign_id, identity.user_id, identity.wallet_address
            )
            if last_at:
                elapsed = time.time() - _parse_ts(last_at)
                if elapsed < cooldown_seconds:
                    remaining = int(cooldown_seconds - elapsed)
                    return _deny("blocked_cooldown", f"Cooldown active: {remaining}s remaining")

        # ── 10. Per-user cap ─────────────────────────────────────────────
        max_per_user = int(rule.get("max_per_user", 1))
        if max_per_user > 0:
            user_count = await decision_repo.get_eligible_count(
                tenant_id, campaign_id, identity.user_id, identity.wallet_address
            )
            if user_count >= max_per_user:
                return _deny("blocked_cap", f"Per-user claim cap reached: {user_count}/{max_per_user}")

        # ── 11. Total uses cap ───────────────────────────────────────────
        max_total_uses = rule.get("max_total_uses")
        if max_total_uses is not None:
            total_count = await decision_repo.get_eligible_count(tenant_id, campaign_id, None, None)
            if total_count >= int(max_total_uses):
                return _deny("blocked_cap", f"Campaign total use cap reached: {total_count}/{max_total_uses}")

        # ── 12. Budget policy (observational) ────────────────────────────
        budget_policy = campaign.get("budget_policy") or {}
        max_budget = budget_policy.get("max_total_reward_amount")
        reward_amount = rule.get("reward_amount")
        if max_budget is not None and reward_amount is not None and budget_policy.get("track_spend", False):
            total_count = await decision_repo.get_eligible_count(tenant_id, campaign_id, None, None)
            estimated_spend = float(total_count) * float(reward_amount)
            if estimated_spend >= float(max_budget):
                return _deny("blocked_budget", f"Tenant-declared budget policy exceeded: {estimated_spend} >= {max_budget}")

        # ── All gates passed — eligible ───────────────────────────────────
        reward = {
            "amount": str(rule.get("reward_amount", "")) if rule.get("reward_amount") is not None else None,
            "unit": rule.get("reward_unit"),
            "currency": rule.get("reward_currency"),
            "metadata": rule.get("reward_metadata", {}),
        }

        return PolicyDecision(
            eligible=True,
            decision="eligible",
            decision_reason=f"Rule matched: {rule.get('name', rule_id)}",
            campaign_id=campaign_id,
            rule_id=rule_id,
            rule=rule,
            campaign=campaign,
            execution_mode=execution_mode,
            rail=rail,
            attribution=self._attr_summary(attribution),
            fraud=self._fraud_summary(fraud),
            identity=self._identity_summary(identity),
            reward=reward,
            next_action={"type": "create_reward_action_payload"},
        )

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _attr_summary(attr: Optional[AttributionResultInput]) -> Optional[dict]:
        if attr is None:
            return None
        return {
            "result_id": attr.attribution_result_id,
            "weight": attr.attribution_weight,
            "confidence": attr.confidence,
            "model": attr.model,
            "channel": attr.channel,
            "journey_id": attr.journey_id,
        }

    @staticmethod
    def _fraud_summary(fraud: Optional[FraudDecisionInput]) -> Optional[dict]:
        if fraud is None:
            return None
        return {
            "decision_id": fraud.fraud_decision_id,
            "score": fraud.score,
            "decision": fraud.decision,
        }

    @staticmethod
    def _identity_summary(identity: IdentityInput) -> dict:
        return {
            "cluster_id": identity.identity_cluster_id,
            "confidence": identity.identity_confidence,
            "wallet_binding_confidence": identity.wallet_binding_confidence,
            "wallet_address": identity.wallet_address,
        }

    @staticmethod
    def _decision_from_record(record: dict) -> PolicyDecision:
        """Reconstruct a PolicyDecision from a stored eligibility decision."""
        return PolicyDecision(
            eligible=record.get("eligible", False),
            decision=record.get("decision", "ineligible"),
            decision_reason=record.get("decision_reason"),
            denial_reason=record.get("denial_reason"),
            campaign_id=record.get("campaign_id"),
            rule_id=record.get("rule_id"),
            execution_mode=record.get("execution_mode"),
            rail=record.get("rail"),
        )


def _parse_ts(ts: str) -> float:
    """Parse an ISO timestamp string to a Unix epoch float."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, AttributeError):
        return 0.0
