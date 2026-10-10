"""Registry of supported governed action targets."""

from __future__ import annotations

from .base import BaseActionTarget


class SlackActionTarget(BaseActionTarget):
    target_type = "slack"
    label = "Slack"
    description = "Post approved action context to an operator Slack channel."
    supports_cancellation = False


class WebhookActionTarget(BaseActionTarget):
    target_type = "webhook"
    label = "Webhook"
    description = "Send approved action payloads to a tenant-owned webhook."


class CrmActionTarget(BaseActionTarget):
    target_type = "crm"
    label = "CRM task"
    description = "Create account or lifecycle tasks in a CRM integration."
    supports_cancellation = True


class MarketingActionTarget(BaseActionTarget):
    target_type = "marketing"
    label = "Marketing automation"
    description = "Queue approved audience or journey changes in a marketing tool."
    supports_cancellation = True
    premium_connector = True


class TicketingActionTarget(BaseActionTarget):
    target_type = "ticketing"
    label = "Ticketing"
    description = "Open fraud, support, or operations tickets for human review."
    supports_cancellation = True


class AgentAssistActionTarget(BaseActionTarget):
    target_type = "agent_assist"
    label = "Agent assist"
    description = "Queue approved actions for an internal agent-assisted workflow."
    requires_configuration = False
    supports_cancellation = True


class ActionTargetRegistry:
    def __init__(self) -> None:
        self._targets = {
            target.target_type: target
            for target in (
                SlackActionTarget(),
                WebhookActionTarget(),
                CrmActionTarget(),
                MarketingActionTarget(),
                TicketingActionTarget(),
                AgentAssistActionTarget(),
            )
        }

    def list_targets(self) -> list[BaseActionTarget]:
        return list(self._targets.values())

    def get(self, target_type: str) -> BaseActionTarget:
        target = self._targets.get(target_type)
        if target is None:
            raise ValueError(f"Unknown action target_type: {target_type}")
        return target
