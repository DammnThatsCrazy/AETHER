"""Source roles: what a stream proves, independent of which vendor emits it.

A vendor is not a role. One provider can play several roles, and each role is
declared per stream so that trust follows the stream, not the brand:

* ``agent_runtime`` — the runtime that hosts an agent (who the agent is, its
  task, tool calls, delegation, and the reason it gives). Grok Bot, OpenAI
  Agents, Claude, and Cursor are examples. Its records are claims.
* ``tool_bridge`` — the call boundary where an agent touched a system, such as
  an MCP server or a provider's AI connector. Its records can bind an agent
  invocation to a provider object when the call returns that object's ID.
* ``system_of_record`` — the provider that owns a fact (Shopify orders, Stripe
  charges, Ramp transactions, GitHub pull requests). Domain packs decide which
  facts it may establish.
* ``network_observer`` — request-level corroboration from infrastructure the
  tenant controls, such as an edge proxy or model gateway.
* ``authority_issuer`` — the system that granted what an agent was allowed to
  do: OAuth grants and scopes, write-access approvals, spend limits, keys.

The role caps the evidence a stream can contribute on its own. A cap is a
ceiling, not a grant: a stream still needs a verified connection and an
accepted authority decision before any fact it emits becomes truth.

Domain packs remain contract/policy modules (see the universal connector
runtime blueprint). ``agent_activity`` and ``authority`` are the packs this
module introduces; the others already exist as stream ``domain_pack`` values or
blueprint packs.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable, Literal, Mapping, get_args

from shared.agent_lineage.vocabulary import PRINCIPAL_EVIDENCE_CLASSES


SOURCE_ROLE_CONTRACT_VERSION = "1"

SourceRole = Literal[
    "agent_runtime",
    "tool_bridge",
    "system_of_record",
    "network_observer",
    "authority_issuer",
]
SOURCE_ROLES: tuple[str, ...] = get_args(SourceRole)

# Domain packs a role-tagged stream may declare. ``agent_activity`` carries the
# agent task/tool/delegation/outcome vocabulary from ``shared.agent_lineage``;
# ``authority`` carries grants, scopes, limits, approvals, and revocations.
DOMAIN_PACKS: tuple[str, ...] = (
    "commerce",
    "payments",
    "communications",
    "advertising",
    "crm",
    "analytics",
    "operations",
    "agent_activity",
    "authority",
)

_ROLE_DOMAIN_PACKS: Mapping[str, frozenset[str]] = MappingProxyType({
    # A runtime or bridge describes agent activity, never a domain fact.
    "agent_runtime": frozenset({"agent_activity"}),
    "tool_bridge": frozenset({"agent_activity"}),
    # A system of record emits domain facts. Authority facts it owns (for
    # example a spend policy in a spend-management system) belong to a
    # separate authority_issuer stream so their trust is declared separately.
    "system_of_record": frozenset(set(DOMAIN_PACKS) - {"agent_activity", "authority"}),
    # An observer corroborates; it records agent activity it saw on the wire.
    "network_observer": frozenset({"agent_activity"}),
    "authority_issuer": frozenset({"authority"}),
})

# The strongest principal evidence class a stream of this role can contribute
# without a second, independent source. ``tool_bridge`` reaches a
# deterministic binding only through a returned object ID (see
# ``shared.integration_contracts.correlation``); ``network_observer`` reaches
# a cryptographic attestation only through a verified signed request.
_ROLE_EVIDENCE_CEILING: Mapping[str, str] = MappingProxyType({
    "agent_runtime": "PROVIDER_ASSERTED",
    "tool_bridge": "DETERMINISTIC_BINDING",
    "system_of_record": "PROVIDER_ASSERTED",
    "network_observer": "CRYPTOGRAPHICALLY_ATTESTED",
    "authority_issuer": "VERIFIED_AUTHORITY",
})


def _evidence_rank(evidence_class: str) -> int:
    """Lower is stronger; unknown classes rank weakest."""
    try:
        return PRINCIPAL_EVIDENCE_CLASSES.index(evidence_class)
    except ValueError:
        return len(PRINCIPAL_EVIDENCE_CLASSES)


def is_source_role(value: str) -> bool:
    return value in SOURCE_ROLES


def allowed_domain_packs(role: str) -> frozenset[str]:
    """Domain packs a stream with ``role`` may declare."""
    if role not in _ROLE_DOMAIN_PACKS:
        raise ValueError(f"unknown source role {role!r}")
    return _ROLE_DOMAIN_PACKS[role]


def evidence_ceiling(role: str) -> str:
    """The strongest evidence class a ``role`` stream contributes on its own."""
    if role not in _ROLE_EVIDENCE_CEILING:
        raise ValueError(f"unknown source role {role!r}")
    return _ROLE_EVIDENCE_CEILING[role]


def cap_evidence(role: str, evidence_class: str) -> str:
    """Clamp ``evidence_class`` to the role's ceiling; never strengthen it."""
    if evidence_class not in PRINCIPAL_EVIDENCE_CLASSES:
        return "UNKNOWN"
    ceiling = evidence_ceiling(role)
    if _evidence_rank(evidence_class) < _evidence_rank(ceiling):
        return ceiling
    return evidence_class


def role_domain_pack_violation(role: str, domain_pack: str) -> str | None:
    """A reason string when a role cannot declare ``domain_pack``, else None."""
    if role not in _ROLE_DOMAIN_PACKS:
        return f"unknown source role {role!r}"
    if domain_pack not in _ROLE_DOMAIN_PACKS[role]:
        allowed = ", ".join(sorted(_ROLE_DOMAIN_PACKS[role]))
        return f"source_role {role!r} cannot declare domain_pack {domain_pack!r} (allowed: {allowed})"
    return None


def provider_source_roles(streams: Iterable[object]) -> frozenset[str]:
    """The roles a provider plays, derived from its declared streams.

    Roles are never declared at the vendor level; a provider plays exactly the
    roles its role-tagged streams declare. Untagged (legacy) streams add none.
    """
    roles: set[str] = set()
    for stream in streams:
        role = getattr(stream, "source_role", None)
        if role is not None:
            roles.add(role)
    return frozenset(roles)


__all__ = [
    "DOMAIN_PACKS",
    "SOURCE_ROLES",
    "SOURCE_ROLE_CONTRACT_VERSION",
    "SourceRole",
    "allowed_domain_packs",
    "cap_evidence",
    "evidence_ceiling",
    "is_source_role",
    "provider_source_roles",
    "role_domain_pack_violation",
]
