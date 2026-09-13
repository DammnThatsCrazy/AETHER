"""Normalizes provider-specific payloads into AgenticObservationRecord."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from services.agentic_observability.models import (
    AgenticObservationRecord, ObservationSource, ObservationActor, AgentRef,
    ObservationObject, ObservationAction, ObservationProvenance,
    ObservationEconomics, ObservationRisk, ActorType, ActionStatus,
    AutonomyLevel, ObservationProvider, MCPObservationContext,
)


_NORMALIZER_ID = "agentic_observability.event_normalizer"


def resolve_provider(raw: dict) -> str:
    """Resolve a provider hint from a raw payload to a catalog-consistent id.

    Reads the provider hint from ``raw['provider']`` or a nested
    ``raw['source']['provider']`` (whichever is present), normalizes it to the
    lowercase snake form the ``provider_catalog`` uses, and returns the catalog
    ``provider_id`` verbatim when it is a known catalog entry. Unknown-but-named
    providers (e.g. the agentic ``ObservationProvider`` values like ``robinhood``)
    are returned in their normalized form; a missing hint falls back to
    ``"unknown"``. This is the single source of provider identity carried into
    the canonical spine so downstream projections stay catalog-consistent.
    """
    source_data = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    hint = (
        raw.get("provider")
        or (source_data or {}).get("provider")
        or raw.get("provider_id")
    )
    if not hint:
        return "unknown"
    normalized = str(hint).strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized or normalized == "unknown":
        return "unknown"
    try:
        from services.provider_catalog.catalog import get_provider

        if get_provider(normalized) is not None:
            return normalized
    except Exception:  # pragma: no cover — catalog import is best-effort
        pass
    return normalized


def _extract_mcp(raw: dict) -> "MCPObservationContext | None":
    """Populate the MCP observation context from nested or provider-flat keys."""
    mcp_data = raw.get("mcp") if isinstance(raw.get("mcp"), dict) else {}
    tools = raw.get("tools") or (mcp_data.get("tools") if isinstance(mcp_data, dict) else None) or []
    first_tool = tools[0] if isinstance(tools, (list, tuple)) and tools else None
    server_name = mcp_data.get("server_name") or raw.get("server_name")
    server_url = mcp_data.get("server_url") or raw.get("server_url")
    tool_name = mcp_data.get("tool_name") or raw.get("tool_name") or first_tool
    protocol_version = mcp_data.get("protocol_version") or raw.get("protocol_version")
    if not any([server_name, server_url, tool_name, protocol_version]):
        return None
    return MCPObservationContext(
        server_name=server_name,
        server_url=server_url,
        tool_name=tool_name,
        protocol_version=protocol_version,
    )


def normalize(raw: dict, provider: str, tenant_id: str, event_name: str) -> AgenticObservationRecord:
    """Normalize a provider-specific payload into a canonical AgenticObservationRecord."""
    raw_hash = AgenticObservationRecord.hash_payload(raw)

    # source: read nested source dict first, fall back to top-level keys.
    # resolve_provider carries a catalog-consistent provider_id; the enum stays
    # a back-compat shim (_to_provider maps known agentic providers, else UNKNOWN).
    source_data = raw.get("source") or {}
    resolved_provider = resolve_provider(raw)
    if resolved_provider == "unknown" and provider:
        resolved_provider = str(provider).strip().lower() or "unknown"
    source = ObservationSource(
        provider=_to_provider(source_data.get("provider") or resolved_provider or provider),
        provider_event_id=source_data.get("provider_event_id") or raw.get("event_id") or raw.get("id"),
        integration_id=source_data.get("integration_id") or raw.get("integration_id"),
        webhook_id=source_data.get("webhook_id") or raw.get("webhook_id"),
    )

    actor_data = raw.get("actor") or {}
    actor = ObservationActor(
        actor_type=ActorType(actor_data.get("actor_type", "agent")),
        actor_id=actor_data.get("actor_id") or raw.get("agent_id"),
        external_actor_id=actor_data.get("external_actor_id"),
    )

    # agent metadata: carry model/framework/autonomy_level into stored record
    agent: Any = None
    agent_data = raw.get("agent") or {}
    if agent_data:
        autonomy_raw = agent_data.get("autonomy_level")
        try:
            autonomy = AutonomyLevel(autonomy_raw) if autonomy_raw else None
        except ValueError:
            autonomy = None
        agent = AgentRef(
            agent_id=agent_data.get("agent_id"),
            external_agent_id=agent_data.get("external_agent_id"),
            model=agent_data.get("model"),
            framework=agent_data.get("framework"),
            autonomy_level=autonomy,
        )

    obj_data = raw.get("object", {})
    obj = ObservationObject(
        object_type=obj_data.get("object_type", "resource"),
        object_id=obj_data.get("object_id"),
        external_object_id=obj_data.get("external_object_id"),
    )

    action_data = raw.get("action", {})
    action = ObservationAction(
        name=action_data.get("name", event_name),
        status=ActionStatus(action_data.get("status", "observed")),
        intent=action_data.get("intent"),
        outcome=action_data.get("outcome"),
    )

    economics = None
    if "economics" in raw and raw["economics"]:
        econ = raw["economics"]
        if econ.get("is_execution_by_aether") is True:
            raise ValueError("execution_by_aether must be False")
        economics = ObservationEconomics(
            amount=econ.get("amount"),
            currency=econ.get("currency"),
            asset=econ.get("asset"),
            network=econ.get("network"),
            rail=econ.get("rail"),
            direction=econ.get("direction"),
            is_execution_by_aether=False,
        )

    provenance = ObservationProvenance(
        raw_event_hash=raw_hash,
        normalized_by=_NORMALIZER_ID,
        schema_version="1.0",
    )

    caller_risk = raw.get("risk")
    risk: Any = None
    if caller_risk and isinstance(caller_risk, dict):
        risk = ObservationRisk(
            risk_level=caller_risk.get("risk_level"),
            reason_codes=caller_risk.get("reason_codes", []),
            policy_flags=caller_risk.get("policy_flags", []),
            requires_review=caller_risk.get("requires_review", False),
        )

    mcp = _extract_mcp(raw)

    _now = datetime.now(timezone.utc).isoformat()
    return AgenticObservationRecord(
        event_name=event_name,
        tenant_id=tenant_id,
        observed_at=raw.get("observed_at") or raw.get("timestamp") or _now,
        source=source,
        actor=actor,
        agent=agent,
        object=obj,
        action=action,
        economics=economics,
        risk=risk,
        provenance=provenance,
        mcp=mcp,
    )


def _to_provider(p: str) -> ObservationProvider:
    try:
        return ObservationProvider(p.lower())
    except ValueError:
        return ObservationProvider.UNKNOWN
