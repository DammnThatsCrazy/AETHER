"""
Aether Agent Layer — Graph Staging Interface
Explicit interface between the agent layer and the graph/lake systems.
The agent layer stages mutations here; approved mutations are committed
through graph interfaces.

This module does NOT own the graph storage implementation (PostgreSQL,
Neptune, etc.) — it provides the agent-layer-side staging contract.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from models.mutations import MutationStatus, StagedMutation

logger = logging.getLogger("aether.shared.graph.staging")


class GraphStagingInterface:
    """
    Interface for staging and committing approved mutations to the graph.
    Production: delegates to services/intelligence or repositories/lake.
    """

    def __init__(self):
        self._committed: list[dict[str, Any]] = []

    def commit_mutation(self, mutation: StagedMutation) -> bool:
        """
        Commit an approved mutation to the canonical graph state.
        Returns True on success.

        IMPORTANT: Only approved mutations may be committed.
        This enforces the vNext requirement that all graph mutations
        require human approval.
        """
        if mutation.status != MutationStatus.APPROVED:
            logger.error(
                f"Cannot commit mutation {mutation.staged_mutation_id[:8]}... "
                f"— status is {mutation.status.value}, expected APPROVED"
            )
            return False

        # In production, this delegates to the graph write layer
        self._committed.append({
            "mutation_id": mutation.staged_mutation_id,
            "entity_id": mutation.entity_id,
            "changes": mutation.proposed_changes,
            "class": mutation.mutation_class.name,
        })
        mutation.commit()

        logger.info(
            f"Mutation committed: {mutation.staged_mutation_id[:8]}... "
            f"entity={mutation.entity_id[:8]}..."
        )
        return True

    def rollback_mutation(self, mutation: StagedMutation) -> bool:
        """Mark a committed mutation as rolled back."""
        if mutation.status != MutationStatus.COMMITTED:
            return False
        mutation.rollback()
        logger.info(f"Mutation rolled back: {mutation.staged_mutation_id[:8]}...")
        return True

    @property
    def commit_history(self) -> list[dict[str, Any]]:
        return list(self._committed)
