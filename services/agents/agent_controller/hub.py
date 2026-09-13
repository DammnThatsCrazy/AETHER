"""
Aether Agent Layer — Controller Hub
Assembles the full multi-controller hierarchy and provides the
single integration point for the agent layer.

Hierarchy:
  Governance Controller
    -> Nous Controller
        -> Domain Controllers (intake, discovery, enrichment, verification,
                               commit, recovery, kinesis, catalyst)
            -> Teams -> Workers / Tools / Verifiers / Stagers / Recovery Paths
"""

from __future__ import annotations

import logging
from typing import Any

from models.atoms import AtomRegistry
from shared.events.objective_events import EventBus
from shared.graph.staging import GraphStagingInterface

from agent_controller.controllers.kinesis import KinesisController
from agent_controller.controllers.commit import CommitController
from agent_controller.controllers.discovery import DiscoveryController
from agent_controller.controllers.enrichment import EnrichmentController
from agent_controller.controllers.intake import IntakeController
from agent_controller.controllers.recovery import RecoveryController
from agent_controller.controllers.catalyst import CatalystController
from agent_controller.controllers.verification import VerificationController
from agent_controller.governance import GovernanceController, GovernancePolicy
from agent_controller.nous import NousController
from agent_controller.planning.stopping_policy import StoppingPolicy
from agent_controller.runtime.briefing import BriefingStore
from agent_controller.runtime.checkpointing import CheckpointStore
from agent_controller.runtime.cycle_runtime import CycleRuntime
from agent_controller.runtime.objective_runtime import ObjectiveRuntime
from agent_controller.runtime.review_batching import ReviewBatchingRuntime
from agent_controller.runtime.atom_identity import (
    create_controller_atom,
)

logger = logging.getLogger("aether.hub")


class ControllerHub:
    """
    Assembles and wires the full controller hierarchy.
    This is the main entry point for the agent layer.
    """

    def __init__(
        self,
        governance_policy: GovernancePolicy | None = None,
        atoms_enabled: bool = False,
        cycle_budget: float = 50.0,
        cycle_policy_ceiling: int = 100,
    ):
        # --- Shared runtimes ---
        self.event_bus = EventBus()
        self.objective_runtime = ObjectiveRuntime()
        self.checkpoint_store = CheckpointStore()
        self.briefing_store = BriefingStore()
        self.review_runtime = ReviewBatchingRuntime()
        self.graph_staging = GraphStagingInterface()
        self.atom_registry = AtomRegistry(enabled=atoms_enabled)

        # --- Cycle runtime (shared behavior, not a controller) ---
        self.cycle = CycleRuntime(
            budget_limit=cycle_budget,
            policy_ceiling=cycle_policy_ceiling,
        )
        stopping_policy = StoppingPolicy()
        self.cycle.register_stop_hook(stopping_policy.as_cycle_hook())

        # --- Governance Controller (top) ---
        self.governance = GovernanceController(governance_policy)

        # --- Nous Controller (orchestrator under Governance) ---
        self.nous = NousController(
            governance=self.governance,
            objective_runtime=self.objective_runtime,
            event_bus=self.event_bus,
            cycle=self.cycle,
        )

        # --- Domain Controllers ---
        self.intake = IntakeController(self.objective_runtime)
        self.discovery = DiscoveryController()
        self.enrichment = EnrichmentController()
        self.verification = VerificationController()
        self.commit = CommitController(self.review_runtime, self.graph_staging)
        self.recovery = RecoveryController(self.checkpoint_store, self.objective_runtime)
        self.kinesis = KinesisController(self.checkpoint_store, self.briefing_store, self.event_bus)
        self.catalyst = CatalystController(self.event_bus)

        # --- Register domain controllers with Nous ---
        self.nous.register_controller("intake", self.intake)
        self.nous.register_controller("discovery", self.discovery)
        self.nous.register_controller("enrichment", self.enrichment)
        self.nous.register_controller("verification", self.verification)
        self.nous.register_controller("commit", self.commit)
        self.nous.register_controller("recovery", self.recovery)
        self.nous.register_controller("kinesis", self.kinesis)
        self.nous.register_controller("catalyst", self.catalyst)

        # --- Optional Atoms registration ---
        if atoms_enabled:
            self._register_atoms()

        logger.info("Controller hub assembled — all controllers wired")

    def _register_atoms(self) -> None:
        """Register all controllers as Atoms identities."""
        controllers = [
            ("governance", "GOV", ["policy", "budget", "kill_switch", "arbitration"]),
            ("nous", "NOUS", ["orchestration", "synthesis", "supervision"]),
            ("intake", "INTK", ["normalization", "dedupe", "admission"]),
            ("discovery", "DISC", ["evidence_collection", "source_polling"]),
            ("enrichment", "ENRC", ["fact_generation", "resolution"]),
            ("verification", "VRFY", ["evidence_check", "provenance", "scoring"]),
            ("commit", "CMIT", ["staging", "review", "approval"]),
            ("recovery", "RCVR", ["retry", "fallback", "rollback"]),
            ("kinesis", "KNSS", ["continuity", "briefing", "handoff"]),
            ("catalyst", "CTLS", ["scheduling", "wake_routing"]),
        ]
        for name, designation, caps in controllers:
            create_controller_atom(
                self.atom_registry, name,
                designation=designation, capabilities=caps,
            )

    # ------------------------------------------------------------------
    # Controller health (aggregated)
    # ------------------------------------------------------------------

    def controller_health(self) -> dict[str, Any]:
        """Aggregate health from all controllers."""
        return {
            "governance": self.governance.health(),
            "nous": self.nous.health(),
            "intake": self.intake.health(),
            "discovery": self.discovery.health(),
            "enrichment": self.enrichment.health(),
            "verification": self.verification.health(),
            "commit": self.commit.health(),
            "recovery": self.recovery.health(),
            "kinesis": self.kinesis.health(),
            "catalyst": self.catalyst.health(),
            "cycle": self.cycle.summary(),
            "atoms": {
                "enabled": self.atom_registry.enabled,
                "count": self.atom_registry.count,
            },
        }
