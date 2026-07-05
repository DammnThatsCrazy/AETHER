"""Stablecoin payment/onchain reconciliation."""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinReconciliationRepository
from shared.common.common import utc_now
from .models import FinalityState

class ReconciliationState(str, Enum):
    MATCHED = "matched"; PARTIAL = "partial"; MISMATCHED = "mismatched"; DUPLICATE = "duplicate"; MISSING_ONCHAIN = "missing_onchain"; MISSING_TENANT_EVENT = "missing_tenant_event"; PENDING_FINALITY = "pending_finality"; REVERTED = "reverted"; UNRESOLVED = "unresolved"

@dataclass(frozen=True)
class PaymentIntentEvidence:
    tenant_id: str
    payment_intent_id: str
    expected_payer: str
    expected_recipient: str
    deployment_id: str
    chain_id: str
    amount_atomic: int
    expires_at: str = ""

@dataclass(frozen=True)
class OnchainEvidence:
    transaction_hash: str
    payer: str
    recipient: str
    deployment_id: str
    chain_id: str
    amount_atomic: int
    finality_status: FinalityState
    evidence: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ReconciliationResult:
    tenant_id: str
    payment_intent_id: str
    state: ReconciliationState
    reason: str
    evidence: Mapping[str, Any]

class StablecoinReconciliationService:
    def __init__(self, repo: StablecoinReconciliationRepository | None = None) -> None:
        self.repo = repo or StablecoinReconciliationRepository()

    async def reconcile(self, intent: PaymentIntentEvidence | None, onchain: OnchainEvidence | None) -> ReconciliationResult:
        if intent is None and onchain is None:
            raise ValueError("reconciliation requires tenant or onchain evidence")
        if intent is None:
            result = ReconciliationResult("", "", ReconciliationState.MISSING_TENANT_EVENT, "onchain evidence has no tenant payment intent", dict(onchain.evidence if onchain else {}))
        elif onchain is None:
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.MISSING_ONCHAIN, "tenant payment intent has no onchain evidence", {})
        elif onchain.finality_status == FinalityState.REVERTED:
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.REVERTED, "onchain transaction reverted", dict(onchain.evidence))
        elif onchain.finality_status != FinalityState.FINALIZED:
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.PENDING_FINALITY, "onchain transaction is not finalized", dict(onchain.evidence))
        elif self._matches(intent, onchain):
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.MATCHED, "tenant intent matches finalized onchain evidence", dict(onchain.evidence))
        elif self._partial(intent, onchain):
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.PARTIAL, "payer/recipient/deployment match but amount differs", dict(onchain.evidence))
        else:
            result = ReconciliationResult(intent.tenant_id, intent.payment_intent_id, ReconciliationState.MISMATCHED, "tenant intent conflicts with onchain evidence", dict(onchain.evidence))
        await self._persist(result)
        return result

    @staticmethod
    def _matches(intent: PaymentIntentEvidence, onchain: OnchainEvidence) -> bool:
        return (
            intent.expected_payer.lower() == onchain.payer.lower()
            and intent.expected_recipient.lower() == onchain.recipient.lower()
            and intent.deployment_id == onchain.deployment_id
            and intent.chain_id == onchain.chain_id
            and intent.amount_atomic == onchain.amount_atomic
        )

    @staticmethod
    def _partial(intent: PaymentIntentEvidence, onchain: OnchainEvidence) -> bool:
        return (
            intent.expected_payer.lower() == onchain.payer.lower()
            and intent.expected_recipient.lower() == onchain.recipient.lower()
            and intent.deployment_id == onchain.deployment_id
            and intent.chain_id == onchain.chain_id
        )

    async def _persist(self, result: ReconciliationResult) -> None:
        rid = f"stablecoin_reconciliation:{result.tenant_id}:{result.payment_intent_id}:{result.state.value}"
        await self.repo.insert(rid, {"reconciliation_id": rid, "tenant_id": result.tenant_id, "payment_intent_id": result.payment_intent_id, "state": result.state.value, "reason": result.reason, "evidence": dict(result.evidence), "created_at": utc_now().isoformat()})
