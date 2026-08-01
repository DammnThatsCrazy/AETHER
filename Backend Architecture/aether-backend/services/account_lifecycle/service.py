"""Account deletion state machine and idempotent erasure processor."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from repositories.account_deletion import (
    AccountDeletionWorkflowRepository,
    DetachedRetentionStubRepository,
)
from repositories.repos import APIKeyRepository, AdminRepository, UserRepository
from services.account_lifecycle.models import (
    DeletionStatus,
    RECOVERY_WINDOW_DAYS,
    StorageResultStatus,
    validate_step_up_evidence,
)
from services.account_lifecycle.storage_registry import (
    STORAGE_DOMAIN_REGISTRY,
    manifest_template,
    storage_domains_by_name,
    validate_storage_domain_coverage,
)
from shared.cache.cache import CacheKey
from shared.common.common import BadRequestError, ConflictError, NotFoundError
from shared.logger.logger import get_logger

logger = get_logger("aether.account_lifecycle")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class AccountLifecycleService:
    """Durable account-deletion workflow.

    Dependencies are injectable so tests can exercise the state machine without
    a database. Production/non-local persistence remains the repository's
    PostgreSQL path; in-memory repositories are only the existing local mode.
    """

    def __init__(
        self,
        *,
        workflow_repo: AccountDeletionWorkflowRepository | None = None,
        retention_repo: DetachedRetentionStubRepository | None = None,
        now_factory: Callable[[], datetime] = _now,
    ) -> None:
        validate_storage_domain_coverage()
        self._workflow_repo = workflow_repo or AccountDeletionWorkflowRepository()
        self._retention_repo = retention_repo or DetachedRetentionStubRepository()
        self._now = now_factory

    async def request_deletion(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        idempotency_key: str,
        reauth_evidence: dict[str, Any],
        actor_type: str = "tenant_user",
    ) -> dict:
        """Suspend immediately and open the durable 30-day recovery window."""

        if not tenant_id or not actor_id:
            raise BadRequestError("tenant_id and actor_id are required")
        if not idempotency_key or len(idempotency_key) > 256:
            raise BadRequestError("a bounded idempotency_key is required")
        now = self._now()
        safe_evidence = validate_step_up_evidence(reauth_evidence, now=now)

        existing = await self._workflow_repo.find_by_idempotency(tenant_id, idempotency_key)
        if existing:
            return self._public_workflow(existing)
        existing_workflows = await self._workflow_repo.find_by_tenant(tenant_id)
        active = [
            item for item in existing_workflows
            if item.get("status") in {DeletionStatus.RECOVERY.value, DeletionStatus.PROCESSING.value}
        ]
        if active:
            raise ConflictError("an account-deletion workflow is already active")

        tenant = await AdminRepository().find_by_id(tenant_id)
        if not tenant:
            raise NotFoundError("tenant")
        prior_status = str(tenant.get("status", "active"))
        if prior_status != "active":
            raise ConflictError("tenant is not active and cannot open account recovery")

        request_id = f"adl_{uuid.uuid4().hex[:20]}"
        recovery_until = now + timedelta(days=RECOVERY_WINDOW_DAYS)
        domains = manifest_template()
        workflow = {
            "id": request_id,
            "tenant_id": tenant_id,
            "requested_at": _iso(now),
            "recovery_until": _iso(recovery_until),
            "status": DeletionStatus.RECOVERY.value,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "reauth_evidence": safe_evidence,
            "idempotency_key": idempotency_key,
            "storage_results": {"domains": domains, "registry_version": 1},
            "retry_count": 0,
            "completed_at": None,
            "failed_at": None,
            "cancelled_at": None,
            "erasure_manifest": {
                "version": 1,
                "recovery_window_days": RECOVERY_WINDOW_DAYS,
                "fully_erased": False,
                "domains": domains,
            },
        }
        inserted = await self._workflow_repo.insert(workflow)
        if not inserted:
            replay = await self._workflow_repo.find_by_idempotency(tenant_id, idempotency_key)
            if replay:
                return self._public_workflow(replay)
            raise ConflictError("account-deletion idempotency conflict")

        try:
            await AdminRepository().update(
                tenant_id,
                {
                    "status": "suspended",
                    "suspension_reason": "account_deletion_recovery_window",
                    "account_deletion_id": request_id,
                    "suspended_at": _iso(now),
                    "prior_status": prior_status,
                },
            )
            await self._revoke_credentials(tenant_id, domains)
            await self._workflow_repo.update_request(
                request_id,
                {
                    "storage_results": {"domains": domains, "registry_version": 1},
                    "erasure_manifest": {
                        **workflow["erasure_manifest"],
                        "domains": domains,
                    },
                },
            )
        except Exception as exc:
            logger.exception("account deletion suspension failed: %s", exc)
            await self._workflow_repo.update_request(
                request_id,
                {"status": DeletionStatus.FAILED.value, "failed_at": _iso(self._now())},
            )
            raise

        return await self._get_required(request_id, tenant_id=tenant_id)

    async def get_status(self, workflow_id: str, *, tenant_id: str) -> dict:
        return self._public_workflow(await self._get_required(workflow_id, tenant_id=tenant_id))

    async def cancel_during_window(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        actor_id: str,
        reauth_evidence: dict[str, Any],
    ) -> dict:
        now = self._now()
        safe_evidence = validate_step_up_evidence(reauth_evidence, now=now)
        workflow = await self._get_required(workflow_id, tenant_id=tenant_id)
        if workflow.get("status") != DeletionStatus.RECOVERY.value:
            raise ConflictError("account deletion is no longer in the recovery window")
        if now >= _parse_time(workflow["recovery_until"]):
            raise ConflictError("the account-deletion recovery window has expired")

        await AdminRepository().update(
            tenant_id,
            {
                "status": "active",
                "suspension_reason": None,
                "account_deletion_id": None,
                "reactivated_at": _iso(now),
            },
        )
        updated = await self._workflow_repo.update_request(
            workflow_id,
            {
                "status": DeletionStatus.CANCELLED.value,
                "cancelled_at": _iso(now),
                "cancelled_by": actor_id,
                "cancel_reauth_evidence": safe_evidence,
            },
        )
        if not updated:
            raise NotFoundError("account-deletion workflow")
        return await self.get_status(workflow_id, tenant_id=tenant_id)

    async def process_retry(
        self,
        workflow_id: str,
        *,
        tenant_id: str,
        now: datetime | None = None,
    ) -> dict:
        """Process due domains; replaying this call is safe and idempotent."""

        current = now or self._now()
        workflow = await self._get_required(workflow_id, tenant_id=tenant_id)
        status = workflow.get("status")
        if status == DeletionStatus.COMPLETED.value:
            return workflow
        if status == DeletionStatus.CANCELLED.value:
            raise ConflictError("cancelled account deletion cannot be processed")
        if current < _parse_time(workflow["recovery_until"]):
            raise ConflictError("account deletion is still within its recovery window")
        if status == DeletionStatus.PROCESSING.value:
            return workflow

        await self._workflow_repo.update_request(
            workflow_id,
            {
                "status": DeletionStatus.PROCESSING.value,
                "retry_count": int(workflow.get("retry_count", 0)) + 1,
            },
        )
        workflow = await self._get_required(workflow_id, tenant_id=tenant_id)
        domains = (workflow.get("storage_results") or {}).get("domains", {})
        try:
            for domain in STORAGE_DOMAIN_REGISTRY:
                result = domains[domain.name]
                if result["status"] in {
                    StorageResultStatus.COMPLETED.value,
                    StorageResultStatus.REVOKED.value,
                    StorageResultStatus.RETAINED.value,
                    StorageResultStatus.UNAVAILABLE.value,
                    StorageResultStatus.DEFERRED.value,
                }:
                    continue
                await self._process_domain(domain.name, workflow, result)
                result["completed_at"] = _iso(current)
                result["error"] = None
        except Exception as exc:
            logger.exception("account deletion domain failed: %s", exc)
            for item in domains.values():
                if item.get("status") == StorageResultStatus.PENDING.value:
                    item["status"] = StorageResultStatus.FAILED.value
                    item["error"] = type(exc).__name__
                    item["completed_at"] = _iso(current)

        has_failed = any(
            item.get("status") == StorageResultStatus.FAILED.value
            for item in domains.values()
        )
        next_status = DeletionStatus.FAILED.value if has_failed else DeletionStatus.COMPLETED.value
        manifest = dict(workflow.get("erasure_manifest") or {})
        manifest["domains"] = domains
        manifest["fully_erased"] = not any(
            item.get("status") in {
                StorageResultStatus.UNAVAILABLE.value,
                StorageResultStatus.DEFERRED.value,
            }
            for item in domains.values()
        )
        manifest["completion"] = (
            "failed" if has_failed else
            "completed_with_unavailable_or_deferred_domains"
            if not manifest["fully_erased"] else "completed"
        )
        changes = {
            "status": next_status,
            "storage_results": {"domains": domains, "registry_version": 1},
            "erasure_manifest": manifest,
        }
        if next_status == DeletionStatus.COMPLETED.value:
            changes["completed_at"] = _iso(current)
        else:
            changes["failed_at"] = _iso(current)
        await self._workflow_repo.update_request(workflow_id, changes)
        return await self._get_required(workflow_id, tenant_id=tenant_id)

    async def _revoke_credentials(self, tenant_id: str, domains: dict[str, dict]) -> None:
        from services.auth.sessions import (
            public_ingest_service,
            service_credential_service,
            session_service,
        )

        session_count = await session_service.revoke_all_for_tenant(tenant_id)
        self._mark_result(domains["sessions"], StorageResultStatus.REVOKED.value, "revoke", session_count)
        credential_count = await service_credential_service.revoke_all_for_tenant(tenant_id)
        self._mark_result(
            domains["service_credentials"], StorageResultStatus.REVOKED.value, "revoke", credential_count
        )
        ingest_count = await public_ingest_service.revoke_all_for_tenant(tenant_id)
        self._mark_result(
            domains["public_ingest_identifiers"], StorageResultStatus.REVOKED.value, "revoke", ingest_count
        )
        key_count = await self._revoke_api_keys(tenant_id)
        self._mark_result(domains["api_keys"], StorageResultStatus.REVOKED.value, "revoke", key_count)

    @staticmethod
    def _mark_result(result: dict, status: str, action: str, count: int) -> None:
        result.update({"status": status, "action": action, "records_affected": count})

    async def _revoke_api_keys(self, tenant_id: str) -> int:
        repository = APIKeyRepository()
        keys = await repository.find_many(filters={"tenant_id": tenant_id}, limit=1000)
        revoked = 0
        for record in keys:
            key_id = record.get("id")
            if not key_id or record.get("status") == "revoked":
                continue
            await repository.update(
                key_id,
                {"status": "revoked", "revoked_at": _iso(self._now())},
            )
            key_hash = record.get("key_hash")
            if key_hash:
                try:
                    from dependencies.providers import get_registry
                    await get_registry().cache.delete(CacheKey.api_key(key_hash))
                except Exception:
                    pass
            revoked += 1
        return revoked

    async def _process_domain(self, name: str, workflow: dict, result: dict) -> None:
        tenant_id = workflow["tenant_id"]
        if name == "tenant_core":
            users = await UserRepository().delete_by_entity("tenant_id", tenant_id)
            tenant_deleted = 1 if await AdminRepository().delete(tenant_id) else 0
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", users + tenant_deleted)
            return
        if name == "api_keys":
            deleted = await APIKeyRepository().delete_by_entity("tenant_id", tenant_id)
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", deleted)
            return
        if name == "sessions":
            from services.auth.sessions import session_service
            count = await session_service.revoke_all_for_tenant(tenant_id)
            self._mark_result(result, StorageResultStatus.REVOKED.value, "revoke", count)
            return
        if name == "service_credentials":
            from services.auth.sessions import service_credential_service
            count = await service_credential_service.revoke_all_for_tenant(tenant_id)
            self._mark_result(result, StorageResultStatus.REVOKED.value, "revoke", count)
            return
        if name == "public_ingest_identifiers":
            from services.auth.sessions import public_ingest_service
            count = await public_ingest_service.revoke_all_for_tenant(tenant_id)
            self._mark_result(result, StorageResultStatus.REVOKED.value, "revoke", count)
            return
        if name == "notification_webhooks":
            from repositories.repos import WebhookRepository
            count = await WebhookRepository().delete_by_entity("tenant_id", tenant_id)
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", count)
            return
        if name == "provider_credentials":
            from repositories.repos import ProvidersRepository
            count = await ProvidersRepository().delete_by_entity("tenant_id", tenant_id)
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", count)
            return
        if name == "webhook_delivery_claims":
            from services.notification_intelligence.customer_webhook_delivery import (
                CustomerWebhookDeliveryRepository,
            )
            count = await CustomerWebhookDeliveryRepository().claims.delete_by_tenant(tenant_id)
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", count)
            return
        if name == "webhook_delivery_attempts":
            from repositories.delivery_repos import DeliveryAttemptRepository
            count = await DeliveryAttemptRepository().delete_by_entity("tenant_id", tenant_id)
            self._mark_result(result, StorageResultStatus.COMPLETED.value, "erase", count)
            return
        if name in {"billing", "audit"}:
            stub_id = f"ret_{workflow['id']}_{name}"
            await self._retention_repo.insert(stub_id, {
                "workflow_id": workflow["id"],
                "domain": name,
                "tenant_ref": hashlib.sha256(tenant_id.encode()).hexdigest(),
                "retention_reason": "legal_obligation",
                "detached_at": _iso(self._now()),
                "source_records_erased": False,
            })
            self._mark_result(result, StorageResultStatus.RETAINED.value, "retain_detached_stub", 1)
            return
        # Registry entries with no provider are initialized explicitly as
        # unavailable/deferred and are not dispatched here.
        descriptor = storage_domains_by_name()[name]
        result.update({"status": descriptor.mode, "action": "not_attempted", "reason": descriptor.reason})

    async def _get_required(self, workflow_id: str, *, tenant_id: str) -> dict:
        workflow = await self._workflow_repo.find_by_request_id(workflow_id)
        if not workflow or workflow.get("tenant_id") != tenant_id:
            raise NotFoundError("account-deletion workflow")
        return workflow

    @staticmethod
    def _public_workflow(workflow: dict) -> dict:
        result = dict(workflow)
        evidence = dict(result.get("reauth_evidence") or {})
        evidence.pop("evidence_id", None)
        result["reauth_evidence"] = evidence
        result.pop("cancel_reauth_evidence", None)
        return result


account_lifecycle_service = AccountLifecycleService()
