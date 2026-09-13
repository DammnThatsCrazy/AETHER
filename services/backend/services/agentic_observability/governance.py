"""
Agentic Governance Service — DSR, metering, security controls, rollout, audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repositories.agentic_observability_repos import (
    AgentActivityRepository,
    AgentConnectionRepository,
    AgentRiskSignalRepository,
    AgentToolRepository,
    AgenticBronzeObservationRepository,
    AgenticProjectionOutboxRepository,
    ExternalAccountRepository,
    SilverAgentActivityFactRepository,
    SilverAgentToolInvocationFactRepository,
    SilverMCPConnectionFactRepository,
    SilverAgentRiskFactRepository,
)
from services.agentic_observability.product_surfaces import AgenticProductSurfacesService
from services.agentic_observability.reconciliation import AgenticReconciliationService
from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.governance")

_AGENTIC_TABLES = (
    ("obs_agent_activities", AgentActivityRepository),
    ("obs_agent_connections", AgentConnectionRepository),
    ("obs_agent_tools", AgentToolRepository),
    ("obs_agent_risk_signals", AgentRiskSignalRepository),
    ("obs_external_accounts", ExternalAccountRepository),
    # Bronze/Silver repos must be scanned so DSR catches all observation records
    # including generic events stored only in bronze_agentic_observations or Silver facts.
    ("bronze_agentic_observations", AgenticBronzeObservationRepository),
    ("silver_agent_activity_facts", SilverAgentActivityFactRepository),
    ("silver_agent_tool_invocation_facts", SilverAgentToolInvocationFactRepository),
    ("silver_mcp_connection_facts", SilverMCPConnectionFactRepository),
    ("silver_agent_risk_facts", SilverAgentRiskFactRepository),
)

_PERSON_FIELDS = frozenset({"actor_id", "external_actor_id", "profile_id", "anonymous_id"})
_AGENT_FIELDS = frozenset({"agent_id", "external_agent_id"})
_OBJECT_FIELDS = frozenset({"object_id", "external_object_id"})
_ALL_SUBJECT_FIELDS = _PERSON_FIELDS | _AGENT_FIELDS | _OBJECT_FIELDS


def _row_matches_subject(row: dict[str, Any], subject_id: str) -> bool:
    for key in _ALL_SUBJECT_FIELDS:
        val = row.get(key)
        if val and str(val) == subject_id:
            return True
        for v in row.values():
            if isinstance(v, dict) and str(v.get(key, "")) == subject_id:
                return True
    return False


def _redact_subject(row: dict[str, Any], subject_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in row.items():
        if k in _ALL_SUBJECT_FIELDS:
            result[k] = "[REDACTED]" if str(v) == subject_id else v
        elif isinstance(v, dict):
            result[k] = _redact_subject(v, subject_id)
        else:
            result[k] = v
    return result


@dataclass(frozen=True)
class AgenticDSRPreview:
    subject_id: str
    tenant_id: str
    matched_rows: list[dict[str, Any]] = field(default_factory=list)
    tables_checked: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "matched_row_count": len(self.matched_rows),
            "tables_checked": list(self.tables_checked),
            "observation_only": True,
        }


class AgenticGovernanceService:
    def __init__(self) -> None:
        self._reconcile = AgenticReconciliationService()
        self._surfaces = AgenticProductSurfacesService()

    async def usage_metering(self, tenant_id: str) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for table_name, repo_cls in _AGENTIC_TABLES:
            repo = repo_cls()
            counts[table_name] = await repo.count(filters={"tenant_id": tenant_id})
        outbox = AgenticProjectionOutboxRepository()
        counts["agentic_projection_outbox"] = await outbox.count(filters={"tenant_id": tenant_id})
        return {
            "tenant_id": tenant_id,
            "observation_counts": counts,
            "total_observations": sum(counts.values()),
            "observation_only": True,
        }

    async def dsr_preview(
        self, tenant_id: str, subject_id: str, action: str = "preview"
    ) -> dict[str, Any]:
        matched: list[dict[str, Any]] = []
        tables_checked: list[str] = []
        for table_name, repo_cls in _AGENTIC_TABLES:
            repo = repo_cls()
            rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=500)
            tables_checked.append(table_name)
            for row in rows:
                if _row_matches_subject(row, subject_id):
                    matched.append({"table": table_name, "row_id": row.get("id", "")})
        preview = AgenticDSRPreview(
            subject_id=subject_id,
            tenant_id=tenant_id,
            matched_rows=matched,
            tables_checked=tables_checked,
        )
        return preview.as_dict()

    async def dsr_export(
        self, tenant_id: str, subject_id: str, include_rows: bool = False
    ) -> dict[str, Any]:
        result = await self.dsr_preview(tenant_id, subject_id)
        if include_rows:
            full_rows: list[dict[str, Any]] = []
            for table_name, repo_cls in _AGENTIC_TABLES:
                repo = repo_cls()
                rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=500)
                for row in rows:
                    if _row_matches_subject(row, subject_id):
                        full_rows.append({"table": table_name, "row": _redact_subject(row, subject_id)})
            result["rows"] = full_rows
        result["export_format"] = "json"
        result["observation_only"] = True
        return result

    async def security_and_privacy_controls(self, tenant_id: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "controls": [
                {
                    "id": "sensitive_key_redaction",
                    "status": "active",
                    "description": "Sensitive keys redacted at pipeline ingestion",
                },
                {
                    "id": "no_execution_invariant",
                    "status": "active",
                    "description": "execution_by_aether is always False; enforced at model, route, and pipeline level",
                },
                {
                    "id": "tenant_isolation",
                    "status": "active",
                    "description": "All repos filter by tenant_id; tenant mismatch rejected at 403",
                },
                {
                    "id": "dsr_preview_export",
                    "status": "active",
                    "description": "DSR preview and export available for all agentic observation tables",
                },
                {
                    "id": "graph_tombstone",
                    "status": "not_implemented",
                    "description": "Graph tombstone execution for DSR not yet implemented",
                },
                {
                    "id": "ci_static_scan",
                    "status": "not_implemented",
                    "description": "CI-gated static security scanning not yet configured",
                },
            ],
            "observation_only": True,
        }

    def rollout_controls(self) -> dict[str, Any]:
        from config.settings import get_settings
        try:
            settings = get_settings()
            cfg = settings.agentic_observability
            flags: dict[str, Any] = {
                "enabled": cfg.enabled,
                "mcp_enabled": cfg.mcp_enabled,
                "external_accounts_enabled": cfg.external_accounts_enabled,
                "provider_verification_enabled": cfg.provider_verification_enabled,
                "communication_enabled": cfg.communication_enabled,
                "protocol_enabled": cfg.protocol_enabled,
                "kyber_enabled": cfg.kyber_enabled,
            }
        except Exception:
            flags = {"enabled": False, "note": "settings unavailable"}
        return {
            "feature_flags": flags,
            "release_gate": "internal_preview",
            "observation_only": True,
        }

    async def operator_audit_package(self, tenant_id: str) -> dict[str, Any]:
        health = await self._reconcile.pipeline_health(tenant_id)
        reconcile = await self._reconcile.reconcile(tenant_id, limit=50)
        metering = await self.usage_metering(tenant_id)
        controls = await self.security_and_privacy_controls(tenant_id)
        rollout = self.rollout_controls()
        return {
            "tenant_id": tenant_id,
            "pipeline_health": health,
            "reconciliation_summary": reconcile,
            "usage_metering": metering,
            "security_controls": controls,
            "rollout_controls": rollout,
            "observation_only": True,
        }

    async def release_candidate_evidence(
        self, tenant_id: str, agent_id: str, campaign_id: str
    ) -> dict[str, Any]:
        profile = await self._surfaces.agent_profile360(tenant_id, agent_id)
        journey = await self._surfaces.journey_v2_agentic_steps(tenant_id, agent_id)
        campaign = await self._surfaces.campaign_agentic_influence(tenant_id, campaign_id)
        audit = await self.operator_audit_package(tenant_id)
        from services.agentic_observability.release_readiness import AgenticReleaseReadinessService
        readiness = AgenticReleaseReadinessService().readiness()
        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "campaign_id": campaign_id,
            "agent_profile360": profile,
            "journey_steps": journey,
            "campaign_influence": campaign,
            "operator_audit": audit,
            "release_readiness": readiness,
            "observation_only": True,
        }
