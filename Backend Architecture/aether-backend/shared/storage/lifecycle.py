"""
Aether Shared — Cross-Store Storage Lifecycle (FT-8-OBJECT-BACKED-BRONZE)

Retention, deletion, DSR erasure, and legal holds applied consistently across
ALL THREE stores an externalized resource spans:

    row store (Postgres)  +  object store (S3/in-memory)  +  descriptor index

Policy comes from config/storage_policies.yaml ONLY (via
``shared.storage.manager.policy_for`` — fail-closed for unknown types); this
module never invents a parallel policy source:

  * ``retention_class``  — ``standard`` resources age out after
                           ``STORAGE_RETENTION_STANDARD_DAYS``; ``legal``
                           resources are NEVER swept by this lifecycle
                           (compliance-owned).
  * ``delete_behavior``  — ``hard_delete`` removes rows + object bytes +
                           descriptor rows entirely; ``tombstone`` removes the
                           payload bytes and subject identifiers but retains
                           structural stubs (rows keep their ids, descriptors
                           keep their checksummed audit trail with
                           ``tombstoned: true``); ``preserve`` is never swept.
  * ``legal_hold_supported`` — placing a hold on a type whose policy forbids
                           holds fails closed with StoragePolicyViolationError.

Legal holds (``storage_legal_holds`` table, StorageLegalHoldRepository) BLOCK
every deletion path — retention sweeps and DSR erasure — until released. A
hold may scope to a whole tenant, one resource type, and/or one subject.
Retention (which cannot know which subjects live inside a packed object)
treats ANY matching active hold as blocking; a DSR for subject A is only
blocked by holds covering A (or unscoped holds), because re-packing removes
only A's records and preserves every held subject's data.

DSR erasure strategy (simplest correct approach, chosen deliberately):
subject rows are removed from the row store per ``delete_behavior``, and each
packed object containing the subject is HYDRATED, FILTERED, AND RE-PACKED
without the subject's records (new descriptor, lineage → old descriptor;
surviving rows re-pointed). The old object is always deleted. Re-pack runs
with the master externalization flag overridden ON: erasure is a compliance
operation and must work even when the write path is disabled — the
per-resource-type policy (``allow_object_externalization``) is still
enforced by ``StorageManager.externalize``.

The retention sweep is wired into the existing maintenance retention worker
(services/security/retention_worker.py) behind
``STORAGE_LIFECYCLE_RETENTION_ENABLED`` (default OFF).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.storage.compaction import (
    BRONZE_RESOURCE_TYPE,
    SUBJECT_FIELDS,
    BronzeRowStore,
    _parse_iso,
    _row_age_stamp,
)
from shared.storage.descriptor import StorageDescriptor
from shared.storage.manager import StorageManager, StoragePolicy, StoragePolicyViolationError

logger = get_logger("aether.storage.lifecycle")

# Repository page sizes for full-coverage scans. Every scan below PAGES to
# exhaustion — a single capped fetch would silently skip data past the cap
# (holds that must block deletion, expired descriptors, a subject's rows),
# which is fail-open for compliance paths. Module-level so tests can shrink
# them to exercise the pagination itself.
_HOLD_PAGE_SIZE = 500
_DESCRIPTOR_PAGE_SIZE = 1_000
_SUBJECT_ROW_PAGE_SIZE = 10_000
# Hard ceiling on erase-loop iterations — bounds the loop if a row mutation
# ever fails to make progress (belt-and-braces; converges in 1-2 passes).
_MAX_ERASE_PASSES = 1_000


class LegalHoldActiveError(RuntimeError):
    """A deletion was attempted against data covered by an active legal hold."""


def _record_matches_subject(record: Mapping[str, Any], subject_ref: str) -> bool:
    """True when a packed record belongs to the data subject."""
    return any(record.get(f) == subject_ref for f in SUBJECT_FIELDS if record.get(f))


class StorageLifecycle:
    """Policy-driven retention / deletion / DSR / legal holds across stores."""

    def __init__(
        self,
        manager: Optional[StorageManager] = None,
        row_store: Optional[BronzeRowStore] = None,
        hold_repo: Optional[Any] = None,
        *,
        policies_path: Optional[Path] = None,
        standard_retention_days: Optional[int] = None,
    ) -> None:
        # Lifecycle mutations (retention deletion, DSR re-pack) are compliance
        # operations: the manager overrides the master write-path flag while
        # the per-type policy stays enforced (see module docstring).
        self.manager = manager or StorageManager(
            policies_path=policies_path, externalization_enabled=True
        )
        self.rows = row_store or BronzeRowStore()
        self._hold_repo = hold_repo
        self._standard_retention_days = standard_retention_days

    # -- collaborators ---------------------------------------------------------

    @property
    def hold_repo(self) -> Any:
        if self._hold_repo is None:
            from repositories.repos import StorageLegalHoldRepository  # lazy

            self._hold_repo = StorageLegalHoldRepository()
        return self._hold_repo

    @property
    def descriptor_repo(self) -> Any:
        return self.manager.descriptor_repo

    @property
    def object_store(self) -> Any:
        return self.manager.object_store

    def _standard_days(self) -> int:
        if self._standard_retention_days is not None:
            return self._standard_retention_days
        from config.settings import settings  # lazy — avoids import cycles

        return int(settings.storage_plane.retention_standard_days)

    # ═══════════════════════════════════════════════════════════════════════
    # LEGAL HOLDS
    # ═══════════════════════════════════════════════════════════════════════

    async def place_hold(
        self,
        tenant_id: str,
        *,
        reason: str,
        resource_type: str = "",
        subject_ref: str = "",
        placed_by: str = "operator",
    ) -> dict:
        """Place an active legal hold. Fail-closed on unsupported types.

        ``resource_type=""`` holds every resource type for the tenant;
        ``subject_ref=""`` holds every subject in scope.
        """
        if not tenant_id:
            raise ValueError("legal hold requires a tenant_id")
        if not (reason or "").strip():
            raise ValueError("legal hold requires a non-empty reason")
        if resource_type:
            policy = self.manager.policy_for(resource_type)  # KeyError if unknown
            if not policy.legal_hold_supported:
                raise StoragePolicyViolationError(
                    f"Policy for {resource_type!r} does not support legal holds"
                )
        hold_id = f"hold_{uuid.uuid4().hex}"
        record = {
            "hold_id": hold_id,
            "tenant_id": tenant_id,
            "resource_type": resource_type,
            "subject_ref": subject_ref,
            "reason": reason.strip(),
            "placed_by": placed_by,
            "status": "active",
            "placed_at": utc_now().isoformat(),
            "released_at": None,
            "released_by": None,
        }
        await self.hold_repo.insert(hold_id, record)
        logger.info(
            f"Legal hold placed hold={hold_id} tenant={tenant_id} "
            f"resource_type={resource_type or '*'} subject={subject_ref or '*'}"
        )
        return record

    async def release_hold(self, hold_id: str, *, released_by: str = "operator") -> dict:
        """Release a hold; subsequent deletions in its scope proceed."""
        row = await self.hold_repo.find_by_id(hold_id)
        if row is None:
            raise KeyError(f"legal hold {hold_id!r} not found")
        row["status"] = "released"
        row["released_at"] = utc_now().isoformat()
        row["released_by"] = released_by
        await self.hold_repo.update(hold_id, row)
        logger.info(f"Legal hold released hold={hold_id} by={released_by}")
        return row

    async def active_hold(
        self,
        tenant_id: str,
        resource_type: str,
        subject_ref: Optional[str] = None,
    ) -> Optional[dict]:
        """First active hold blocking a deletion in the given scope.

        ``subject_ref=None`` means the deletion is NOT subject-scoped
        (retention sweep): any matching hold blocks, including subject-scoped
        ones — a packed object may contain the held subject. A subject-scoped
        deletion (DSR) is blocked only by holds covering that subject or by
        subject-unscoped holds.

        Pages through EVERY active hold — capping at one page would let a
        matching hold beyond the page slip past and allow a blocked deletion.
        """
        offset = 0
        while True:
            holds = await self.hold_repo.find_many(
                filters={"tenant_id": tenant_id, "status": "active"},
                limit=_HOLD_PAGE_SIZE,
                offset=offset,
            )
            for hold in holds:
                hold_type = hold.get("resource_type") or ""
                if hold_type and hold_type != resource_type:
                    continue
                hold_subject = hold.get("subject_ref") or ""
                if subject_ref is not None and hold_subject and hold_subject != subject_ref:
                    continue
                return hold
            if len(holds) < _HOLD_PAGE_SIZE:
                return None
            offset += _HOLD_PAGE_SIZE

    # ═══════════════════════════════════════════════════════════════════════
    # RETENTION — policy retention_class over objects AND rows
    # ═══════════════════════════════════════════════════════════════════════

    def _retention_days(self, policy: StoragePolicy) -> Optional[int]:
        """None = never swept by this lifecycle (legal class is compliance-owned)."""
        if policy.retention_class == "legal":
            return None
        return self._standard_days()

    async def apply_retention(
        self, resource_type: str = BRONZE_RESOURCE_TYPE, *, now: Optional[datetime] = None,
    ) -> dict:
        """Age out one resource type per its registry policy, across stores.

        Returns a report dict; every skip (legal class, preserve behavior,
        active hold) is explicit and counted, never silent.
        """
        policy = self.manager.policy_for(resource_type)  # KeyError if unknown
        report: dict[str, Any] = {
            "resource_type": resource_type,
            "delete_behavior": policy.delete_behavior,
            "objects_deleted": 0,
            "objects_tombstoned": 0,
            "rows_deleted": 0,
            "rows_tombstoned": 0,
            "held": 0,
            "skipped": None,
        }
        days = self._retention_days(policy)
        if days is None:
            report["skipped"] = "retention_class=legal is compliance-owned"
            return report
        if policy.delete_behavior == "preserve":
            report["skipped"] = "delete_behavior=preserve is never swept"
            return report

        cutoff = (now or utc_now()) - timedelta(days=days)

        # -- externalized objects (descriptor index drives the scan) ----------
        # Snapshot ids first (paged to exhaustion), THEN mutate: deleting while
        # offset-paging the same filter would skip entries.
        for descriptor_row in await self._all_descriptors(resource_type):
            if descriptor_row.get("tombstoned"):
                continue
            if not await self._descriptor_expired(descriptor_row, resource_type, cutoff):
                continue
            tenant_id = str(descriptor_row.get("tenant_id") or "")
            if await self.active_hold(tenant_id, resource_type):
                report["held"] += 1
                metrics.increment("storage_lifecycle_legal_hold_blocked_total")
                continue
            await self._remove_descriptor_scope(
                descriptor_row, policy.delete_behavior, resource_type, report
            )

        # -- hot rows that were never externalized (Bronze only) --------------
        # Snapshot to exhaustion first (offset paging BEFORE mutation), so one
        # retention pass covers every expired row instead of the first page.
        if resource_type == BRONZE_RESOURCE_TYPE:
            expired: list[dict] = []
            offset = 0
            while True:
                page = await self.rows.expired_unexternalized(
                    cutoff, limit=_SUBJECT_ROW_PAGE_SIZE, offset=offset
                )
                expired.extend(page)
                if len(page) < _SUBJECT_ROW_PAGE_SIZE:
                    break
                offset += _SUBJECT_ROW_PAGE_SIZE
            by_tenant: dict[str, list[str]] = {}
            for row in expired:
                by_tenant.setdefault(str(row.get("tenant_id") or ""), []).append(
                    str(row.get("id"))
                )
            for tenant_id, row_ids in sorted(by_tenant.items()):
                if await self.active_hold(tenant_id, resource_type):
                    report["held"] += 1
                    metrics.increment("storage_lifecycle_legal_hold_blocked_total")
                    continue
                if policy.delete_behavior == "hard_delete":
                    deleted = await self.rows.delete_rows(row_ids)
                    report["rows_deleted"] += deleted
                    metrics.increment(
                        "storage_lifecycle_retention_row_deleted_total", value=deleted
                    )
                else:
                    stubbed = await self.rows.tombstone_rows(row_ids)
                    report["rows_tombstoned"] += stubbed
                    metrics.increment(
                        "storage_lifecycle_retention_row_tombstoned_total", value=stubbed
                    )

        return report

    async def _all_descriptors(
        self, resource_type: Optional[str] = None, tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """Every matching descriptor row, paged to exhaustion.

        Mutating scans snapshot this list FIRST — deleting rows while
        offset-paging the same filter would skip every other page boundary.
        """
        filters: dict[str, Any] = {}
        if resource_type is not None:
            filters["resource_type"] = resource_type
        if tenant_id is not None:
            filters["tenant_id"] = tenant_id
        collected: list[dict] = []
        offset = 0
        while True:
            page = await self.descriptor_repo.find_many(
                filters=filters or None, limit=_DESCRIPTOR_PAGE_SIZE, offset=offset,
            )
            collected.extend(page)
            if len(page) < _DESCRIPTOR_PAGE_SIZE:
                return collected
            offset += _DESCRIPTOR_PAGE_SIZE

    async def _descriptor_expired(
        self, descriptor_row: Mapping[str, Any], resource_type: str, cutoff: datetime,
    ) -> bool:
        """True when everything a descriptor's object holds is past retention.

        The descriptor's own ``created_at`` is the COMPACTION time, not the
        data's age — aging by it would grant every packed payload a fresh
        retention window at compaction. For Bronze, age from the newest
        surviving source row (rows keep ``received_at``); the object expires
        only when its newest row is past the cutoff. Descriptors with no rows
        left (orphans after DSR/hard-delete) fall back to descriptor age.
        """
        if resource_type == BRONZE_RESOURCE_TYPE:
            descriptor_id = str(
                descriptor_row.get("descriptor_id") or descriptor_row.get("id") or ""
            )
            rows = (
                await self.rows.all_rows_for_descriptor(descriptor_id)
                if descriptor_id else []
            )
            if rows:
                return max(_row_age_stamp(r) for r in rows) <= cutoff
        return _parse_iso(descriptor_row.get("created_at")) <= cutoff

    async def _remove_descriptor_scope(
        self,
        descriptor_row: Mapping[str, Any],
        delete_behavior: str,
        resource_type: str,
        report: dict,
    ) -> None:
        """Apply delete_behavior to one descriptor + its object + its rows."""
        descriptor_id = str(
            descriptor_row.get("descriptor_id") or descriptor_row.get("id") or ""
        )
        locator = str(descriptor_row.get("locator") or "")
        if locator:
            self.object_store.delete(locator)  # bytes go in BOTH behaviors

        row_ids: list[str] = []
        if resource_type == BRONZE_RESOURCE_TYPE and descriptor_id:
            rows = await self.rows.all_rows_for_descriptor(descriptor_id)
            row_ids = [str(r.get("id")) for r in rows]

        if delete_behavior == "hard_delete":
            if row_ids:
                deleted = await self.rows.delete_rows(row_ids)
                report["rows_deleted"] += deleted
                metrics.increment(
                    "storage_lifecycle_retention_row_deleted_total", value=deleted
                )
            if descriptor_id:
                await self.descriptor_repo.delete(descriptor_id)
            report["objects_deleted"] += 1
            metrics.increment("storage_lifecycle_retention_object_deleted_total")
        else:  # tombstone — retain structural stubs, remove data
            if row_ids:
                stubbed = await self.rows.tombstone_rows(row_ids)
                report["rows_tombstoned"] += stubbed
                metrics.increment(
                    "storage_lifecycle_retention_row_tombstoned_total", value=stubbed
                )
            if descriptor_id:
                await self.descriptor_repo.update(
                    descriptor_id,
                    {
                        **dict(descriptor_row),
                        "tombstoned": True,
                        "tombstoned_at": utc_now().isoformat(),
                    },
                )
            report["objects_tombstoned"] += 1
            metrics.increment("storage_lifecycle_retention_object_tombstoned_total")

    async def apply_retention_sweep(self) -> dict:
        """Retention pass over every resource type with externalized objects
        (plus the Bronze row store). Called by the retention worker."""
        resource_types = {BRONZE_RESOURCE_TYPE}
        for descriptor_row in await self._all_descriptors():
            if descriptor_row.get("resource_type"):
                resource_types.add(str(descriptor_row["resource_type"]))
        combined: dict[str, Any] = {}
        for resource_type in sorted(resource_types):
            try:
                combined[resource_type] = await self.apply_retention(resource_type)
            except Exception as exc:
                metrics.increment("storage_lifecycle_sweep_error_total")
                logger.error(
                    f"Storage lifecycle retention failed for {resource_type!r}: {exc}"
                )
                combined[resource_type] = {"error": f"{type(exc).__name__}: {exc}"}
        return combined

    # ═══════════════════════════════════════════════════════════════════════
    # DSR — subject erasure across row store + object store + descriptors
    # ═══════════════════════════════════════════════════════════════════════

    async def dsr_erase_subject(
        self,
        tenant_id: str,
        subject_ref: str,
        resource_type: str = BRONZE_RESOURCE_TYPE,
    ) -> dict:
        """Erase one data subject across all three stores.

        Hot rows are removed per the policy delete_behavior; every packed
        object containing the subject is re-packed WITHOUT the subject (or
        deleted outright when nothing else remains). Active legal holds
        covering the subject block the whole request with NO mutation.
        """
        if not tenant_id:
            raise ValueError("dsr_erase_subject requires a tenant_id")
        if not subject_ref:
            raise ValueError("dsr_erase_subject requires a subject_ref")
        policy = self.manager.policy_for(resource_type)  # KeyError if unknown

        hold = await self.active_hold(tenant_id, resource_type, subject_ref)
        if hold is not None:
            metrics.increment("storage_lifecycle_legal_hold_blocked_total")
            logger.warning(
                f"DSR erasure blocked by legal hold {hold.get('hold_id')!r} "
                f"tenant={tenant_id} subject={subject_ref}"
            )
            return {
                "status": "blocked_legal_hold",
                "hold_id": hold.get("hold_id"),
                "reason": hold.get("reason"),
                "rows_removed": 0,
                "packed_records_removed": 0,
                "objects_repacked": 0,
                "objects_deleted": 0,
            }

        report: dict[str, Any] = {
            "status": "completed",
            "delete_behavior": policy.delete_behavior,
            "rows_removed": 0,
            "packed_records_removed": 0,
            "objects_repacked": 0,
            "objects_deleted": 0,
        }

        # 1. Row store — subject rows (hot payloads AND externalized metadata).
        # Loop to exhaustion: one capped fetch would leave a high-volume
        # subject partially erased while the request reports completed. Each
        # pass mutates the batch (hard_delete removes rows; tombstone strips
        # the subject identifiers), so the next fetch converges to empty.
        if resource_type == BRONZE_RESOURCE_TYPE:
            for _ in range(_MAX_ERASE_PASSES):
                subject_rows = await self.rows.rows_for_subject(
                    tenant_id, subject_ref, limit=_SUBJECT_ROW_PAGE_SIZE
                )
                if not subject_rows:
                    break
                row_ids = [str(r.get("id")) for r in subject_rows]
                if policy.delete_behavior == "hard_delete":
                    mutated = await self.rows.delete_rows(row_ids)
                else:
                    mutated = await self.rows.tombstone_rows(row_ids)
                report["rows_removed"] += mutated
                if mutated == 0:  # no progress — bail rather than spin
                    logger.error(
                        f"DSR row erase made no progress tenant={tenant_id} "
                        f"subject={subject_ref} ({len(row_ids)} rows matched)"
                    )
                    report["status"] = "partial"
                    break

        # 2. Object store + descriptor index — re-pack without the subject.
        # Snapshot every descriptor first (paged to exhaustion) — a single
        # capped, newest-first fetch would skip older packed objects and
        # report completion while the subject's payload survives.
        descriptors = await self._all_descriptors(resource_type, tenant_id=tenant_id)
        for descriptor_row in descriptors:
            if descriptor_row.get("tombstoned"):
                continue
            descriptor = StorageDescriptor.from_dict(descriptor_row)
            records = await self.manager.hydrate(descriptor)  # checksum verified
            if not isinstance(records, list):
                continue  # raw-bytes objects carry no per-subject records
            keep = [r for r in records if not _record_matches_subject(r, subject_ref)]
            removed = len(records) - len(keep)
            if removed == 0:
                continue

            superseded_by = ""
            if keep:
                new_descriptor = await self.manager.externalize(
                    resource_type,
                    tenant_id,
                    keep,
                    lineage=[descriptor.descriptor_id],
                )
                await self.rows.repoint_descriptor(
                    descriptor.descriptor_id,
                    new_descriptor.descriptor_id,
                    new_descriptor.locator,
                )
                superseded_by = new_descriptor.descriptor_id
                report["objects_repacked"] += 1
                metrics.increment("storage_lifecycle_dsr_objects_repacked_total")
            else:
                report["objects_deleted"] += 1

            self.object_store.delete(descriptor.locator)
            if policy.delete_behavior == "hard_delete":
                await self.descriptor_repo.delete(descriptor.descriptor_id)
            else:
                await self.descriptor_repo.update(
                    descriptor.descriptor_id,
                    {
                        **dict(descriptor_row),
                        "tombstoned": True,
                        "tombstoned_at": utc_now().isoformat(),
                        "superseded_by": superseded_by,
                    },
                )
            report["packed_records_removed"] += removed

        erased = report["rows_removed"] + report["packed_records_removed"]
        if erased:
            metrics.increment(
                "storage_lifecycle_dsr_records_erased_total", value=erased
            )
        logger.info(
            f"DSR erasure completed tenant={tenant_id} subject={subject_ref} "
            f"rows={report['rows_removed']} packed={report['packed_records_removed']} "
            f"repacked={report['objects_repacked']} deleted={report['objects_deleted']}"
        )
        return report


class ExternalizedBronzeDSRAdapter:
    """Adapter matching the ``delete_by_entity(field, entity_id)`` protocol
    that shared/privacy/retention.py's DeletionPlan dispatches hard_delete
    steps through — wire it under the ``object_store:bronze_sdk_events`` key
    to make DSAR cascades reach externalized Bronze objects."""

    def __init__(self, tenant_id: str, lifecycle: Optional[StorageLifecycle] = None) -> None:
        self.tenant_id = tenant_id
        self.lifecycle = lifecycle or StorageLifecycle()

    async def delete_by_entity(self, entity_field: str, entity_id: str) -> int:
        report = await self.lifecycle.dsr_erase_subject(self.tenant_id, entity_id)
        if report.get("status") == "blocked_legal_hold":
            # Surface the block as a failed step (reason preserved) instead of
            # silently reporting zero deletions.
            raise LegalHoldActiveError(
                f"legal hold {report.get('hold_id')!r} blocks erasure of "
                f"{entity_id!r}: {report.get('reason')}"
            )
        return int(report.get("rows_removed", 0)) + int(
            report.get("packed_records_removed", 0)
        )
