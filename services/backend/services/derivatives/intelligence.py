"""Derivatives graph, profile, campaign, and Noesis intelligence helpers.

This module emits projection intents for existing graph/profile/journey systems. It
is deliberately not a graph client, journey compiler, or campaign registry. Every
intent is tenant-scoped, evidence-backed, bitemporal, and read-only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Iterable, Mapping, Sequence

from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus, SourceRef

INTELLIGENCE_VERSION = "derivatives-intelligence-v1"


class EvidenceClass(StrEnum):
    FACT = "fact"
    COMPUTATION = "computation"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class GraphLayer(StrEnum):
    H2H = "H2H"
    H2A = "H2A"
    A2H = "A2H"
    A2A = "A2A"
    DOMAIN_EXCLUDED = "DOMAIN_EXCLUDED"


ACTOR_EDGE_LAYER_MAP: dict[str, GraphLayer] = {
    "REFERRED_TO_VENUE": GraphLayer.H2H,
    "FUNDED": GraphLayer.H2H,
    "SHARES_TRADING_ACCOUNT_WITH": GraphLayer.H2H,
    "AUTHORIZED": GraphLayer.H2H,
    "COPIES_STRATEGY_FROM": GraphLayer.H2H,
    "PARTICIPATES_IN_VAULT_WITH": GraphLayer.H2H,
    "MEMBER_OF_TRADING_ORG_WITH": GraphLayer.H2H,
    "POSSIBLY_COORDINATED_WITH": GraphLayer.H2H,
    "POSSIBLY_MIRRORS": GraphLayer.H2H,
    "DELEGATES_TRADING_TO": GraphLayer.H2A,
    "AUTHORIZES_MARKETS_FOR": GraphLayer.H2A,
    "SETS_RISK_POLICY_FOR": GraphLayer.H2A,
    "APPROVES_TRADE_FROM": GraphLayer.H2A,
    "FUNDS_AGENT": GraphLayer.H2A,
    "OVERRIDES_AGENT": GraphLayer.H2A,
    "REVOKES_TRADING_AUTHORITY": GraphLayer.H2A,
    "RECOMMENDS_TRADE_TO": GraphLayer.A2H,
    "REQUESTS_APPROVAL_FROM": GraphLayer.A2H,
    "WARNS": GraphLayer.A2H,
    "REQUESTS_MARGIN_FROM": GraphLayer.A2H,
    "REPORTS_PNL_TO": GraphLayer.A2H,
    "ESCALATES_RISK_TO": GraphLayer.A2H,
    "EXPLAINS_DECISION_TO": GraphLayer.A2H,
    "PROPOSES_TRADE_TO": GraphLayer.A2A,
    "REQUESTS_RISK_REVIEW_FROM": GraphLayer.A2A,
    "APPROVES_EXECUTION_FOR": GraphLayer.A2A,
    "VETOES_EXECUTION_FOR": GraphLayer.A2A,
    "ROUTES_ORDER_TO": GraphLayer.A2A,
    "VERIFIES_FILL_FROM": GraphLayer.A2A,
    "RECONCILES_POSITION_FOR": GraphLayer.A2A,
}

DOMAIN_EDGE_LAYER_MAP: dict[str, GraphLayer] = {
    edge: GraphLayer.DOMAIN_EXCLUDED
    for edge in (
        "CONTROLS", "AUTHENTICATES", "HAS_SUBACCOUNT", "PARTICIPATES_IN_VAULT", "HOLDS_POSITION",
        "CREATED_ORDER", "CONTAINS_FILL", "EXECUTED_ON", "ON_MARKET", "LISTED_ON", "SETTLES_IN",
        "MARGINED_BY", "BACKED_BY", "PRICED_BY", "INCURRED_FEE", "PAID_FUNDING", "RECEIVED_FUNDING",
        "LIQUIDATED_BY", "GENERATED_PNL", "GOVERNED_BY_POLICY", "ATTRIBUTED_TO_CAMPAIGN",
        "PART_OF_JOURNEY", "DERIVED_FROM_EVENT",
    )
}

EDGE_LAYER_MAP: dict[str, GraphLayer] = {**ACTOR_EDGE_LAYER_MAP, **DOMAIN_EDGE_LAYER_MAP}


@dataclass(frozen=True)
class EvidenceEnvelope:
    evidence_class: EvidenceClass
    source_refs: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    confidence: Decimal
    valid_time: str
    recorded_time: str
    explanation: str
    calculation_version: str = INTELLIGENCE_VERSION
    model_version: str | None = None
    data_freshness_seconds: int | None = None

    def __post_init__(self) -> None:
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        if self.evidence_class is not EvidenceClass.INSUFFICIENT_EVIDENCE and not self.source_refs:
            raise ValueError("evidence-backed derivative intelligence requires source_refs")


@dataclass(frozen=True)
class DerivativesGraphEdgeIntent:
    tenant_id: str
    edge_type: str
    from_ref: str
    to_ref: str
    layer: GraphLayer
    evidence: EvidenceEnvelope
    valid_from: str
    recorded_at: str
    properties: Mapping[str, str] = field(default_factory=dict)
    execution_by_aether: bool = False

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_LAYER_MAP:
            raise ValueError(f"unclassified derivatives edge: {self.edge_type}")
        if EDGE_LAYER_MAP[self.edge_type] is not self.layer:
            raise ValueError(f"edge {self.edge_type} must be classified as {EDGE_LAYER_MAP[self.edge_type].value}")
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if self.execution_by_aether:
            raise ValueError("Aether graph projections must remain observational")

    @property
    def idempotency_key(self) -> str:
        material = "|".join([self.tenant_id, self.edge_type, self.from_ref, self.to_ref, self.valid_from])
        return "derivatives:graph:" + sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthorityGrant:
    tenant_id: str
    human_ref: str
    agent_ref: str
    risk_policy_ref: str
    markets: tuple[str, ...]
    max_leverage: Decimal | None
    max_notional: Decimal | None
    approval_required: bool
    valid_from: str
    recorded_at: str
    source_ref: SourceRef

    def to_graph_edges(self) -> list[DerivativesGraphEdgeIntent]:
        evidence = EvidenceEnvelope(
            evidence_class=EvidenceClass.FACT,
            source_refs=(self.source_ref.idempotency_component,),
            source_event_ids=(self.source_ref.source_record_id,),
            confidence=Decimal("1"),
            valid_time=self.valid_from,
            recorded_time=self.recorded_at,
            explanation="Human granted bounded read-only derivatives trading authority to an agent.",
        )
        props = {
            "markets": ",".join(self.markets),
            "approval_required": str(self.approval_required).lower(),
            "withdrawal_prohibited": "true",
        }
        if self.max_leverage is not None:
            props["max_leverage"] = str(self.max_leverage)
        if self.max_notional is not None:
            props["max_notional"] = str(self.max_notional)
        return [
            DerivativesGraphEdgeIntent(self.tenant_id, "DELEGATES_TRADING_TO", self.human_ref, self.agent_ref, GraphLayer.H2A, evidence, self.valid_from, self.recorded_at, props),
            DerivativesGraphEdgeIntent(self.tenant_id, "GOVERNED_BY_POLICY", self.agent_ref, self.risk_policy_ref, GraphLayer.DOMAIN_EXCLUDED, evidence, self.valid_from, self.recorded_at, props),
        ]


def project_position_edges(position: PositionEpochState, recorded_at: str, source_refs: Sequence[str] | None = None) -> list[DerivativesGraphEdgeIntent]:
    source = tuple(source_refs or position.source_fill_ids)
    evidence = EvidenceEnvelope(
        evidence_class=EvidenceClass.COMPUTATION,
        source_refs=source,
        source_event_ids=tuple(position.source_fill_ids),
        confidence=Decimal("1"),
        valid_time=position.opened_at or recorded_at,
        recorded_time=recorded_at,
        explanation="Position epoch reconstructed from normalized derivative fill facts.",
    )
    account_ref = f"trading_account:{position.trading_account_id}"
    position_ref = f"position_epoch:{position.epoch_id}"
    market_ref = f"derivative_market:{position.canonical_market_id}"
    return [
        DerivativesGraphEdgeIntent(position.tenant_id, "HOLDS_POSITION", account_ref, position_ref, GraphLayer.DOMAIN_EXCLUDED, evidence, position.opened_at or recorded_at, recorded_at),
        DerivativesGraphEdgeIntent(position.tenant_id, "ON_MARKET", position_ref, market_ref, GraphLayer.DOMAIN_EXCLUDED, evidence, position.opened_at or recorded_at, recorded_at),
        DerivativesGraphEdgeIntent(position.tenant_id, "GENERATED_PNL", position_ref, account_ref, GraphLayer.DOMAIN_EXCLUDED, evidence, position.closed_at or recorded_at, recorded_at, {"net_realized_pnl": str(position.net_realized_pnl)}),
    ]


def compute_behavior_features(tenant_id: str, positions: Iterable[PositionEpochState], window: str) -> dict[str, object]:
    scoped = [p for p in positions if p.tenant_id == tenant_id]
    total = Decimal(len(scoped))
    longs = Decimal(sum(1 for p in scoped if p.side is PositionSide.LONG))
    shorts = Decimal(sum(1 for p in scoped if p.side is PositionSide.SHORT))
    closed = Decimal(sum(1 for p in scoped if p.status is PositionStatus.CLOSED))
    gross_pnl = sum((p.realized_pnl for p in scoped), Decimal("0"))
    fees = sum((p.fees for p in scoped), Decimal("0"))
    markets = sorted({p.canonical_market_id for p in scoped})
    return {
        "tenant_id": tenant_id,
        "window": window,
        "calculation_version": INTELLIGENCE_VERSION,
        "position_count": int(total),
        "long_bias": _ratio(longs, total),
        "short_bias": _ratio(shorts, total),
        "closed_position_ratio": _ratio(closed, total),
        "gross_realized_pnl": gross_pnl,
        "fees": fees,
        "net_realized_pnl": gross_pnl - fees,
        "market_concentration_count": len(markets),
        "markets": markets,
    }


def build_profile360_derivatives_summary(tenant_id: str, positions: Iterable[PositionEpochState], window: str = "lifetime") -> dict[str, object]:
    features = compute_behavior_features(tenant_id, positions, window)
    state = "empty" if features["position_count"] == 0 else "complete"
    return {
        "tenant_id": tenant_id,
        "dimension": "derivatives",
        "state": state,
        "data_freshness_state": "partial" if state == "empty" else "complete",
        "evidence_class": EvidenceClass.COMPUTATION.value if state == "complete" else EvidenceClass.INSUFFICIENT_EVIDENCE.value,
        "features": features,
    }


def build_campaign_outcome_claim(tenant_id: str, campaign_id: str, positions: Iterable[PositionEpochState]) -> dict[str, object]:
    features = compute_behavior_features(tenant_id, positions, "lifetime")
    return {
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "claim": "campaign_preceded_derivatives_outcome",
        "claim_class": EvidenceClass.INFERENCE.value,
        "attribution_credit": "not_assigned",
        "causal_status": "not_proven",
        "net_realized_pnl": features["net_realized_pnl"],
        "explanation": "Temporal linkage is represented separately from attribution credit and causal support.",
    }


def answer_noesis_derivatives_question(tenant_id: str, question: str, positions: Iterable[PositionEpochState]) -> dict[str, object]:
    scoped = [p for p in positions if p.tenant_id == tenant_id]
    if not scoped:
        return {
            "tenant_id": tenant_id,
            "answer": "Insufficient derivatives evidence is available for this tenant.",
            "claims": [{"class": EvidenceClass.INSUFFICIENT_EVIDENCE.value, "text": "No tenant-scoped derivative positions were provided."}],
        }
    features = compute_behavior_features(tenant_id, scoped, "lifetime")
    return {
        "tenant_id": tenant_id,
        "answer": f"The tenant has {features['position_count']} derivative position epoch(s) with net realized PnL {features['net_realized_pnl']}.",
        "question": question,
        "claims": [
            {"class": EvidenceClass.FACT.value, "text": "Position epochs are tenant-scoped canonical derivatives records."},
            {"class": EvidenceClass.COMPUTATION.value, "text": "Net realized PnL is realized PnL less fees."},
            {"class": EvidenceClass.INFERENCE.value, "text": "Campaign or coordination conclusions require separate supporting evidence."},
        ],
    }


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return numerator / denominator
