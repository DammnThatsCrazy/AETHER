from services.intelligence.action_targets.base import BaseActionTarget

class CRMTaskActionTarget(BaseActionTarget):
    target_type = "crm_task"
    label = "CRM task"
    description = "Create a CRM task placeholder from an approved decision."
    supported_action_types = ("manual", "playbook_step", "sales", "customer_success")
    supports_cancellation = True
    premium_connector = True
