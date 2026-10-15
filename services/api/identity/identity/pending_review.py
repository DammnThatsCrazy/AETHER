"""Tenant-scoped, non-authoritative late-binding review items."""

from __future__ import annotations

import hashlib
import asyncio
import json
from typing import Any

from repositories.repos import BaseRepository
from shared.common.common import utc_now

_ACTION_LOCK: asyncio.Lock | None = None
_ACTION_LOCK_LOOP: asyncio.AbstractEventLoop | None = None


def _action_lock() -> asyncio.Lock:
    global _ACTION_LOCK, _ACTION_LOCK_LOOP
    loop = asyncio.get_running_loop()
    if _ACTION_LOCK is None or _ACTION_LOCK_LOOP is not loop:
        _ACTION_LOCK = asyncio.Lock()
        _ACTION_LOCK_LOOP = loop
    return _ACTION_LOCK


class _PendingIdentityReviewStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_pending_reviews")

    async def compare_and_set_status(
        self,
        *,
        tenant_id: str,
        record_id: str,
        expected_status: str,
        patch: dict[str, Any],
    ) -> bool:
        """Atomically apply an action transition when its prior state matches."""
        pool = await self._ensure_pool()
        if pool is None:
            async with _action_lock():
                row = self._store.get(record_id)
                if (
                    not row
                    or row.get("tenant_id") != tenant_id
                    or row.get("status") != expected_status
                ):
                    return False
                row.update(patch)
                row["updated_at"] = utc_now().isoformat()
                self._store[record_id] = row
                return True

        await self._ensure_table()
        safe_patch = {**patch, "updated_at": utc_now().isoformat()}
        result = await pool.fetchrow(
            f"""UPDATE {self.table_name}
                SET data = data || $1::jsonb, updated_at = NOW()
                WHERE id = $2 AND tenant_id = $3 AND data->>'status' = $4
                RETURNING id""",
            json.dumps(safe_patch, separators=(",", ":")),
            record_id,
            tenant_id,
            expected_status,
        )
        return result is not None


class PendingIdentityReviewRepository:
    """Persist unresolved SDK-to-import candidate decisions idempotently.

    These records are review context only. They contain tenant-local references
    and reason/evidence metadata, never contact values or merge authority.
    """

    def __init__(self) -> None:
        self._store = _PendingIdentityReviewStore()

    @staticmethod
    def _record_id(
        tenant_id: str,
        identify_source_identity_id: str,
        candidate_source_identity_ids: list[str],
        reason_codes: list[str],
    ) -> str:
        material = "\0".join((
            tenant_id,
            identify_source_identity_id,
            ",".join(sorted(set(candidate_source_identity_ids))),
            ",".join(sorted(set(reason_codes))),
        ))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    async def upsert_candidate(
        self,
        *,
        tenant_id: str,
        identify_source_identity_id: str,
        candidate_source_identity_ids: list[str],
        reason_codes: list[str],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        candidates = sorted({str(value) for value in candidate_source_identity_ids if value})
        if not tenant_id or not identify_source_identity_id or not candidates:
            raise ValueError("tenant, identify source, and candidate references are required")
        safe_reasons = sorted({str(value) for value in reason_codes if value})
        record_id = self._record_id(
            tenant_id, identify_source_identity_id, candidates, safe_reasons
        )
        # Evidence from the adapter is already metadata-only. Whitelist fields at
        # this persistence boundary so future adapter additions cannot store PII.
        safe_evidence = []
        for item in evidence:
            if not isinstance(item, dict):
                continue
            safe_evidence.append({
                key: item[key]
                for key in (
                    "source_identity_id", "claim_type", "claim_verification_status",
                    "claim_id", "import_id", "import_commit_id",
                    "provisional_canonical_entity_id",
                )
                if item.get(key) is not None
            })
            digest = item.get("claim_digest")
            if (
                isinstance(digest, str)
                and len(digest) == 64
                and all(char in "0123456789abcdef" for char in digest)
            ):
                safe_evidence[-1]["claim_digest"] = digest
        existing = await self._store.find_by_id(record_id)
        now = utc_now().isoformat()
        if existing:
            if existing.get("tenant_id") != tenant_id:
                raise RuntimeError("pending review key tenant mismatch")
            # Repeated identify calls refresh evidence and last_seen without
            # creating another queue item or changing its disposition.
            existing["last_seen_at"] = now
            existing["seen_count"] = int(existing.get("seen_count", 1)) + 1
            if existing.get("status") == "open":
                existing["evidence"] = safe_evidence
            return await self._store.update(record_id, existing)
        row = {
            "id": record_id,
            "tenant_id": tenant_id,
            "entry_type": "late_binding_candidate",
            "identify_source_identity_id": identify_source_identity_id,
            "candidate_source_identity_ids": candidates,
            "reason_codes": safe_reasons,
            "evidence": safe_evidence,
            "recommended_action": "review_identity_evidence",
            "authority": "none",
            "status": "open",
            "seen_count": 1,
            "created_at": now,
            "last_seen_at": now,
        }
        return await self._store.insert(record_id, row)

    async def list_for_review(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return tenant-owned candidates whose disposition still needs attention.

        An approval can outlive the request that started it. Keep its durable
        progress and recovery states visible so the tenant can distinguish an
        in-flight decision from one that can be safely retried.
        """
        rows = await self._store.find_many(
            filters={"tenant_id": tenant_id, "entry_type": "late_binding_candidate"},
            limit=limit,
            sort_by="created_at",
            sort_order="desc",
        )
        reviewable = {"open", "approving", "approval_recovery_required", "merge_committed"}
        return [
            row for row in rows
            if row.get("tenant_id") == tenant_id and row.get("status") in reviewable
        ]

    async def list_open(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Backward-compatible name for the tenant review queue query."""
        return await self.list_for_review(tenant_id, limit=limit)

    async def get(self, tenant_id: str, record_id: str) -> dict[str, Any] | None:
        row = await self._store.find_by_id(record_id)
        if not row or row.get("tenant_id") != tenant_id:
            return None
        return row

    async def set_disposition(
        self,
        *,
        tenant_id: str,
        record_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Persist an action result without adding caller supplied payloads.

        Results are restricted to opaque identity decision references and stable
        reason codes. This keeps raw SDK traits, provider payloads, consent
        receipts, and operator supplied text out of the review ledger.
        """
        row = await self.get(tenant_id, record_id)
        if row is None:
            return None
        safe_result: dict[str, Any] = {}
        for key in (
            "canonical_entity_id", "decision_id", "restatement_job_id",
            "resolution_revision_before", "resolution_revision_after",
            "consent_receipt_id", "identify_source_identity_id",
            "candidate_source_identity_id", "sdk_entity_id",
        ):
            value = (result or {}).get(key)
            if isinstance(value, (str, int)) and value != "":
                safe_result[key] = value
        row["status"] = status
        row["updated_at"] = utc_now().isoformat()
        row["action_result"] = safe_result
        if reason_codes is not None:
            row["reason_codes"] = sorted({str(code) for code in reason_codes if code})
        return await self._store.update(record_id, row)

    async def compare_and_set_disposition(
        self,
        *,
        tenant_id: str,
        record_id: str,
        expected_status: str,
        status: str,
        result: dict[str, Any] | None = None,
        reason_codes: list[str] | None = None,
    ) -> bool:
        """Transition an action only for the caller that owns the prior state."""
        safe_result: dict[str, Any] = {}
        for key in (
            "canonical_entity_id", "decision_id", "restatement_job_id",
            "resolution_revision_before", "resolution_revision_after",
            "consent_receipt_id", "identify_source_identity_id",
            "candidate_source_identity_id", "sdk_entity_id",
        ):
            value = (result or {}).get(key)
            if isinstance(value, (str, int)) and value != "":
                safe_result[key] = value
        patch: dict[str, Any] = {
            "status": status,
            "action_result": safe_result,
        }
        if reason_codes is not None:
            patch["reason_codes"] = sorted({str(code) for code in reason_codes if code})
        return await self._store.compare_and_set_status(
            tenant_id=tenant_id,
            record_id=record_id,
            expected_status=expected_status,
            patch=patch,
        )


__all__ = ["PendingIdentityReviewRepository"]
