"""
Aether Agent Layer — Graph Conflict Detection
Detects and reports conflicts between staged mutations before commit.
"""

from __future__ import annotations

import logging
from typing import Any

from models.mutations import StagedMutation

logger = logging.getLogger("aether.shared.graph.conflicts")


class ConflictDetector:
    """Detects conflicting mutations targeting the same entities/fields."""

    def detect_conflicts(self, mutations: list[StagedMutation]) -> list[dict[str, Any]]:
        """
        Check a set of mutations for conflicts.
        Returns a list of conflict descriptions.
        """
        conflicts = []
        by_entity: dict[str, list[StagedMutation]] = {}
        for m in mutations:
            by_entity.setdefault(m.entity_id, []).append(m)

        for entity_id, entity_mutations in by_entity.items():
            if len(entity_mutations) <= 1:
                continue
            # Check for overlapping field changes
            fields_seen: dict[str, str] = {}
            for m in entity_mutations:
                for field_name in m.proposed_changes:
                    if field_name in fields_seen:
                        conflicts.append({
                            "entity_id": entity_id,
                            "field": field_name,
                            "mutation_a": fields_seen[field_name],
                            "mutation_b": m.staged_mutation_id,
                            "type": "field_overlap",
                        })
                    else:
                        fields_seen[field_name] = m.staged_mutation_id

        if conflicts:
            logger.warning(f"Detected {len(conflicts)} mutation conflicts")
        return conflicts
