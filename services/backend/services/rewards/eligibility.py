"""
Aether Backend — Reward Eligibility Engine

Rule-based eligibility evaluation for automated on-chain rewards.
Supports campaign-scoped rules, tiered rewards, cooldowns, and caps.

Design:
    - Rules are composable predicates evaluated against inbound events.
    - Each rule carries conditions: event_type filter, channel filter,
      minimum attribution weight, maximum fraud score gate.
    - Campaigns group rule sets with reward tiers, budgets, and time windows.
    - Anti-gaming guards: cooldown periods, per-user claim caps, fraud-score
      thresholds, and budget exhaustion checks.

Integration:
    Used by ``services.rewards.routes`` after fraud and attribution pipelines
    have scored the incoming event.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shared.common.common import NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.rewards.eligibility")


# ═══════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class RewardTier:
    """A single reward denomination."""

    name: str
    amount_wei: int
    token_symbol: str = "ETH"
    description: str = ""
    vm_type: str = "evm"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "amount_wei": self.amount_wei,
            "token_symbol": self.token_symbol,
            "description": self.description,
            "vm_type": self.vm_type,
        }


@dataclass
class RewardRule:
    """
    Predicate that determines whether an event qualifies for a reward tier.

    Attributes:
        event_types:            Which event types trigger this rule.
        required_channel:       Optional attribution-channel filter (e.g. ``social``).
        min_attribution_weight: Minimum attribution weight required (0.0 – 1.0).
        max_fraud_score:        Upper fraud-score ceiling; events above are rejected.
        reward_tier:            The tier paid out when the rule matches.
        cooldown_seconds:       Minimum seconds between claims by the same user.
        max_per_user:           Maximum claims per user per campaign.
        requires_wallet:        Whether a wallet address is mandatory.
    """

    event_types: list[str]
    reward_tier: RewardTier
    required_channel: Optional[str] = None
    min_attribution_weight: float = 0.0
    max_fraud_score: float = 40.0
    cooldown_seconds: int = 86_400  # 24 h
    max_per_user: int = 1
    requires_wallet: bool = True

    def to_dict(self) -> dict:
        return {
            "event_types": self.event_types,
            "required_channel": self.required_channel,
            "min_attribution_weight": self.min_attribution_weight,
            "max_fraud_score": self.max_fraud_score,
            "reward_tier": self.reward_tier.to_dict(),
            "cooldown_seconds": self.cooldown_seconds,
            "max_per_user": self.max_per_user,
            "requires_wallet": self.requires_wallet,
        }


@dataclass
class Campaign:
    """
    A reward campaign containing one or more rules.

    Attributes:
        id:                Unique campaign identifier.
        name:              Human-readable label.
        description:       Campaign description.
        rules:             Ordered list of reward rules; first match wins.
        start_time:        Optional activation timestamp (UTC).
        end_time:          Optional expiry timestamp (UTC).
        total_budget_wei:  Total reward budget in wei.
        spent_wei:         Wei already disbursed.
        active:            Administrative toggle.
        chain_id:          Target chain identifier.
        contract_address:  Reward contract address.
        vm_type:           Target VM family (evm, svm, bitcoin, movevm, near, tvm, cosmos).
        program_id:        Solana program ID (SVM only); alias for contract_address on Solana.
    """

    id: str
    name: str
    description: str = ""
    rules: list[RewardRule] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_budget_wei: int = 0
    spent_wei: int = 0
    active: bool = True
    chain_id: int = 1
    contract_address: Optional[str] = None
    vm_type: str = "evm"
    program_id: Optional[str] = None

    # -- helpers ---------------------------------------------------------

    @property
    def budget_remaining_wei(self) -> int:
        return max(self.total_budget_wei - self.spent_wei, 0)

    def is_within_time_window(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return True

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "rules": [r.to_dict() for r in self.rules],
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_budget_wei": self.total_budget_wei,
            "spent_wei": self.spent_wei,
            "budget_remaining_wei": self.budget_remaining_wei,
            "active": self.active,
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "vm_type": self.vm_type,
        }
        if self.program_id is not None:
            result["program_id"] = self.program_id
        return result


@dataclass
class EligibilityResult:
    """Outcome of a single eligibility evaluation."""

    eligible: bool
    campaign_id: str
    rule_index: int = -1
    reward_tier: Optional[RewardTier] = None
    denial_reason: Optional[str] = None
    fraud_score: float = 0.0
    attribution_weight: float = 0.0

    def to_dict(self) -> dict:
        return {
            "eligible": self.eligible,
            "campaign_id": self.campaign_id,
            "rule_index": self.rule_index,
            "reward_tier": self.reward_tier.to_dict() if self.reward_tier else None,
            "denial_reason": self.denial_reason,
            "fraud_score": self.fraud_score,
            "attribution_weight": self.attribution_weight,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ELIGIBILITY ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class EligibilityEngine:
    """
    Evaluates inbound events against all registered campaigns and returns
    the first matching ``EligibilityResult``.

    Stores:
        _campaigns:      id -> Campaign
        _claim_counts:   (user_address, campaign_id) -> claim count
        _last_claim_ts:  (user_address, campaign_id) -> unix epoch (seconds)
    """

    def __init__(self) -> None:
        self._campaigns: dict[str, Campaign] = {}
        self._claim_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._last_claim_ts: dict[tuple[str, str], float] = {}
        self._claim_lock = threading.Lock()

    # -- campaign management ---------------------------------------------

    def register_campaign(self, campaign: Campaign) -> None:
        """Register or replace a campaign."""
        self._campaigns[campaign.id] = campaign
        logger.info(
            f"Campaign registered: id={campaign.id} name={campaign.name} "
            f"rules={len(campaign.rules)} budget={campaign.total_budget_wei} wei"
        )
        metrics.increment("rewards_campaigns_registered")

    def get_campaign(self, campaign_id: str) -> Campaign:
        campaign = self._campaigns.get(campaign_id)
        if campaign is None:
            raise NotFoundError("Campaign")
        return campaign

    def list_campaigns(self) -> list[Campaign]:
        return list(self._campaigns.values())

    # -- evaluation ------------------------------------------------------

    async def evaluate(
        self,
        event: dict,
        fraud_score: float,
        attribution_weight: float,
        user_address: Optional[str] = None,
    ) -> EligibilityResult:
        """
        Evaluate an event against every active campaign's rules.

        Returns the first matching result.  If no campaign matches, returns
        an ineligible result with a denial reason.

        Args:
            event:              The normalised event dict (must contain ``event_type``
                                and optionally ``channel``).
            fraud_score:        Fraud score from the fraud pipeline (0–100).
            attribution_weight: Attribution weight from the attribution resolver (0–1).
            user_address:       User wallet address; ``None`` when unknown.
        """
        event_type = event.get("event_type", "")
        channel = event.get("channel")
        now = datetime.now(timezone.utc)
        now_ts = time.time()

        for campaign in self._campaigns.values():
            result = self._evaluate_campaign(
                campaign=campaign,
                event_type=event_type,
                channel=channel,
                fraud_score=fraud_score,
                attribution_weight=attribution_weight,
                user_address=user_address,
                now=now,
                now_ts=now_ts,
            )
            if result is not None:
                metrics.increment(
                    "rewards_eligibility_evaluated",
                    labels={"eligible": str(result.eligible), "campaign": campaign.id},
                )
                return result

        # No campaign matched at all
        metrics.increment("rewards_eligibility_evaluated", labels={"eligible": "False", "campaign": "none"})
        return EligibilityResult(
            eligible=False,
            campaign_id="",
            fraud_score=fraud_score,
            attribution_weight=attribution_weight,
            denial_reason="No matching campaign found for this event",
        )

    # -- claim recording -------------------------------------------------

    def record_claim(self, user_address: str, campaign_id: str) -> None:
        """Record that a user has claimed a reward from a campaign.

        Thread-safe: uses a lock to prevent lost-update races on
        concurrent claim submissions.
        """
        with self._claim_lock:
            key = (user_address.lower(), campaign_id)
            self._claim_counts[key] += 1
            self._last_claim_ts[key] = time.time()

            campaign = self._campaigns.get(campaign_id)
            if campaign and campaign.rules:
                # Debit the first-matching tier amount from campaign budget
                campaign.spent_wei += campaign.rules[0].reward_tier.amount_wei

        logger.info(
            f"Claim recorded: user={user_address} campaign={campaign_id} "
            f"total_claims={self._claim_counts[(user_address.lower(), campaign_id)]}"
        )
        metrics.increment("rewards_claims_recorded", labels={"campaign": campaign_id})

    # -- private helpers -------------------------------------------------

    def _evaluate_campaign(
        self,
        campaign: Campaign,
        event_type: str,
        channel: Optional[str],
        fraud_score: float,
        attribution_weight: float,
        user_address: Optional[str],
        now: datetime,
        now_ts: float,
    ) -> Optional[EligibilityResult]:
        """
        Run gate checks against a single campaign and its rules.
        Returns ``None`` when the campaign is completely irrelevant
        (e.g. inactive or out-of-window), or an ``EligibilityResult``
        when a definitive eligible / ineligible determination can be made.
        """
        base = dict(campaign_id=campaign.id, fraud_score=fraud_score, attribution_weight=attribution_weight)

        # Campaign-level gates
        if not campaign.active:
            return None  # silently skip inactive campaigns
        if not campaign.is_within_time_window(now):
            return None
        if campaign.budget_remaining_wei <= 0:
            return EligibilityResult(eligible=False, denial_reason="Campaign budget exhausted", **base)

        for idx, rule in enumerate(campaign.rules):
            denial = self._check_rule(
                rule=rule,
                event_type=event_type,
                channel=channel,
                fraud_score=fraud_score,
                attribution_weight=attribution_weight,
                user_address=user_address,
                campaign_id=campaign.id,
                now_ts=now_ts,
            )
            if denial is not None:
                # Rule matched the event type but a gate blocked it
                if denial == "__skip__":
                    continue  # event type doesn't match; try next rule
                return EligibilityResult(
                    eligible=False,
                    rule_index=idx,
                    denial_reason=denial,
                    **base,
                )

            # All gates passed — eligible
            return EligibilityResult(
                eligible=True,
                rule_index=idx,
                reward_tier=rule.reward_tier,
                **base,
            )

        return None  # no rule in this campaign matched the event type

    def _check_rule(
        self,
        rule: RewardRule,
        event_type: str,
        channel: Optional[str],
        fraud_score: float,
        attribution_weight: float,
        user_address: Optional[str],
        campaign_id: str,
        now_ts: float,
    ) -> Optional[str]:
        """
        Returns ``None`` when the rule passes, ``"__skip__"`` when the event
        type simply doesn't match, or a human-readable denial reason string.
        """
        # Event type match
        if event_type not in rule.event_types:
            return "__skip__"

        # Channel filter
        if rule.required_channel and channel != rule.required_channel:
            return f"Channel mismatch: required={rule.required_channel} got={channel}"

        # Attribution weight gate
        if attribution_weight < rule.min_attribution_weight:
            return (
                f"Attribution weight too low: {attribution_weight:.4f} "
                f"< {rule.min_attribution_weight:.4f}"
            )

        # Fraud score gate
        if fraud_score > rule.max_fraud_score:
            return f"Fraud score too high: {fraud_score:.2f} > {rule.max_fraud_score:.2f}"

        # Wallet requirement
        if rule.requires_wallet and not user_address:
            return "Wallet address required but not provided"

        # Per-user claim cap and cooldown (only when wallet is known)
        if user_address:
            key = (user_address.lower(), campaign_id)

            if self._claim_counts[key] >= rule.max_per_user:
                return f"Claim cap reached: {self._claim_counts[key]}/{rule.max_per_user}"

            last_ts = self._last_claim_ts.get(key)
            if last_ts is not None:
                elapsed = now_ts - last_ts
                if elapsed < rule.cooldown_seconds:
                    remaining = int(rule.cooldown_seconds - elapsed)
                    return f"Cooldown active: {remaining}s remaining"

        return None  # all gates passed
