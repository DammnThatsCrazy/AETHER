"""Risk signal evaluation for agentic observability."""
from __future__ import annotations

from services.agentic_observability.models import AgenticObservationRecord, ObservationRisk, RiskLevel


_KNOWN_MCP_SERVERS = {
    "filesystem", "memory", "sequential-thinking", "fetch",
    "brave-search", "github", "slack", "google-maps",
}

_HIGH_FREQ_TOOL_THRESHOLD = 50


def evaluate_risk(record: AgenticObservationRecord, recent_invocation_count: int = 0) -> ObservationRisk:
    """Evaluate risk signals from an observed agentic activity."""
    reason_codes: list[str] = []
    policy_flags: list[str] = []
    risk_level = RiskLevel.LOW

    if record.agent and record.agent.autonomy_level and record.agent.autonomy_level.value == "autonomous_observed":
        if not record.agent.agent_id:
            reason_codes.append("autonomous_agent_without_known_id")
            risk_level = max_risk(risk_level, RiskLevel.HIGH)
        else:
            reason_codes.append("autonomous_agent_observed")
            risk_level = max_risk(risk_level, RiskLevel.MEDIUM)

    if record.event_name == "agent_mcp_connection_observed":
        server = record.object.object_id or ""
        if server and server not in _KNOWN_MCP_SERVERS:
            reason_codes.append("unknown_mcp_server")
            risk_level = max_risk(risk_level, RiskLevel.MEDIUM)

    if record.event_name == "agent_tool_invocation_observed" and recent_invocation_count > _HIGH_FREQ_TOOL_THRESHOLD:
        reason_codes.append("high_frequency_tool_invocation")
        policy_flags.append("rate_limit_review")
        risk_level = max_risk(risk_level, RiskLevel.HIGH)

    if record.economics and record.economics.amount:
        if record.economics.amount > 10000:
            reason_codes.append("large_economic_amount_observed")
            risk_level = max_risk(risk_level, RiskLevel.MEDIUM)

    return ObservationRisk(
        risk_level=risk_level,
        reason_codes=reason_codes,
        policy_flags=policy_flags,
        requires_review=risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
    )


def max_risk(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
    return order[max(order.index(a), order.index(b))]
