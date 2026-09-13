"""
Aether Agent Layer — Evidence & Verification Models
Models for evidence collection, candidate facts, and verification results.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class VerificationDecision(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    INCONCLUSIVE = "inconclusive"


class FactVerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DISPUTED = "disputed"


# ---------------------------------------------------------------------------
# EvidenceRecord — raw evidence captured during discovery
# ---------------------------------------------------------------------------

@dataclass
class EvidenceRecord:
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    entity_id: str = ""
    source: str = ""
    source_reference: str = ""
    content_hash: str = ""
    structured_payload: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    captured_by: str = ""


# ---------------------------------------------------------------------------
# CandidateFact — a fact derived from evidence, pending verification
# ---------------------------------------------------------------------------

@dataclass
class CandidateFact:
    fact_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str = ""
    fact_type: str = ""
    value: Any = None
    supporting_evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    produced_by: str = ""
    verification_status: FactVerificationStatus = FactVerificationStatus.UNVERIFIED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# VerificationResult — outcome of verification checks on facts/evidence
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    verification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    entity_id: str = ""
    fact_ids: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    passed_checks: list[str] = field(default_factory=list)
    failed_checks: list[str] = field(default_factory=list)
    score: float = 0.0
    decision: VerificationDecision = VerificationDecision.INCONCLUSIVE
    review_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def pass_rate(self) -> float:
        if not self.checks_run:
            return 0.0
        return len(self.passed_checks) / len(self.checks_run)
