"""
Aether Agent Layer — Routing Policy
Determines which domain controller and team should handle a given plan step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from models.objectives import PlanStep

logger = logging.getLogger("aether.planning.routing")


@dataclass
class RoutingDecision:
    controller: str
    team: str = ""
    reason: str = ""
    priority: int = 2


class RoutingPolicy:
    """
    Routes plan steps to the appropriate domain controller and team
    based on domain, load, and capability matching.
    """

    def __init__(self):
        self._controller_capabilities: dict[str, list[str]] = {
            "intake": ["normalization", "dedupe", "admission", "classification"],
            "discovery": ["source_polling", "evidence_collection", "web_crawl", "api_scan"],
            "enrichment": ["fact_generation", "resolution", "reconciliation", "profiling"],
            "verification": ["evidence_check", "provenance", "schema_check", "scoring"],
            "commit": ["staging", "batch_review", "approval_queue", "graph_write"],
            "recovery": ["retry", "fallback", "compensation", "rollback", "checkpoint_restore"],
            "bolt": ["continuity", "briefing", "handoff", "run_history"],
            "trigger": ["scheduling", "wake_routing", "missed_fire", "orphan_cleanup"],
        }
        self._team_load: dict[str, int] = {}

    def route_step(self, step: PlanStep) -> RoutingDecision:
        """Determine the best controller and team for a plan step."""
        domain = step.required_domain
        if domain in self._controller_capabilities:
            return RoutingDecision(
                controller=domain,
                team=self._select_team(domain),
                reason=f"Direct domain match: {domain}",
            )
        # Fallback: try capability matching
        for ctrl, caps in self._controller_capabilities.items():
            if domain in caps:
                return RoutingDecision(
                    controller=ctrl,
                    team=self._select_team(ctrl),
                    reason=f"Capability match: {domain} -> {ctrl}",
                )
        return RoutingDecision(
            controller="intake",
            reason=f"No match for domain '{domain}', defaulting to intake",
        )

    def _select_team(self, controller: str) -> str:
        """Select the least-loaded team under a controller."""
        # Simple round-robin placeholder — production uses real load metrics
        return f"{controller}_default"

    def register_team_load(self, team: str, load: int) -> None:
        self._team_load[team] = load
