"""
Aether Agent Layer — Review Batching Runtime
Groups staged mutations into review batches for human approval.

Grouping rules:
- By objective
- By entity
- By severity
- High-risk / high-severity items surfaced distinctly

All classes require human approval in vNext.
Classes 1-2 may be grouped more aggressively.
Classes 3-5 require stronger visibility in the review UI.
"""

from __future__ import annotations

import logging
from typing import Optional

from models.mutations import (
    MutationStatus,
    ReviewBatch,
    ReviewStatus,
    StagedMutation,
)

logger = logging.getLogger("aether.runtime.review")


class ReviewBatchingRuntime:
    """
    Manages the staging area and review batch lifecycle.
    Ensures no mutations are committed without human approval.
    """

    def __init__(self):
        self._staged: dict[str, StagedMutation] = {}
        self._batches: dict[str, ReviewBatch] = {}

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def stage_mutation(self, mutation: StagedMutation) -> None:
        mutation.stage_for_review()
        self._staged[mutation.staged_mutation_id] = mutation
        logger.info(
            f"Mutation staged: {mutation.staged_mutation_id[:8]}... "
            f"class={mutation.mutation_class.name} entity={mutation.entity_id[:8]}..."
        )

    def get_staged(self, mutation_id: str) -> Optional[StagedMutation]:
        return self._staged.get(mutation_id)

    def pending_mutations(self) -> list[StagedMutation]:
        return [
            m for m in self._staged.values()
            if m.status == MutationStatus.PENDING_REVIEW
        ]

    # ------------------------------------------------------------------
    # Batch creation
    # ------------------------------------------------------------------

    def create_batch_by_objective(self, objective_id: str) -> Optional[ReviewBatch]:
        """Group all pending mutations for an objective into a review batch."""
        mutations = [
            m for m in self.pending_mutations()
            if m.objective_id == objective_id
        ]
        if not mutations:
            return None
        return self._build_batch(objective_id, mutations)

    def create_batches_auto(self) -> list[ReviewBatch]:
        """
        Auto-batch all pending mutations. Groups low-risk (class 1-2)
        aggressively; keeps high-risk (class 3-5) in smaller, more
        visible batches.
        """
        pending = self.pending_mutations()
        if not pending:
            return []

        # Group by objective
        by_objective: dict[str, list[StagedMutation]] = {}
        for m in pending:
            by_objective.setdefault(m.objective_id, []).append(m)

        batches = []
        for obj_id, mutations in by_objective.items():
            low_risk = [m for m in mutations if m.mutation_class.value <= 2]
            high_risk = [m for m in mutations if m.mutation_class.value >= 3]

            if low_risk:
                batches.append(self._build_batch(obj_id, low_risk))
            # High-risk: one batch per entity for visibility
            if high_risk:
                by_entity: dict[str, list[StagedMutation]] = {}
                for m in high_risk:
                    by_entity.setdefault(m.entity_id, []).append(m)
                for entity_id, entity_mutations in by_entity.items():
                    batches.append(self._build_batch(obj_id, entity_mutations))

        return batches

    def _build_batch(
        self, objective_id: str, mutations: list[StagedMutation]
    ) -> ReviewBatch:
        entity_ids = list({m.entity_id for m in mutations})
        max_severity = min(m.severity for m in mutations)  # lower = more severe
        batch = ReviewBatch(
            objective_id=objective_id,
            entity_ids=entity_ids,
            severity=max_severity,
            staged_mutation_ids=[m.staged_mutation_id for m in mutations],
        )
        self._batches[batch.review_batch_id] = batch
        logger.info(
            f"Review batch created: {batch.review_batch_id[:8]}... "
            f"mutations={len(mutations)} severity={max_severity}"
        )
        return batch

    # ------------------------------------------------------------------
    # Review actions
    # ------------------------------------------------------------------

    def approve_batch(self, batch_id: str, reviewer: str, notes: str = "") -> None:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise ValueError(f"Batch {batch_id} not found")
        batch.approve(notes)
        batch.reviewed_by = reviewer
        for mid in batch.staged_mutation_ids:
            m = self._staged.get(mid)
            if m:
                m.approve()
        logger.info(f"Batch {batch_id[:8]}... approved by {reviewer}")

    def reject_batch(self, batch_id: str, reviewer: str, notes: str = "") -> None:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise ValueError(f"Batch {batch_id} not found")
        batch.reject(notes)
        batch.reviewed_by = reviewer
        for mid in batch.staged_mutation_ids:
            m = self._staged.get(mid)
            if m:
                m.reject()
        logger.info(f"Batch {batch_id[:8]}... rejected by {reviewer}")

    def open_batches(self) -> list[ReviewBatch]:
        return [
            b for b in self._batches.values()
            if b.review_status in (ReviewStatus.OPEN, ReviewStatus.IN_REVIEW)
        ]

    def approved_mutations(self) -> list[StagedMutation]:
        return [
            m for m in self._staged.values()
            if m.status == MutationStatus.APPROVED
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def pending_count(self) -> int:
        return len(self.pending_mutations())

    @property
    def open_batch_count(self) -> int:
        return len(self.open_batches())
