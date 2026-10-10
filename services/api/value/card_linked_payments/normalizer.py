"""V1 card-linked normalizers with fail-closed basis and PII rules."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .models import CardActivityBasis, CardLinkedFlowObserved, CardLinkedSource, ObservationConfidence, reject_blocked_fields


def _ts() -> str: return datetime.now(timezone.utc).isoformat()

def normalize_provider_webhook(payload: dict[str, Any]) -> CardLinkedFlowObserved:
    reject_blocked_fields(payload)
    basis = CardActivityBasis(payload.get("basis") or "spend")
    if basis not in {CardActivityBasis.SPEND, CardActivityBasis.SETTLEMENT, CardActivityBasis.REFUND,
                     CardActivityBasis.REVERSAL, CardActivityBasis.AUTHORIZATION, CardActivityBasis.CLEARING}:
        # Off-chain provider evidence is spend-side only — never top-up/funding.
        raise ValueError("provider webhook basis must be spend, settlement, refund, or reversal "
                         "(authorization/clearing also allowed); never topup/funding")
    ts = payload.get("occurred_at") or _ts()
    return CardLinkedFlowObserved(id=payload["id"], tenant_id=payload["tenant_id"], actor_kind=payload.get("actor_kind", "human"), rail="card", basis=basis, source=CardLinkedSource.PROVIDER_WEBHOOK, confidence=ObservationConfidence.STRONG, evidence_refs=payload.get("evidence_refs", [payload.get("provider_event_id", payload["id"])]), reconciliation_state="provider_only", occurred_at=ts, observed_at=_ts(), created_at=_ts(), updated_at=_ts(), card_program_id=payload.get("card_program_id"), issuer_id=payload.get("issuer_id"), payment_network=payload.get("payment_network", "unknown"), wallet_address_hash=payload.get("wallet_address_hash"), amount_usd=payload.get("amount_usd"), campaign_id=payload.get("campaign_id"), journey_id=payload.get("journey_id"))

def normalize_onchain_observation(payload: dict[str, Any]) -> CardLinkedFlowObserved:
    reject_blocked_fields(payload)
    basis = CardActivityBasis(payload.get("basis") or "topup")
    if basis not in {CardActivityBasis.TOPUP, CardActivityBasis.FUNDING, CardActivityBasis.SETTLEMENT}:
        raise ValueError("on-chain card-linked basis must be topup, funding, or settlement")
    ts = payload.get("occurred_at") or _ts()
    return CardLinkedFlowObserved(id=payload["id"], tenant_id=payload["tenant_id"], actor_kind=payload.get("actor_kind", "wallet"), rail="onchain", basis=basis, source=CardLinkedSource.ONCHAIN_OBSERVER, confidence=ObservationConfidence.PROBABLE, evidence_refs=payload.get("evidence_refs", [payload.get("tx_hash", payload["id"])]), reconciliation_state="onchain_only", occurred_at=ts, observed_at=_ts(), created_at=_ts(), updated_at=_ts(), wallet_address_hash=payload.get("wallet_address_hash"), card_program_id=payload.get("card_program_id"), chain=payload.get("chain"), asset=payload.get("asset"), amount_usd=payload.get("amount_usd"), campaign_id=payload.get("campaign_id"), journey_id=payload.get("journey_id"))
