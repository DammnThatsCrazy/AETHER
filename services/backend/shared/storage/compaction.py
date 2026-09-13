"""
Aether Shared — Object-Backed Bronze Compaction (FT-8-OBJECT-BACKED-BRONZE)

Packs COLD Bronze payload batches into externalized objects while the hot,
searchable metadata stays in Postgres forever:

  - ``BronzeRowStore``       dual-backend accessor for the typed
                             ``bronze_sdk_events`` table (asyncpg in prod, the
                             shared in-memory store locally — same idiom as
                             services/ingestion/bronze_bulk.py).
  - ``BronzeObjectCompactor``the compaction sweep + historical read routing.

Compaction contract:

  * Only rows older than the age threshold
    (``BRONZE_COMPACTION_MIN_AGE_HOURS``) whose payload has not already been
    externalized are candidates.
  * Candidates are packed PER TENANT through
    ``StorageManager.externalize("bronze_sdk_events", ...)`` — the policy
    registry (codec/format/allow_object_externalization) and the master
    ``STORAGE_EXTERNALIZATION_ENABLED`` flag are both enforced there.
  * Each packed record carries ``bronze_id`` plus the subject identifiers
    (``user_id`` / ``anonymous_id`` / ``entity_id``) so historical routing can
    address a single row's payload and the DSR lifecycle can re-pack an object
    WITHOUT a subject without consulting deleted hot rows.
  * After the object + descriptor are durable, the hot rows are stripped:
    ``payload`` becomes ``{}``, ``payload_externalized`` flips true, and
    ``payload_descriptor_id`` / ``payload_locator`` point at the descriptor.
    Every typed searchable column (event ids, types, timestamps, session /
    anonymous / user / entity ids, payload_hash) is KEPT — searchable metadata
    is never deleted by compaction.
  * Ordering is crash-safe for data: externalize first, strip second. A crash
    between the two leaves rows hot (payload still in Postgres) plus one
    descriptor-indexed object nobody references — duplicate storage, never
    data loss; the retention lifecycle ages the stray object out.

Historical routing (``read_payload``): a read that hits an externalized row
resolves the descriptor, hydrates the object through
``StorageManager.hydrate`` (sha256 verified — ``ChecksumMismatchError`` on any
drift), and returns that row's payload from the packed records.

Flag-gated, default OFF: the sweep no-ops unless BOTH
``BRONZE_OBJECT_COMPACTION_ENABLED`` and ``STORAGE_EXTERNALIZATION_ENABLED``
are true (see config/settings.py StoragePlaneConfig).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from shared.storage.descriptor import StorageDescriptor
from shared.storage.manager import StorageManager

logger = get_logger("aether.storage.compaction")

BRONZE_RESOURCE_TYPE = "bronze_sdk_events"
_BRONZE_TABLE = "bronze_sdk_events"

# Identifier fields a packed record carries so DSR re-pack can match a data
# subject without the (already deleted) hot rows.
SUBJECT_FIELDS = ("user_id", "anonymous_id", "entity_id")


class BronzePayloadUnavailableError(KeyError):
    """An externalized row's payload cannot be resolved (descriptor missing,
    tombstoned by the lifecycle, or the row is absent from the packed object)."""


def _payload_dict(value: Any) -> dict:
    """Coerce a Bronze ``payload`` column value to a dict.

    The asyncpg pool registers no jsonb codec, so PG fetches return jsonb
    columns as JSON **strings** (the in-memory backend stores real dicts).
    ``dict()`` on a string raises ValueError — decode first.
    """
    if isinstance(value, str):
        import json

        return json.loads(value) if value else {}
    return dict(value or {})


def _parse_iso(value: Any) -> datetime:
    """Parse an ISO8601 string (Z or offset) into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _row_age_stamp(row: Mapping[str, Any]) -> datetime:
    """The timestamp compaction/retention ages a Bronze row by."""
    return _parse_iso(row.get("received_at") or row.get("created_at"))


# ═══════════════════════════════════════════════════════════════════════════
# BRONZE ROW STORE — typed bronze_sdk_events access (PostgreSQL / in-memory)
# ═══════════════════════════════════════════════════════════════════════════

class BronzeRowStore:
    """Set-based access to the typed ``bronze_sdk_events`` table.

    PostgreSQL statements keep the typed columns AND the ``data`` JSONB
    envelope in lockstep (BaseRepository filters read ``data->>'key'``); the
    in-memory backend mutates the shared ``_IN_MEMORY_STORES`` dicts so the
    full lifecycle is testable without a database.
    """

    def __init__(self, table: str = _BRONZE_TABLE) -> None:
        self.table = table

    # -- backends -------------------------------------------------------------

    async def _pool(self) -> Any:
        from repositories.repos import get_pool  # lazy — mirrors bronze_bulk

        return await get_pool()

    def _memory(self) -> dict:
        # Resolved on every call so suites that evict and re-import
        # repositories.repos always see the current generation's store.
        from repositories.repos import _IN_MEMORY_STORES

        return _IN_MEMORY_STORES.setdefault(self.table, {})

    # -- selection ------------------------------------------------------------

    async def compaction_candidates(
        self, cutoff: datetime, limit: int, offset: int = 0,
    ) -> list[dict]:
        """Typed V2 rows with a hot payload older than ``cutoff``.

        SCOPED TO TYPED ROWS (``event_id`` + typed ``payload`` populated by the
        V2 transactional path). Legacy V1 BaseRepository rows keep their raw
        event only inside ``data->'payload'`` with every typed column NULL —
        packing them would externalize ``{}`` and mark_externalized would then
        overwrite ``data.payload``, destroying the original record. They are
        excluded here and keep their hot payloads (their erasure runs through
        the legacy DSAR postgresql steps, unchanged by FT-8).
        """
        pool = await self._pool()
        if pool is None:
            rows = [
                dict(r) for r in self._memory().values()
                if not r.get("payload_externalized")
                and not r.get("tombstoned")
                and r.get("event_id")  # typed V2 rows only (see docstring)
                and r.get("payload") is not None
                and _row_age_stamp(r) <= cutoff
            ]
            rows.sort(key=_row_age_stamp)
            return rows[offset:offset + limit]
        records = await pool.fetch(
            f"""
            SELECT id, tenant_id, event_id, user_id, anonymous_id, entity_id,
                   payload, received_at
            FROM {self.table}
            WHERE COALESCE(payload_externalized, FALSE) = FALSE
              AND event_id IS NOT NULL
              AND payload IS NOT NULL
              AND COALESCE(received_at, created_at) <= $1
              AND COALESCE(data->>'tombstoned', 'false') <> 'true'
            ORDER BY COALESCE(received_at, created_at)
            LIMIT $2 OFFSET $3
            """,
            cutoff, limit, offset,
        )
        return [dict(r) for r in records]

    async def expired_unexternalized(
        self, cutoff: datetime, limit: int = 10_000, offset: int = 0,
    ) -> list[dict]:
        """Never-externalized typed rows older than the retention cutoff."""
        return await self.compaction_candidates(cutoff, limit, offset)

    async def rows_for_descriptor(
        self, descriptor_id: str, limit: int = 10_000, offset: int = 0,
    ) -> list[dict]:
        """Rows whose externalized payload lives under one descriptor."""
        pool = await self._pool()
        if pool is None:
            matched = [
                dict(r) for r in self._memory().values()
                if r.get("payload_descriptor_id") == descriptor_id
            ]
            return matched[offset:offset + limit]
        records = await pool.fetch(
            f"SELECT data FROM {self.table} "
            "WHERE payload_descriptor_id = $1 LIMIT $2 OFFSET $3",
            descriptor_id, limit, offset,
        )
        return [self._decode_data(r) for r in records]

    async def all_rows_for_descriptor(
        self, descriptor_id: str, page_size: int = 10_000,
    ) -> list[dict]:
        """Every row under one descriptor, paged to exhaustion.

        Lifecycle mutations (expiry decisions, descriptor-scope removal, the
        stale-pack rebuild) MUST see the full row set — one capped page would
        strand rows pointing at a deleted/tombstoned descriptor when a pack
        holds more rows than the page.
        """
        collected: list[dict] = []
        offset = 0
        while True:
            page = await self.rows_for_descriptor(descriptor_id, page_size, offset)
            collected.extend(page)
            if len(page) < page_size:
                return collected
            offset += page_size

    async def rows_for_subject(
        self, tenant_id: str, subject_ref: str, limit: int = 10_000,
    ) -> list[dict]:
        """Rows belonging to a data subject (user / anonymous / entity match)."""
        pool = await self._pool()
        if pool is None:
            return [
                dict(r) for r in self._memory().values()
                if r.get("tenant_id") == tenant_id
                and not r.get("tombstoned")
                and any(r.get(f) == subject_ref for f in SUBJECT_FIELDS if r.get(f))
            ][:limit]
        records = await pool.fetch(
            f"""
            SELECT data FROM {self.table}
            WHERE tenant_id = $1
              AND (user_id = $2 OR anonymous_id = $2 OR entity_id = $2)
              AND COALESCE(data->>'tombstoned', 'false') <> 'true'
            LIMIT $3
            """,
            tenant_id, subject_ref, limit,
        )
        return [self._decode_data(r) for r in records]

    @staticmethod
    def _decode_data(record: Any) -> dict:
        import json

        data = record["data"]
        return json.loads(data) if isinstance(data, str) else dict(data)

    # -- mutation ---------------------------------------------------------------

    async def mark_externalized(
        self, row_ids: Sequence[str], descriptor_id: str, locator: str,
    ) -> int:
        """Strip the hot payload; keep every searchable metadata column.

        Rows deleted, tombstoned, or ALREADY EXTERNALIZED since selection (a
        concurrent DSR/retention pass, or another compaction worker that won
        the race for the same cold rows) are NOT marked — the returned count
        falling short of ``len(row_ids)`` is the compactor's race signal to
        rebuild its packed object without the contested rows (see
        ``compact_once``). Without the already-externalized guard, the losing
        worker would silently re-point rows at its own pack and orphan the
        winner's object as an unreferenced duplicate payload copy.
        """
        if not row_ids:
            return 0
        now_iso = utc_now().isoformat()
        pool = await self._pool()
        if pool is None:
            store = self._memory()
            marked = 0
            for rid in row_ids:
                row = store.get(rid)
                if row is None or row.get("tombstoned") or row.get("payload_externalized"):
                    continue
                row["payload"] = {}
                row["payload_externalized"] = True
                row["payload_descriptor_id"] = descriptor_id
                row["payload_locator"] = locator
                row["updated_at"] = now_iso
                marked += 1
            return marked
        result = await pool.execute(
            f"""
            UPDATE {self.table}
            SET payload = '{{}}'::jsonb,
                payload_externalized = TRUE,
                payload_descriptor_id = $2,
                data = data || jsonb_build_object(
                    'payload', '{{}}'::jsonb,
                    'payload_externalized', true,
                    'payload_descriptor_id', $2::text,
                    'payload_locator', $3::text),
                updated_at = now()
            WHERE id = ANY($1)
              AND COALESCE(data->>'tombstoned', 'false') <> 'true'
              AND COALESCE(payload_externalized, FALSE) = FALSE
            """,
            list(row_ids), descriptor_id, locator,
        )
        return _rowcount(result)

    async def repoint_descriptor(
        self, old_descriptor_id: str, new_descriptor_id: str, new_locator: str,
    ) -> int:
        """Re-point surviving rows after a DSR re-pack replaced their object."""
        pool = await self._pool()
        if pool is None:
            store = self._memory()
            moved = 0
            now_iso = utc_now().isoformat()
            for row in store.values():
                if row.get("payload_descriptor_id") == old_descriptor_id:
                    row["payload_descriptor_id"] = new_descriptor_id
                    row["payload_locator"] = new_locator
                    row["updated_at"] = now_iso
                    moved += 1
            return moved
        result = await pool.execute(
            f"""
            UPDATE {self.table}
            SET payload_descriptor_id = $2,
                data = data || jsonb_build_object(
                    'payload_descriptor_id', $2::text,
                    'payload_locator', $3::text),
                updated_at = now()
            WHERE payload_descriptor_id = $1
            """,
            old_descriptor_id, new_descriptor_id, new_locator,
        )
        return _rowcount(result)

    async def delete_rows(self, row_ids: Sequence[str]) -> int:
        """hard_delete semantics: rows are removed entirely."""
        if not row_ids:
            return 0
        pool = await self._pool()
        if pool is None:
            store = self._memory()
            return sum(1 for rid in row_ids if store.pop(rid, None) is not None)
        result = await pool.execute(
            f"DELETE FROM {self.table} WHERE id = ANY($1)", list(row_ids)
        )
        return _rowcount(result)

    async def tombstone_rows(self, row_ids: Sequence[str]) -> int:
        """tombstone semantics: structure retained, payload + subject
        identifiers cleared, ``tombstoned`` flag set."""
        if not row_ids:
            return 0
        now_iso = utc_now().isoformat()
        pool = await self._pool()
        if pool is None:
            store = self._memory()
            marked = 0
            for rid in row_ids:
                row = store.get(rid)
                if row is None:
                    continue
                row["payload"] = {}
                row["user_id"] = None
                row["anonymous_id"] = ""
                row["entity_id"] = ""
                row["session_id"] = ""
                row["tombstoned"] = True
                row["tombstoned_at"] = now_iso
                row["updated_at"] = now_iso
                marked += 1
            return marked
        result = await pool.execute(
            f"""
            UPDATE {self.table}
            SET payload = '{{}}'::jsonb,
                user_id = NULL, anonymous_id = '', entity_id = '', session_id = '',
                data = data || jsonb_build_object(
                    'payload', '{{}}'::jsonb,
                    'user_id', NULL,
                    'anonymous_id', '',
                    'entity_id', '',
                    'session_id', '',
                    'tombstoned', true,
                    'tombstoned_at', $2::text),
                updated_at = now()
            WHERE id = ANY($1)
            """,
            list(row_ids), now_iso,
        )
        return _rowcount(result)


def _rowcount(execute_result: Any) -> int:
    """Parse asyncpg's ``UPDATE n`` / ``DELETE n`` status string."""
    try:
        return int(str(execute_result).rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# COMPACTOR — pack cold payloads, route historical reads
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CompactionStats:
    """Outcome of one ``compact_once`` pass."""

    enabled: bool = True
    candidates: int = 0
    rows_externalized: int = 0
    objects_written: int = 0
    descriptor_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class BronzeObjectCompactor:
    """Flag-gated compaction sweep + historical payload routing for Bronze."""

    def __init__(
        self,
        manager: Optional[StorageManager] = None,
        row_store: Optional[BronzeRowStore] = None,
        *,
        batch_size: Optional[int] = None,
        min_age_hours: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.manager = manager or StorageManager()
        self.rows = row_store or BronzeRowStore()
        self._batch_size = batch_size
        self._min_age_hours = min_age_hours
        self._enabled_override = enabled

    # -- flags / tuning (read at call time so tests and ops see live values) --

    def _storage_plane(self) -> Any:
        from config.settings import settings  # lazy — avoids import cycles

        return settings.storage_plane

    def _enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        plane = self._storage_plane()
        return bool(plane.bronze_compaction_enabled and plane.externalization_enabled)

    @property
    def batch_size(self) -> int:
        if self._batch_size is not None:
            return self._batch_size
        return int(self._storage_plane().bronze_compaction_batch_size)

    @property
    def min_age_hours(self) -> int:
        if self._min_age_hours is not None:
            return self._min_age_hours
        return int(self._storage_plane().bronze_compaction_min_age_hours)

    # -- compaction sweep -----------------------------------------------------

    @staticmethod
    def _packed_record(row: Mapping[str, Any]) -> dict:
        """One packed jsonl record: row identity + subject ids + payload."""
        return {
            "bronze_id": row.get("id", ""),
            "event_id": row.get("event_id", ""),
            "user_id": row.get("user_id"),
            "anonymous_id": row.get("anonymous_id", ""),
            "entity_id": row.get("entity_id", ""),
            "payload": _payload_dict(row.get("payload")),
        }

    async def compact_once(self) -> CompactionStats:
        """Pack one batch of cold Bronze rows into per-tenant objects.

        No-ops (returns ``enabled=False``) unless both the compaction flag and
        the master externalization flag are on. Externalize-then-strip ordering
        makes a mid-sweep crash storage-duplicating, never data-losing.
        """
        if not self._enabled():
            return CompactionStats(enabled=False)

        cutoff = utc_now() - timedelta(hours=self.min_age_hours)
        candidates = await self.rows.compaction_candidates(cutoff, self.batch_size)
        stats = CompactionStats(candidates=len(candidates))
        metrics.increment("storage_bronze_compaction_run_total")
        if not candidates:
            return stats

        by_tenant: dict[str, list[dict]] = {}
        for row in candidates:
            by_tenant.setdefault(str(row.get("tenant_id") or ""), []).append(row)

        for tenant_id, tenant_rows in sorted(by_tenant.items()):
            row_ids = [str(r.get("id")) for r in tenant_rows]
            try:
                descriptor = await self.manager.externalize(
                    BRONZE_RESOURCE_TYPE,
                    tenant_id,
                    [self._packed_record(r) for r in tenant_rows],
                    lineage=row_ids,
                )
                marked = await self.rows.mark_externalized(
                    row_ids, descriptor.descriptor_id, descriptor.locator
                )
                if marked != len(row_ids):
                    # Race: a DSR/retention pass deleted or tombstoned some
                    # candidates between selection and mark. The object just
                    # written still contains THEIR payloads — rebuild it from
                    # the rows that actually got marked so an erased subject's
                    # data never survives inside a packed object.
                    descriptor, marked = await self._rebuild_stale_pack(
                        tenant_id, descriptor, tenant_rows
                    )
                    metrics.increment("storage_bronze_compaction_stale_rebuild_total")
                    if descriptor is None:  # nothing survived — pack dropped
                        continue
            except Exception as exc:  # per-tenant failure — other tenants proceed
                stats.errors.append(f"{tenant_id}: {type(exc).__name__}: {exc}")
                logger.error(
                    f"Bronze compaction failed for tenant={tenant_id}: {exc}"
                )
                continue
            stats.objects_written += 1
            stats.rows_externalized += marked
            stats.descriptor_ids.append(descriptor.descriptor_id)
            logger.info(
                f"Bronze compaction packed tenant={tenant_id} rows={marked} "
                f"descriptor={descriptor.descriptor_id} locator={descriptor.locator}"
            )

        if stats.rows_externalized:
            metrics.increment(
                "storage_bronze_rows_externalized_total", value=stats.rows_externalized
            )
        return stats

    async def _rebuild_stale_pack(
        self,
        tenant_id: str,
        stale_descriptor: Any,
        candidate_rows: Sequence[Mapping[str, Any]],
    ) -> tuple[Any, int]:
        """Replace a just-written pack that contains rows erased mid-sweep.

        ``mark_externalized`` marking fewer rows than were packed means a
        concurrent DSR/retention pass removed candidates AFTER the object was
        written. The survivors are exactly the rows now pointing at the stale
        descriptor; re-pack only them (payloads come from the still-in-memory
        candidates), re-point, then drop the stale object + descriptor so the
        erased data does not persist in object storage.

        Returns ``(new_descriptor, survivor_count)`` — ``(None, 0)`` when no
        row survived and the pack was simply dropped.
        """
        survivors = await self.rows.all_rows_for_descriptor(stale_descriptor.descriptor_id)
        survivor_ids = {str(r.get("id")) for r in survivors}
        repack_rows = [r for r in candidate_rows if str(r.get("id")) in survivor_ids]

        new_descriptor = None
        if repack_rows:
            new_descriptor = await self.manager.externalize(
                BRONZE_RESOURCE_TYPE,
                tenant_id,
                [self._packed_record(r) for r in repack_rows],
                lineage=[str(r.get("id")) for r in repack_rows],
            )
            await self.rows.repoint_descriptor(
                stale_descriptor.descriptor_id,
                new_descriptor.descriptor_id,
                new_descriptor.locator,
            )

        self.manager.object_store.delete(stale_descriptor.locator)
        await self.manager.descriptor_repo.delete(stale_descriptor.descriptor_id)
        logger.warning(
            f"Bronze compaction rebuilt stale pack tenant={tenant_id} "
            f"stale={stale_descriptor.descriptor_id} survivors={len(repack_rows)}"
        )
        return new_descriptor, len(repack_rows)

    # -- historical routing -----------------------------------------------------

    async def read_payload(self, row: Mapping[str, Any]) -> dict:
        """Return a Bronze row's payload, hydrating from the object store when
        the hot payload was externalized.

        Raises ``BronzePayloadUnavailableError`` (a KeyError) when the
        descriptor is missing/tombstoned or the row is absent from the packed
        object, and propagates ``ChecksumMismatchError`` from hydration.
        """
        if not row.get("payload_externalized"):
            metrics.increment("storage_bronze_payload_route_hot_total")
            return _payload_dict(row.get("payload"))

        descriptor_id = str(row.get("payload_descriptor_id") or "")
        descriptor_row = (
            await self.manager.descriptor_repo.find_by_id(descriptor_id)
            if descriptor_id else None
        )
        if descriptor_row is None:
            raise BronzePayloadUnavailableError(
                f"Bronze row {row.get('id')!r} is externalized but descriptor "
                f"{descriptor_id!r} does not exist"
            )
        if descriptor_row.get("tombstoned"):
            raise BronzePayloadUnavailableError(
                f"Bronze row {row.get('id')!r} payload was removed by the "
                f"storage lifecycle (descriptor {descriptor_id!r} tombstoned)"
            )

        descriptor = StorageDescriptor.from_dict(descriptor_row)
        records = await self.manager.hydrate(descriptor)  # checksum verified
        row_id = row.get("id")
        for record in records if isinstance(records, list) else []:
            if record.get("bronze_id") == row_id:
                metrics.increment("storage_bronze_payload_route_hydrated_total")
                return _payload_dict(record.get("payload"))
        raise BronzePayloadUnavailableError(
            f"Bronze row {row_id!r} not present in object {descriptor.locator!r}"
        )
