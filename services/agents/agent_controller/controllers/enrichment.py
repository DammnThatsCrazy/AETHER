"""
Aether Agent Layer — Enrichment Controller
Orchestrates candidate fact generation, entity resolution/reconciliation,
and enrichment team routing.
"""

from __future__ import annotations

import logging
from typing import Any

from models.evidence import CandidateFact
from models.objectives import PlanStep

logger = logging.getLogger("aether.controllers.enrichment")


class EnrichmentController:
    """
    Generates candidate facts from evidence, orchestrates entity
    resolution and reconciliation, and routes work to enrichment teams.
    """

    def __init__(self, worker_registry: Any = None):
        self._teams: dict[str, Any] = {}
        self._fact_store: list[CandidateFact] = []
        self._worker_registry = worker_registry

    def register_team(self, team_name: str, team: Any) -> None:
        self._teams[team_name] = team

    def handle_step(self, step: PlanStep, objective_id: str) -> dict[str, Any]:
        """Execute an enrichment step: generate candidate facts from evidence."""
        facts_generated = []

        # Generate candidate facts
        team_name = step.assigned_team or "enrichment_default"
        evidence_ids = step.input_schema.get("evidence_ids", [])

        fact = CandidateFact(
            entity_id=step.input_schema.get("entity_id", ""),
            fact_type="enrichment",
            produced_by=f"enrichment.{team_name}",
            supporting_evidence_ids=evidence_ids,
        )
        self._fact_store.append(fact)
        facts_generated.append(fact.fact_id)

        logger.info(
            f"Enrichment: generated {len(facts_generated)} candidate facts "
            f"for objective {objective_id[:8]}..."
        )
        return {
            "action": "facts_generated",
            "fact_ids": facts_generated,
            "team": team_name,
        }

    def get_facts(self, entity_id: str) -> list[CandidateFact]:
        return [f for f in self._fact_store if f.entity_id == entity_id]

    def health(self) -> dict[str, Any]:
        return {
            "controller": "enrichment",
            "status": "active",
            "teams": list(self._teams.keys()),
            "total_facts": len(self._fact_store),
        }
