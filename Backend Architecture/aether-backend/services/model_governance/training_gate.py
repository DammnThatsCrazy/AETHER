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
from shared.rights_authority.contracts import ActorRef
from shared.rights_authority.pep import evaluate_rights


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
        model_allowed_purposes: Optional[Iterable[str]] = None,
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
        # Explicit scope override wins; otherwise resolve from the ML registry.
        scope_src = (
            model_allowed_purposes
            if model_allowed_purposes is not None
            else policy.allowed_training_purposes(model_id)
        )
        model_scope = set(scope_src)

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
            rights_envelope_refs=[
                str(ref) for ref in (
                    record.get("rights_envelope_refs")
                    or record.get("envelope_refs")
                    or ([record.get("rights_envelope_id")] if record.get("rights_envelope_id") else [])
                ) if ref
            ],
            rights_policy_set_ref=record.get("rights_policy_set_ref"),
            rights_source_grant_refs=[
                str(ref) for ref in (record.get("rights_source_grant_refs") or record.get("source_grant_refs") or []) if ref
            ],
            rights_lineage_set_hash=record.get("rights_lineage_set_hash") or record.get("lineage_set_hash"),
            retention_deadline=record.get("retention_deadline"),
            revocation_strategy=record.get("revocation_strategy"),
            training_basis_evidence=[
                str(ref) for ref in (record.get("training_basis_evidence") or []) if ref
            ],
        )

    async def _apply_rights(
        self, decision: TrainingDataDecision, record: dict,
    ) -> TrainingDataDecision:
        """Authorize model training and preserve the signed rights evidence."""
        result = await evaluate_rights(
            action="train",
            tenant_id=decision.tenant_id,
            actor=ActorRef(kind="service", id="model_training", tenant_id=decision.tenant_id),
            purpose="model_training",
            artifacts=[record.get("artifact_ref") or record.get("record_ref")],
            envelope_refs=decision.rights_envelope_refs,
            source_grant_refs=decision.rights_source_grant_refs,
            policy_set_ref=decision.rights_policy_set_ref,
            metadata={
                "record_ref": decision.record_ref,
                "training_basis_evidence": decision.training_basis_evidence,
                "revocation_strategy": decision.revocation_strategy,
            },
        )
        if result.decision is None:
            return decision
        signed = result.decision
        reasons = list(decision.quarantine_reasons)
        if not result.proceed:
            reasons.extend(
                f"rights_{signed.outcome}:{reason}" for reason in signed.reasons
            )
            if not signed.reasons:
                reasons.append(f"rights_{signed.outcome}")
        return decision.model_copy(update={
            "admitted": decision.admitted and result.proceed,
            "quarantine_reasons": sorted(set(reasons)),
            "rights_decision_id": signed.decision_id,
            "rights_outcome": signed.outcome,
            "rights_envelope_refs": signed.envelope_refs or decision.rights_envelope_refs,
            "rights_policy_set_ref": signed.policy_set_ref or decision.rights_policy_set_ref,
        })

    async def partition(
        self,
        records: Sequence[dict],
        *,
        model_id: str,
        tenant_id: Optional[str] = None,
        granted_training_opt_ins: Iterable[str] = (),
        model_allowed_purposes: Optional[Iterable[str]] = None,
        persist: bool = True,
    ) -> TrainingDataGateResult:
        result = TrainingDataGateResult(model_id=model_id, tenant_id=tenant_id)
        for rec in records:
            decision = self.evaluate_record(
                rec,
                model_id=model_id,
                tenant_id=tenant_id,
                granted_training_opt_ins=granted_training_opt_ins,
                model_allowed_purposes=model_allowed_purposes,
            )
            decision = await self._apply_rights(decision, rec)
            if decision.admitted:
                result.admitted.append(decision)
            else:
                result.quarantined.append(decision)
            if persist:
                await self._repo.insert(decision.decision_id, decision.model_dump())
        return result


training_data_gate = TrainingDataGate()
