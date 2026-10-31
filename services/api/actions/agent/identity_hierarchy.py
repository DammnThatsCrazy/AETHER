"""Agent identity hierarchy semantics (High-Cardinality Agent Lineage, AO-2).

    Agent Definition --DEPLOYED_AS--> Agent Deployment --INSTANTIATED_AS--> Agent Instance
                                                  \\--> Run -> Task -> Step / Invocation

One logical agent may have 10 deployments and 10,000 concurrent instances;
those must never become 10,010 logical identities. Only the *definition* is a
logical agent identity. Deployment, instance, run, task and invocation are
addressable evidence/runtime records. The deployment registry
(``deployments.py``) stays the authority for deployments; instances are
high-cardinality and live in ``silver_agent_execution_facts``
(``agent_instance_id``) and the lineage index, not in a table of their own, so
this slice needs no migration.

Mirrors the hand-authored twin in ``packages/shared/agent-deployment.ts``
(parity: ``tests/contracts/test_agent_deployment_hierarchy_parity.py``).

Guardrail (work order section 34): a human and an agent never become the same
canonical entity. They are connected by relationships (OPERATES, AUTHORIZED,
OWNS, ACTED_ON_BEHALF_OF), never merged. The identity resolver's veto engine
already blocks person/agent merges; ``ensure_distinct_human_agent`` is the same
rule enforced at the lineage boundary, and every hierarchy identifier below is
non-identity-evidence for the resolver.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

# Hierarchy levels, outermost first. Mirrors AGENT_HIERARCHY_LEVELS in
# shared.agent_lineage.vocabulary (level names are the seam's; the ordering and
# edges here are the identity semantics).
HIERARCHY_LEVELS: tuple[str, ...] = (
    "agent_definition", "agent_deployment", "agent_instance",
    "agent_run", "task", "invocation",
)

# Levels that are a logical identity. Everything else is a record about a
# definition, never another agent.
LOGICAL_IDENTITY_LEVELS: frozenset[str] = frozenset({"agent_definition"})

HIERARCHY_EDGES: tuple[tuple[str, str, str], ...] = (
    ("agent_definition", "DEPLOYED_AS", "agent_deployment"),
    ("agent_deployment", "INSTANTIATED_AS", "agent_instance"),
)

# Where each level's identifier is carried (silver_agent_execution_facts column).
HIERARCHY_ID_COLUMNS: dict[str, str] = {
    "agent_definition": "agent_definition_id",
    "agent_deployment": "deployment_id",
    "agent_instance": "agent_instance_id",
    "agent_run": "source_run_id",
    "task": "task_id",
    "invocation": "source_event_id",
}

# Identifier names that must never be treated as identity-merge evidence for a
# person/entity. (``agent_id`` / ``deployment_id`` are already on the resolver's
# denylist; the rest are the new hierarchy identifiers.)
NON_IDENTITY_EVIDENCE_FIELDS: frozenset[str] = frozenset({
    "agent_id", "deployment_id", "agent_definition_id", "agent_deployment_id",
    "agent_instance_id", "source_run_id", "canonical_run_id", "root_run_id",
    "parent_run_id", "task_id", "span_id", "trace_id",
})

HUMAN_ENTITY_KINDS: frozenset[str] = frozenset({"human", "person", "user"})
AGENT_ENTITY_KINDS: frozenset[str] = frozenset({
    "agent", "agent_definition", "agent_deployment", "agent_instance",
    "external_agent", "agentic_account",
})


class HumanAgentIdentityError(ValueError):
    """Raised when a human and an agent would collapse into one identity."""


def is_logical_identity(level: str) -> bool:
    return level in LOGICAL_IDENTITY_LEVELS


def ensure_distinct_human_agent(
    *,
    human_entity_id: str,
    agent_entity_id: str,
    human_kind: str = "human",
    agent_kind: str = "agent",
) -> None:
    """Refuse to treat a human and an agent as the same canonical entity.

    A relationship (OPERATES / AUTHORIZED / OWNS / ACTED_ON_BEHALF_OF) is the
    only legal connection; sharing an email, wallet, device, IP, API-key
    namespace or deployment is not identity.
    """
    if human_kind not in HUMAN_ENTITY_KINDS:
        raise HumanAgentIdentityError(f"{human_kind!r} is not a human entity kind")
    if agent_kind not in AGENT_ENTITY_KINDS:
        raise HumanAgentIdentityError(f"{agent_kind!r} is not an agent entity kind")
    if not human_entity_id or not agent_entity_id:
        raise HumanAgentIdentityError("both entity ids are required")
    if human_entity_id == agent_entity_id:
        raise HumanAgentIdentityError(
            "a human and an agent must never share one canonical entity id; "
            "connect them with a relationship edge"
        )


def hierarchy_refs_from_deployment(deployment: Mapping[str, Any]) -> dict[str, Optional[str]]:
    """Definition and deployment references for one registry record.

    ``agent_definition_ref`` is the tenant-scoped *source* reference carried by
    the registry (``agent_id`` + ``agent_source_namespace``); it is a reference,
    not a canonical Agent entity id, which identity authority resolves.
    """
    return {
        "tenant_id": deployment.get("tenant_id"),
        "agent_definition_ref": deployment.get("agent_id"),
        "agent_source_namespace": deployment.get("agent_source_namespace"),
        "deployment_id": deployment.get("id"),
    }
