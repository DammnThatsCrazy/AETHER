"""Action target registry for governed integration dispatch."""
from __future__ import annotations

from services.intelligence.action_targets.agent_assist import AgentAssistedActionTarget
from services.intelligence.action_targets.base import BaseActionTarget
from services.intelligence.action_targets.crm import CRMTaskActionTarget
from services.intelligence.action_targets.marketing import MarketingAutomationActionTarget
from services.intelligence.action_targets.slack import SlackActionTarget
from services.intelligence.action_targets.ticketing import TicketingActionTarget
from services.intelligence.action_targets.webhook import WebhookActionTarget


class ActionTargetRegistry:
    def __init__(self, targets: list[BaseActionTarget] | None = None) -> None:
        self._targets = targets or [
            SlackActionTarget(),
            WebhookActionTarget(),
            CRMTaskActionTarget(),
            MarketingAutomationActionTarget(),
            TicketingActionTarget(),
            AgentAssistedActionTarget(),
        ]

    @property
    def targets(self) -> list[BaseActionTarget]:
        return list(self._targets)

    def get(self, target_type: str) -> BaseActionTarget | None:
        return next((target for target in self._targets if target.target_type == target_type), None)

    def require(self, target_type: str) -> BaseActionTarget:
        target = self.get(target_type)
        if target is None:
            raise ValueError(f"Unknown action target: {target_type}")
        return target
