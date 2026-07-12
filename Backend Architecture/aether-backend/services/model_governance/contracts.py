"""Model-governance evidence contracts.

Two evidence shapes:

  - ``TrainingDataDecision`` — per training record/label: was it admissible for
    model training under the consent purposes it was collected under, or is it
    quarantined (with an explicit reason)?  Identity-derived labels are held to
    the same rule (§3.10 label quarantine).
  - ``InferenceGateResult`` — the outcome of the inference policy gate (§3.9),
    wrapping the canonical ``ConsentPolicyDecision`` so serve-inference evidence
    lands in the same audit ledger as every other consent decision.
"""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, Field

from services.policy.contracts import ConsentPolicyDecision
from services.security.contracts import now_iso

# Why a training record was refused admission to a training set.
QuarantineReason = str  # e.g. "purpose_forbids_training:web3", "separate_opt_in_required:financial_activity"


class TrainingDataDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"tdg_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    model_id: str
    record_ref: str
    # Consent purposes the record was collected under.
    source_purposes: list[str] = Field(default_factory=list)
    # True when this record's label was derived from identity resolution (§3.10).
    identity_derived_label: bool = False
    admitted: bool = True
    quarantine_reasons: list[str] = Field(default_factory=list)
    # Purposes that required a separate model-training opt-in the caller lacked.
    missing_training_opt_in: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class TrainingDataGateResult(BaseModel):
    model_id: str
    tenant_id: Optional[str] = None
    admitted: list[TrainingDataDecision] = Field(default_factory=list)
    quarantined: list[TrainingDataDecision] = Field(default_factory=list)

    @property
    def admitted_count(self) -> int:
        return len(self.admitted)

    @property
    def quarantined_count(self) -> int:
        return len(self.quarantined)

    def summary(self) -> dict:
        return {
            "model_id": self.model_id,
            "tenant_id": self.tenant_id,
            "admitted_count": self.admitted_count,
            "quarantined_count": self.quarantined_count,
            "quarantine_reasons": sorted(
                {r for d in self.quarantined for r in d.quarantine_reasons}
            ),
        }


class InferenceGateResult(BaseModel):
    model_id: str
    allowed: bool
    blocked: bool = False
    enforced: bool = False
    reason: Optional[str] = None
    policy_decision_id: Optional[str] = None
    required_purposes: list[str] = Field(default_factory=list)
    missing_purposes: list[str] = Field(default_factory=list)
    decision: Optional[ConsentPolicyDecision] = None
