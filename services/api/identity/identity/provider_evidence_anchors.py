"""Durable lifecycle anchors for provider-derived identity claims."""

from __future__ import annotations

import hashlib
from typing import Any

from repositories.repos import BaseRepository


class ProviderIdentityEvidenceAnchorRepository(BaseRepository):
    """One current lifecycle anchor per provider identity claim.

    A claim is candidate-visible only after its owning sync run or verified
    webhook delivery reaches completed. Starting a new durable capture replaces
    the previous anchor with pending, which fails closed while it is in flight.
    """

    def __init__(self) -> None:
        super().__init__("provider_identity_evidence_anchors")

    @staticmethod
    def _id(tenant_id: str, claim_id: str) -> str:
        material = f"{tenant_id}:{claim_id}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def set_pending(
        self,
        *,
        tenant_id: str,
        claim_id: str,
        source_identity_id: str,
        source_record_id: str,
        raw_checksum: str,
        raw_schema_version: str,
        provider_identity: str,
        connection_id: str,
        account_id: str,
        lifecycle_type: str,
        lifecycle_id: str,
    ) -> dict[str, Any]:
        if lifecycle_type not in {"provider_sync_run", "provider_webhook_inbox"}:
            raise ValueError("unsupported provider evidence lifecycle type")
        if not lifecycle_id:
            raise ValueError("provider evidence lifecycle id is required")
        anchor_id = self._id(tenant_id, claim_id)
        row = {
            "id": anchor_id,
            "tenant_id": tenant_id,
            "claim_id": claim_id,
            "source_identity_id": source_identity_id,
            "source_record_id": source_record_id,
            "raw_checksum": raw_checksum,
            "raw_schema_version": raw_schema_version,
            "provider_identity": provider_identity,
            "connection_id": connection_id,
            "account_id": account_id,
            "lifecycle_type": lifecycle_type,
            "lifecycle_id": lifecycle_id,
            "lifecycle_status": "pending",
        }
        existing = await self.find_by_id(anchor_id)
        if existing:
            return await self.update(anchor_id, row)
        return await self.insert(anchor_id, row)

    async def finish_lifecycle(
        self, *, tenant_id: str, lifecycle_type: str, lifecycle_id: str, status: str
    ) -> int:
        if status not in {"completed", "failed", "rolled_back"}:
            raise ValueError("unsupported provider evidence lifecycle status")
        rows = await self.find_many(filters={
            "tenant_id": tenant_id,
            "lifecycle_type": lifecycle_type,
            "lifecycle_id": lifecycle_id,
        }, limit=10000)
        for row in rows:
            row["lifecycle_status"] = status
            await self.update(str(row["id"]), row)
        return len(rows)

    async def get_current_committed_anchor(
        self,
        *,
        tenant_id: str,
        claim_id: str,
        source_identity_id: str,
        source_record_id: str,
        provider_identity: str,
        connection_id: str,
        account_id: str,
    ) -> dict[str, Any] | None:
        row = await self.find_by_id(self._id(tenant_id, claim_id))
        if not row:
            return None
        expected = {
            "tenant_id": tenant_id,
            "claim_id": claim_id,
            "source_identity_id": source_identity_id,
            "source_record_id": source_record_id,
            "provider_identity": provider_identity,
            "connection_id": connection_id,
            "account_id": account_id,
            "lifecycle_status": "completed",
        }
        if any(row.get(key) != value for key, value in expected.items()):
            return None
        if row.get("lifecycle_type") not in {
            "provider_sync_run", "provider_webhook_inbox"
        } or not row.get("lifecycle_id"):
            return None
        if not row.get("raw_checksum") or not row.get("raw_schema_version"):
            return None
        if not await self._lifecycle_is_completed(row):
            return None
        return row

    @staticmethod
    async def _lifecycle_is_completed(anchor: dict[str, Any]) -> bool:
        """Re-read the owning durable ledger so stale anchor state cannot win."""
        lifecycle_type = anchor.get("lifecycle_type")
        lifecycle_id = str(anchor.get("lifecycle_id") or "")
        if lifecycle_type == "provider_sync_run":
            from journeys.comms.sync_runs import SyncRunRepository

            run = await SyncRunRepository().get(lifecycle_id)
            return bool(
                run
                and run.get("sync_run_id") == lifecycle_id
                and run.get("tenant_id") == anchor.get("tenant_id")
                and run.get("connector_instance_id") == anchor.get("connection_id")
                and run.get("provider") == anchor.get("provider_identity")
                and run.get("provider_account_id") == anchor.get("account_id")
                and run.get("status") == "completed"
            )
        if lifecycle_type == "provider_webhook_inbox":
            from repositories.delivery_repos import WebhookInboxRepository

            inbox = await WebhookInboxRepository().find_by_id(lifecycle_id)
            return bool(
                inbox
                and inbox.get("tenant_id") == anchor.get("tenant_id")
                and inbox.get("provider") == anchor.get("provider_identity")
                and inbox.get("verified") is True
                and inbox.get("processed") is True
            )
        return False


__all__ = ["ProviderIdentityEvidenceAnchorRepository"]
