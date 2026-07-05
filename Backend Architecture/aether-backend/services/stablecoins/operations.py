"""Kyber Stablecoin Operations and remediation controls.

PR4 keeps operations read-only by default. Remediation requests create durable,
audited intents that an operator workflow can execute later; no pipeline replay,
graph mutation, or financial correction is performed inline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from repositories.lake import BronzeRepository, SilverRepository
from repositories.stablecoin_repos import (
    StablecoinGoldRepository,
    StablecoinObservationRepository,
    StablecoinReconciliationRepository,
    StablecoinRemediationAuditRepository,
    StablecoinSupportAssertionRepository,
)
from shared.common.common import utc_now


class RemediationAction(str, Enum):
    REPLAY_INGESTION = "replay_ingestion"
    RERUN_NORMALIZATION = "rerun_normalization"
    RERUN_CLASSIFICATION = "rerun_classification"
    RERUN_RECONCILIATION = "rerun_reconciliation"
    REMATERIALIZE_GOLD = "rematerialize_gold"
    REPROJECT_GRAPH = "reproject_graph"
    REBUILD_PROFILE360 = "rebuild_profile360"
    QUARANTINE_DEPLOYMENT = "quarantine_deployment"
    CORRECT_CLASSIFICATION = "correct_classification"
    ROLLBACK_SOURCE_EXECUTION = "rollback_source_execution"
    RESOLVE_INCIDENT = "resolve_incident"


@dataclass(frozen=True)
class RemediationRequest:
    tenant_id: str
    action: RemediationAction
    actor_id: str
    reason: str
    evidence_reference: str
    target: Mapping[str, Any]
    before_state: Mapping[str, Any] = field(default_factory=dict)
    after_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required for stablecoin remediation")
        if not self.actor_id:
            raise ValueError("actor_id is required for stablecoin remediation")
        if not self.reason:
            raise ValueError("reason is required for stablecoin remediation")
        if not self.evidence_reference:
            raise ValueError("evidence_reference is required for stablecoin remediation")


class StablecoinOperationsService:
    def __init__(self) -> None:
        self.bronze = BronzeRepository("stablecoin")
        self.silver = SilverRepository("stablecoin")
        self.observations = StablecoinObservationRepository()
        self.reconciliation = StablecoinReconciliationRepository()
        self.support = StablecoinSupportAssertionRepository()
        self.gold = StablecoinGoldRepository()
        self.audit = StablecoinRemediationAuditRepository()

    async def tenant_health(self, tenant_id: str) -> dict[str, Any]:
        if not tenant_id:
            raise ValueError("tenant_id is required for stablecoin operations")
        bronze_count = await self.bronze.count(filters={"tenant_id": tenant_id})
        silver_count = await self.silver.count(filters={"tenant_id": tenant_id})
        observation_count = await self.observations.count(filters={"tenant_id": tenant_id})
        reconciliation_rows = await self.reconciliation.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        support_count = await self.support.count(filters={"tenant_id": tenant_id})
        gold_count = await self.gold.count(filters={"tenant_id": tenant_id})
        mismatches = sum(1 for row in reconciliation_rows if row.get("state") not in {"matched", "pending_finality"})
        return {
            "tenant_id": tenant_id,
            "bronze_count": bronze_count,
            "silver_count": silver_count,
            "observation_count": observation_count,
            "gold_count": gold_count,
            "support_assertion_count": support_count,
            "reconciliation_count": len(reconciliation_rows),
            "reconciliation_failures": mismatches,
            "pipeline_state": "needs_attention" if mismatches else "healthy",
            "feature_surface": "kyber_stablecoin_operations",
            "observation_only": True,
        }

    async def lineage(self, tenant_id: str, observation_id: str) -> dict[str, Any]:
        if not tenant_id or not observation_id:
            raise ValueError("tenant_id and observation_id are required for stablecoin lineage")
        observation = await self.observations.find_by_id(observation_id)
        if not observation or observation.get("tenant_id") != tenant_id:
            raise ValueError("stablecoin observation not found for tenant")
        return {
            "tenant_id": tenant_id,
            "observation_id": observation_id,
            "lineage": [
                {"layer": "provider", "id": observation.get("source_record_id"), "source": observation.get("source")},
                {"layer": "bronze", "id": observation.get("evidence_id")},
                {"layer": "silver", "id": observation_id, "status": observation.get("finality_status")},
                {"layer": "classification", "event_type": observation.get("event_type")},
                {"layer": "reconciliation", "status": "lookup_required"},
                {"layer": "gold", "status": "materialized_by_metric_identity"},
                {"layer": "graph", "status": "not_projected_by_pr4_ops"},
                {"layer": "profile360", "status": "not_built_by_pr4_ops"},
                {"layer": "tenant_ui", "status": "feature_flagged"},
            ],
            "observation_only": True,
        }

    async def request_remediation(self, request: RemediationRequest) -> dict[str, Any]:
        now = utc_now().isoformat()
        audit_id = f"stablecoin_remediation:{request.tenant_id}:{request.action.value}:{request.actor_id}:{now}"
        record = {
            "audit_id": audit_id,
            "tenant_id": request.tenant_id,
            "action": request.action.value,
            "actor_id": request.actor_id,
            "reason": request.reason,
            "evidence_reference": request.evidence_reference,
            "target": dict(request.target),
            "before_state": dict(request.before_state),
            "after_state": dict(request.after_state),
            "status": "recorded_not_executed",
            "created_at": now,
            "observation_only": True,
        }
        return await self.audit.insert(audit_id, record)
