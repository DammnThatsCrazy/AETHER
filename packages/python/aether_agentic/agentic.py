"""Python Agentic Observation Contract v2 helpers.

This module builds observation-only telemetry envelopes for server-side agents
and MCP runtimes. It intentionally contains no provider execution client and no
provider credential handling: AETHER observes, correlates, verifies, explains,
and recommends; AETHER does not execute external actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, MutableMapping
from uuid import uuid4

TrackFn = Callable[[dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _without_none(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None}


@dataclass(slots=True)
class AgenticObservationInput:
    """Input shape for a Contract v2 observation envelope."""

    tenant_id: str
    event_type: str
    object: Mapping[str, Any]
    action: Mapping[str, Any]
    event_id: str | None = None
    observed_at: str | None = None
    source: Mapping[str, Any] = field(default_factory=dict)
    actor: Mapping[str, Any] = field(default_factory=dict)
    agent: Mapping[str, Any] | None = None
    runtime: Mapping[str, Any] | None = None
    correlation: Mapping[str, Any] | None = None
    mcp: Mapping[str, Any] | None = None
    authorization: Mapping[str, Any] | None = None
    verification: Mapping[str, Any] | None = None
    privacy: Mapping[str, Any] | None = None
    risk: Mapping[str, Any] | None = None
    economics: Mapping[str, Any] | None = None


def build_agentic_observation(input: AgenticObservationInput | Mapping[str, Any]) -> dict[str, Any]:
    """Build a Contract v2 event without executing any provider action."""

    data: MutableMapping[str, Any]
    if isinstance(input, AgenticObservationInput):
        data = asdict(input)
    else:
        data = dict(input)

    observed_at = data.get("observed_at") or _now_iso()
    event_id = data.get("event_id") or f"agentic_{uuid4().hex}"
    source = dict(data.get("source") or {})
    actor = dict(data.get("actor") or {})
    agent = data.get("agent")
    economics = dict(data.get("economics") or {})
    if economics:
        economics["is_execution_by_aether"] = False

    event = {
        "event_id": event_id,
        "event_type": data["event_type"],
        "event_name": data["event_type"],
        "tenant_id": data["tenant_id"],
        "schema_version": "2.0",
        "observed_at": observed_at,
        "received_at": observed_at,
        "source": _without_none(
            {
                "provider": source.get("provider", "custom"),
                "provider_event_id": source.get("provider_event_id"),
                "integration_id": source.get("integration_id"),
                "webhook_id": source.get("webhook_id"),
                "sdk_name": source.get("sdk_name", "aether-python"),
                "sdk_version": source.get("sdk_version"),
            }
        ),
        "actor": _without_none(
            {
                "actor_type": actor.get("actor_type", "agent"),
                "actor_id": actor.get("actor_id") or (agent or {}).get("agent_id"),
                "external_actor_id": actor.get("external_actor_id"),
            }
        ),
        "agent": agent,
        "runtime": data.get("runtime"),
        "correlation": data.get("correlation"),
        "mcp": data.get("mcp"),
        "authorization": data.get("authorization"),
        "object": data["object"],
        "action": data["action"],
        "economics": economics or None,
        "verification": data.get("verification"),
        "risk": data.get("risk"),
        "privacy": data.get("privacy") or {"content_capture_mode": "metadata_only", "privacy_class": "metadata"},
        "provenance": {
            "raw_event_hash": data.get("event_id") or "sdk_generated_before_transport_hash",
            "normalized_by": "aether-python",
            "schema_version": "2.0",
        },
    }
    return _without_none(event)


def to_ingestion_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Map a Contract v2 event into the generic Python SDK ingestion shape."""

    return {
        "type": event["event_type"],
        "message_id": event["event_id"],
        "timestamp": event["observed_at"],
        "properties": {**dict(event), "execution_by_aether": False, "agentic_contract_version": "2.0"},
    }


class AgenticObservationClient:
    """Small queue-backed Python client for Contract v2 agentic observations."""

    def __init__(self, track: TrackFn | None = None) -> None:
        self._track = track
        self._queue: list[dict[str, Any]] = []

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    def observe_agentic(self, input: AgenticObservationInput | Mapping[str, Any]) -> dict[str, Any]:
        event = to_ingestion_event(build_agentic_observation(input))
        if self._track is not None:
            self._track(event)
        else:
            self._queue.append(event)
        return event

    def drain(self) -> list[dict[str, Any]]:
        events = list(self._queue)
        self._queue.clear()
        return events

    def observe_agent(self, *, tenant_id: str, agent_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_activity_observed",
                "agent": {**dict(kwargs.get("agent") or {}), "agent_id": agent_id},
                "object": {"object_type": "agent", "object_id": agent_id},
                "action": {"name": "agent_observed", "status": "observed"},
            }
        )

    def observe_mcp_connection(self, *, tenant_id: str, connection_id: str, server_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_mcp_connection_observed",
                "correlation": {**dict(kwargs.get("correlation") or {}), "connection_id": connection_id},
                "mcp": {**dict(kwargs.get("mcp") or {}), "server_name": server_name},
                "object": {"object_type": "mcp_connection", "object_id": connection_id},
                "action": {"name": "mcp_connection_observed", "status": "observed"},
            }
        )

    def observe_tool_invocation(self, *, tenant_id: str, invocation_id: str, tool_name: str, tool_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_tool_invocation_observed",
                "correlation": {**dict(kwargs.get("correlation") or {}), "invocation_id": invocation_id},
                "mcp": {**dict(kwargs.get("mcp") or {}), "tool_name": tool_name, "tool_id": tool_id},
                "object": {"object_type": "tool", "object_id": tool_id or tool_name},
                "action": {"name": "tool_invocation_observed", "status": "observed"},
            }
        )

    def observe_authorization(self, *, tenant_id: str, authorization_id: str, external_account_id: str, scopes: list[str], **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_permission_observed",
                "authorization": {
                    **dict(kwargs.get("authorization") or {}),
                    "authorization_id": authorization_id,
                    "external_account_id": external_account_id,
                    "scopes": scopes,
                },
                "object": {"object_type": "authorization_grant", "object_id": authorization_id},
                "action": {"name": "authorization_observed", "status": "observed"},
            }
        )

    def observe_provider_action(self, *, tenant_id: str, provider_action_id: str, provider_request_id: str | None = None, external_object_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_tool_invocation_observed",
                "correlation": {
                    **dict(kwargs.get("correlation") or {}),
                    "provider_request_id": provider_request_id,
                    "external_object_id": external_object_id,
                },
                "object": {"object_type": "provider_action", "object_id": provider_action_id, "external_object_id": external_object_id},
                "action": {"name": "provider_action_observed", "status": "observed"},
            }
        )

    def observe_provider_verification(self, *, tenant_id: str, verification_id: str, status: str, provider_request_id: str | None = None, external_object_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.observe_agentic(
            {
                **kwargs,
                "tenant_id": tenant_id,
                "event_type": "agent_risk_signal_observed" if status == "contradicted" else "agent_activity_observed",
                "verification": {
                    **dict(kwargs.get("verification") or {}),
                    "verification_status": status,
                    "provider_request_id": provider_request_id,
                    "external_object_id": external_object_id,
                },
                "object": {"object_type": "provider_verification", "object_id": verification_id, "external_object_id": external_object_id},
                "action": {"name": "provider_verification_observed", "status": "failed_observed" if status == "contradicted" else "observed"},
            }
        )
