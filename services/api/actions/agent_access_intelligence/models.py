"""Domain models for the Agent Access Intelligence capability catalog (PR 2, Phase A).

Every record is tenant-scoped and derived from observed agent-execution facts. Models
are flat (no nesting) so they round-trip through ``BaseRepository`` — which stores the
whole dict as JSONB and filters on top-level ``data->>'key'`` — and so DSR erasure by
``tenant_id`` works via ``delete_by_entity``.

Honesty rule (monoprompt §4.4 / §9): unknown or unobserved state is typed as ``unknown``,
never optimistically filled. A capability record is *evidence of observed access*, not an
assertion of authority.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# Bounded provenance / association list sizes — the graph and per-event detail stay in
# Silver; the catalog keeps only a bounded, most-recent sample (ADR: high-cardinality data
# remains outside derived aggregates).
_MAX_SAMPLE_EVENT_IDS = 25
_MAX_CAPABILITY_IDS = 100
# Replay-dedup window: observation_count is deduplicated over the most-recent N distinct
# source events per record. This is a BOUNDED window (kept separate from the 25-item display
# sample so the small display list never shrinks the dedup guarantee). A redelivery older
# than this window may be counted again — observation_count is a bounded-window count, not an
# exactly-once counter; row identity is always exactly-once (deterministic id). Kept private
# (leading underscore) so it is stripped from public API output.
_MAX_DEDUP_EVENT_IDS = 512


class CapabilityKind(str, Enum):
    """What the observed capability *is*. Derived from the source event + fields; the
    default is an honest ``unknown`` rather than a guessed classification."""

    MCP_TOOL = "mcp_tool"            # a tool exposed by an MCP server
    PROVIDER_ACTION = "provider_action"  # a provider/tool action with no MCP server context
    ACCOUNT = "account"             # an external account / portfolio the agent can reach
    RESOURCE = "resource"           # an external resource/object the agent can reach
    UNKNOWN = "unknown"


class DiscoveryState(str, Enum):
    OBSERVED = "observed"           # seen via runtime observation (the only Phase A source)


class InstallationStatus(str, Enum):
    ACTIVE = "active"               # observed and not revoked


def capability_id_for(
    tenant_id: str, provider: Optional[str], server_key: Optional[str], tool_name: Optional[str]
) -> str:
    """Deterministic, bounded capability identity — idempotent across re-observation.

    Keyed by (tenant, provider, server, tool). Includes tenant so identities never
    collide across tenants (a cross-tenant ``find_by_id`` can therefore never hit
    another tenant's row)."""
    raw = f"{tenant_id}|{provider or ''}|{server_key or ''}|{tool_name or ''}"
    return "cap_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def installation_id_for(
    tenant_id: str, agent_id: Optional[str], server_key: Optional[str]
) -> str:
    """Deterministic, bounded installation identity — (tenant, agent, server)."""
    raw = f"{tenant_id}|{agent_id or ''}|{server_key or ''}"
    return "inst_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class Capability(BaseModel):
    """One distinct observed external capability for a tenant."""

    capability_id: str
    tenant_id: str
    capability_kind: CapabilityKind = CapabilityKind.UNKNOWN
    provider: Optional[str] = None
    server_name: Optional[str] = None
    server_url: Optional[str] = None
    tool_name: Optional[str] = None
    protocol_version: Optional[str] = None
    latest_risk_level: Optional[str] = None
    discovery_state: DiscoveryState = DiscoveryState.OBSERVED
    # Observed-origin identity (PR 2, Phase B2 / monoprompt §9.3). `publisher_ref` groups
    # capabilities by the origin they *claim*; it is not evidence that the origin is who it
    # says it is, and there is deliberately no `verified` state anywhere — see identity.py.
    # `artifact_digest` exists so a *change* in a capability's identity is detectable even
    # though its provenance is unverifiable; §9.5 drift compares exactly that.
    publisher_ref: Optional[str] = None
    publisher_label: Optional[str] = None
    artifact_digest: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    observation_count: int = 0
    # Bounded provenance back to the source observations (most-recent N).
    sample_source_event_ids: list[str] = Field(default_factory=list)


class CapabilityInstallation(BaseModel):
    """An observed agent↔server binding (which agent can reach which server)."""

    installation_id: str
    tenant_id: str
    agent_id: Optional[str] = None
    provider: Optional[str] = None
    server_name: Optional[str] = None
    server_url: Optional[str] = None
    protocol_version: Optional[str] = None
    status: InstallationStatus = InstallationStatus.ACTIVE
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    observation_count: int = 0
    # Bounded set of capabilities observed on this installation.
    capability_ids: list[str] = Field(default_factory=list)


def clamp_event_ids(ids: list[str]) -> list[str]:
    return ids[:_MAX_SAMPLE_EVENT_IDS]


def clamp_capability_ids(ids: list[str]) -> list[str]:
    return ids[:_MAX_CAPABILITY_IDS]


def clamp_dedup_ids(ids: list[str]) -> list[str]:
    return ids[:_MAX_DEDUP_EVENT_IDS]
