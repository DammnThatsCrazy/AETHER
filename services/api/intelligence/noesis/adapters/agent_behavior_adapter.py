"""Noesis read-only adapter for the ``agent_behavior`` intent (WO-115).

Answers "what does this agent usually do / what did it decide / what can't
Aether see" by reading the backend-owned Agent360 behavior read model — the
same bounded, tenant-scoped Silver read and governance inputs the
``GET /v1/agent/agents/{agent_ref}/behavior`` route uses, so the conversational
surface and the HTTP surface cannot drift.

Read-only. Noesis never writes a fact, resolves or merges agent identity, or
upgrades an inferred claim; agent refs are source-reported. A read that raises
returns ``sufficient=False`` with an honest answer rather than crashing the
conversation surface.

Returns the standard adapter envelope::

    {"answer": str, "results": list, "sources": list, "sufficient": bool}
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.agent_behavior")

SOURCES = ["silver_agent_execution_facts", "delegation_repository"]


async def read_agent_behavior(tenant_id: str, agent_ref: str) -> dict[str, Any]:
    """Build the Agent360 behavior read model exactly as the HTTP route does."""
    from actions.agent.deployment_routes import _agent_continuity_reviews, _behavior_facts
    from intelligence.agent_behavior.read_models import agent360_behavior
    from repositories.repos import DelegationRepository

    facts, truncated = await _behavior_facts(tenant_id, agent_ref)
    grants = await DelegationRepository().active_for(agent_ref, tenant_id)
    return agent360_behavior(
        facts, agent_ref, truncated=truncated, grants=grants,
        queued_reviews=await _agent_continuity_reviews(tenant_id, agent_ref),
    )


def _section_value(sections: dict[str, Any], name: str) -> tuple[str, Any]:
    section = sections.get(name) or {}
    return str(section.get("state") or "unavailable"), section.get("data")


def summarize(read_model: dict[str, Any]) -> dict[str, Any]:
    """Turn a read model into the Noesis adapter envelope."""
    agent_ref = read_model.get("agent_ref")
    sections = read_model.get("sections") or {}
    behavior_status, behavior = _section_value(sections, "behavior")
    decisions_status, decisions = _section_value(sections, "decisions")
    _, observability = _section_value(sections, "observability")
    cannot_see = list((observability or {}).get("what_aether_cannot_see") or [])

    if behavior_status == "unavailable" or not behavior:
        answer = (
            f"No observed behavior facts for agent {agent_ref} in this tenant. "
            "Absence of facts is not evidence the agent is inactive."
        )
        if cannot_see:
            answer += f" Aether cannot see: {', '.join(map(str, cannot_see[:6]))}."
        return {
            "answer": answer,
            "results": [read_model],
            "sources": SOURCES,
            "sufficient": False,
        }

    usual = behavior.get("what_it_usually_does") or {}
    tools = [t.get("tool") for t in usual.get("top_tools") or [] if t.get("tool")]
    parts = [f"Agent {agent_ref} (source-reported ref; not an identity resolution)."]
    if usual.get("usual_disposition"):
        parts.append(f"Usual disposition: {usual['usual_disposition']} (inferred, {usual.get('basis')}).")
    if tools:
        parts.append(f"Most-used tools: {', '.join(map(str, tools[:5]))}.")
    count = len(decisions or []) if decisions_status != "unavailable" else 0
    parts.append(f"{count} reconstructed decision(s).")
    if read_model.get("source_truncated"):
        parts.append("The source read was capped, so this view is partial.")
    if cannot_see:
        parts.append(f"Aether cannot see: {', '.join(map(str, cannot_see[:6]))}.")
    return {
        "answer": " ".join(parts),
        "results": [read_model],
        "sources": SOURCES,
        "sufficient": True,
    }


async def agent_behavior(tenant_id: str, agent_ref: Optional[str]) -> dict[str, Any]:
    if not agent_ref:
        return {
            "answer": "Which agent should I explain? Name an agent ref, e.g. 'agent ag_123'.",
            "results": [], "sources": [], "sufficient": False,
        }
    try:
        read_model = await read_agent_behavior(tenant_id, agent_ref)
    except Exception as exc:  # honest unavailability, never a crash
        logger.warning(
            "agent behavior read model unavailable for Noesis",
            extra={"tenant_id": tenant_id, "error": type(exc).__name__},
        )
        return {
            "answer": f"The behavior read model for agent {agent_ref} is unavailable right now.",
            "results": [], "sources": SOURCES, "sufficient": False,
        }
    return summarize(read_model)
