"""Read-only reconciliation of agent execution links against canonical sources.

This check deliberately does not inspect the projection outbox or call the
projection mutation builder. It resolves tenant-scoped Silver source rows to
canonical repositories, derives the expected link identities, and compares
them with a bounded tenant-owned graph edge scan. A complete result is still a
best-effort comparison across non-snapshot source and graph reads.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable, Optional, Sequence

from shared.graph.graph import Edge, EdgeType, GraphClient
from value.x402.provenance import is_server_authoritative_x402_metadata

_REFERENCE_MAX_LENGTH = 256
_ECONOMIC_EDGE = str(EdgeType.CORRELATED_WITH_ECONOMIC_RECORD)
_DELEGATION_EDGE = str(EdgeType.REFERENCES_DELEGATION_RECORD)
_IDENTITY_EDGE = str(EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT)
_CHECKED_EDGE_TYPES = (_ECONOMIC_EDGE, _DELEGATION_EDGE, _IDENTITY_EDGE)
_MAX_SOURCE_ROWS = 50_000
_MAX_SOURCE_PAGE_SIZE = 1_000
_MAX_GRAPH_EDGE_SCAN = 10_000
_MAX_PAGE_CALLS = 100


@dataclass(frozen=True)
class ExpectedAgentEconomyLink:
    """Normalized expected edge, also used by optional authority extensions."""

    tenant_id: str
    source_event_id: str
    edge_type: str
    from_vertex_id: str
    to_vertex_id: str
    record_kind: str
    authorization_status: Optional[str] = None
    expected_properties: dict[str, Any] = field(default_factory=dict)


AuthorityExtension = Callable[
    [dict[str, Any], dict[str, Any]],
    Awaitable[dict[str, Any]] | dict[str, Any],
]


def agent_run_authority_extension(resolver: Any) -> AuthorityExtension:
    """Adapt the canonical run authority result into checker status records.

    The extension contributes policy/identity status only. Graph expectations
    still come from the checker's own tenant-scoped source resolution and graph
    reads; the resolver's mutation builder and outbox are never consulted.
    """
    async def evaluate(row: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        resolved = await resolver.resolve(row)
        statuses: list[dict[str, Any]] = []
        delegation_resolution = resolved.get("delegation_resolution") or {}
        if delegation_resolution.get("status") not in (None, "not_supplied"):
            party_status = delegation_resolution.get("party_identity_status") or "unresolved"
            statuses.append({
                "authority": "delegation_identity",
                "status": "matched" if party_status == "matched" else "indeterminate",
                "party_identity_status": party_status,
                "actor_identity_status": delegation_resolution.get("actor_identity_status"),
                "target_identity_status": delegation_resolution.get("target_identity_status"),
                "delegation_id": delegation_resolution.get("delegation_id"),
                "execution_occurrence": "source_reported",
                "execution_verified": False,
            })
        authorization = resolved.get("delegation_authorization") or {}
        if authorization.get("status") not in (None, "not_supplied"):
            statuses.append({
                "authority": "delegation_authorization",
                **authorization,
                "execution_occurrence": (
                    (resolved.get("execution_occurrence") or {}).get("status")
                    or "source_reported"
                ),
                "execution_verified": bool(
                    (resolved.get("execution_occurrence") or {}).get("verified", False)
                ),
            })
        occurrence = resolved.get("execution_occurrence") or {}
        statuses.append({
            "authority": "execution_occurrence",
            "status": occurrence.get("status") or "source_reported",
            "execution_occurrence": occurrence.get("status") or "source_reported",
            "execution_verified": bool(occurrence.get("verified", False)),
            "reason": occurrence.get("reason"),
        })
        return {"statuses": statuses}

    return evaluate


def _ref(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (
        not value
        or len(value) > _REFERENCE_MAX_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return None
    return value


def _tenant_owned(properties: Optional[dict[str, Any]], tenant_id: str) -> bool:
    """Require every persisted tenant spelling to agree with this scope."""
    if not properties:
        return False
    values = [
        str(properties[key])
        for key in ("tenantId", "tenant_id")
        if properties.get(key) not in (None, "")
    ]
    return bool(values) and all(value == str(tenant_id) for value in values)


def _scoped_id(kind: str, tenant_id: str, *references: str) -> str:
    """Reproduce the persisted opaque ID contract from its documented tuple."""
    material = json.dumps(
        [tenant_id, *references], ensure_ascii=False, separators=(",", ":")
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]
    return f"{kind}_{digest}"


def _link_key(link: ExpectedAgentEconomyLink | Edge) -> tuple[str, str, str, str, str]:
    if isinstance(link, Edge):
        props = link.properties or {}
        if link.edge_type == _DELEGATION_EDGE:
            record_kind = "delegation"
        elif link.edge_type == _ECONOMIC_EDGE:
            record_kind = str(props.get("economic_record_kind") or "unknown")
        else:
            record_kind = "identity_binding"
        return (
            link.edge_type,
            str(props.get("source_event_id") or ""),
            link.from_vertex_id,
            link.to_vertex_id,
            record_kind,
        )
    return (
        link.edge_type,
        link.source_event_id,
        link.from_vertex_id,
        link.to_vertex_id,
        link.record_kind,
    )


class AgentEconomyGraphStateChecker:
    """Compare agent execution economic/delegation links with persisted graph.

    All canonical repository queries include the requested tenant and an exact
    source reference. ``authority_extensions`` can contribute identity or
    authorization findings and normalized graph-link expectations without
    coupling this checker to a specific identity implementation.
    """

    def __init__(
        self,
        *,
        graph: Optional[GraphClient] = None,
        analytics: Any = None,
        deployment_repo: Any = None,
        delegation_repo: Any = None,
        payment_intent_repo: Any = None,
        settlement_repo: Any = None,
        identity_binding_repo: Any = None,
        entity_repo: Any = None,
        authority_extensions: Sequence[AuthorityExtension] = (),
    ) -> None:
        self._graph = graph
        self._analytics = analytics
        self._deployment_repo = deployment_repo
        self._delegation_repo = delegation_repo
        self._payment_intent_repo = payment_intent_repo
        self._settlement_repo = settlement_repo
        self._identity_binding_repo = identity_binding_repo
        self._entity_repo = entity_repo
        self._authority_extensions = tuple(authority_extensions)

    def _dependencies(self) -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
        graph = self._graph
        analytics = self._analytics
        deployments = self._deployment_repo
        delegations = self._delegation_repo
        intents = self._payment_intent_repo
        settlements = self._settlement_repo
        identity_bindings = self._identity_binding_repo
        entities = self._entity_repo
        if graph is None:
            from shared.graph.graph import get_graph_client

            graph = get_graph_client()
        if analytics is None:
            from dependencies.providers import get_cache
            from repositories.repos import AnalyticsRepository

            analytics = AnalyticsRepository(get_cache())
        if deployments is None:
            from actions.agent.deployments import get_deployment_repository

            deployments = get_deployment_repository()
        if delegations is None or intents is None or settlements is None or entities is None:
            from repositories.repos import (
                DelegationRepository,
                EntityRepository,
                PaymentIntentRepository,
                SettlementEventRepository,
            )

            delegations = delegations or DelegationRepository()
            intents = intents or PaymentIntentRepository()
            settlements = settlements or SettlementEventRepository()
            entities = entities or EntityRepository()
        if identity_bindings is None:
            from actions.agent_marketplace.identity_binding import (
                AgentDeploymentIdentityBindingRepository,
            )

            identity_bindings = AgentDeploymentIdentityBindingRepository()
        return graph, analytics, deployments, delegations, intents, settlements, identity_bindings, entities

    @staticmethod
    async def _find_exact(repository: Any, *, tenant_id: str, field: str, reference: str) -> tuple[Optional[dict], str]:
        """Use a tenant predicate and a tiny result cap; ambiguity fails closed."""
        rows = await repository.find_many(
            filters={"tenant_id": tenant_id, field: reference}, limit=2,
        )
        exact = [
            row for row in rows
            if row.get("tenant_id") == tenant_id and str(row.get(field) or "") == reference
        ]
        if len(exact) == 1:
            return exact[0], "matched"
        if len(exact) > 1:
            return None, "ambiguous"
        return None, "unresolved"

    async def _expected_identity_links(
        self,
        tenant_id: str,
        deployments: Any,
        identity_bindings: Any,
        entities: Any,
        *,
        limit: int,
    ) -> tuple[list[ExpectedAgentEconomyLink], list[dict[str, Any]], bool, Optional[str]]:
        """Resolve all active tenant bindings, including deployments with no Silver rows."""
        try:
            rows = await identity_bindings.find_many(
                filters={"tenant_id": tenant_id, "status": "active"},
                limit=limit + 1,
            )
        except Exception as exc:
            return [], [{
                "type": "unresolved",
                "authority": "agent_deployment_identity_binding",
                "reason": "identity_binding_scan_failed",
                "error_type": type(exc).__name__,
            }], True, type(exc).__name__
        truncated = len(rows) > limit
        rows = rows[:limit]
        links: list[ExpectedAgentEconomyLink] = []
        statuses: list[dict[str, Any]] = []
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for binding in rows:
            if binding.get("tenant_id") != tenant_id:
                statuses.append({
                    "type": "unauthorized",
                    "authority": "agent_deployment_identity_binding",
                    "reason": "binding_tenant_mismatch",
                })
                continue
            namespace = _ref(binding.get("source_namespace"))
            source_ref = _ref(binding.get("source_agent_ref"))
            if not namespace or not source_ref:
                statuses.append({
                    "type": "unresolved",
                    "authority": "agent_deployment_identity_binding",
                    "reason": "binding_source_reference_invalid",
                })
                continue
            grouped.setdefault((namespace.lower(), source_ref), []).append(binding)
        binding_by_source: dict[tuple[str, str], dict[str, Any]] = {}
        for (namespace, source_ref), bindings in grouped.items():
            if len(bindings) != 1:
                statuses.append({
                    "type": "unresolved",
                    "authority": "agent_deployment_identity_binding",
                    "status": "indeterminate",
                    "source_namespace": namespace,
                    "source_agent_ref": source_ref,
                    "reason": "multiple_active_identity_bindings",
                })
                continue
            binding_by_source[(namespace, source_ref)] = bindings[0]

        deployment_cursor: Optional[str] = None
        deployment_scan_complete = False
        deployment_count = 0
        deployment_page_count = 0
        # DurableStore scans may return an empty-but-truncated page when a
        # backend's storage page contains no matching tenant rows. Permit a
        # small number of such advances, but keep the total number of backend
        # calls bounded independently of the number of matching rows.
        deployment_page_cap = min(
            _MAX_PAGE_CALLS,
            max(1, (limit + 249) // 250 + 8),
        )
        matched_bindings: set[tuple[str, str]] = set()
        while deployment_count < limit and deployment_page_count < deployment_page_cap:
            page_size = min(250, limit - deployment_count)
            try:
                deployments_page, next_cursor, deployment_truncated = await deployments.list_page(
                    tenant_id, limit=page_size, cursor=deployment_cursor,
                )
            except Exception as exc:
                return links, statuses, True, type(exc).__name__
            deployment_page_count += 1
            if len(deployments_page) > page_size:
                return links, statuses, True, "deployment_page_exceeded_requested_limit"
            deployment_count += len(deployments_page)
            for deployment in deployments_page:
                if deployment.get("tenant_id") != tenant_id:
                    statuses.append({
                        "type": "unauthorized",
                        "authority": "agent_deployment_identity_binding",
                        "reason": "deployment_scan_tenant_mismatch",
                    })
                    continue
                deployment_id = _ref(deployment.get("id"))
                source_ref = _ref(deployment.get("agent_id"))
                namespace = _ref(deployment.get("agent_source_namespace"))
                if not (deployment_id and source_ref and namespace):
                    continue
                binding_key = (namespace.lower(), source_ref)
                binding = binding_by_source.get(binding_key)
                if binding is None:
                    continue
                canonical_id = _ref(binding.get("canonical_agent_entity_id"))
                if binding.get("binding_authority") != "tenant_admin_explicit" or not canonical_id:
                    statuses.append({
                        "type": "unresolved",
                        "authority": "agent_deployment_identity_binding",
                        "status": "indeterminate",
                        "source_namespace": namespace,
                        "source_agent_ref": source_ref,
                        "deployment_id": deployment_id,
                        "reason": "binding_fields_invalid",
                    })
                    continue
                try:
                    entity_rows = await entities.find_many(
                        filters={
                            "tenant_id": tenant_id,
                            "entity_id": canonical_id,
                            "entity_type": "agent",
                        },
                        limit=2,
                    )
                except Exception as exc:
                    statuses.append({
                        "type": "unresolved",
                        "authority": "agent_deployment_identity_binding",
                        "status": "unavailable",
                        "source_namespace": namespace,
                        "source_agent_ref": source_ref,
                        "deployment_id": deployment_id,
                        "reason": "binding_target_authority_unavailable",
                        "error_type": type(exc).__name__,
                    })
                    continue
                exact_entities = [
                    entity for entity in entity_rows
                    if entity.get("tenant_id") == tenant_id
                    and entity.get("entity_id") == canonical_id
                    and entity.get("entity_type") == "agent"
                ]
                if len(exact_entities) != 1:
                    statuses.append({
                        "type": "unresolved",
                        "authority": "agent_deployment_identity_binding",
                        "status": "indeterminate",
                        "source_namespace": namespace,
                        "source_agent_ref": source_ref,
                        "deployment_id": deployment_id,
                        "canonical_agent_entity_id": canonical_id,
                        "reason": "canonical_agent_entity_unresolved",
                    })
                    continue
                links.append(ExpectedAgentEconomyLink(
                    tenant_id=tenant_id,
                    source_event_id=str(binding.get("id") or deployment_id),
                    edge_type=_IDENTITY_EDGE,
                    from_vertex_id=canonical_id,
                    to_vertex_id=deployment_id,
                    record_kind="identity_binding",
                    expected_properties={
                        "provenance": "agent_deployment_identity_binding",
                        "binding_authority": "tenant_admin_explicit",
                        "source_namespace": namespace,
                        "source_agent_ref": source_ref,
                        "canonical_agent_entity_id": canonical_id,
                    },
                ))
                matched_bindings.add(binding_key)
            if not deployment_truncated:
                deployment_scan_complete = True
                break
            if not next_cursor or next_cursor == deployment_cursor:
                return links, statuses, True, "invalid_or_stalled_deployment_cursor"
            deployment_cursor = next_cursor
        if deployment_count >= limit and not deployment_scan_complete:
            truncated = True
        if deployment_page_count >= deployment_page_cap and not deployment_scan_complete:
            truncated = True
        if not truncated and not deployment_scan_complete:
            truncated = True
        for (namespace, source_ref), binding in binding_by_source.items():
            if (namespace, source_ref) not in matched_bindings:
                statuses.append({
                    "type": "unresolved",
                    "authority": "agent_deployment_identity_binding",
                    "status": "indeterminate",
                    "source_namespace": namespace,
                    "source_agent_ref": source_ref,
                    "reason": "no_tenant_deployment_matches_binding",
                })
        if truncated:
            statuses.append({
                "type": "unresolved",
                "authority": "agent_deployment_identity_binding",
                "status": "indeterminate",
                "reason": "identity_binding_scan_truncated",
            })
        return links, statuses, truncated, None

    async def _resolve_row(
        self,
        row: dict[str, Any],
        tenant_id: str,
        deployments: Any,
        delegations: Any,
        intents: Any,
        settlements: Any,
        identity_bindings: Any,
        entities: Any,
    ) -> tuple[list[ExpectedAgentEconomyLink], list[dict[str, Any]], dict[str, Any]]:
        expected: list[ExpectedAgentEconomyLink] = []
        issues: list[dict[str, Any]] = []
        event_id = _ref(row.get("source_event_id"))
        deployment_id = _ref(row.get("deployment_id"))
        run_id = _ref(row.get("run_id"))
        # query_silver_page already scopes by tenant; verify the returned row as
        # defense in depth before using any caller-controlled reference.
        if row.get("tenant_id") != tenant_id:
            return [], [{"type": "unauthorized", "reason": "silver_row_tenant_mismatch"}], {}
        if not event_id or not deployment_id or not run_id:
            if _ref(row.get("delegation_id")) or _ref(row.get("payment_intent_ref")) or _ref(row.get("settlement_event_ref")):
                issues.append({
                    "type": "unresolved",
                    "source_event_id": event_id,
                    "reason": "missing_source_event_deployment_or_run_reference",
                })
            return expected, issues, {"deployment": "unresolved"}

        source_id = _scoped_id("agent_action", tenant_id, deployment_id, event_id)
        deployment = await deployments.get_record(tenant_id, deployment_id)
        deployment_ok = bool(
            deployment
            and deployment.get("tenant_id") == tenant_id
            and str(deployment.get("id") or "") == deployment_id
        )
        if not deployment_ok:
            if _ref(row.get("delegation_id")) or _ref(row.get("payment_intent_ref")) or _ref(row.get("settlement_event_ref")):
                issues.append({
                    "type": "unresolved",
                    "source_event_id": event_id,
                    "reason": "deployment_not_registered_for_tenant",
                })
        agent_id = _ref(deployment.get("agent_id")) if deployment_ok else None

        identity_status: dict[str, Any] = {
            "authority": "agent_deployment_identity_binding",
            "status": "unresolved" if deployment_ok else "indeterminate",
            "reason": "deployment_identity_unavailable" if not deployment_ok else "binding_not_found",
            "execution_occurrence": "source_reported",
            "execution_verified": False,
        }
        if deployment_ok and agent_id:
            namespace = _ref(deployment.get("agent_source_namespace"))
            if namespace:
                try:
                    bindings = await identity_bindings.find_for_source(
                        tenant_id, namespace.lower(), agent_id,
                    )
                    if len(bindings) > 1:
                        identity_status.update({
                            "status": "indeterminate",
                            "reason": "multiple_active_identity_bindings",
                        })
                    elif len(bindings) == 1:
                        binding = bindings[0]
                        canonical_id = _ref(binding.get("canonical_agent_entity_id"))
                        binding_ok = bool(
                            binding.get("tenant_id") == tenant_id
                            and binding.get("source_namespace") == namespace.lower()
                            and binding.get("source_agent_ref") == agent_id
                            and binding.get("status") == "active"
                            and binding.get("binding_authority") == "tenant_admin_explicit"
                            and binding.get("source_deployment_id") == deployment_id
                            and canonical_id
                        )
                        entity_rows = await entities.find_many(
                            filters={
                                "tenant_id": tenant_id,
                                "entity_id": canonical_id,
                                "entity_type": "agent",
                            },
                            limit=2,
                        ) if binding_ok else []
                        matched_entities = [
                            entity for entity in entity_rows
                            if entity.get("tenant_id") == tenant_id
                            and entity.get("entity_id") == canonical_id
                            and entity.get("entity_type") == "agent"
                        ]
                        if binding_ok and len(matched_entities) == 1 and canonical_id:
                            identity_status.update({
                                "status": "matched",
                                "reason": "tenant_admin_explicit_binding",
                                "source_namespace": namespace.lower(),
                                "source_agent_ref": agent_id,
                                "canonical_agent_entity_id": canonical_id,
                            })
                            expected.append(ExpectedAgentEconomyLink(
                                tenant_id=tenant_id,
                                source_event_id=str(binding.get("id") or deployment_id),
                                edge_type=_IDENTITY_EDGE,
                                from_vertex_id=canonical_id,
                                to_vertex_id=deployment_id,
                                record_kind="identity_binding",
                                expected_properties={
                                    "provenance": "agent_deployment_identity_binding",
                                    "binding_authority": "tenant_admin_explicit",
                                    "source_namespace": namespace.lower(),
                                    "source_agent_ref": agent_id,
                                    "canonical_agent_entity_id": canonical_id,
                                },
                            ))
                        else:
                            identity_status.update({
                                "status": "unresolved",
                                "reason": "canonical_agent_entity_not_found_or_binding_invalid",
                            })
                except Exception as exc:
                    identity_status.update({
                        "status": "unavailable",
                        "reason": "identity_binding_authority_unavailable",
                        "error_type": type(exc).__name__,
                    })
            else:
                identity_status.update({
                    "status": "unresolved",
                    "reason": "source_namespace_missing",
                })

        delegation_ref = _ref(row.get("delegation_id"))
        delegation_context: dict[str, Any] = {
            "status": "not_supplied" if delegation_ref is None else "unresolved",
            "deployment": deployment,
            "agent_id": agent_id,
        }
        if delegation_ref is not None and deployment_ok and agent_id:
            record, status = await self._find_exact(
                delegations, tenant_id=tenant_id,
                field="delegation_id", reference=delegation_ref,
            )
            delegation_context.update({"status": status, "record": record})
            if record is not None:
                target_id = _scoped_id("delegation", tenant_id, delegation_ref)
                expected.append(ExpectedAgentEconomyLink(
                    tenant_id=tenant_id,
                    source_event_id=event_id,
                    edge_type=_DELEGATION_EDGE,
                    from_vertex_id=source_id,
                    to_vertex_id=target_id,
                    record_kind="delegation",
                    authorization_status="correlation_only",
                    expected_properties={
                        "authorization_claim": "none",
                        "execution_occurrence": "source_reported",
                        "execution_verified": False,
                    },
                ))
                # A matching record reference does not resolve source agent
                # identity to grantor/grantee, and never proves authorization.
                delegation_context["party_identity_status"] = "unresolved"
            else:
                issues.append({
                    "type": "unresolved",
                    "source_event_id": event_id,
                    "reference_kind": "delegation",
                    "reference": delegation_ref,
                    "reason": status,
                })
        elif delegation_ref is not None:
            issues.append({
                "type": "unresolved",
                "source_event_id": event_id,
                "reference_kind": "delegation",
                "reference": delegation_ref,
                "reason": "deployment_identity_unavailable",
            })

        intent_ref = _ref(row.get("payment_intent_ref"))
        settlement_ref = _ref(row.get("settlement_event_ref"))
        economic_context: dict[str, Any] = {
            "status": "not_supplied" if intent_ref is None and settlement_ref is None else "unresolved",
            "deployment": deployment,
            "agent_id": agent_id,
        }
        if intent_ref is not None or settlement_ref is not None:
            if not deployment_ok or not agent_id:
                issues.append({
                    "type": "unresolved",
                    "source_event_id": event_id,
                    "reference_kind": "economic",
                    "reason": "deployment_identity_unavailable",
                })
            else:
                intent = None
                settlement = None
                resolution_error: Optional[str] = None
                if intent_ref is not None:
                    intent, intent_status = await self._find_exact(
                        intents, tenant_id=tenant_id,
                        field="intent_id", reference=intent_ref,
                    )
                    if intent is None:
                        resolution_error = intent_status
                if settlement_ref is not None:
                    settlement, settlement_status = await self._find_exact(
                        settlements, tenant_id=tenant_id,
                        field="settlement_event_id", reference=settlement_ref,
                    )
                    if settlement is None:
                        resolution_error = settlement_status
                    elif intent is None:
                        implied_intent = _ref(settlement.get("intent_id"))
                        if implied_intent is None:
                            resolution_error = "settlement_missing_intent_reference"
                        else:
                            intent, intent_status = await self._find_exact(
                                intents, tenant_id=tenant_id,
                                field="intent_id", reference=implied_intent,
                            )
                            if intent is None:
                                resolution_error = intent_status
                    elif settlement.get("intent_id") != intent.get("intent_id"):
                        resolution_error = "settlement_intent_mismatch"

                if resolution_error is None and intent is None:
                    resolution_error = "payment_intent_unresolved"
                if resolution_error is None and intent is not None:
                    if intent.get("agent_id") != agent_id:
                        resolution_error = "payment_intent_agent_mismatch"
                    elif not is_server_authoritative_x402_metadata(intent.get("metadata")):
                        resolution_error = "payment_intent_provenance_untrusted"
                if resolution_error is None and settlement is not None:
                    if settlement.get("agent_id") != agent_id:
                        resolution_error = "settlement_agent_mismatch"
                    elif settlement.get("intent_id") != intent.get("intent_id"):
                        resolution_error = "settlement_intent_mismatch"
                    elif not is_server_authoritative_x402_metadata(settlement.get("metadata")):
                        resolution_error = "settlement_provenance_untrusted"
                if resolution_error is not None:
                    issue_type = "unauthorized" if any(
                        marker in resolution_error
                        for marker in ("agent_mismatch", "provenance_untrusted", "intent_mismatch")
                    ) else "unresolved"
                    issues.append({
                        "type": issue_type,
                        "source_event_id": event_id,
                        "reference_kind": "economic",
                        "reference": settlement_ref or intent_ref,
                        "reason": resolution_error,
                    })
                    economic_context["status"] = issue_type
                    economic_context["reason"] = resolution_error
                else:
                    economic_context.update({"status": "matched", "intent": intent, "settlement": settlement})
                    assert intent is not None
                    expected.append(ExpectedAgentEconomyLink(
                        tenant_id=tenant_id,
                        source_event_id=event_id,
                        edge_type=_ECONOMIC_EDGE,
                        from_vertex_id=source_id,
                        to_vertex_id=f"{tenant_id}:{intent['intent_id']}",
                        record_kind="payment_intent",
                    ))
                    if settlement is not None:
                        expected.append(ExpectedAgentEconomyLink(
                            tenant_id=tenant_id,
                            source_event_id=event_id,
                            edge_type=_ECONOMIC_EDGE,
                            from_vertex_id=source_id,
                            to_vertex_id=f"{tenant_id}:{settlement['settlement_event_id']}",
                            record_kind="settlement_event",
                        ))

        extension_context = {
            "tenant_id": tenant_id,
            "source_event_id": event_id,
            "source_vertex_id": source_id,
            "deployment": deployment,
            "delegation": delegation_context,
            "economic": economic_context,
            "identity": identity_status,
            "authority_statuses": [],
        }
        for extension in self._authority_extensions:
            extension_result = extension(row, extension_context)
            if hasattr(extension_result, "__await__"):
                extension_result = await extension_result
            if not isinstance(extension_result, dict):
                issues.append({
                    "type": "unresolved",
                    "source_event_id": event_id,
                    "reason": "authority_extension_invalid_result",
                })
                continue
            for status in extension_result.get("statuses", []):
                if isinstance(status, dict):
                    if status.get("tenant_id") not in (None, tenant_id):
                        issues.append({
                            "type": "unauthorized",
                            "source_event_id": event_id,
                            "reason": "authority_extension_tenant_mismatch",
                        })
                        continue
                    normalized_status = {
                        **status,
                        "source_event_id": status.get("source_event_id") or event_id,
                    }
                    status_value = status.get("status") or status.get("type")
                    if status_value in {"out_of_scope", "unauthorized", "denied"}:
                        normalized_status["type"] = "unauthorized"
                    elif status_value in {"indeterminate", "unresolved", "unavailable"}:
                        normalized_status["type"] = "unresolved"
                    if normalized_status.get("type") in {"unauthorized", "unresolved"}:
                        issues.append(normalized_status)
                    extension_context["authority_statuses"].append(normalized_status)
            for candidate in extension_result.get("expected_links", []):
                if isinstance(candidate, ExpectedAgentEconomyLink):
                    normalized_link = candidate
                elif isinstance(candidate, dict) and candidate.get("tenant_id") == tenant_id:
                    try:
                        normalized_link = ExpectedAgentEconomyLink(**candidate)
                    except (TypeError, ValueError):
                        issues.append({
                            "type": "unresolved",
                            "source_event_id": event_id,
                            "reason": "authority_extension_invalid_link",
                        })
                        continue
                else:
                    issues.append({
                        "type": "unauthorized",
                        "source_event_id": event_id,
                        "reason": "authority_extension_tenant_mismatch_or_invalid_link",
                    })
                    continue
                if (
                    normalized_link.tenant_id != tenant_id
                    or normalized_link.source_event_id not in ("", event_id)
                    or (
                        normalized_link.edge_type != _IDENTITY_EDGE
                        and normalized_link.from_vertex_id != source_id
                    )
                ):
                    issues.append({
                        "type": "unauthorized",
                        "source_event_id": event_id,
                        "reason": "authority_extension_link_scope_mismatch",
                    })
                    continue
                expected.append(normalized_link)
        return expected, issues, extension_context

    async def reconcile(
        self,
        tenant_id: str,
        *,
        source_page_size: int = 250,
        max_source_rows: int = 5_000,
        graph_edge_limit: int = 5_000,
        issue_limit: int = 500,
    ) -> dict[str, Any]:
        """Return bounded, non-mutating findings for one tenant.

        ``extra`` is relative to source rows scanned; set ``coverage.status``
        to ``partial`` if either the Silver source scan or graph edge scan is
        truncated or unavailable. Even a fully paged scan is not a consistent
        snapshot across the source repositories and graph.
        """
        tenant_id = str(tenant_id or "").strip()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if max_source_rows < 1 or graph_edge_limit < 1:
            raise ValueError("scan limits must be positive")
        if max_source_rows > _MAX_SOURCE_ROWS or graph_edge_limit > _MAX_GRAPH_EDGE_SCAN:
            raise ValueError("scan limits exceed the checker maximum")
        if source_page_size < 1:
            raise ValueError("source_page_size must be positive")
        (
            graph, analytics, deployments, delegations, intents, settlements,
            identity_bindings, entities,
        ) = self._dependencies()

        source_rows: list[dict[str, Any]] = []
        source_cursor: Optional[str] = None
        source_complete = False
        source_error: Optional[str] = None
        normalized_page_size = min(int(source_page_size), _MAX_SOURCE_PAGE_SIZE)
        source_page_cap = min(
            _MAX_PAGE_CALLS,
            max(1, (max_source_rows + normalized_page_size - 1) // normalized_page_size + 8),
        )
        source_page_count = 0
        while len(source_rows) < max_source_rows and source_page_count < source_page_cap:
            page_limit = min(normalized_page_size, max_source_rows - len(source_rows))
            try:
                page, next_cursor, truncated = await analytics.query_silver_page(
                    "silver_agent_execution_facts",
                    {"tenant_id": tenant_id},
                    limit=page_limit,
                    cursor=source_cursor,
                )
            except Exception as exc:
                source_error = type(exc).__name__
                break
            source_page_count += 1
            if len(page) > page_limit:
                source_error = "source_page_exceeded_requested_limit"
                source_rows.extend(page[:page_limit])
                break
            source_rows.extend(page)
            if not truncated:
                source_complete = True
                break
            if not next_cursor or next_cursor == source_cursor:
                source_error = "invalid_or_stalled_source_cursor"
                break
            source_cursor = next_cursor
        if source_page_count >= source_page_cap and not source_complete and source_error is None:
            source_error = "source_scan_page_limit_reached"
        source_truncated = not source_complete

        identity_links, identity_statuses, identity_truncated, identity_error = (
            await self._expected_identity_links(
                tenant_id,
                deployments,
                identity_bindings,
                entities,
                limit=max(1, min(max_source_rows, 5_000)),
            )
        )

        try:
            observed_edges, graph_truncated = await graph.get_edges_for_tenant(
                tenant_id,
                limit=graph_edge_limit,
                edge_types=list(_CHECKED_EDGE_TYPES),
                include_revoked=False,
            )
            graph_error = None
        except Exception as exc:
            observed_edges = []
            graph_truncated = True
            graph_error = type(exc).__name__

        expected_links: list[ExpectedAgentEconomyLink] = []
        issues: list[dict[str, Any]] = []
        authority_statuses: list[dict[str, Any]] = []
        expected_links.extend(identity_links)
        issues.extend(identity_statuses)
        for row in source_rows:
            try:
                links, row_issues, context = await self._resolve_row(
                    row, tenant_id, deployments, delegations, intents, settlements,
                    identity_bindings, entities,
                )
            except Exception as exc:
                links, row_issues, context = [], [{
                    "type": "unresolved",
                    "source_event_id": _ref(row.get("source_event_id")),
                    "reason": "canonical_source_unavailable",
                    "error_type": type(exc).__name__,
                }], {}
            expected_links.extend(links)
            issues.extend(row_issues)
            auth = context.get("delegation") if context else None
            if isinstance(auth, dict) and auth.get("status") not in (None, "not_supplied"):
                authority_statuses.append({
                    "source_event_id": context.get("source_event_id"),
                    "delegation_reference_status": auth.get("status"),
                    "party_identity_status": auth.get("party_identity_status", "unresolved"),
                    "authorization_claim": "none",
                })
            identity = context.get("identity") if context else None
            if isinstance(identity, dict):
                authority_statuses.append({
                    "source_event_id": context.get("source_event_id"),
                    "tenant_id": tenant_id,
                    **identity,
                })
                if identity.get("status") in {"unresolved", "unavailable", "indeterminate"}:
                    issues.append({
                        "type": "unresolved",
                        "source_event_id": context.get("source_event_id"),
                        "reference_kind": "identity",
                        "reason": identity.get("reason") or "identity_binding_unresolved",
                    })
            if context:
                for status in context.get("authority_statuses", []):
                    authority_statuses.append({
                        "source_event_id": context.get("source_event_id"),
                        "tenant_id": tenant_id,
                        **status,
                        "execution_occurrence": status.get("execution_occurrence") or "source_reported",
                        "execution_verified": status.get("execution_verified", False),
                    })

        authorization_status_by_event = {
            _ref(status.get("source_event_id")): status.get("status")
            for status in authority_statuses
            if status.get("authority") == "delegation_authorization"
            and _ref(status.get("source_event_id")) is not None
            and status.get("status")
        }
        expected_links = [
            replace(
                link,
                expected_properties={
                    **link.expected_properties,
                    "delegation_authorization_status": authorization_status_by_event[
                        link.source_event_id
                    ],
                },
            )
            if link.edge_type == _DELEGATION_EDGE
            and link.source_event_id in authorization_status_by_event
            else link
            for link in expected_links
        ]

        expected_by_key: dict[tuple[str, str, str, str, str], ExpectedAgentEconomyLink] = {}
        for expected in expected_links:
            expected_by_key.setdefault(_link_key(expected), expected)
        actual_by_key: dict[tuple[str, str, str, str, str], list[Edge]] = {}
        malformed_tenant_edges: list[Edge] = []
        expected_identity_endpoints = {
            (link.from_vertex_id, link.to_vertex_id)
            for link in expected_links
            if link.edge_type == _IDENTITY_EDGE
        }
        for edge in observed_edges:
            if not _tenant_owned(edge.properties, tenant_id):
                malformed_tenant_edges.append(edge)
                continue
            props = edge.properties or {}
            is_identity_binding_edge = bool(
                props.get("provenance") == "agent_deployment_identity_binding"
                or props.get("binding_authority") == "tenant_admin_explicit"
                or props.get("source_namespace")
                or props.get("source_agent_ref")
                or (edge.from_vertex_id, edge.to_vertex_id) in expected_identity_endpoints
            )
            if edge.edge_type == _IDENTITY_EDGE and not is_identity_binding_edge:
                # This canonical edge type can represent other identity
                # authorities. The check owns only this explicit binding.
                continue
            actual_by_key.setdefault(_link_key(edge), []).append(edge)

        missing: list[dict[str, Any]] = []
        mismatched: list[dict[str, Any]] = []
        unauthorized: list[dict[str, Any]] = []
        consumed_actual_keys: set[tuple[str, str, str, str, str]] = set()
        expected_groups: dict[tuple[str, str, str], list[ExpectedAgentEconomyLink]] = {}
        actual_groups: dict[tuple[str, str, str], list[tuple[tuple[str, str, str, str, str], Edge]]] = {}
        for key, expected in expected_by_key.items():
            actuals = actual_by_key.get(key, [])
            if actuals:
                consumed_actual_keys.add(key)
                observed_properties = actuals[0].properties or {}
                property_mismatches = {
                    name: {
                        "expected": value,
                        "observed": observed_properties.get(name),
                    }
                    for name, value in expected.expected_properties.items()
                    if observed_properties.get(name) != value
                }
                if property_mismatches:
                    finding = {
                        "source_event_id": expected.source_event_id,
                        "edge_type": expected.edge_type,
                        "record_kind": expected.record_kind,
                        "reason": "persisted_edge_properties_mismatch",
                        "properties": property_mismatches,
                    }
                    if expected.edge_type == _IDENTITY_EDGE or (
                        expected.edge_type == _DELEGATION_EDGE
                        and property_mismatches.get("authorization_claim", {}).get("observed")
                        != "none"
                    ):
                        unauthorized.append(finding)
                    else:
                        mismatched.append(finding)
                if expected.authorization_status == "unauthorized":
                    unauthorized.append({
                        "source_event_id": expected.source_event_id,
                        "edge_type": expected.edge_type,
                        "reason": "persisted_link_for_unauthorized_reference",
                        "to_vertex_id": expected.to_vertex_id,
                    })
                continue
            group = (expected.edge_type, expected.source_event_id, "")
            expected_groups.setdefault(group, []).append(expected)
        rejected_economic_sources = {
            _ref(issue.get("source_event_id"))
            for issue in issues
            if issue.get("type") == "unauthorized"
            and issue.get("reference_kind") == "economic"
            and _ref(issue.get("source_event_id")) is not None
        }
        for key, edges in actual_by_key.items():
            if key in expected_by_key:
                consumed_actual_keys.add(key)
                continue
            edge_type, source_event_id, _from_id, _to_id, _record_kind = key
            group = (edge_type, source_event_id, "")
            for edge in edges:
                actual_groups.setdefault(group, []).append((key, edge))

        for group, expected_group in expected_groups.items():
            alternatives = actual_groups.get(group, [])
            if alternatives:
                for expected in expected_group:
                    key, edge = alternatives.pop(0)
                    mismatched.append({
                        "source_event_id": expected.source_event_id,
                        "edge_type": expected.edge_type,
                        "record_kind": expected.record_kind,
                        "expected_to_vertex_id": expected.to_vertex_id,
                        "observed_to_vertex_id": edge.to_vertex_id,
                    })
                    consumed_actual_keys.add(key)
            else:
                for expected in expected_group:
                    missing.append({
                        "source_event_id": expected.source_event_id,
                        "edge_type": expected.edge_type,
                        "record_kind": expected.record_kind,
                        "from_vertex_id": expected.from_vertex_id,
                        "to_vertex_id": expected.to_vertex_id,
                    })

        extra: list[dict[str, Any]] = []
        for key, edges in actual_by_key.items():
            if key in consumed_actual_keys:
                extras = edges[1:]
            else:
                extras = edges
            for edge in extras:
                if edge.edge_type == _ECONOMIC_EDGE and _ref(
                    (edge.properties or {}).get("source_event_id")
                ) in rejected_economic_sources:
                    unauthorized.append({
                        "source_event_id": _ref((edge.properties or {}).get("source_event_id")),
                        "edge_type": edge.edge_type,
                        "reason": "persisted_link_for_unauthorized_economic_reference",
                        "to_vertex_id": edge.to_vertex_id,
                    })
                    continue
                if not source_complete and _ref((edge.properties or {}).get("source_event_id")):
                    scope = "unmatched_within_partial_source_scan"
                else:
                    scope = "unmatched_source_evidence"
                extra.append({
                    "source_event_id": _ref((edge.properties or {}).get("source_event_id")),
                    "edge_type": edge.edge_type,
                    "record_kind": (
                        "delegation" if edge.edge_type == _DELEGATION_EDGE else (
                            (edge.properties or {}).get("economic_record_kind")
                            if edge.edge_type == _ECONOMIC_EDGE else "identity_binding"
                        )
                    ),
                    "from_vertex_id": edge.from_vertex_id,
                    "to_vertex_id": edge.to_vertex_id,
                    "scope": scope,
                })
        for edge in malformed_tenant_edges:
            unauthorized.append({
                "source_event_id": _ref((edge.properties or {}).get("source_event_id")),
                "edge_type": edge.edge_type,
                "reason": "tenant_owned_edge_has_mismatched_tenant_property",
            })

        endpoint_findings: list[dict[str, Any]] = []
        if graph_error is None:
            checked_endpoints: set[tuple[str, str]] = set()
            for expected in expected_links:
                for endpoint_role, vertex_id in (
                    ("source", expected.from_vertex_id), ("target", expected.to_vertex_id),
                ):
                    identity = (endpoint_role, vertex_id)
                    if identity in checked_endpoints:
                        continue
                    checked_endpoints.add(identity)
                    try:
                        vertex = await graph.get_vertex_for_tenant(tenant_id, vertex_id)
                    except Exception as exc:
                        endpoint_findings.append({
                            "type": "unresolved",
                            "endpoint_role": endpoint_role,
                            "vertex_id": vertex_id,
                            "reason": "tenant_scoped_vertex_read_failed",
                            "error_type": type(exc).__name__,
                        })
                        continue
                    if vertex is None:
                        endpoint_findings.append({
                            "type": "missing",
                            "endpoint_role": endpoint_role,
                            "vertex_id": vertex_id,
                            "reason": "vertex_missing_or_not_visible_in_tenant",
                        })
                    elif not _tenant_owned(vertex.properties, tenant_id):
                        endpoint_findings.append({
                            "type": "unauthorized",
                            "endpoint_role": endpoint_role,
                            "vertex_id": vertex_id,
                            "reason": "tenant_scoped_vertex_read_returned_mismatched_tenant",
                        })

        issues.extend(endpoint_findings)
        if source_error:
            issues.append({"type": "unresolved", "reason": "source_scan_failed", "error_type": source_error})
        if graph_error:
            issues.append({"type": "unresolved", "reason": "graph_edge_scan_failed", "error_type": graph_error})
        all_findings = {
            "missing": missing + [item for item in issues if item.get("type") == "missing"],
            "extra": extra,
            "mismatched": mismatched + [item for item in issues if item.get("type") == "mismatched"],
            "unresolved": [item for item in issues if item.get("type") == "unresolved"],
            "unauthorized": unauthorized + [item for item in issues if item.get("type") == "unauthorized"],
        }
        delegation_events_requiring_authority = {
            _ref(row.get("source_event_id"))
            for row in source_rows
            if _ref(row.get("delegation_id")) is not None
            and _ref(row.get("source_event_id")) is not None
        }
        delegation_events_with_authority = {
            _ref(status.get("source_event_id"))
            for status in authority_statuses
            if status.get("authority") == "delegation_authorization"
            and _ref(status.get("source_event_id")) is not None
        }
        delegation_authority_checked = (
            delegation_events_requiring_authority.issubset(delegation_events_with_authority)
        )
        coverage_complete = (
            source_complete and not identity_truncated and identity_error is None
            and not graph_truncated and graph_error is None
            and delegation_authority_checked
        )
        total_counts = {key: len(value) for key, value in all_findings.items()}
        return {
            "tenant_id": tenant_id,
            "status": "consistent" if coverage_complete and not any(total_counts.values()) else (
                "inconsistent" if any(total_counts.values()) else "partial"
            ),
            "coverage": {
                "status": "complete" if coverage_complete else "partial",
                "scope": "agent_execution_economic_and_delegation_links",
                "source_rows_scanned": len(source_rows),
                "source_scan_complete": source_complete,
                "source_scan_truncated": source_truncated,
                "source_scan_error": source_error,
                "source_next_cursor": source_cursor if source_truncated else None,
                "identity_bindings_scanned": len(identity_links) + sum(
                    1 for item in identity_statuses
                    if item.get("authority") == "agent_deployment_identity_binding"
                    and item.get("status") in {"matched", "indeterminate", "unavailable"}
                ),
                "identity_binding_scan_complete": not identity_truncated and identity_error is None,
                "identity_binding_scan_truncated": identity_truncated,
                "identity_binding_scan_error": identity_error,
                "authority_extension_configured": bool(self._authority_extensions),
                "delegation_authority_checked": delegation_authority_checked,
                "graph_edges_scanned": len(observed_edges),
                "graph_edge_scan_complete": not graph_truncated and graph_error is None,
                "graph_edge_scan_truncated": graph_truncated,
                "graph_edge_scan_error": graph_error,
                "edge_enumeration": "tenant_scoped",
                "includes_orphan_scanned_tenant_edges": True,
                "includes_revoked_edges": False,
                "consistency": "best_effort_non_snapshot",
                "blind_spots": [
                    "Edges without the requested tenant ownership property are outside the tenant edge scan.",
                    "A complete scan is not a transactionally consistent snapshot across Silver, canonical repositories, and graph.",
                    "Identity authorization is reported only by configured authority extensions; a delegation reference edge is correlation-only.",
                ],
            },
            "source_reference_statuses": authority_statuses[:issue_limit],
            "counts": total_counts,
            "findings": {
                key: rows[:issue_limit] for key, rows in all_findings.items()
            },
            "findings_truncated": any(count > issue_limit for count in total_counts.values()),
        }


__all__ = [
    "AgentEconomyGraphStateChecker",
    "ExpectedAgentEconomyLink",
    "agent_run_authority_extension",
]
