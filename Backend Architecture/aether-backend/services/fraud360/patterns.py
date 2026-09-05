"""Fraud360 Day-1 ``FraudPattern`` registry (Phase 3).

FraudPattern is a **registered pattern system, not a parallel taxonomy**. The
Day-1 families seed the registry ALIGNED to the shipped network taxonomy
(``services/fraud_networks/models.py``) — every ``network_type_ref`` names a
shipped ``NetworkType`` value and every ``member_role_ref`` a shipped
``MemberRole`` value. Alignment is enforced by
``tests/unit/test_fraud360_patterns.py`` (which imports ``NetworkType`` /
``MemberRole`` and asserts membership), never by re-declaring the taxonomy.

Matching a pattern only produces a suspicion-state ``FraudHypothesis``; a
matched pattern is NOT proof of fraud. Tenant-defined extensions register
through this same typed registry.
"""

from __future__ import annotations

from typing import Final

from services.fraud360.contracts import FraudPattern

# Day-1 families (blueprint §14): promotion abuse, referral abuse, synthetic
# identity, account takeover, payment fraud, refund/chargeback abuse, bot
# activity, device farm, conversion manipulation, credential abuse, agent
# abuse, counterparty fraud, collusion, circular value flow, wallet abuse,
# reward extraction. Each row references real shipped NetworkType / MemberRole
# values only.
FRAUD_PATTERNS: Final[tuple[FraudPattern, ...]] = (
    FraudPattern(
        pattern_id="promotion_abuse",
        family="promotion abuse",
        display_name="Promotion abuse",
        description=(
            "A beneficiary repeatedly extracts promotional value beyond the "
            "intended offer by gaming eligibility, quantity, or velocity limits."
        ),
        network_type_refs=["commerce_abuse_ring"],
        member_role_refs=["orchestrator", "beneficiary", "aggregator"],
        required_evidence_types=["transaction", "event", "entity"],
        materiality_guidance=(
            "Estimate promotional value extracted via economic360 revenue "
            "adjustments / campaign economics."
        ),
        enabled=True,
    ),
    FraudPattern(
        pattern_id="referral_abuse",
        family="referral abuse",
        display_name="Referral abuse",
        description=(
            "Self-referrals or coordinated referral rings inflate referral "
            "credit by manufacturing fake referees or circular signups."
        ),
        network_type_refs=["referral_abuse_ring"],
        member_role_refs=["orchestrator", "recruiter", "beneficiary"],
        required_evidence_types=["relationship", "entity", "event"],
        materiality_guidance="Value = referral credit / reward paid to fabricated referees.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="synthetic_identity",
        family="synthetic identity",
        display_name="Synthetic identity",
        description=(
            "A fabricated identity blending real and invented attributes, "
            "used to open accounts and extract credit or rewards without a "
            "real underlying person."
        ),
        network_type_refs=["synthetic_identity_ring"],
        member_role_refs=["synthetic_identity", "controller", "beneficiary"],
        required_evidence_types=["entity", "document", "annotation"],
        materiality_guidance="Exposure = credit/limit + rewards granted to synthetic identities.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="account_takeover",
        family="account takeover",
        display_name="Account takeover",
        description=(
            "A legitimate account's credentials are compromised and the "
            "account is used to move value or perform unauthorized actions."
        ),
        network_type_refs=["account_takeover_cluster"],
        member_role_refs=["compromised_account", "controller", "cash_out_node"],
        required_evidence_types=["entity", "event", "annotation"],
        materiality_guidance="Exposure = value moved from compromised accounts before containment.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="payment_fraud",
        family="payment fraud",
        display_name="Payment fraud",
        description=(
            "Fraudulent payment instruments or deceptive payment behavior — "
            "stolen cards, first-party chargeback abuse precursors, or "
            "non-payment — used to obtain goods, funds, or services."
        ),
        network_type_refs=["card_fraud_ring", "mule_network"],
        member_role_refs=["mule", "cash_out_node", "injection_point"],
        required_evidence_types=["transaction", "relationship", "entity"],
        materiality_guidance="Exposure = unauthorized/fraudulent transaction value (economic360).",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="refund_chargeback_abuse",
        family="refund/chargeback abuse",
        display_name="Refund / chargeback abuse",
        description=(
            "Goods, services, or funds are obtained then refunds/chargebacks "
            "are abused so the merchant loses both the value and the "
            "counterparty keeps the benefit."
        ),
        network_type_refs=["commerce_abuse_ring", "card_fraud_ring"],
        member_role_refs=["orchestrator", "beneficiary"],
        required_evidence_types=["transaction", "document", "event"],
        materiality_guidance="Exposure = refunded/charged-back value net of returned goods.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="bot_activity",
        family="bot activity",
        display_name="Bot activity",
        description=(
            "Automated, non-human behavior — bulk account creation, "
            "credential stuffing, or scaled automated transactions — "
            "coordinated without human intent per action."
        ),
        network_type_refs=["coordinated_inauthentic_behavior"],
        member_role_refs=["orchestrator", "injection_point", "relay"],
        required_evidence_types=["event", "model_output", "entity"],
        materiality_guidance="Value = economic advantage gained by automated inauthentic scale.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="device_farm",
        family="device farm",
        display_name="Device farm",
        description=(
            "A fleet of emulated or repurposed devices presents as many "
            "distinct users to bypass device-level anti-fraud controls."
        ),
        network_type_refs=["coordinated_inauthentic_behavior", "delegation_abuse_cluster"],
        member_role_refs=["orchestrator", "controller", "relay"],
        required_evidence_types=["entity", "model_output", "event"],
        materiality_guidance="Value = rewards/limits obtained from farmed device identities.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="conversion_manipulation",
        family="conversion manipulation",
        display_name="Conversion manipulation",
        description=(
            "Inorganic traffic or fake actions inflate conversion, engagement, "
            "or attribution metrics to extract payout or misreport performance."
        ),
        network_type_refs=["coordinated_inauthentic_behavior"],
        member_role_refs=["orchestrator", "beneficiary", "aggregator"],
        required_evidence_types=["event", "model_output", "relationship"],
        materiality_guidance="Value = payout/attribution credit tied to fabricated conversions.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="credential_abuse",
        family="credential abuse",
        display_name="Credential abuse",
        description=(
            "Stolen or brute-forced credentials are tested and reused across "
            "accounts — credential stuffing and session/OTP interception."
        ),
        network_type_refs=["account_takeover_cluster", "delegation_abuse_cluster"],
        member_role_refs=["compromised_account", "injection_point"],
        required_evidence_types=["event", "annotation", "entity"],
        materiality_guidance="Exposure = accounts reached via abused credentials.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="agent_abuse",
        family="agent abuse",
        display_name="Agent abuse",
        description=(
            "An autonomous agent is delegated authority and then abused — "
            "prompt-injected, over-provisioned, or steered into actions the "
            "principal did not intend."
        ),
        network_type_refs=["delegation_abuse_cluster"],
        member_role_refs=["controller", "facilitator", "beneficiary"],
        required_evidence_types=["event", "entity", "annotation"],
        materiality_guidance="Exposure = value/actions an abused agent executed beyond intent.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="counterparty_fraud",
        family="counterparty fraud",
        display_name="Counterparty fraud",
        description=(
            "The counterparty to a transaction is itself fraudulent or "
            "colluding — a bad merchant, fake buyer, or intermediary that "
            "converts value to itself."
        ),
        network_type_refs=["commerce_abuse_ring", "card_fraud_ring", "mule_network"],
        member_role_refs=["facilitator", "cash_out_node", "mule"],
        required_evidence_types=["transaction", "relationship", "entity"],
        materiality_guidance="Exposure = value moved through fraudulent counterparties.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="collusion",
        family="collusion",
        display_name="Collusion",
        description=(
            "Multiple actors coordinate to defeat independent controls — "
            "collusive bidding, shared-benefit rings, or insider-outsider "
            "arrangements."
        ),
        network_type_refs=["coordinated_inauthentic_behavior", "commerce_abuse_ring"],
        member_role_refs=["orchestrator", "recruiter", "facilitator", "aggregator"],
        required_evidence_types=["relationship", "event", "entity"],
        materiality_guidance="Value = joint benefit extracted by the coordinated group.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="circular_value_flow",
        family="circular value flow",
        display_name="Circular value flow",
        description=(
            "Value circulates through controlled accounts or counterparties — "
            "layering, smurfing, wash activity — to obscure origin or "
            "manufacture apparent activity."
        ),
        network_type_refs=["layering_network", "smurfing_network", "wash_trading_ring"],
        member_role_refs=["controller", "splitter", "aggregator", "relay"],
        required_evidence_types=["transaction", "relationship", "event"],
        materiality_guidance="Exposure = value cycled through the ring (tracked, not double-counted).",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="wallet_abuse",
        family="wallet abuse",
        display_name="Wallet abuse",
        description=(
            "Wallets are used as controlled conduits — collection points, "
            "cash-out nodes, or reward sinks — for funds whose beneficial "
            "owner is concealed."
        ),
        network_type_refs=["layering_network", "mule_network", "reward_farming_ring"],
        member_role_refs=["mule", "cash_out_node", "beneficiary", "controller"],
        required_evidence_types=["transaction", "entity", "relationship"],
        materiality_guidance="Exposure = value passing through controlled wallets.",
        enabled=True,
    ),
    FraudPattern(
        pattern_id="reward_extraction",
        family="reward extraction",
        display_name="Reward extraction",
        description=(
            "Farming, airdrop harvesting, and loyalty/reward arbitrage extract "
            "programmatic rewards at inauthentic scale or through ineligible "
            "participants."
        ),
        network_type_refs=["reward_farming_ring", "airdrop_farming_cluster"],
        member_role_refs=["beneficiary", "aggregator", "splitter", "recruiter"],
        required_evidence_types=["event", "transaction", "entity"],
        materiality_guidance="Exposure = rewards/airdrops extracted by the farming population.",
        enabled=True,
    ),
)

#: Machine-readable keys for registry consumers (blueprint §14 Day-1 set).
FRAUD_PATTERN_KEYS: Final[frozenset[str]] = frozenset(
    p.pattern_id for p in FRAUD_PATTERNS
)

_FRAUD_PATTERN_BY_ID: Final[dict[str, FraudPattern]] = {
    p.pattern_id: p for p in FRAUD_PATTERNS
}


def fraud_pattern(pattern_id: str) -> FraudPattern | None:
    """Return the registered pattern for ``pattern_id`` (None when unknown)."""
    return _FRAUD_PATTERN_BY_ID.get(pattern_id)


__all__ = [
    "FRAUD_PATTERNS",
    "FRAUD_PATTERN_KEYS",
    "fraud_pattern",
]
