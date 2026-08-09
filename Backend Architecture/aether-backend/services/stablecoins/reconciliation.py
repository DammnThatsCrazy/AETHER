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
    MATCHED = "matched"
    PARTIAL = "partial"
    MISMATCHED = "mismatched"
    DUPLICATE = "duplicate"
    MISSING_ONCHAIN = "missing_onchain"
    MISSING_TENANT_EVENT = "missing_tenant_event"
    PENDING_FINALITY = "pending_finality"
    REVERTED = "reverted"
    UNRESOLVED = "unresolved"


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

    async def reconcile(
        self,
        intent: PaymentIntentEvidence | None,
        onchain: OnchainEvidence | None,
    ) -> ReconciliationResult:
        if intent is None and onchain is None:
            raise ValueError("reconciliation requires tenant or onchain evidence")
        if intent is None:
            result = ReconciliationResult(
                "", "", ReconciliationState.MISSING_TENANT_EVENT,
                "onchain evidence has no tenant payment intent",
                dict(onchain.evidence if onchain else {}),
            )
        elif onchain is None:
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.MISSING_ONCHAIN,
                "tenant payment intent has no onchain evidence", {},
            )
        elif await self._is_duplicate(intent, onchain):
            # The SAME onchain transaction was already reconciled for this
            # payment intent (idempotent replay of a provider poll, or a second
            # record for one confirmed tx). DUPLICATE is a first-class outcome —
            # never silently re-persisted as MATCHED and never counted twice.
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.DUPLICATE,
                "onchain transaction already reconciled for this payment intent",
                self._evidence(onchain),
            )
        elif onchain.finality_status == FinalityState.REVERTED:
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.REVERTED,
                "onchain transaction reverted", self._evidence(onchain),
            )
        elif onchain.finality_status != FinalityState.FINALIZED:
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.PENDING_FINALITY,
                "onchain transaction is not finalized", self._evidence(onchain),
            )
        elif self._matches(intent, onchain):
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.MATCHED,
                "tenant intent matches finalized onchain evidence", self._evidence(onchain),
            )
        elif self._partial(intent, onchain):
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.PARTIAL,
                "payer/recipient/deployment match but amount differs", self._evidence(onchain),
            )
        else:
            result = ReconciliationResult(
                intent.tenant_id, intent.payment_intent_id,
                ReconciliationState.MISMATCHED,
                "tenant intent conflicts with onchain evidence", self._evidence(onchain),
            )
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

    @staticmethod
    def _evidence(onchain: OnchainEvidence) -> dict[str, Any]:
        """Persisted evidence always carries the transaction hash so duplicate
        detection and the operator audit trail can identify the onchain record."""
        return {**dict(onchain.evidence), "transaction_hash": onchain.transaction_hash}

    async def reconcile_batch(
        self,
        intent: PaymentIntentEvidence,
        onchain_records: list[OnchainEvidence],
    ) -> list[ReconciliationResult]:
        """Reconcile one payment intent against every onchain candidate.

        The first match wins; any record whose transaction hash was already
        reconciled (including within this batch) resolves to DUPLICATE so a
        provider that replays the same confirmed tx cannot double-count volume.
        """
        if not onchain_records:
            return [await self.reconcile(intent, None)]
        results: list[ReconciliationResult] = []
        reconciled: set[str] = set()
        for record in onchain_records:
            if record.transaction_hash in reconciled:
                results.append(ReconciliationResult(
                    intent.tenant_id, intent.payment_intent_id,
                    ReconciliationState.DUPLICATE,
                    "onchain transaction already reconciled within batch",
                    dict(record.evidence),
                ))
                continue
            result = await self.reconcile(intent, record)
            results.append(result)
            if result.state in (ReconciliationState.MATCHED, ReconciliationState.PARTIAL, ReconciliationState.DUPLICATE):
                reconciled.add(record.transaction_hash)
        return results

    async def _is_duplicate(self, intent: PaymentIntentEvidence, onchain: OnchainEvidence) -> bool:
        """True when this exact onchain transaction was already reconciled for
        the payment intent (idempotent replay / duplicate observation)."""
        if not onchain.transaction_hash:
            return False
        prior = await self._prior_transaction_hashes(intent.tenant_id, intent.payment_intent_id)
        return onchain.transaction_hash in prior

    async def _prior_transaction_hashes(self, tenant_id: str, payment_intent_id: str) -> set[str]:
        rows = await self.repo.find_many(
            filters={"tenant_id": tenant_id, "payment_intent_id": payment_intent_id}, limit=10000
        )
        return {str(r.get("transaction_hash") or "") for r in rows if r.get("transaction_hash")}

    async def _persist(self, result: ReconciliationResult) -> None:
        rid = f"stablecoin_reconciliation:{result.tenant_id}:{result.payment_intent_id}:{result.state.value}"
        await self.repo.insert(rid, {
            "reconciliation_id": rid,
            "tenant_id": result.tenant_id,
            "payment_intent_id": result.payment_intent_id,
            "state": result.state.value,
            "reason": result.reason,
            "evidence": dict(result.evidence),
            "transaction_hash": str(result.evidence.get("transaction_hash") or ""),
            "created_at": utc_now().isoformat(),
        })
