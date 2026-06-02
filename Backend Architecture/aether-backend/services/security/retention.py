"""Data Retention Policies + Data Requests.

Retention policies and data requests (export / delete / review) are processed as
structured, audited records. Guardrails:
  - audit logs are never silently deleted
  - billing records are preserved when retention requires it
  - cross-resource deletions require a manifest
  - legal-hold notes are stored as structured metadata
  - deletes preserve an audit stub where required
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError, utc_now
from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .contracts import (
    ActorType,
    DataRequest,
    DataRequestStatus,
    DataRequestType,
    DataRetentionPolicy,
    RetentionDeleteBehavior,
    RetentionResourceType,
    now_iso,
    sanitize_metadata,
)
from .policy_engine import policy_engine
from .repositories import DataRequestRepository, DataRetentionPolicyRepository

logger = get_logger("aether.security.retention")

# Resource types that must never be hard-deleted regardless of policy.
_PRESERVE_RESOURCES = {"audit_log", "billing_record"}

# Sensible default retention policies seeded per tenant on first read.
_DEFAULT_POLICIES: list[dict[str, Any]] = [
    {"resource_type": "event", "retention_days": 730, "delete_behavior": "anonymize"},
    {"resource_type": "audit_log", "retention_days": 2555, "delete_behavior": "preserve_audit_stub", "legal_hold_supported": True},
    {"resource_type": "billing_record", "retention_days": 2555, "delete_behavior": "preserve_audit_stub"},
    {"resource_type": "audit_export", "retention_days": 90, "delete_behavior": "hard_delete"},
]


class DataRetentionService:
    def __init__(
        self,
        policy_repo: Optional[DataRetentionPolicyRepository] = None,
        request_repo: Optional[DataRequestRepository] = None,
    ) -> None:
        self._policies = policy_repo or DataRetentionPolicyRepository()
        self._requests = request_repo or DataRequestRepository()

    # ── Retention policies ────────────────────────────────────────────────────

    async def list_policies(self, tenant_id: Optional[str] = None) -> list[dict]:
        if tenant_id is None:
            return await self._policies.list_all(limit=500)
        existing = await self._policies.list_for_tenant(tenant_id, limit=500)
        if existing:
            return existing
        # Seed defaults on first access so tenants always have a baseline.
        seeded: list[dict] = []
        for spec in _DEFAULT_POLICIES:
            pol = DataRetentionPolicy(tenant_id=tenant_id, **spec)
            await self._policies.insert(pol.policy_id, pol.model_dump())
            seeded.append(pol.model_dump())
        return seeded

    async def create_policy(
        self, *, tenant_id: Optional[str], resource_type: RetentionResourceType,
        retention_days: int, delete_behavior: RetentionDeleteBehavior = 'soft_delete',
        legal_hold_supported: bool = True, enabled: bool = True, actor_id: str = "system",
    ) -> DataRetentionPolicy:
        if resource_type in _PRESERVE_RESOURCES and delete_behavior == 'hard_delete':
            raise BadRequestError(
                f"{resource_type} may not use hard_delete; use preserve_audit_stub"
            )
        pol = DataRetentionPolicy(
            tenant_id=tenant_id, resource_type=resource_type,
            retention_days=retention_days, delete_behavior=delete_behavior,
            legal_hold_supported=legal_hold_supported, enabled=enabled,
        )
        await self._policies.insert(pol.policy_id, pol.model_dump())
        await audit_ledger.record(
            actor_id=actor_id, actor_type='olympus_operator',
            event_type="data_retention.policy_created", resource_type="data_retention_policy",
            action="configure", outcome='allowed', tenant_id=tenant_id,
            resource_id=pol.policy_id,
            metadata={"resource_type": resource_type, "retention_days": retention_days, "delete_behavior": delete_behavior},
        )
        return pol

    async def update_policy(
        self, policy_id: str, updates: dict[str, Any], actor_id: str = "system",
    ) -> dict:
        row = await self._policies.find_by_id(policy_id)
        if row is None:
            raise NotFoundError(f"retention policy {policy_id!r} not found")
        if (updates.get("delete_behavior") == 'hard_delete'
                and row.get("resource_type") in _PRESERVE_RESOURCES):
            raise BadRequestError(
                f"{row.get('resource_type')} may not use hard_delete"
            )
        allowed_fields = {"retention_days", "delete_behavior", "legal_hold_supported", "enabled"}
        clean = {k: v for k, v in updates.items() if k in allowed_fields}
        row.update(clean)
        row["updated_at"] = now_iso()
        await self._policies.update(policy_id, row)
        await audit_ledger.record(
            actor_id=actor_id, actor_type='olympus_operator',
            event_type="data_retention.policy_updated", resource_type="data_retention_policy",
            action="configure", outcome='allowed', tenant_id=row.get("tenant_id"),
            resource_id=policy_id, metadata=sanitize_metadata(clean),
        )
        return row

    # ── Data requests ─────────────────────────────────────────────────────────

    async def create_request(
        self, *, tenant_id: str, request_type: DataRequestType, requested_by: str,
        actor_type: ActorType = 'tenant_user', target_resource_type: Optional[str] = None,
        target_resource_id: Optional[str] = None, legal_hold_note: Optional[str] = None,
        has_manifest: bool = True,
    ) -> DataRequest:
        # Deletion requests pass through the policy engine guardrails first.
        if request_type in ("delete_entity", "delete_tenant"):
            decision = await policy_engine.check_data_deletion(
                actor_id=requested_by, actor_type=actor_type, tenant_id=tenant_id,
                resource_type=target_resource_type or "entity",
                has_manifest=has_manifest,
            )
            if not decision.allowed:
                req = DataRequest(
                    tenant_id=tenant_id, request_type=request_type, requested_by=requested_by,
                    status='denied', target_resource_type=target_resource_type,
                    target_resource_id=target_resource_id, result_summary=decision.reason,
                    completed_at=now_iso(),
                )
                await self._requests.insert(req.data_request_id, req.model_dump())
                return req

        req = DataRequest(
            tenant_id=tenant_id, request_type=request_type, requested_by=requested_by,
            status='requested', target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
        )
        data = req.model_dump()
        if legal_hold_note:
            data["legal_hold"] = {"note": legal_hold_note, "recorded_at": now_iso()}
        await self._requests.insert(req.data_request_id, sanitize_metadata(data))
        await audit_ledger.record(
            actor_id=requested_by, actor_type=actor_type,
            event_type=f"data_request.{request_type}", resource_type="data_request",
            action=request_type, outcome='allowed', tenant_id=tenant_id,
            resource_id=req.data_request_id,
            metadata={"target_resource_type": target_resource_type, "legal_hold": bool(legal_hold_note)},
        )
        return req

    async def process_request(
        self, data_request_id: str, *, status: DataRequestStatus,
        result_summary: str = "", actor_id: str = "system",
    ) -> dict:
        row = await self._requests.find_by_id(data_request_id)
        if row is None:
            raise NotFoundError(f"data request {data_request_id!r} not found")
        row["status"] = status
        if result_summary:
            row["result_summary"] = result_summary
        if status in ("completed", "denied", "failed"):
            row["completed_at"] = now_iso()
        # Preserve an audit stub for any tenant-deletion processing.
        if row.get("request_type") == "delete_tenant" and status == "completed":
            row["audit_stub_preserved"] = True
        await self._requests.update(data_request_id, row)
        await audit_ledger.record(
            actor_id=actor_id, actor_type='olympus_operator',
            event_type="data_request.processed", resource_type="data_request",
            action="process", outcome='allowed' if status != 'failed' else 'failed',
            tenant_id=row.get("tenant_id"), resource_id=data_request_id,
            metadata={"status": status},
        )
        return row

    async def list_requests(self, tenant_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        if tenant_id is None:
            return await self._requests.list_all(limit=limit)
        return await self._requests.list_for_tenant(tenant_id, limit=limit)


data_retention_service = DataRetentionService()
