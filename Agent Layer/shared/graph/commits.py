"""
Aether Agent Layer — Graph Commits Interface
Tracks committed mutations and provides commit history for auditing.
Complements the staging interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aether.shared.graph.commits")


@dataclass
class CommitRecord:
    """Record of a committed mutation for audit purposes."""
    commit_id: str = ""
    mutation_id: str = ""
    entity_id: str = ""
    mutation_class: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    committed_by: str = ""
    approved_by: str = ""
    committed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CommitLog:
    """In-memory commit log. Production: backed by durable store."""

    def __init__(self):
        self._commits: list[CommitRecord] = []

    def record(self, commit: CommitRecord) -> None:
        self._commits.append(commit)
        logger.info(f"Commit recorded: {commit.mutation_id[:8]}... -> {commit.entity_id[:8]}...")

    def history(self, entity_id: str | None = None) -> list[CommitRecord]:
        if entity_id:
            return [c for c in self._commits if c.entity_id == entity_id]
        return list(self._commits)

    @property
    def total_commits(self) -> int:
        return len(self._commits)
