from __future__ import annotations

from services.intelligence.recommendation_families.base import BaseRecommendationFamily, RecommendationGenerationContext, _num


class AgentGovernanceRecommendationFamily(BaseRecommendationFamily):
    family_key = "agent_governance"
    family_label = "Agent governance"
    detection_signal_keys = ("agent_failure_rate", "agent_spend_rate", "unauthorized_attempts", "tool_error_rate", "approval_escalation_rate")
    primary_signal = "agent_failure_rate"
    detect_threshold = 0.3
    default_expected_outcome = "Prevent unsafe or wasteful autonomous agent behavior."
    default_downside_risk = "Over-restriction can slow legitimate automation."
    default_policy_flags = ('agent_policy_review', 'human_approval_required', 'critical')

    def expected_value(self, context: RecommendationGenerationContext) -> float | None:
        value = context.value("economic_expected_value", context.value("expected_value_usd", context.value("agent_spend_rate")))
        if value is None:
            return None
        return round(_num(value) * 1.0, 2)

    def action_specs(self, context: RecommendationGenerationContext) -> list[dict]:
        value = self.expected_value(context)
        return [
            {"key": "require_human_approval", "label": "Require human approval", "approval": "critical", "flags": ['agent_policy_review', 'human_approval_required', 'critical']},
            {"key": "restrict_capability", "label": "Restrict capability", "approval": "critical", "flags": ['agent_policy_review', 'human_approval_required', 'critical']},
            {"key": "inspect_tool_invocation_chain", "label": "Inspect tool invocation chain", "approval": "elevated", "flags": ['agent_policy_review', 'human_approval_required', 'critical']},
            {"key": "open_kyber_diagnostic", "label": "Open Kyber diagnostic", "approval": "elevated", "flags": ['agent_policy_review', 'human_approval_required', 'critical']}
        ]
