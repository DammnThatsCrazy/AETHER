"""
Aether Agent Layer — Mutation & Review Models
Models for staged mutations, review batches, and the commit approval workflow.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MutationClass(int, Enum):
    """
    Mutation classification for review severity routing.

    Class 1 — additive low-risk metadata
    Class 2 — enrichment updates to non-critical fields
    Class 3 — identity / merge / split / canonicalization changes
    Class 4 — destructive or rollback-sensitive mutations
    Class 5 — policy-sensitive / high-impact graph mutations
    """
    ADDITIVE_METADATA = 1
    ENRICHMENT_UPDATE = 2
    IDENTITY_CHANGE = 3
    DESTRUCTIVE = 4
    POLICY_SENSITIVE = 5


class MutationStatus(str, Enum):
    STAGED = "staged"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"


class ReviewStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIAL = "partial"
    DEFERRED = "deferred"


# ---------------------------------------------------------------------------
# StagedMutation — a proposed graph change awaiting review
# ---------------------------------------------------------------------------

@dataclass
class StagedMutation:
    staged_mutation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    entity_id: str = ""
    mutation_class: MutationClass = MutationClass.ADDITIVE_METADATA
    severity: int = 2
    proposed_changes: dict[str, Any] = field(default_factory=dict)
    supporting_fact_ids: list[str] = field(default_factory=list)
    verification_ids: list[str] = field(default_factory=list)
    status: MutationStatus = MutationStatus.STAGED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def stage_for_review(self) -> None:
        self.status = MutationStatus.PENDING_REVIEW

    def approve(self) -> None:
        self.status = MutationStatus.APPROVED

    def reject(self) -> None:
        self.status = MutationStatus.REJECTED

    def commit(self) -> None:
        self.status = MutationStatus.COMMITTED

    def rollback(self) -> None:
        self.status = MutationStatus.ROLLED_BACK

    @property
    def is_high_risk(self) -> bool:
        return self.mutation_class.value >= MutationClass.IDENTITY_CHANGE.value


# ---------------------------------------------------------------------------
# ReviewBatch — a grouped set of mutations for human review
# ---------------------------------------------------------------------------

@dataclass
class ReviewBatch:
    review_batch_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    entity_ids: list[str] = field(default_factory=list)
    severity: int = 2
    staged_mutation_ids: list[str] = field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.OPEN
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None
    review_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def start_review(self, reviewer: str) -> None:
        self.review_status = ReviewStatus.IN_REVIEW
        self.reviewed_by = reviewer

    def approve(self, notes: str = "") -> None:
        self.review_status = ReviewStatus.APPROVED
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_notes = notes

    def reject(self, notes: str = "") -> None:
        self.review_status = ReviewStatus.REJECTED
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_notes = notes

    def defer(self, notes: str = "") -> None:
        self.review_status = ReviewStatus.DEFERRED
        self.reviewed_at = datetime.now(timezone.utc)
        self.review_notes = notes

    @property
    def has_high_risk_items(self) -> bool:
        """Placeholder — caller should check mutation classes externally."""
        return self.severity <= 1
