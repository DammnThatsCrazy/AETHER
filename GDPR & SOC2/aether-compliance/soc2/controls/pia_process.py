"""
P-2.1 — Privacy Impact Assessment Process (GDPR Art. 35)
Defines triggers, workflow, risk matrix, and SDLC integration for PIAs.

A PIA template already exists in policies/policy_generator.py (_gen_pia_template).
This module adds the process governance: when PIAs are required, how they are
conducted, the risk matrix, and how findings are tracked to closure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PIATrigger(str, Enum):
    NEW_DATA_COLLECTION = "new_data_collection"
    NEW_PROCESSING_PURPOSE = "new_processing_purpose"
    NEW_SUB_PROCESSOR = "new_sub_processor"
    HIGH_VOLUME_PROCESSING = "high_volume_processing"
    SENSITIVE_CATEGORY = "sensitive_category"
    SYSTEMATIC_MONITORING = "systematic_monitoring"
    AUTOMATED_DECISION_MAKING = "automated_decision_making"
    CROSS_BORDER_TRANSFER = "cross_border_transfer"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class PIAStatus(str, Enum):
    DRAFT = "draft"
    DPO_REVIEW = "dpo_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONDITIONAL = "conditional"    # Approved with mandatory mitigations


@dataclass
class PIARisk:
    risk_id: str
    description: str
    likelihood: str     # low | medium | high
    severity: str       # low | medium | high
    mitigation: str
    residual_risk: RiskLevel
    owner: str


@dataclass
class PIARecord:
    """A completed Privacy Impact Assessment record."""
    pia_id: str
    activity_name: str
    trigger: PIATrigger
    description: str
    data_categories: list
    data_subjects: str
    processing_volume: str
    legal_basis: str
    necessity_assessment: str
    risks: list
    mitigations_applied: list
    dpo_consulted: bool = False
    dpo_opinion: str = ""
    status: PIAStatus = PIAStatus.DRAFT
    approved_by: str = ""
    conditions: list = field(default_factory=list)
    review_date: str = ""


# SDLC integration gates
SDLC_GATES = [
    {
        "gate": "Feature Discovery",
        "action": "Complete PIA trigger screening checklist",
        "owner": "Product Manager",
        "blocker": False,
    },
    {
        "gate": "Design Review",
        "action": "If triggers identified: complete PIA draft and DPO review",
        "owner": "Privacy Lead",
        "blocker": True,    # Cannot proceed to implementation without DPO sign-off
    },
    {
        "gate": "Implementation Complete",
        "action": "Verify all mandatory mitigations are implemented",
        "owner": "Engineering Lead",
        "blocker": True,
    },
    {
        "gate": "Pre-Production",
        "action": "Final PIA sign-off and ROPA update",
        "owner": "DPO / Privacy Lead",
        "blocker": True,
    },
]

TRIGGER_SCREENING_QUESTIONS = [
    ("Does this feature collect new categories of personal data?", PIATrigger.NEW_DATA_COLLECTION),
    ("Does this feature use existing data for a new purpose?", PIATrigger.NEW_PROCESSING_PURPOSE),
    ("Does this feature send data to a new third-party service?", PIATrigger.NEW_SUB_PROCESSOR),
    ("Will this processing cover more than 100,000 data subjects?", PIATrigger.HIGH_VOLUME_PROCESSING),
    ("Does this process special category data (health, biometric, etc.)?", PIATrigger.SENSITIVE_CATEGORY),
    ("Does this feature systematically monitor user behaviour?", PIATrigger.SYSTEMATIC_MONITORING),
    ("Does this feature make automated decisions with legal/significant effect?", PIATrigger.AUTOMATED_DECISION_MAKING),
    ("Does this feature transfer data outside the EEA?", PIATrigger.CROSS_BORDER_TRANSFER),
]

RISK_MATRIX = {
    ("low", "low"):     RiskLevel.LOW,
    ("low", "medium"):  RiskLevel.LOW,
    ("low", "high"):    RiskLevel.MEDIUM,
    ("medium", "low"):  RiskLevel.LOW,
    ("medium", "medium"): RiskLevel.MEDIUM,
    ("medium", "high"): RiskLevel.HIGH,
    ("high", "low"):    RiskLevel.MEDIUM,
    ("high", "medium"): RiskLevel.HIGH,
    ("high", "high"):   RiskLevel.VERY_HIGH,
}


class PIAProcess:
    """Manages the Privacy Impact Assessment workflow."""

    def __init__(self):
        self.records: list[PIARecord] = []

    def screen_triggers(self, feature_description: str, answers: dict) -> list[PIATrigger]:
        """Return list of triggered PIA conditions from screening questions."""
        triggered = []
        for _, trigger in TRIGGER_SCREENING_QUESTIONS:
            if answers.get(trigger.value, False):
                triggered.append(trigger)
        return triggered

    def create_pia(
        self,
        activity_name: str,
        trigger: PIATrigger,
        description: str,
        data_categories: list,
        data_subjects: str,
        legal_basis: str,
    ) -> PIARecord:
        pia_id = f"PIA-{len(self.records) + 1:04d}"
        record = PIARecord(
            pia_id=pia_id,
            activity_name=activity_name,
            trigger=trigger,
            description=description,
            data_categories=data_categories,
            data_subjects=data_subjects,
            processing_volume="TBD",
            legal_basis=legal_basis,
            necessity_assessment="",
            risks=[],
            mitigations_applied=[],
        )
        self.records.append(record)
        return record

    def assess_risk(
        self,
        pia: PIARecord,
        risk_description: str,
        likelihood: str,
        severity: str,
        mitigation: str,
        owner: str,
    ) -> PIARisk:
        risk_id = f"{pia.pia_id}-R{len(pia.risks) + 1:02d}"
        residual = RISK_MATRIX.get((likelihood, severity), RiskLevel.MEDIUM)
        risk = PIARisk(
            risk_id=risk_id,
            description=risk_description,
            likelihood=likelihood,
            severity=severity,
            mitigation=mitigation,
            residual_risk=residual,
            owner=owner,
        )
        pia.risks.append(risk)
        return risk

    def submit_for_dpo_review(self, pia: PIARecord) -> None:
        pia.status = PIAStatus.DPO_REVIEW

    def dpo_approve(self, pia: PIARecord, approver: str, conditions: list = None) -> None:
        pia.dpo_consulted = True
        pia.approved_by = approver
        pia.status = PIAStatus.CONDITIONAL if conditions else PIAStatus.APPROVED
        pia.conditions = conditions or []

    def generate_evidence(self) -> dict:
        approved = [r for r in self.records if r.status in (PIAStatus.APPROVED, PIAStatus.CONDITIONAL)]
        return {
            "control": "P-2.1",
            "artifact": "Privacy Impact Assessment Process",
            "trigger_types": len(TRIGGER_SCREENING_QUESTIONS),
            "sdlc_gates": len(SDLC_GATES),
            "risk_matrix_cells": len(RISK_MATRIX),
            "pias_conducted": len(self.records),
            "pias_approved": len(approved),
            "policy_template": "policies/policy_generator.py::_gen_pia_template (7 sections, Art. 35 aligned)",
            "status": "IMPLEMENTED",
            "evidence_type": "process_document",
        }

    def print_process(self) -> None:
        print(f"\n  Privacy Impact Assessment Process (Art. 35)")
        print(f"  Trigger conditions: {len(TRIGGER_SCREENING_QUESTIONS)}")
        print(f"  SDLC integration gates: {len(SDLC_GATES)}")
        print(f"\n  SDLC Gates:")
        for g in SDLC_GATES:
            blocker = " [BLOCKER]" if g["blocker"] else ""
            print(f"    {g['gate']}: {g['action'][:60]}...{blocker}")
        print(f"\n  Trigger Screening:")
        for q, trigger in TRIGGER_SCREENING_QUESTIONS:
            print(f"    [{trigger.value}] {q}")
