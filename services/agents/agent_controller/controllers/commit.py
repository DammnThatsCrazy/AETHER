"""
Aether Agent Layer — Commit Controller
Stages graph mutations, builds review batches, maintains the internal
approval queue, and applies approved changes through graph interfaces.

CRITICAL: No direct auto-commit. All mutations require human approval in vNext.
"""

from __future__ import annotations

import logging
from typing import Any

from models.mutations import MutationClass, StagedMutation
from models.objectives import PlanStep
from shared.graph.staging import GraphStagingInterface

from agent_controller.runtime.review_batching import ReviewBatchingRuntime

logger = logging.getLogger("aether.controllers.commit")


class CommitController:
    """
    Stages mutations, builds review batches, and commits approved changes.
    Never commits without human approval.
    """

    def __init__(
        self,
        review_runtime: ReviewBatchingRuntime,
        graph_staging: GraphStagingInterface,
    ):
        self.review = review_runtime
        self.graph = graph_staging

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Stage mutations from verified facts and build review batches."""
        fact_ids = step.input_schema.get("fact_ids", [])
        entity_id = step.input_schema.get("entity_id", "")
        verification_ids = step.input_schema.get("verification_ids", [])
        proposed_changes = step.input_schema.get("proposed_changes", {})
        mutation_class = step.input_schema.get("mutation_class", 1)

        # Stage the mutation
        mutation = StagedMutation(
            objective_id=objective_id,
            entity_id=entity_id,
            mutation_class=MutationClass(mutation_class),
            severity=mutation_class,
            proposed_changes=proposed_changes,
            supporting_fact_ids=fact_ids,
            verification_ids=verification_ids,
        )
        self.review.stage_mutation(mutation)

        # Auto-batch for this objective
        batch = self.review.create_batch_by_objective(objective_id)

        logger.info(
            f"Commit: staged mutation {mutation.staged_mutation_id[:8]}... "
            f"class={mutation.mutation_class.name} "
            f"for objective {objective_id[:8]}..."
        )
        return {
            "action": "mutation_staged",
            "mutation_id": mutation.staged_mutation_id,
            "batch_id": batch.review_batch_id if batch else None,
            "awaiting_review": True,
        }

    def commit_approved(self) -> list[dict[str, Any]]:
        """Commit all approved mutations through the graph interface."""
        results = []
        for mutation in self.review.approved_mutations():
            success = self.graph.commit_mutation(mutation)
            results.append({
                "mutation_id": mutation.staged_mutation_id,
                "committed": success,
            })
        return results

    def health(self) -> dict[str, Any]:
        return {
            "controller": "commit",
            "status": "active",
            "pending_mutations": self.review.pending_count,
            "open_batches": self.review.open_batch_count,
        }
