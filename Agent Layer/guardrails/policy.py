"""
Aether Agent Layer — Policy Guardrails
Policy enforcement for the multi-controller architecture.
Extends the existing guardrails with controller-aware policy checks.
"""

from __future__ import annotations

import logging
from typing import Any

from models.mutations import MutationClass

logger = logging.getLogger("aether.guardrails.policy")


class PolicyGuard:
    """
    Enforces agent layer policy rules across controllers.
    Works alongside the existing Guardrails facade.
    """

    def __init__(
        self,
        require_human_approval: bool = True,
        allowed_mutation_classes: list[int] | None = None,
        max_batch_size: int = 50,
    ):
        self.require_human_approval = require_human_approval
        self.allowed_mutation_classes = allowed_mutation_classes or [1, 2, 3, 4, 5]
        self.max_batch_size = max_batch_size

    def check_mutation_allowed(self, mutation_class: MutationClass) -> bool:
        """Check if a mutation class is allowed under current policy."""
        return mutation_class.value in self.allowed_mutation_classes

    def check_batch_size(self, batch_size: int) -> bool:
        """Check if a review batch is within size limits."""
        return batch_size <= self.max_batch_size

    def check_auto_commit_allowed(self) -> bool:
        """In vNext, auto-commit is never allowed."""
        if self.require_human_approval:
            return False
        return True

    def mutation_visibility(self, mutation_class: MutationClass) -> str:
        """
        Determine review UI visibility for a mutation class.
        Classes 1-2: standard visibility (can be grouped aggressively)
        Classes 3-5: high visibility (surfaced distinctly)
        """
        if mutation_class.value >= 3:
            return "high"
        return "standard"
