"""Resolve source-reported agent-run references against tenant authorities.

Telemetry references are candidates only. Payment and delegation facts in this
module are read from their canonical repositories and are never accepted from
the external agent payload itself.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from actions.agent.deployments import get_deployment_repository
from repositories.repos import (
    DelegationRepository,
    PaymentIntentRepository,
    SettlementEventRepository,
)
from shared.graph.edge_properties import build_edge_properties, make_edge_idempotency_key
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from value.x402.provenance import is_server_authoritative_x402_metadata
from value.value.models import to_decimal_string

_MAX_REFERENCE_LENGTH = 256


def tenant_scoped_graph_id(kind: str, tenant_id: str, *refs: str) -> str:
    """Return the same opaque deterministic ID used for external-run records."""
    material = json.dumps([tenant_id, *refs], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]
    return f"{kind}_{digest}"


def _reference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > _MAX_REFERENCE_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        return None
    return normalized


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _graph_timestamp(value: Any) -> str:
    parsed = _parse_timestamp(value)
    return parsed.isoformat() if parsed is not None else "1970-01-01T00:00:00+00:00"


def _delegation_state_at(record: dict[str, Any], occurred_at: Any) -> str:
    instant = _parse_timestamp(occurred_at)
    if any(
        record.get(field) and _parse_timestamp(record.get(field)) is None
        for field in ("starts_at", "ends_at", "revoked_at")
    ):
        return "unknown"
    starts_at = _parse_timestamp(record.get("starts_at"))
    ends_at = _parse_timestamp(record.get("ends_at"))
    revoked_at = _parse_timestamp(record.get("revoked_at"))
    if instant is None:
        return "unknown_time"
    if starts_at is not None and instant < starts_at:
        return "not_yet_active"
    if revoked_at is not None and instant >= revoked_at:
        return "revoked"
    if ends_at is not None and instant >= ends_at:
        return "expired"
    return "active"


def delegation_is_current_or_scheduled(record: dict[str, Any], instant: Any) -> bool:
    return _delegation_state_at(record, instant) in {"active", "not_yet_active"}


def delegation_vertex(record: dict[str, Any]) -> Vertex:
    """Build a scope-free graph representation from one canonical grant row."""
    tenant_id = str(record.get("tenant_id") or "")
    delegation_id = str(record.get("delegation_id") or "")
    return Vertex(
        vertex_type=VertexType.DELEGATION,
        vertex_id=tenant_scoped_graph_id("delegation", tenant_id, delegation_id),
        properties={
            "tenant_id": tenant_id,
            "delegation_id": delegation_id,
            "grantor_entity_id": str(record.get("grantor_entity_id") or ""),
            "grantee_entity_id": str(record.get("grantee_entity_id") or ""),
            "starts_at": record.get("starts_at"),
            "ends_at": record.get("ends_at"),
            "revoked_at": record.get("revoked_at"),
            "source_authority": "delegations",
        },
    )


def delegation_relationships(
    record: dict[str, Any], source_event_id: str, *, include_delegate_edge: bool = True,
) -> list[Edge]:
    """Build canonical grant relationships from the authoritative row only."""
    tenant_id = str(record.get("tenant_id") or "")
    delegation_id = str(record.get("delegation_id") or "")
    grantor_id = str(record.get("grantor_entity_id") or "")
    grantee_id = str(record.get("grantee_entity_id") or "")
    if not all((tenant_id, delegation_id, grantor_id, grantee_id, source_event_id)):
        return []
    node_id = delegation_vertex(record).vertex_id
    starts_at = str(record.get("starts_at") or "1970-01-01T00:00:00+00:00")
    ends = [
        parsed for parsed in (
            _parse_timestamp(record.get("ends_at")),
            _parse_timestamp(record.get("revoked_at")),
        ) if parsed is not None
    ]
    valid_to = min(ends).isoformat() if ends else ""

    def edge(edge_type: str, from_id: str, to_id: str) -> Edge:
        return Edge(
            edge_type=edge_type,
            from_vertex_id=from_id,
            to_vertex_id=to_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=edge_type,
                from_vertex_id=from_id,
                to_vertex_id=to_id,
                actor_kind="system",
                actor_id="delegation_projector",
                provenance="delegation_repository",
                provenance_class="direct",
                source_event_id=source_event_id,
                valid_from=starts_at,
                valid_to=valid_to,
                confidence=1.0,
                consent_purpose="agent",
                delegation_id=delegation_id,
                revoked_at=record.get("revoked_at"),
                causality_class="authorized_delegation",
            ),
        )

    relationships: list[Edge] = []
    if include_delegate_edge:
        relationships.append(edge(EdgeType.DELEGATES, grantor_id, grantee_id))
    for edge_type, from_id, to_id in (
        (EdgeType.GRANTED_BY, node_id, grantor_id),
        (EdgeType.GRANTED_TO, node_id, grantee_id),
    ):
        relationship = edge(edge_type, from_id, to_id)
        # These edges describe the durable record's endpoints. Their identity
        # is per delegation record, and remains stable across grant/revoke events.
        relationship.properties["idempotency_key"] = make_edge_idempotency_key(
            tenant_id, edge_type, from_id, to_id, f"delegation:{delegation_id}"
        )
        relationship.properties.pop("valid_to", None)
        relationships.append(relationship)
    return relationships


class AgentRunAuthorityResolver:
    """Tenant-scoped exact-ID resolver for agent-reported run references."""

    def __init__(
        self,
        *,
        delegation_repo: DelegationRepository | None = None,
        payment_intent_repo: PaymentIntentRepository | None = None,
        settlement_repo: SettlementEventRepository | None = None,
    ) -> None:
        self._delegations = delegation_repo or DelegationRepository()
        self._intents = payment_intent_repo or PaymentIntentRepository()
        self._settlements = settlement_repo or SettlementEventRepository()
        self._deployments = get_deployment_repository()
        self._deployment_agent_refs: dict[tuple[str, str], str | None] = {}

    async def _registered_deployment_agent_ref(
        self, tenant_id: str, deployment_id: str,
    ) -> str | None:
        """Read the tenant's deployment registry reference, not a canonical entity."""
        if not tenant_id or not deployment_id:
            return None
        key = (tenant_id, deployment_id)
        if key not in self._deployment_agent_refs:
            deployment = await self._deployments.get_record(tenant_id, deployment_id)
            if (
                deployment is None
                or deployment.get("tenant_id") != tenant_id
                or deployment.get("id") != deployment_id
            ):
                self._deployment_agent_refs[key] = None
            else:
                self._deployment_agent_refs[key] = _reference(deployment.get("agent_id"))
        return self._deployment_agent_refs[key]

    async def resolve(self, row: dict[str, Any]) -> dict[str, Any]:
        delegation, delegation_record = await self._resolve_delegation(row)
        economic, intent, settlement = await self._resolve_economic(row)
        return {
            "delegation_resolution": delegation,
            "economic_outcome": economic,
            "delegation_record": delegation_record,
            "payment_intent": intent,
            "settlement_event": settlement,
        }

    async def _resolve_delegation(
        self, row: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        reference = _reference(row.get("delegation_id"))
        if reference is None:
            return ({"status": "not_supplied"}, None)
        tenant_id = str(row.get("tenant_id") or "")
        deployment_id = str(row.get("deployment_id") or "")
        if not tenant_id or not deployment_id:
            return ({"status": "unresolved"}, None)
        try:
            agent_ref = await self._registered_deployment_agent_ref(tenant_id, deployment_id)
        except Exception:
            return ({"status": "unavailable"}, None)
        if not agent_ref:
            return ({"status": "unresolved"}, None)
        try:
            record = await self._delegations.find_by_id(reference)
        except Exception:
            return ({"status": "unavailable"}, None)
        if (
            not record
            or record.get("tenant_id") != tenant_id
            or record.get("delegation_id") != reference
        ):
            return ({"status": "unresolved"}, None)
        resolution = {
            "status": "matched_reference",
            "delegation_id": reference,
            "state_at_event": _delegation_state_at(record, row.get("occurred_at")),
            "grantor_entity_id": record.get("grantor_entity_id"),
            "grantee_entity_id": record.get("grantee_entity_id"),
            "party_identity_status": "unresolved",
            "source_authority": "delegations",
        }
        return resolution, record

    async def _resolve_economic(
        self, row: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
        intent_ref = _reference(row.get("payment_intent_ref"))
        settlement_ref = _reference(row.get("settlement_event_ref"))
        if intent_ref is None and settlement_ref is None:
            return ({"status": "not_supplied", "records": []}, None, None)

        tenant_id = str(row.get("tenant_id") or "")
        deployment_id = str(row.get("deployment_id") or "")
        # Resolve the deployment's tenant-registered agent reference directly.
        # Do not use the Silver row or SDK-authored agent ID for economic matching.
        if not tenant_id or not deployment_id:
            return ({"status": "unresolved", "records": []}, None, None)

        try:
            agent_id = await self._registered_deployment_agent_ref(tenant_id, deployment_id)
            if not agent_id:
                return ({"status": "unresolved", "records": []}, None, None)

            intent = (
                await self._intents.find_for_tenant(intent_ref, tenant_id)
                if intent_ref is not None else None
            )
            settlement = None
            if settlement_ref is not None:
                settlement = await self._settlements.find_by_id(settlement_ref)
                if (
                    not settlement
                    or settlement.get("settlement_event_id") != settlement_ref
                    or settlement.get("tenant_id") != tenant_id
                    or settlement.get("agent_id") != agent_id
                ):
                    return ({"status": "unresolved", "records": []}, None, None)
                if intent is None:
                    implied_intent_id = _reference(settlement.get("intent_id"))
                    if implied_intent_id is None:
                        return ({"status": "unresolved", "records": []}, None, None)
                    intent = await self._intents.find_for_tenant(implied_intent_id, tenant_id)
                elif settlement.get("intent_id") != intent.get("intent_id"):
                    return ({"status": "unresolved", "records": []}, None, None)

            if (
                not intent
                or (intent_ref is not None and intent.get("intent_id") != intent_ref)
                or intent.get("tenant_id") != tenant_id
                or intent.get("agent_id") != agent_id
                or not is_server_authoritative_x402_metadata(intent.get("metadata"))
            ):
                return ({"status": "unresolved", "records": []}, None, None)
            if settlement is not None and (
                settlement.get("intent_id") != intent.get("intent_id")
                or settlement.get("tenant_id") != tenant_id
                or settlement.get("agent_id") != agent_id
                or not is_server_authoritative_x402_metadata(settlement.get("metadata"))
            ):
                return ({"status": "unresolved", "records": []}, None, None)
        except Exception:
            return ({"status": "unavailable", "records": []}, None, None)

        try:
            amount = to_decimal_string(settlement.get("amount") if settlement else intent.get("amount"))
        except Exception:
            amount = None
        records = [{
            "payment_intent_id": intent.get("intent_id"),
            "settlement_event_id": settlement.get("settlement_event_id") if settlement else None,
            "intent_status": intent.get("settlement_status"),
            "settlement_status": settlement.get("status") if settlement else None,
            "amount": amount,
            "currency": settlement.get("currency") if settlement else intent.get("currency"),
            "provider": settlement.get("provider") or intent.get("provider"),
            "protocol": settlement.get("protocol") or intent.get("protocol"),
            "source_authority": "x402_commerce",
            "source_topic": (
                (settlement if settlement else intent).get("metadata", {}).get("source_topic")
            ),
        }]
        return ({"status": "matched", "records": records}, intent, settlement)


def build_agent_run_authority_mutations(
    row: dict[str, Any], resolved: dict[str, Any]
) -> list[Any]:
    """Build replayable links only for references matched to canonical rows."""
    tenant_id = str(row.get("tenant_id") or "")
    deployment_id = str(row.get("deployment_id") or "")
    run_id = str(row.get("run_id") or "")
    source_event_id = str(row.get("source_event_id") or "")
    if not (tenant_id and deployment_id and run_id and source_event_id):
        return []
    action_id = tenant_scoped_graph_id("agent_action", tenant_id, deployment_id, source_event_id)
    source_time = row.get("occurred_at")
    occurred_at = _graph_timestamp(source_time)
    time_basis = "source_occurred_at" if _parse_timestamp(source_time) else "unknown_source_time"
    mutations: list[Any] = []

    delegation = resolved.get("delegation_record")
    if delegation and delegation.get("tenant_id") == tenant_id:
        node = delegation_vertex(delegation)
        mutations.append(node)
        edge_type = EdgeType.REFERENCES_DELEGATION_RECORD
        properties = build_edge_properties(
            tenant_id=tenant_id,
            edge_type=edge_type,
            from_vertex_id=action_id,
            to_vertex_id=node.vertex_id,
            actor_kind="system",
            actor_id="agent_marketplace_authority_resolver",
            provenance="agent_run_authority_resolution",
            provenance_class="silver",
            source_event_id=source_event_id,
            valid_from=occurred_at,
            confidence=1.0,
            correlation_basis="exact_tenant_scoped_reference",
            authorization_claim="none",
            party_identity_status="unresolved",
            time_basis=time_basis,
        )
        mutations.append(Edge(
            edge_type=edge_type,
            from_vertex_id=action_id,
            to_vertex_id=node.vertex_id,
            properties=properties,
        ))

    intent = resolved.get("payment_intent")
    settlement = resolved.get("settlement_event")
    if intent and intent.get("tenant_id") == tenant_id:
        from value.x402.economic_mutations import (
            agent_payment_intent_vertex,
            agent_settlement_event_vertex,
        )

        intent_vertex = agent_payment_intent_vertex(intent)
        mutations.append(intent_vertex)
        edge_type = EdgeType.CORRELATED_WITH_ECONOMIC_RECORD
        intent_edge = Edge(
            edge_type=edge_type,
            from_vertex_id=action_id,
            to_vertex_id=intent_vertex.vertex_id,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=edge_type,
                from_vertex_id=action_id,
                to_vertex_id=intent_vertex.vertex_id,
                actor_kind="system",
                actor_id="agent_marketplace_authority_resolver",
                provenance="agent_run_authority_resolution",
                provenance_class="silver",
                source_event_id=source_event_id,
                valid_from=occurred_at,
                confidence=1.0,
                correlation_basis="exact_tenant_and_registry_agent_reference",
                economic_record_kind="payment_intent",
                time_basis=time_basis,
            ),
        )
        mutations.append(intent_edge)

        if settlement and settlement.get("tenant_id") == tenant_id:
            settlement_vertex = agent_settlement_event_vertex(settlement)
            mutations.extend([
                settlement_vertex,
                Edge(
                    edge_type=EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
                    from_vertex_id=action_id,
                    to_vertex_id=settlement_vertex.vertex_id,
                    properties=build_edge_properties(
                        tenant_id=tenant_id,
                        edge_type=EdgeType.CORRELATED_WITH_ECONOMIC_RECORD,
                        from_vertex_id=action_id,
                        to_vertex_id=settlement_vertex.vertex_id,
                        actor_kind="system",
                        actor_id="agent_marketplace_authority_resolver",
                        provenance="agent_run_authority_resolution",
                        provenance_class="silver",
                        source_event_id=source_event_id,
                        valid_from=occurred_at,
                        confidence=1.0,
                        correlation_basis="exact_tenant_and_registry_agent_reference",
                        economic_record_kind="settlement_event",
                        time_basis=time_basis,
                    ),
                ),
            ])
    return mutations
