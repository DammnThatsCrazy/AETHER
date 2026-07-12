"""TrainingDataGate (§3.5 + §3.10).

Filters a set of candidate training records against consent purposes before they
may enter a training set. A record is *quarantined* (not admitted) when:

  - it was collected under a purpose whose ``allowModelTraining`` is false
    (e.g. ``web3``/``credit``/``location``); or
  - it was collected under a purpose that requires a *separate* model-training
    opt-in the caller does not hold (``financial_activity`` /
    ``economic_observability`` / ``cross_chain_observability``); or
  - the model declares an explicit ``allowed_training_purposes`` scope and the
    record's purpose is outside it; or
  - it is an identity-derived label (§3.10) with no trainable source purpose.

Quarantine is fail-closed: a record with *no* declared source purpose is never
admitted. Decisions are persisted as durable provenance evidence.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

from services.model_governance import consent_purposes as purposes
from services.model_governance import policy
from services.model_governance.contracts import (
    TrainingDataDecision,
    TrainingDataGateResult,
)
from services.model_governance.repositories import TrainingDataDecisionRepository


class TrainingDataGate:
    def __init__(self, repo: Optional[TrainingDataDecisionRepository] = None) -> None:
        self._repo = repo or TrainingDataDecisionRepository()

    @staticmethod
    def _purpose_admissible(p: str, opt_ins: set[str], model_scope: set[str]) -> bool:
        """True if a record collected under purpose ``p`` may enter training."""
        if model_scope and p not in model_scope:
            return False
        if purposes.requires_separate_training_opt_in(p):
            # Training is possible for these purposes ONLY behind a separate
            # opt-in (their default ``allowModelTraining`` is false).
            return p in opt_ins
        return purposes.model_training_allowed(p)

    def evaluate_record(
        self,
        record: dict,
        *,
        model_id: str,
        tenant_id: Optional[str] = None,
        granted_training_opt_ins: Iterable[str] = (),
    ) -> TrainingDataDecision:
        opt_ins = set(granted_training_opt_ins or [])
        source_purposes = [p for p in (record.get("source_purposes") or []) if p]
        identity_label = bool(
            record.get("identity_derived_label")
            or record.get("label_source") == "identity_resolution"
        )
        record_ref = str(
            record.get("record_ref")
            or record.get("id")
            or record.get("event_id")
            or "unknown"
        )
        model_scope = set(policy.allowed_training_purposes(model_id))

        reasons: list[str] = []
        missing_opt_in: list[str] = []

        if not source_purposes:
            # Fail closed — provenance-less data is never trainable.
            reasons.append("no_source_purpose")

        for p in source_purposes:
            if model_scope and p not in model_scope:
                reasons.append(f"purpose_not_allowed_for_model:{p}")
                continue
            if purposes.requires_separate_training_opt_in(p):
                # Allowed only behind a separate model-training opt-in.
                if p not in opt_ins:
                    reasons.append(f"separate_opt_in_required:{p}")
                    missing_opt_in.append(p)
                continue
            if not purposes.model_training_allowed(p):
                reasons.append(f"purpose_forbids_training:{p}")

        # §3.10 — an identity-derived label needs at least one purpose that is
        # actually admissible for training; otherwise the label is quarantined.
        if identity_label:
            admissible = any(
                self._purpose_admissible(p, opt_ins, model_scope)
                for p in source_purposes
            )
            if not admissible and "identity_label_unconsented" not in reasons:
                reasons.append("identity_label_unconsented")

        admitted = not reasons
        return TrainingDataDecision(
            tenant_id=tenant_id,
            model_id=model_id,
            record_ref=record_ref,
            source_purposes=source_purposes,
            identity_derived_label=identity_label,
            admitted=admitted,
            quarantine_reasons=sorted(set(reasons)),
            missing_training_opt_in=sorted(set(missing_opt_in)),
        )

    async def partition(
        self,
        records: Sequence[dict],
        *,
        model_id: str,
        tenant_id: Optional[str] = None,
        granted_training_opt_ins: Iterable[str] = (),
        persist: bool = True,
    ) -> TrainingDataGateResult:
        result = TrainingDataGateResult(model_id=model_id, tenant_id=tenant_id)
        for rec in records:
            decision = self.evaluate_record(
                rec,
                model_id=model_id,
                tenant_id=tenant_id,
                granted_training_opt_ins=granted_training_opt_ins,
            )
            if decision.admitted:
                result.admitted.append(decision)
            else:
                result.quarantined.append(decision)
            if persist:
                await self._repo.insert(decision.decision_id, decision.model_dump())
        return result


training_data_gate = TrainingDataGate()
