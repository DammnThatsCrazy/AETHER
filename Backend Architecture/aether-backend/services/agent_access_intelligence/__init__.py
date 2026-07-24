"""Agent Access Intelligence (PR 2) — capability catalog, authority & governance.

This service turns the agent-execution observations that PR 1 routes through the
canonical ingestion spine (``silver_agent_execution_facts``) into a tenant-scoped
inventory of the external capabilities an agent can actually reach: MCP tools,
provider actions, servers, and the agent↔server installations that bind them.

Phase A is the capability catalog + installations inventory, a maintained
materialization upserted out-of-band from the silver fact stream. It is NOT a Silver
dispatcher projector (a catalog is a table→table derivation, not a Bronze-event
projection). Phase B1 adds capability authority (authorizations stored as delegation
rows) and the ``capability.invoke`` policy; Phase B2 adds artifact/publisher identity
and the declared side that drift compares against — see
``docs/source-of-truth/AGENT_ACCESS_INTELLIGENCE_PR2.md``.

Identity note, because it is the easiest thing here to get wrong: nothing in this
package verifies a third-party publisher, and no ``verified`` state exists anywhere in
it. ``identity.py`` derives a grouping key for a *claimed* origin and a digest that makes
*change* detectable — neither is provenance.
"""

from __future__ import annotations

from .catalog_service import CapabilityCatalogService, capability_catalog_service
from .identity import (
    IdentityState,
    artifact_digest_for,
    declaration_id_for,
    identity_state_for,
    publisher_label_for,
    publisher_ref_for,
)

__all__ = [
    "CapabilityCatalogService",
    "capability_catalog_service",
    "IdentityState",
    "artifact_digest_for",
    "declaration_id_for",
    "identity_state_for",
    "publisher_label_for",
    "publisher_ref_for",
]
