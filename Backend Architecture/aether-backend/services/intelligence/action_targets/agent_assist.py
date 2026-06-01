from services.intelligence.action_targets.base import BaseActionTarget

class AgentAssistedActionTarget(BaseActionTarget):
    target_type = "agent_assist"
    label = "Agent assist"
    description = "Queue a governed agent-assist task without autonomous irreversible execution."
    supported_action_types = ("manual", "playbook_step", "agent_assist", "agent_governance")
    supports_cancellation = True
    premium_connector = True
    approval_policy_notes = "Agent assist dispatches remain non-irreversible and require human approval for elevated or critical actions."
