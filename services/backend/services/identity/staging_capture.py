"""Tenant-scoped source data for a staging identity proof capture.

This module deliberately does not execute scenarios or invent their outcomes.
It exposes only durable, explicitly recorded results from the scenario ledger;
an absent or incomplete execution batch remains incomplete for proof collection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config.settings import settings
from services.identity.decision_evidence import IdentityDecisionEvidenceRepository
from services.identity.explainability import AdminIdentityService
from services.identity.hashing import hash_value
from services.identity.contract_inventory import (
    REQUIRED_IDENTITY_CONTRACT_IDS,
    REQUIRED_STAGING_IDENTITY_FLAGS,
    observed_identity_contract_ids,
)
from services.identity.repository import IdentityResolutionRepository
from services.identity.scenario_evidence import IdentityScenarioEvidenceRepository
from services.jobs.service import get_jobs_service
from services.projections.projection_restatement_orchestrator import (
    PROJECTION_RESTATEMENT_JOB_TYPE,
)


def _stable_tenant_ref(tenant_id: str) -> str:
    return "tenant:" + hash_value(tenant_id, scope="staging-identity-evidence:tenant")[:24]


def _stable_ref(kind: str, tenant_id: str, value: Any) -> str | None:
    if value is None or value == "":
        return None
    material = f"{tenant_id}\0{kind}\0{value}"
    return f"{kind}:" + hash_value(material, scope="staging-identity-evidence:reference")[:24]


def _safe_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.astimezone(timezone.utc).isoformat()
    if isinstance(value, str) and value:
        return value
    return ""


def _safe_counts(value: Any) -> dict[str, int]:
    """Keep aggregate counters while dropping labels or values that could carry data."""
    if not isinstance(value, dict):
        return {}
    return {
        key: count for key, count in value.items()
        if isinstance(key, str) and 0 < len(key) <= 80
        and all(char.isalnum() or char in "_.:-" for char in key)
        and isinstance(count, int) and not isinstance(count, bool) and count >= 0
    }


def _safe_decision(row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    result = {
        key: row.get(key)
        for key in (
            "decision_type", "confidence_score", "confidence_tier",
            "merge_policy_version", "review_status", "created_at",
        )
        if row.get(key) is not None
    }
    for key, kind in (
        ("decision_id", "decision"),
        ("entity_id", "entity"),
        ("subject_entity_id", "entity"),
    ):
        ref = _stable_ref(kind, tenant_id, row.get(key))
        if ref:
            result[key] = ref
    connectors = row.get("source_connectors")
    if isinstance(connectors, list):
        result["source_connectors"] = sorted({
            item for item in connectors
            if isinstance(item, str) and 0 < len(item) <= 80
            and all(char.isalnum() or char in "_.:-" for char in item)
        })
    return result


def _safe_event(row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    keys = (
        "decision_type", "resolution_revision_before", "resolution_revision_after",
        "restatement_status", "created_at", "status",
    )
    result = {key: row.get(key) for key in keys if row.get(key) is not None}
    for key, kind in (
        ("id", "event"),
        ("from_entity_id", "entity"),
        ("into_entity_id", "entity"),
        ("original_entity_id", "entity"),
        ("source_merge_event_id", "event"),
        ("restatement_job_id", "job"),
    ):
        ref = _stable_ref(kind, tenant_id, row.get(key))
        if ref:
            result[key] = ref
    resulting = row.get("resulting_entity_ids")
    if isinstance(resulting, list):
        result["resulting_entity_ids"] = sorted({
            ref for value in resulting
            if (ref := _stable_ref("entity", tenant_id, value))
        })
    codes = row.get("reason_codes")
    if isinstance(codes, list):
        result["reason_codes"] = sorted({
            code for code in codes
            if isinstance(code, str) and 0 < len(code) <= 80
            and all(char.isalnum() or char in "_.:-" for char in code)
        })
    return result


def _safe_job(row: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    restatement = payload.get("restatement") if isinstance(payload.get("restatement"), dict) else {}
    projection_status = restatement.get("projection_status")
    safe_status = {}
    if isinstance(projection_status, dict):
        safe_status = {
            name: status
            for name, status in projection_status.items()
            if isinstance(name, str) and 0 < len(name) <= 80
            and all(char.isalnum() or char in "_.:-" for char in name)
            and status in {"queued", "running", "completed", "succeeded", "failed", "retryable_failure", "unsupported"}
        }
    projection_results = restatement.get("projection_evidence")
    safe_results: dict[str, Any] = {}
    if isinstance(projection_results, dict):
        for name, evidence in projection_results.items():
            if not isinstance(name, str) or not isinstance(evidence, dict):
                continue
            summary = {
                key: value for key, value in evidence.items()
                if key in {"status", "mode", "authority", "tenant_status", "deletion_status"}
                and isinstance(value, str) and len(value) <= 80
                and all(char.isalnum() or char in "_.:+-" for char in value)
            }
            summary.update({
                key: value for key, value in evidence.items()
                if key.endswith("_count") and isinstance(value, int)
                and not isinstance(value, bool) and value >= 0
            })
            if summary:
                safe_results[name] = summary
    job_ref = _stable_ref("job", tenant_id, row.get("id") or row.get("job_id"))
    return {
        "job_id": job_ref,
        "status": row.get("status"),
        "created_at": _safe_datetime(row.get("created_at")),
        "completed_at": _safe_datetime(row.get("completed_at")),
        "source_graph_version": restatement.get("graph_version_before") or restatement.get("source_graph_version"),
        "resulting_graph_version": restatement.get("graph_version_after") or restatement.get("resulting_graph_version"),
        "projection_status": safe_status,
        "projection_results": safe_results,
    }


async def capture_staging_identity_state(
    tenant_id: str,
    *,
    repo: IdentityResolutionRepository | None = None,
    decision_repo: IdentityDecisionEvidenceRepository | None = None,
    jobs_service: Any | None = None,
    admin_service: AdminIdentityService | None = None,
    scenario_repo: IdentityScenarioEvidenceRepository | None = None,
    deployment_id: str | None = None,
) -> dict[str, Any]:
    """Capture only persisted state visible to the authenticated tenant.

    Missing scenario execution records remain absent; downstream validation is
    expected to fail closed rather than infer success from aggregate health.
    """
    repo = repo or IdentityResolutionRepository()
    decision_repo = decision_repo or IdentityDecisionEvidenceRepository()
    jobs_service = jobs_service or get_jobs_service()
    admin_service = admin_service or AdminIdentityService(resolver=None)
    scenario_repo = scenario_repo or IdentityScenarioEvidenceRepository()
    now = datetime.now(timezone.utc).isoformat()

    activation = await admin_service.activation_status(tenant_id)
    health = await repo.get_identity_health(tenant_id)
    decisions = await decision_repo.list_for_tenant(tenant_id, limit=500)
    merges = await repo.get_recent_merges(tenant_id, limit=500)
    splits = await repo.get_recent_splits(tenant_id, limit=500)
    jobs = await jobs_service.list_jobs(
        tenant_id, job_type=PROJECTION_RESTATEMENT_JOB_TYPE, limit=500
    )
    scenario_rows = (
        await scenario_repo.list_for_tenant(tenant_id, deployment_id, limit=100)
        if deployment_id else []
    )
    # Capture one execution batch only. An incomplete newer batch must not be
    # combined with or silently replaced by older passing records.
    latest_execution_id = None
    if scenario_rows:
        latest_execution_id = scenario_rows[0].get("execution_id")
    safe_scenarios = [
        {
            "id": row["scenario_id"],
            "status": row["outcome"],
            "executed_at": _safe_datetime(row.get("executed_at")),
            "started_at": _safe_datetime(row.get("started_at")),
            "execution_ref": _stable_ref("execution", tenant_id, row.get("execution_id")),
            "evidence_sha256": row["evidence_sha256"],
            "assertions_passed": row["assertions_passed"],
            "assertions_failed": row["assertions_failed"],
        }
        for row in scenario_rows
        if row.get("execution_id") == latest_execution_id
        and row.get("scenario_id") in {
            "A_import_first_sdk_later", "B_shared_device_no_merge", "C_bad_merge_split",
            "D_agent_human_no_merge", "shared_email_review", "cross_tenant_block",
            "deleted_suppressed_identity_block", "multi_sdk_same_user",
            "connector_reimport_idempotency", "projection_restatement",
        }
        and row.get("outcome") in {"passed", "failed"}
    ]

    safe_decisions = [_safe_decision(row, tenant_id) for row in decisions]
    safe_merges = [_safe_event(row, tenant_id) for row in merges]
    safe_splits = [_safe_event(row, tenant_id) for row in splits]
    safe_jobs = [_safe_job(row, tenant_id) for row in jobs]
    successful_projections: set[str] = set()
    for job in safe_jobs:
        projection_status = job.get("projection_status")
        if isinstance(projection_status, dict):
            successful_projections.update(
                str(name) for name, status in projection_status.items()
                if status in {"succeeded", "completed"}
            )
        projection_results = job.get("projection_results")
        if isinstance(projection_results, dict):
            successful_projections.update(
                str(name) for name, result in projection_results.items()
                if isinstance(result, dict) and result.get("status") in {"succeeded", "completed"}
            )

    # These IDs are supplied by the generated shared identity contract inventory
    # when packaged with the service. An empty inventory is explicit and causes
    # proof validation to fail; source-tree files are never assumed present.
    observed_contracts = observed_identity_contract_ids()
    required_contracts = list(REQUIRED_IDENTITY_CONTRACT_IDS)
    flags = settings.identity_continuity
    flag_values = {
        name: bool(getattr(flags, name))
        for name in REQUIRED_STAGING_IDENTITY_FLAGS
    }
    projections = [
        {
            "projection": name,
            "status": "completed" if name in successful_projections else (
                "unsupported" if name == "syndicates" else "failed"
            ),
        }
        for name in (
            "profile_360", "journey", "campaign_360", "communications_360",
            "value", "signals", "agent_360", "execution_360", "syndicates", "account_360",
        )
    ]
    return {
        "captured_at": now,
        "tenant_ref": _stable_tenant_ref(tenant_id),
        "activation": {
            "historical_data_status": activation.get("historical_data_status"),
            "sdk_status": activation.get("sdk_status"),
            "resolution_counts": _safe_counts(activation.get("resolution_counts")),
            "conflict_counts": _safe_counts(activation.get("conflict_counts")),
            "projection_restatement_status": activation.get("projection_restatement_status"),
            "projection_restatement_counts": _safe_counts(activation.get("projection_restatement_counts")),
            "computed_at": activation.get("computed_at"),
        },
        "health": {
            key: health.get(key)
            for key in ("total_subjects", "total_entities", "total_aliases", "total_clusters", "open_conflicts", "recent_merges", "recent_splits")
        },
        "decisions": safe_decisions,
        "merges": safe_merges,
        "splits": safe_splits,
        "restatement_jobs": safe_jobs,
        "projection_outcomes": projections,
        "feature_flags": flag_values,
        # These only reflect explicit, durable runner submissions. No row is
        # synthesized from aggregate state, contract presence, or fixture names.
        "scenario_results": safe_scenarios,
        "contract_inventory": {
            "required_contract_ids": required_contracts,
            "observed_contract_ids": observed_contracts,
        },
        "evidence": {
            "activation": {"captured_at": now, "status": activation.get("historical_data_status"), "sdk_status": activation.get("sdk_status")},
            "decisions": safe_decisions,
            "merge_events": safe_merges,
            "split_events": safe_splits,
            "restatement_jobs": safe_jobs,
            "projection_outcomes": projections,
            "feature_flags": flag_values,
            "scenario_results": safe_scenarios,
            "contract_inventory": observed_contracts,
            "api_metrics": {"identity_health": {key: health.get(key) for key in ("total_subjects", "total_entities", "total_aliases", "total_clusters", "open_conflicts", "recent_merges", "recent_splits")}},
        },
        "status": "captured" if observed_contracts and safe_jobs and safe_decisions and activation.get("historical_data_status") else "incomplete",
    }
