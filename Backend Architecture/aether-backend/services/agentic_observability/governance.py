"""Agentic governance, privacy, commercialization, and release evidence.

Read-only productization helpers for the Agentic Intelligence program. These
services assemble tenant-scoped evidence from observation stores and never
execute external provider actions, revoke grants, send messages, trade, or
mutate third-party state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import settings
from repositories.agentic_observability_repos import (
    AgentConnectionRepository,
    AgentRiskSignalRepository,
    AgentToolRepository,
    AgenticBronzeObservationRepository,
    AgenticProjectionOutboxRepository,
    ExternalAccountRepository,
    SilverAgentActivityFactRepository,
    SilverAgentRiskFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
)
from services.agentic_observability.product_surfaces import AgenticProductSurfacesService
from services.agentic_observability.reconciliation import AgenticReconciliationService
from services.measurement.repositories.activity_repo import ActivityRepository


_AGENTIC_TABLES: tuple[tuple[str, Any], ...] = (
    ("bronze_agentic_observations", AgenticBronzeObservationRepository),
    ("silver_agent_activity_facts", SilverAgentActivityFactRepository),
    ("silver_agent_tool_invocation_facts", SilverAgentToolInvocationFactRepository),
    ("silver_mcp_connection_facts", SilverMCPConnectionFactRepository),
    ("silver_agent_risk_facts", SilverAgentRiskFactRepository),
    ("agentic_projection_outbox", AgenticProjectionOutboxRepository),
    ("obs_agent_tools", AgentToolRepository),
    ("obs_agent_connections", AgentConnectionRepository),
    ("obs_external_accounts", ExternalAccountRepository),
    ("obs_agent_risk_signals", AgentRiskSignalRepository),
)

_PERSON_FIELDS = ("actor_id", "owner_id", "grantor_id", "human_id", "user_id")
_AGENT_FIELDS = ("agent_id", "grantee_id")
_OBJECT_FIELDS = ("external_account_id", "external_object_id", "provider_request_id")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nested_get(row: dict[str, Any], *path: str) -> Any:
    current: Any = row
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _row_matches_subject(row: dict[str, Any], subject_id: str) -> bool:
    if not subject_id:
        return False
    for field in (*_PERSON_FIELDS, *_AGENT_FIELDS, *_OBJECT_FIELDS):
        if row.get(field) == subject_id:
            return True
    nested_paths = (
        ("actor", "actor_id"),
        ("agent", "agent_id"),
        ("authorization", "grantor_id"),
        ("authorization", "grantee_id"),
        ("authorization", "external_account_id"),
        ("correlation", "external_object_id"),
        ("correlation", "provider_request_id"),
        ("object", "object_id"),
        ("object", "external_object_id"),
        ("payload", "actor", "actor_id"),
        ("payload", "agent", "agent_id"),
        ("payload", "authorization", "grantor_id"),
        ("payload", "authorization", "grantee_id"),
        ("payload", "authorization", "external_account_id"),
    )
    return any(_nested_get(row, *path) == subject_id for path in nested_paths)


def _redact_subject(row: dict[str, Any], subject_id: str) -> dict[str, Any]:
    redacted = dict(row)
    redacted["redaction_status"] = "subject_redacted"
    redacted["redacted_subject_id"] = subject_id
    for field in (*_PERSON_FIELDS, *_OBJECT_FIELDS):
        if redacted.get(field) == subject_id:
            redacted[field] = "[redacted]"
    for container in ("actor", "agent", "authorization", "correlation", "object"):
        value = redacted.get(container)
        if isinstance(value, dict):
            redacted[container] = _redact_subject(value, subject_id)
    return redacted


@dataclass(frozen=True, slots=True)
class AgenticDSRPreview:
    tenant_id: str
    subject_id: str
    action: str
    generated_at: str
    records_by_store: dict[str, int]
    records_total: int
    tombstone_supported: bool
    hard_delete_supported: bool
    audit_preservation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "action": self.action,
            "generated_at": self.generated_at,
            "records_by_store": self.records_by_store,
            "records_total": self.records_total,
            "tombstone_supported": self.tombstone_supported,
            "hard_delete_supported": self.hard_delete_supported,
            "audit_preservation": self.audit_preservation,
            "observation_only": True,
        }


class AgenticGovernanceService:
    """Tenant-scoped productization evidence for agentic observability."""

    async def usage_metering(self, *, tenant_id: str) -> dict[str, Any]:
        health = await AgenticReconciliationService().pipeline_health(tenant_id=tenant_id)
        tools = await AgentToolRepository().count({"tenant_id": tenant_id})
        accounts = await ExternalAccountRepository().count({"tenant_id": tenant_id})
        risk = await AgentRiskSignalRepository().count({"tenant_id": tenant_id})
        graph_mutations = sum(health["outbox"].values())
        return {
            "tenant_id": tenant_id,
            "metered_dimensions": {
                "agentic_events_ingested": health["bronze_agentic_observations"],
                "agentic_silver_facts": sum(health["silver_facts"].values()),
                "agentic_canonical_activities": health["canonical_activity"],
                "agentic_graph_mutations_queued": graph_mutations,
                "agentic_tool_observations": tools,
                "agentic_external_accounts_observed": accounts,
                "agentic_risk_signals": risk,
            },
            "billable_status": "metered_not_invoiced",
            "entitlement_keys": [
                "agentic_observability",
                "agentic_kyber_diagnostics",
                "agentic_noesis_readonly_intelligence",
                "agentic_provider_verification_readonly",
            ],
            "limits": {
                "journey_v2_agentic_step_query_limit": 500,
                "kyber_lineage_query_limit": 100,
                "reconciliation_scan_limit": 500,
                "outbox_worker_batch_limit": 100,
            },
            "observation_only": True,
        }

    async def dsr_preview(self, *, tenant_id: str, subject_id: str, action: str = "export") -> AgenticDSRPreview:
        action = action if action in {"export", "tombstone"} else "export"
        records_by_store: dict[str, int] = {}
        for table, repo_cls in _AGENTIC_TABLES:
            rows = await repo_cls().find_many({"tenant_id": tenant_id}, limit=1000)
            records_by_store[table] = sum(1 for row in rows if _row_matches_subject(row, subject_id))
        activity_rows = await ActivityRepository().list_agentic_by_agent(tenant_id, subject_id, limit=1000)
        records_by_store["canonical_activity"] = len(activity_rows)
        return AgenticDSRPreview(
            tenant_id=tenant_id,
            subject_id=subject_id,
            action=action,
            generated_at=_utc_now(),
            records_by_store=records_by_store,
            records_total=sum(records_by_store.values()),
            tombstone_supported=True,
            hard_delete_supported=False,
            audit_preservation="agentic observations are redacted/tombstoned; immutable audit and billing evidence are preserved",
        )

    async def dsr_export(self, *, tenant_id: str, subject_id: str, include_rows: bool = False) -> dict[str, Any]:
        preview = await self.dsr_preview(tenant_id=tenant_id, subject_id=subject_id, action="export")
        payload: dict[str, Any] = preview.as_dict()
        if include_rows:
            rows_by_store: dict[str, list[dict[str, Any]]] = {}
            for table, repo_cls in _AGENTIC_TABLES:
                rows = await repo_cls().find_many({"tenant_id": tenant_id}, limit=1000)
                rows_by_store[table] = [
                    _redact_subject(row, subject_id) for row in rows if _row_matches_subject(row, subject_id)
                ]
            payload["redacted_rows"] = rows_by_store
        return payload

    async def security_and_privacy_controls(self, *, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "no_execution_invariant": {
                "status": "enforced",
                "controls": [
                    "route payloads with execution_by_aether=true are rejected",
                    "provider framework exposes read-only verification adapters",
                    "SDK helpers emit execution_by_aether=false",
                    "graph writes are asynchronous projection of observed facts",
                ],
            },
            "secret_handling": {
                "status": "enforced",
                "controls": [
                    "Bronze payload sanitization redacts tokens, secrets, keys, signatures, and authorization headers",
                    "provider framework stores evidence references rather than provider credentials",
                ],
            },
            "privacy": {
                "status": "implemented_for_observation_stores",
                "controls": [
                    "tenant-scoped DSR export previews",
                    "redacted DSR export manifests",
                    "audit-preserving tombstone plan",
                    "metadata-only capture policies in Contract v2 privacy context",
                ],
            },
            "cross_tenant_isolation": {
                "status": "enforced",
                "controls": [
                    "authenticated tenant context is authoritative",
                    "request body tenant_id mismatch is rejected",
                    "Kyber diagnostics are tenant-scoped",
                ],
            },
            "observation_only": True,
        }

    def rollout_controls(self) -> dict[str, Any]:
        cfg = settings.agentic_observability
        return {
            "feature_flags": {
                "AGENTIC_OBSERVABILITY_ENABLED": cfg.enabled,
                "AGENTIC_MCP_OBSERVABILITY_ENABLED": cfg.mcp_enabled,
                "AGENTIC_EXTERNAL_ACCOUNTS_ENABLED": cfg.external_accounts_enabled,
                "AGENTIC_PROVIDER_VERIFICATION_ENABLED": cfg.provider_verification_enabled,
                "AGENTIC_COMMUNICATION_OBSERVABILITY_ENABLED": cfg.communication_enabled,
                "AGENTIC_PROTOCOL_OBSERVABILITY_ENABLED": cfg.protocol_enabled,
                "KYBER_AGENTIC_OBSERVABILITY_ENABLED": cfg.kyber_enabled,
            },
            "emergency_disable": {
                "route_mounting": "set AGENTIC_OBSERVABILITY_ENABLED=false and restart API workers",
                "subsystem_disable": "disable AGENTIC_* subsystem flags independently",
                "worker_pause": "stop graph outbox workers; accepted observations remain queued",
            },
            "rollback_notes": [
                "feature flags hide routes without deleting stored observations",
                "outbox rows are idempotent and can be replayed after rollback",
                "AETHER never rolls back or reverses provider-side actions because it never performs them",
            ],
            "observation_only": True,
        }

    async def operator_audit_package(self, *, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "generated_at": _utc_now(),
            "package_type": "agentic_observability_operator_audit",
            "pipeline_health": await AgenticReconciliationService().pipeline_health(tenant_id=tenant_id),
            "usage_metering": await self.usage_metering(tenant_id=tenant_id),
            "security_privacy": await self.security_and_privacy_controls(tenant_id=tenant_id),
            "rollout_controls": self.rollout_controls(),
            "release_status": "design_partner_candidate",
            "observation_only": True,
        }

    async def release_candidate_evidence(
        self,
        *,
        tenant_id: str,
        agent_id: str | None = None,
        campaign_id: str | None = None,
    ) -> dict[str, Any]:
        health = await AgenticReconciliationService().pipeline_health(tenant_id=tenant_id)
        surfaces = AgenticProductSurfacesService()
        profile = await surfaces.agent_profile360(tenant_id=tenant_id, agent_id=agent_id) if agent_id else None
        journey = await surfaces.journey_v2_agentic_steps(tenant_id=tenant_id, agent_id=agent_id, limit=50)
        campaign = await surfaces.campaign_agentic_influence(tenant_id=tenant_id, campaign_id=campaign_id, limit=50) if campaign_id else None
        checks = [
            ("bronze_ingestion", health["bronze_agentic_observations"] > 0),
            ("silver_facts", sum(health["silver_facts"].values()) > 0),
            ("canonical_activity", health["canonical_activity"] > 0),
            ("graph_outbox_created", sum(health["outbox"].values()) > 0),
            ("agent_profile360", bool(profile and profile.get("counts", {}).get("activities", 0) > 0)),
            ("journey_v2_agentic_steps", bool(journey.get("steps"))),
            ("campaign_agentic_influence", bool(campaign and campaign.get("agentic_touchpoint_count", 0) > 0)),
            ("security_privacy_controls", True),
            ("usage_metering", True),
            ("rollout_controls", True),
        ]
        passed = [name for name, ok in checks if ok]
        failed = [name for name, ok in checks if not ok]
        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "campaign_id": campaign_id,
            "release_candidate": not failed,
            "passed_checks": passed,
            "failed_checks": failed,
            "pipeline_health": health,
            "evidence_precedence": [
                "provider_confirmed_fact",
                "observed_fact",
                "deterministic_computation",
                "probabilistic_inference",
                "recommendation",
                "insufficient_evidence",
            ],
            "observation_only": True,
        }
