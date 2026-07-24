"""Agent Access Intelligence (PR 2) — capability catalog, authority & governance.

This service turns the agent-execution observations that PR 1 routes through the
canonical ingestion spine (``silver_agent_execution_facts``) into a tenant-scoped
inventory of the external capabilities an agent can actually reach: MCP tools,
provider actions, servers, and the agent↔server installations that bind them.

Phase A (shipped here) is the capability catalog + installations inventory, a
maintained materialization upserted out-of-band from the silver fact stream. It
is NOT a Silver dispatcher projector (a catalog is a table→table derivation, not
a Bronze-event projection) — see
``docs/source-of-truth/AGENT_ACCESS_INTELLIGENCE_PR2.md``.
"""

from __future__ import annotations

from .catalog_service import CapabilityCatalogService, capability_catalog_service

__all__ = ["CapabilityCatalogService", "capability_catalog_service"]
