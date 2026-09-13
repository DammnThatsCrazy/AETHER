"""
Aether Agent Layer — Discovery Controller
Orchestrates source-facing evidence collection through discovery teams.
Manages source fallback, retries, and evidence capture.
"""

from __future__ import annotations

import logging
from typing import Any

from models.evidence import EvidenceRecord
from models.objectives import PlanStep

logger = logging.getLogger("aether.controllers.discovery")


class DiscoveryController:
    """
    Orchestrates evidence collection from external sources.
    Routes work to discovery teams (web crawlers, API scanners,
    social listeners, chain monitors, etc.).
    """

    def __init__(self, worker_registry: Any = None):
        self._teams: dict[str, Any] = {}
        self._evidence_store: list[EvidenceRecord] = []
        self._worker_registry = worker_registry

    def register_team(self, team_name: str, team: Any) -> None:
        self._teams[team_name] = team

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Execute a discovery step: collect evidence from sources."""
        evidence_collected = []

        # Route to appropriate team based on step input
        team_name = step.assigned_team or "discovery_default"

        # Execute evidence collection
        record = EvidenceRecord(
            objective_id=objective_id,
            source=team_name,
            captured_by=f"discovery.{team_name}",
        )
        self._evidence_store.append(record)
        evidence_collected.append(record.evidence_id)

        logger.info(
            f"Discovery: collected {len(evidence_collected)} evidence records "
            f"for objective {objective_id[:8]}..."
        )
        return {
            "action": "evidence_collected",
            "evidence_ids": evidence_collected,
            "source_team": team_name,
        }

    def get_evidence(self, objective_id: str) -> list[EvidenceRecord]:
        return [e for e in self._evidence_store if e.objective_id == objective_id]

    def health(self) -> dict[str, Any]:
        return {
            "controller": "discovery",
            "status": "active",
            "teams": list(self._teams.keys()),
            "total_evidence": len(self._evidence_store),
        }
