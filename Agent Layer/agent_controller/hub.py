"""
Aether Agent Layer — Controller Hub
Assembles the full multi-controller hierarchy and provides the
single integration point for the agent layer.

Hierarchy:
  Governance Controller
    -> KIRA Controller
        -> Domain Controllers (intake, discovery, enrichment, verification,
                               commit, recovery, bolt, trigger)
            -> Teams -> Workers / Tools / Verifiers / Stagers / Recovery Paths
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agent_controller.governance import GovernanceController, GovernancePolicy
from agent_controller.kira import KiraController
from agent_controller.controllers.intake import IntakeController
from agent_controller.controllers.discovery import DiscoveryController
from agent_controller.controllers.enrichment import EnrichmentController
from agent_controller.controllers.verification import VerificationController
from agent_controller.controllers.commit import CommitController
from agent_controller.controllers.recovery import RecoveryController
from agent_controller.controllers.bolt import BoltController
from agent_controller.controllers.trigger import TriggerController
from agent_controller.runtime.objective_runtime import ObjectiveRuntime
from agent_controller.runtime.loop_runtime import LoopRuntime
from agent_controller.runtime.checkpointing import CheckpointStore
from agent_controller.runtime.briefing import BriefingStore
from agent_controller.runtime.review_batching import ReviewBatchingRuntime
from agent_controller.runtime.unit_identity import (
    create_controller_unit,
)
from agent_controller.planning.stopping_policy import StoppingPolicy
from models.units import UnitRegistry
from shared.events.objective_events import EventBus
from shared.graph.staging import GraphStagingInterface

logger = logging.getLogger("aether.hub")


class ControllerHub:
    """
    Assembles and wires the full controller hierarchy.
    This is the main entry point for the agent layer.
    """

    def __init__(
        self,
        governance_policy: GovernancePolicy | None = None,
        units_enabled: bool = False,
        loop_budget: float = 50.0,
        loop_policy_ceiling: int = 100,
    ):
        # --- Shared runtimes ---
        self.event_bus = EventBus()
        self.objective_runtime = ObjectiveRuntime()
        self.checkpoint_store = CheckpointStore()
        self.briefing_store = BriefingStore()
        self.review_runtime = ReviewBatchingRuntime()
        self.graph_staging = GraphStagingInterface()
        self.unit_registry = UnitRegistry(enabled=units_enabled)

        # --- LOOP runtime (shared behavior, not a controller) ---
        self.loop = LoopRuntime(
            budget_limit=loop_budget,
            policy_ceiling=loop_policy_ceiling,
        )
        stopping_policy = StoppingPolicy()
        self.loop.register_stop_hook(stopping_policy.as_loop_hook())

        # --- Governance Controller (top) ---
        self.governance = GovernanceController(governance_policy)

        # --- KIRA Controller (orchestrator under Governance) ---
        self.kira = KiraController(
            governance=self.governance,
            objective_runtime=self.objective_runtime,
            event_bus=self.event_bus,
            loop=self.loop,
        )

        # --- Domain Controllers ---
        self.intake = IntakeController(self.objective_runtime)
        self.discovery = DiscoveryController()
        self.enrichment = EnrichmentController()
        self.verification = VerificationController()
        self.commit = CommitController(self.review_runtime, self.graph_staging)
        self.recovery = RecoveryController(self.checkpoint_store, self.objective_runtime)
        self.bolt = BoltController(self.checkpoint_store, self.briefing_store, self.event_bus)
        self.trigger = TriggerController(self.event_bus)

        # --- Register domain controllers with KIRA ---
        self.kira.register_controller("intake", self.intake)
        self.kira.register_controller("discovery", self.discovery)
        self.kira.register_controller("enrichment", self.enrichment)
        self.kira.register_controller("verification", self.verification)
        self.kira.register_controller("commit", self.commit)
        self.kira.register_controller("recovery", self.recovery)
        self.kira.register_controller("bolt", self.bolt)
        self.kira.register_controller("trigger", self.trigger)

        # --- Optional UNITS registration ---
        if units_enabled:
            self._register_units()

        logger.info("Controller hub assembled — all controllers wired")

    def _register_units(self) -> None:
        """Register all controllers as UNITS identities."""
        controllers = [
            ("governance", "GOV", ["policy", "budget", "kill_switch", "arbitration"]),
            ("kira", "KIRA", ["orchestration", "synthesis", "supervision"]),
            ("intake", "INTK", ["normalization", "dedupe", "admission"]),
            ("discovery", "DISC", ["evidence_collection", "source_polling"]),
            ("enrichment", "ENRC", ["fact_generation", "resolution"]),
            ("verification", "VRFY", ["evidence_check", "provenance", "scoring"]),
            ("commit", "CMIT", ["staging", "review", "approval"]),
            ("recovery", "RCVR", ["retry", "fallback", "rollback"]),
            ("bolt", "BOLT", ["continuity", "briefing", "handoff"]),
            ("trigger", "TRIG", ["scheduling", "wake_routing"]),
        ]
        for name, designation, caps in controllers:
            create_controller_unit(
                self.unit_registry, name,
                designation=designation, capabilities=caps,
            )

    # ------------------------------------------------------------------
    # Controller health (aggregated)
    # ------------------------------------------------------------------

    def controller_health(self) -> dict[str, Any]:
        """Aggregate health from all controllers."""
        return {
            "governance": self.governance.health(),
            "kira": self.kira.health(),
            "intake": self.intake.health(),
            "discovery": self.discovery.health(),
            "enrichment": self.enrichment.health(),
            "verification": self.verification.health(),
            "commit": self.commit.health(),
            "recovery": self.recovery.health(),
            "bolt": self.bolt.health(),
            "trigger": self.trigger.health(),
            "loop": self.loop.summary(),
            "units": {
                "enabled": self.unit_registry.enabled,
                "count": self.unit_registry.count,
            },
        }
