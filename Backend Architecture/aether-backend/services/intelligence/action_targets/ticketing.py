from services.intelligence.action_targets.base import BaseActionTarget

class TicketingActionTarget(BaseActionTarget):
    target_type = "ticketing"
    label = "Ticketing"
    description = "Create a support or implementation ticket placeholder."
    supported_action_types = ("manual", "playbook_step", "support", "operational_failure")
    supports_cancellation = True
