from services.intelligence.action_targets.base import BaseActionTarget

class MarketingAutomationActionTarget(BaseActionTarget):
    target_type = "marketing_automation"
    label = "Marketing automation"
    description = "Queue a marketing automation placeholder for approved recommendations."
    supported_action_types = ("manual", "playbook_step", "campaign", "retention")
    supports_cancellation = True
    premium_connector = True
