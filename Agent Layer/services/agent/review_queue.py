"""
Aether Agent Layer — Review Queue Service
Manages the internal approval queue for staged mutations.
Provides the review workflow surface for human operators.
"""

from __future__ import annotations

import logging
from typing import Any

from models.mutations import MutationClass, ReviewStatus

logger = logging.getLogger("aether.services.review_queue")


class ReviewQueueService:
    """
    Review queue service for human approval of staged mutations.
    All graph mutations in vNext require human approval.
    """

    def __init__(self, review_runtime: Any, graph_staging: Any):
        self._review = review_runtime
        self._graph = graph_staging

    def pending_review_summary(self) -> dict[str, Any]:
        """Summary of pending reviews grouped by severity."""
        batches = self._review.open_batches()
        summary = {
            "total_batches": len(batches),
            "total_mutations": sum(len(b.staged_mutation_ids) for b in batches),
            "by_severity": {},
        }
        for b in batches:
            sev = str(b.severity)
            summary["by_severity"].setdefault(sev, 0)
            summary["by_severity"][sev] += 1
        return summary

    def approve_and_commit(self, batch_id: str, reviewer: str, notes: str = "") -> dict[str, Any]:
        """
        Approve a review batch and commit all its mutations to the graph.
        Returns commit results.
        """
        self._review.approve_batch(batch_id, reviewer, notes)

        # Commit approved mutations through graph interface
        committed = []
        for mutation in self._review.approved_mutations():
            if mutation.staged_mutation_id in self._get_batch_mutation_ids(batch_id):
                success = self._graph.commit_mutation(mutation)
                committed.append({
                    "mutation_id": mutation.staged_mutation_id,
                    "committed": success,
                })

        return {
            "batch_id": batch_id,
            "reviewer": reviewer,
            "committed": committed,
        }

    def _get_batch_mutation_ids(self, batch_id: str) -> set[str]:
        batches = self._review.open_batches()
        for b in self._review._batches.values():
            if b.review_batch_id == batch_id:
                return set(b.staged_mutation_ids)
        return set()
