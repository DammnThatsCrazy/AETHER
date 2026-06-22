"""Silver projector for agent execution and evaluation events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_AGENT_TYPES = frozenset({
    "agent_task_started",
    "agent_task_completed",
    "agent_task_failed",
    "agent_step_observed",
    "agent_tool_call_observed",
    "agent_handoff_observed",
    "agent_evaluation_observed",
    "agent_cost_observed",
    "agent_grounding_observed",
    "agent_guardrail_observed",
    "agent_human_override_observed",
    "agentic_session_started",
    "agentic_session_completed",
    "agentic_session_abandoned",
})


class AgentExecutionProjector(BaseProjector):
    handles = _AGENT_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "agent_id": p.get("agentId") or p.get("workerId"),
            "task_id": p.get("taskId") or p.get("sessionId"),
            "model_id": p.get("modelId") or p.get("model"),
            "prompt_tokens": p.get("promptTokens"),
            "completion_tokens": p.get("completionTokens"),
            "cost_usd": p.get("costUsd") or p.get("cost"),
            "outcome": p.get("outcome") or p.get("status"),
            "grounding_sources": p.get("groundingSources"),
            "human_override": bool(p.get("humanOverride")),
        })
        return ProjectionResult(table="silver_agent_execution_facts", rows=[row])
