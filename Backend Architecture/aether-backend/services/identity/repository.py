"""Persistence layer for the identity resolution subsystem.

All queries are tenant-scoped. Sensitive alias values are stored as hashes.
Merge and split events are append-only. Audit records are append-only.

Uses the same BaseRepository JSONB pattern as the rest of the backend
(local=in-memory, production=asyncpg/PostgreSQL).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from repositories.repos import BaseRepository

from .models import (
    ConfidenceTier,
    ConflictStatus,
    EdgeType,
    EntityType,
    IdentityAlias,
    IdentityCluster,
    IdentityConflict,
    IdentityEdge,
    IdentityMergeEvent,
    IdentityResolutionAuditRecord,
    IdentitySignalObservation,
    IdentitySignalType,
    IdentitySubject,
    IdentitySplitEvent,
    MergeDecision,
    SubjectStatus,
)


# ── Concrete table repositories ───────────────────────────────────────────────

class _IdentitySubjectStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_subjects")


class _IdentityAliasStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_aliases")


class _IdentitySignalObservationStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_signal_observations")


class _IdentityClusterStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_clusters_v2")


class _IdentityEdgeStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_edges")


class _IdentityMergeEventStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_merge_events")


class _IdentitySplitEventStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_split_events")


class _IdentityConflictStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_conflicts")


class _IdentityAuditStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_resolution_audit")


class _IdentitySuppressionStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("identity_suppression_rules")


# ── Main repository facade ────────────────────────────────────────────────────

class IdentityResolutionRepository:
    """Unified repository for all identity-resolution persistence operations."""

    def __init__(self) -> None:
        self._subjects = _IdentitySubjectStore()
        self._aliases = _IdentityAliasStore()
        self._observations = _IdentitySignalObservationStore()
        self._clusters = _IdentityClusterStore()
        self._edges = _IdentityEdgeStore()
        self._merges = _IdentityMergeEventStore()
        self._splits = _IdentitySplitEventStore()
        self._conflicts = _IdentityConflictStore()
        self._audit = _IdentityAuditStore()
        self._suppressions = _IdentitySuppressionStore()

    # ── Subjects ──────────────────────────────────────────────────────────

    async def create_subject(
        self,
        tenant_id: str,
        canonical_entity_id: str,
        entity_type: "EntityType | str" = EntityType.HUMAN,
        metadata: Optional[dict] = None,
    ) -> dict:
        now = utc_now().isoformat()
        subject_id = str(uuid.uuid4())
        etype = entity_type.value if isinstance(entity_type, EntityType) else str(entity_type)
        return await self._subjects.insert(subject_id, {
            "id": subject_id,
            "tenant_id": tenant_id,
            "canonical_entity_id": canonical_entity_id,
            "entity_type": etype,
            "status": SubjectStatus.ACTIVE.value,
            "first_seen_at": now,
            "last_seen_at": now,
            "metadata": metadata or {},
        })

    async def get_subject_by_canonical_entity_id(
        self, tenant_id: str, canonical_entity_id: str
    ) -> Optional[dict]:
        rows = await self._subjects.find_many(
            filters={"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            limit=1,
        )
        return rows[0] if rows else None

    async def update_subject_last_seen(self, subject_id: str) -> None:
        row = await self._subjects.find_by_id(subject_id)
        if row:
            row["last_seen_at"] = utc_now().isoformat()
            await self._subjects.update(subject_id, row)

    async def mark_subject_merged(self, subject_id: str, into_entity_id: str) -> None:
        """Tombstone a subject by ROW id. Deprecated for merge flows — callers
        merge by canonical entity id and must use
        :meth:`mark_subject_merged_by_canonical_id` instead (both resolver
        paths pass canonical ids, so a row-id lookup silently no-ops)."""
        row = await self._subjects.find_by_id(subject_id)
        if row:
            row["status"] = SubjectStatus.MERGED.value
            row["merged_into_entity_id"] = into_entity_id
            await self._subjects.update(subject_id, row)

    async def mark_subject_merged_by_canonical_id(
        self, tenant_id: str, canonical_entity_id: str, into_entity_id: str
    ) -> dict:
        """Tombstone the subject for a CANONICAL entity id (idempotent).

        This is what merge flows must call: both resolver call sites operate on
        canonical entity ids, not subject row ids. If no subject row exists for
        the merged entity (e.g. it was only ever an alias owner), a tombstone
        row is created so the merge is durably recorded and survivor-redirect
        can follow it.
        """
        row = await self.get_subject_by_canonical_entity_id(tenant_id, canonical_entity_id)
        if row is None:
            row = await self.create_subject(tenant_id, canonical_entity_id)
        row["status"] = SubjectStatus.MERGED.value
        row["merged_into_entity_id"] = into_entity_id
        return await self._subjects.update(row["id"], row)

    async def restore_subject(
        self,
        tenant_id: str,
        canonical_entity_id: str,
        entity_type: "EntityType | str" = EntityType.HUMAN,
    ) -> dict:
        """Reactivate (or create) an ACTIVE subject for a canonical entity.

        Used by fragment-aware identity repair when a split restores a
        pre-merge entity: the pre-merge subject may currently be tombstoned
        (``status == MERGED`` with ``merged_into_entity_id`` set). Restoring
        clears the tombstone so the entity is a live identity again. If no row
        exists yet, an active one is created. Tenant-scoped and idempotent.
        """
        row = await self.get_subject_by_canonical_entity_id(tenant_id, canonical_entity_id)
        if row is None:
            return await self.create_subject(tenant_id, canonical_entity_id, entity_type)
        row["status"] = SubjectStatus.ACTIVE.value
        row["merged_into_entity_id"] = None
        row["last_seen_at"] = utc_now().isoformat()
        return await self._subjects.update(row["id"], row)

    async def resolve_surviving_canonical_entity_id(
        self, tenant_id: str, canonical_entity_id: str, max_hops: int = 10
    ) -> str:
        """Follow merge tombstones to the surviving canonical entity id.

        Tenant-scoped, with a visited-set cycle guard and a hop bound so a
        corrupted chain can never loop forever. Returns the input id unchanged
        when the subject is active, missing, or has no ``merged_into_entity_id``.
        """
        current = canonical_entity_id
        visited: set[str] = set()
        for _ in range(max(1, max_hops)):
            if current in visited:
                break  # cycle — stop at the last safe id
            visited.add(current)
            row = await self.get_subject_by_canonical_entity_id(tenant_id, current)
            if row is None or row.get("status") != SubjectStatus.MERGED.value:
                return current
            nxt = row.get("merged_into_entity_id")
            if not nxt or nxt == current:
                return current
            current = nxt
        return current

    # ── Aliases ───────────────────────────────────────────────────────────

    @staticmethod
    def _alias_type_str(alias_type: "IdentitySignalType | str") -> str:
        return alias_type.value if isinstance(alias_type, IdentitySignalType) else str(alias_type)

    @staticmethod
    def _confidence_tier_str(tier: "ConfidenceTier | str") -> str:
        return tier.value if isinstance(tier, ConfidenceTier) else str(tier)

    async def find_aliases_by_signal(
        self,
        tenant_id: str,
        alias_type: "IdentitySignalType | str",
        alias_value_hash: str,
    ) -> list[dict]:
        rows = await self._aliases.find_many(
            filters={
                "tenant_id": tenant_id,
                "alias_type": self._alias_type_str(alias_type),
                "alias_value_hash": alias_value_hash,
            },
            limit=50,
        )
        # Exclude revoked aliases
        return [r for r in rows if not r.get("revoked_at")]

    async def find_entities_by_alias(
        self,
        tenant_id: str,
        alias_type: "IdentitySignalType | str",
        alias_value_hash: str,
    ) -> list[str]:
        """Return canonical entity IDs that own a given alias hash (tenant-scoped)."""
        aliases = await self.find_aliases_by_signal(tenant_id, alias_type, alias_value_hash)
        return list({a["canonical_entity_id"] for a in aliases})

    # Backwards-compat alias
    async def find_subjects_by_alias(
        self,
        tenant_id: str,
        alias_type: "IdentitySignalType | str",
        alias_value_hash: str,
    ) -> list[str]:
        return await self.find_entities_by_alias(tenant_id, alias_type, alias_value_hash)

    async def upsert_alias(
        self,
        tenant_id: str,
        canonical_entity_id: str,
        alias_type: "IdentitySignalType | str",
        alias_value_hash: str = "",
        alias_display_value_redacted: str = "",
        source: str = "",
        source_event_id: str = "",
        source_platform: str = "",
        confidence: float = 1.0,
        confidence_tier: "ConfidenceTier | str" = ConfidenceTier.DETERMINISTIC,
        consent_snapshot: Optional[dict] = None,
        # convenience alias used by tests
        alias_hash: str = "",
    ) -> dict:
        hash_val = alias_value_hash or alias_hash
        now = utc_now().isoformat()
        type_str = self._alias_type_str(alias_type)
        tier_str = self._confidence_tier_str(confidence_tier)

        # Check for existing active alias
        existing = await self.find_aliases_by_signal(tenant_id, alias_type, hash_val)
        for row in existing:
            if row["canonical_entity_id"] == canonical_entity_id:
                row["last_seen_at"] = now
                return await self._aliases.update(row["id"], row)

        alias_id = str(uuid.uuid4())
        return await self._aliases.insert(alias_id, {
            "id": alias_id,
            "tenant_id": tenant_id,
            "canonical_entity_id": canonical_entity_id,
            "alias_type": type_str,
            "alias_value_hash": hash_val,
            "alias_display_value_redacted": alias_display_value_redacted,
            "source": source,
            "source_event_id": source_event_id,
            "source_platform": source_platform,
            "confidence": confidence,
            "confidence_tier": tier_str,
            "consent_snapshot": consent_snapshot,
            "first_seen_at": now,
            "last_seen_at": now,
            "revoked_at": None,
        })

    async def get_alias_by_id(self, alias_id: str) -> Optional[dict]:
        """Fetch a single alias row by its id (raw, includes revoked).

        Returns the row unfiltered so callers (e.g. fragment-split validation)
        can inspect ``tenant_id`` / ``canonical_entity_id`` / ``revoked_at``
        directly and enforce their own tenant + ownership checks.
        """
        return await self._aliases.find_by_id(alias_id)

    async def revoke_alias(self, alias_id: str) -> Optional[dict]:
        row = await self._aliases.find_by_id(alias_id)
        if row is None or row.get("revoked_at"):
            return row
        row["revoked_at"] = utc_now().isoformat()
        return await self._aliases.update(alias_id, row)

    async def get_aliases_for_entity(
        self, tenant_id: str, canonical_entity_id: str, include_revoked: bool = False
    ) -> list[dict]:
        """Convenience alias for get_entity_aliases (tenant-scoped)."""
        return await self.get_entity_aliases(tenant_id, canonical_entity_id, include_revoked)

    async def get_subject_by_entity_id(
        self, tenant_id: str, canonical_entity_id: str
    ) -> Optional[dict]:
        """Find a subject record by tenant + canonical_entity_id."""
        return await self.get_subject_by_canonical_entity_id(tenant_id, canonical_entity_id)

    async def get_entity_aliases(
        self, tenant_id: str, canonical_entity_id: str, include_revoked: bool = False
    ) -> list[dict]:
        rows = await self._aliases.find_many(
            filters={"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            limit=500,
        )
        if not include_revoked:
            rows = [r for r in rows if not r.get("revoked_at")]
        return rows

    # ── Signal observations ───────────────────────────────────────────────

    async def create_signal_observation(
        self,
        tenant_id: str,
        source_event_id: str,
        source_platform: str,
        source_sdk: str,
        signal_type: IdentitySignalType,
        signal_value_hash: str,
        raw_value_redacted: str = "",
        observed_at: str = "",
        consent_snapshot: Optional[dict] = None,
        context: Optional[dict] = None,
        canonical_entity_id: Optional[str] = None,
    ) -> dict:
        obs_id = str(uuid.uuid4())
        now = utc_now().isoformat()
        return await self._observations.insert(obs_id, {
            "id": obs_id,
            "tenant_id": tenant_id,
            "canonical_entity_id": canonical_entity_id,
            "source_event_id": source_event_id,
            "source_platform": source_platform,
            "source_sdk": source_sdk,
            "signal_type": signal_type.value,
            # Written under both keys: `signal_hash` is the migration column name;
            # `signal_value_hash` preserves the historical JSONB key readers use.
            "signal_hash": signal_value_hash,
            "signal_value_hash": signal_value_hash,
            "raw_value_redacted": raw_value_redacted,
            "observed_at": observed_at or now,
            "consent_snapshot": consent_snapshot,
            "context": context or {},
        })

    async def set_observations_canonical_entity(
        self, tenant_id: str, source_event_id: str, canonical_entity_id: str
    ) -> int:
        """Link an event's persisted observations to the entity it resolved to.

        Observations are written before the canonical entity is known (signals
        are persisted at step 4, resolution happens at step 8), so the resolver
        calls this once the entity id is known. Without it,
        ``get_observations_for_entity`` (which filters on ``canonical_entity_id``)
        can never match and entity-scoped recompute is broken.
        """
        rows = await self._observations.find_many(
            filters={"tenant_id": tenant_id, "source_event_id": source_event_id},
            limit=500,
        )
        updated = 0
        for row in rows:
            if row.get("canonical_entity_id") == canonical_entity_id:
                continue
            row["canonical_entity_id"] = canonical_entity_id
            await self._observations.update(row["id"], row)
            updated += 1
        return updated

    async def get_observation_by_id(self, observation_id: str) -> Optional[dict]:
        """Fetch a single signal observation by its id (raw row)."""
        return await self._observations.find_by_id(observation_id)

    async def relink_observations_to_entity(
        self, tenant_id: str, observation_ids: list[str], canonical_entity_id: str
    ) -> list[str]:
        """Relink specific observations (by id) to a canonical entity.

        Unlike :meth:`set_observations_canonical_entity` (which relinks every
        observation of an *event*), this targets an explicit list of observation
        ids — the primitive fragment-aware identity repair needs to move only the
        observations named in a split fragment. Tenant-scoped and idempotent:
        rows already pointing at ``canonical_entity_id``, of another tenant, or
        not found are skipped. Returns the ids actually moved.
        """
        moved: list[str] = []
        for obs_id in observation_ids:
            row = await self._observations.find_by_id(obs_id)
            if row is None or row.get("tenant_id") != tenant_id:
                continue
            if row.get("canonical_entity_id") == canonical_entity_id:
                continue
            row["canonical_entity_id"] = canonical_entity_id
            await self._observations.update(obs_id, row)
            moved.append(obs_id)
        return moved

    # ── Clusters ──────────────────────────────────────────────────────────

    async def upsert_cluster(
        self,
        tenant_id: str,
        canonical_entity_id: str,
        confidence: float,
        reason_codes: list[str],
    ) -> dict:
        existing_rows = await self._clusters.find_many(
            filters={"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            limit=1,
        )
        now = utc_now().isoformat()

        if existing_rows:
            row = existing_rows[0]
            row["confidence"] = confidence
            row["reason_codes"] = reason_codes
            row["cluster_version"] = row.get("cluster_version", 1) + 1
            return await self._clusters.update(row["id"], row)

        cluster_id = str(uuid.uuid4())
        return await self._clusters.insert(cluster_id, {
            "id": cluster_id,
            "tenant_id": tenant_id,
            "canonical_entity_id": canonical_entity_id,
            "cluster_version": 1,
            "status": "active",
            "confidence": confidence,
            "reason_codes": reason_codes,
        })

    # ── Edges ─────────────────────────────────────────────────────────────

    async def create_identity_edge(
        self,
        tenant_id: str,
        source_entity_id: str,
        target_entity_id: str,
        edge_type: EdgeType,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        # Idempotency: find existing active edge
        existing = await self._edges.find_many(
            filters={
                "tenant_id": tenant_id,
                "source_entity_id": source_entity_id,
                "target_entity_id": target_entity_id,
                "edge_type": edge_type.value,
            },
            limit=1,
        )
        active = [r for r in existing if not r.get("revoked_at")]
        if active:
            return active[0]  # idempotent

        edge_id = str(uuid.uuid4())
        return await self._edges.insert(edge_id, {
            "id": edge_id,
            "tenant_id": tenant_id,
            "source_entity_id": source_entity_id,
            "target_entity_id": target_entity_id,
            "edge_type": edge_type.value,
            "confidence": confidence,
            "confidence_tier": confidence_tier.value,
            "reason_codes": reason_codes,
            "source_event_ids": source_event_ids,
            "consent_snapshot": consent_snapshot,
            "revoked_at": None,
        })

    async def revoke_identity_edge(self, edge_id: str) -> Optional[dict]:
        row = await self._edges.find_by_id(edge_id)
        if row is None or row.get("revoked_at"):
            return row
        row["revoked_at"] = utc_now().isoformat()
        return await self._edges.update(edge_id, row)

    async def get_entity_graph(
        self, tenant_id: str, canonical_entity_id: str
    ) -> list[dict]:
        as_source = await self._edges.find_many(
            filters={"tenant_id": tenant_id, "source_entity_id": canonical_entity_id},
            limit=200,
        )
        as_target = await self._edges.find_many(
            filters={"tenant_id": tenant_id, "target_entity_id": canonical_entity_id},
            limit=200,
        )
        seen: set[str] = set()
        result: list[dict] = []
        for e in (*as_source, *as_target):
            eid = e.get("id", "")
            if eid not in seen:
                seen.add(eid)
                result.append(e)
        return result

    async def revoke_edges_for_merge(
        self, tenant_id: str, from_entity_id: str, edge_type: EdgeType
    ) -> list[str]:
        edges = await self._edges.find_many(
            filters={
                "tenant_id": tenant_id,
                "source_entity_id": from_entity_id,
                "edge_type": edge_type.value,
            },
            limit=500,
        )
        revoked_ids: list[str] = []
        for e in edges:
            if not e.get("revoked_at"):
                await self.revoke_identity_edge(e["id"])
                revoked_ids.append(e["id"])
        return revoked_ids

    # ── Merge events (append-only) ────────────────────────────────────────

    async def create_merge_event(
        self,
        tenant_id: str,
        from_entity_id: str,
        into_entity_id: str,
        resulting_entity_id: str,
        confidence: float,
        confidence_tier: ConfidenceTier,
        reason_codes: list[str],
        source_event_ids: list[str],
        actor_type: str,
        actor_id: str,
    ) -> dict:
        merge_id = str(uuid.uuid4())
        return await self._merges.insert(merge_id, {
            "id": merge_id,
            "tenant_id": tenant_id,
            "from_entity_id": from_entity_id,
            "into_entity_id": into_entity_id,
            "resulting_entity_id": resulting_entity_id,
            "confidence": confidence,
            "confidence_tier": confidence_tier.value,
            "reason_codes": reason_codes,
            "source_event_ids": source_event_ids,
            "actor_type": actor_type,
            "actor_id": actor_id,
        })

    async def get_merge_event_by_id(
        self, tenant_id: str, merge_event_id: str
    ) -> Optional[dict]:
        """Fetch a merge event by id, tenant-scoped.

        Fragment-aware repair's ``restore_pre_merge_entity`` mode reads the
        merge event's ``from_entity_id`` to recover the pre-merge canonical
        entity id. Returns None if the event is missing or belongs to another
        tenant (never leak cross-tenant merge history).
        """
        row = await self._merges.find_by_id(merge_event_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return None
        return row

    async def get_merge_history(
        self, tenant_id: str, canonical_entity_id: str, limit: int = 50
    ) -> list[dict]:
        as_from = await self._merges.find_many(
            filters={"tenant_id": tenant_id, "from_entity_id": canonical_entity_id},
            limit=limit,
        )
        as_into = await self._merges.find_many(
            filters={"tenant_id": tenant_id, "into_entity_id": canonical_entity_id},
            limit=limit,
        )
        seen: set[str] = set()
        result: list[dict] = []
        for m in (*as_from, *as_into):
            mid = m.get("id", "")
            if mid not in seen:
                seen.add(mid)
                result.append(m)
        result.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return result[:limit]

    # ── Split events (append-only) ────────────────────────────────────────

    async def create_split_event(
        self,
        tenant_id: str,
        original_entity_id: str,
        resulting_entity_ids: list[str],
        reason: str,
        actor_type: str,
        actor_id: str,
        source_merge_event_id: Optional[str] = None,
        fragment: Optional[dict] = None,
        mode: Optional[str] = None,
    ) -> dict:
        """Append an immutable split event.

        ``fragment`` and ``mode`` are additive: fragment-aware identity repair
        records exactly which aliases/observations were moved and under which
        split mode so the operation is fully auditable and reversible. Both
        default to None, preserving the original (non-fragment) call sites.
        """
        split_id = str(uuid.uuid4())
        return await self._splits.insert(split_id, {
            "id": split_id,
            "tenant_id": tenant_id,
            "original_entity_id": original_entity_id,
            "resulting_entity_ids": resulting_entity_ids,
            "reason": reason,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "source_merge_event_id": source_merge_event_id,
            "fragment": fragment or {},
            "mode": mode,
        })

    async def get_split_history(
        self, tenant_id: str, canonical_entity_id: str, limit: int = 50
    ) -> list[dict]:
        return await self._splits.find_many(
            filters={"tenant_id": tenant_id, "original_entity_id": canonical_entity_id},
            limit=limit,
        )

    async def get_recent_merges(self, tenant_id: str, limit: int = 50) -> list[dict]:
        """All merge events for a tenant (no entity filter) — used for operator audit."""
        rows = await self._merges.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return rows[:limit]

    async def get_recent_splits(self, tenant_id: str, limit: int = 50) -> list[dict]:
        """All split events for a tenant (no entity filter) — used for operator audit."""
        rows = await self._splits.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return rows[:limit]

    # ── Conflicts ─────────────────────────────────────────────────────────

    async def create_conflict(
        self,
        tenant_id: str,
        candidate_entity_ids: list[str],
        candidate_aliases: list[dict],
        conflict_type: str,
        confidence: float,
        reason_codes: list[str],
    ) -> dict:
        conflict_id = str(uuid.uuid4())
        return await self._conflicts.insert(conflict_id, {
            "id": conflict_id,
            "tenant_id": tenant_id,
            "candidate_entity_ids": candidate_entity_ids,
            "candidate_aliases": candidate_aliases,
            "conflict_type": conflict_type,
            "confidence": confidence,
            "reason_codes": reason_codes,
            "status": ConflictStatus.OPEN.value,
            "resolved_at": None,
            "resolved_by": None,
        })

    async def get_conflicts(
        self,
        tenant_id: str,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if status:
            filters["status"] = status
        return await self._conflicts.find_many(filters=filters, limit=limit)

    async def resolve_conflict(
        self,
        conflict_id: str,
        resolved_by: str,
        tenant_id: str,
    ) -> Optional[dict]:
        row = await self._conflicts.find_by_id(conflict_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return None
        row["status"] = ConflictStatus.RESOLVED.value
        row["resolved_at"] = utc_now().isoformat()
        row["resolved_by"] = resolved_by
        return await self._conflicts.update(conflict_id, row)

    # ── Audit records (append-only) ───────────────────────────────────────

    async def create_audit_record(
        self,
        tenant_id: str,
        decision: str,
        canonical_entity_id: str,
        candidate_entity_ids: list[str],
        confidence: float,
        confidence_tier: "ConfidenceTier | str",
        reason_codes: list[str],
        source_event_ids: list[str],
        policy_result: str,
        consent_snapshot: Optional[dict] = None,
    ) -> dict:
        audit_id = str(uuid.uuid4())
        tier_str = self._confidence_tier_str(confidence_tier)
        return await self._audit.insert(audit_id, {
            "id": audit_id,
            "tenant_id": tenant_id,
            "decision": decision,
            "canonical_entity_id": canonical_entity_id,
            "candidate_entity_ids": candidate_entity_ids,
            "confidence": confidence,
            "confidence_tier": tier_str,
            "reason_codes": reason_codes,
            "source_event_ids": source_event_ids,
            "policy_result": policy_result,
            "consent_snapshot": consent_snapshot,
        })

    async def get_entity_audit(
        self, tenant_id: str, canonical_entity_id: str, limit: int = 100
    ) -> list[dict]:
        return await self._audit.find_many(
            filters={"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            limit=limit,
        )

    async def get_audit_for_entity(
        self, tenant_id: str, canonical_entity_id: str, limit: int = 100
    ) -> list[dict]:
        """Convenience alias for get_entity_audit."""
        return await self.get_entity_audit(tenant_id, canonical_entity_id, limit)

    # ── Signal observation lookups ────────────────────────────────────────

    async def get_observations_for_entity(
        self, tenant_id: str, canonical_entity_id: str, limit: int = 500
    ) -> list[dict]:
        return await self._observations.find_many(
            filters={"tenant_id": tenant_id, "canonical_entity_id": canonical_entity_id},
            limit=limit,
        )

    async def get_observations_for_events(
        self, tenant_id: str, event_ids: list[str], limit: int = 500
    ) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()
        for evt_id in event_ids[:50]:
            rows = await self._observations.find_many(
                filters={"tenant_id": tenant_id, "source_event_id": evt_id},
                limit=20,
            )
            for r in rows:
                rid = r.get("id", "")
                if rid not in seen:
                    seen.add(rid)
                    results.append(r)
        return results[:limit]

    # ── Suppression rules ─────────────────────────────────────────────────

    async def create_suppression_rule(
        self,
        tenant_id: str,
        identifier_hash: str,
        identifier_type: str,
        reason: str,
        created_by: str,
        subject_id: Optional[str] = None,
        rule_type: str = "suppress",
        expires_at: Optional[str] = None,
    ) -> dict:
        existing = await self._suppressions.find_many(
            filters={
                "tenant_id": tenant_id,
                "identifier_type": identifier_type,
                "identifier_hash": identifier_hash,
            },
            limit=5,
        )
        now = utc_now().isoformat()
        active = [
            r for r in existing
            if not r.get("revoked_at")
            and (not r.get("expires_at") or r.get("expires_at", "") > now)
        ]
        if active:
            return active[0]
        rule_id = str(uuid.uuid4())
        return await self._suppressions.insert(rule_id, {
            "id": rule_id,
            "tenant_id": tenant_id,
            "identifier_hash": identifier_hash,
            "identifier_type": identifier_type,
            "subject_id": subject_id,
            "rule_type": rule_type,
            "reason": reason,
            "created_by": created_by,
            "created_at": utc_now().isoformat(),
            "expires_at": expires_at,
            "revoked_at": None,
        })

    async def check_suppression(
        self,
        tenant_id: str,
        identifier_type: str,
        identifier_hash: str,
    ) -> bool:
        """Return True if this identifier hash is suppressed for the tenant."""
        rules = await self._suppressions.find_many(
            filters={
                "tenant_id": tenant_id,
                "identifier_type": identifier_type,
                "identifier_hash": identifier_hash,
            },
            limit=5,
        )
        now = utc_now().isoformat()
        for r in rules:
            if r.get("revoked_at"):
                continue
            expires = r.get("expires_at")
            if expires and expires < now:
                continue
            return True
        return False

    async def revoke_suppression_rule(
        self, tenant_id: str, suppression_id: str
    ) -> Optional[dict]:
        row = await self._suppressions.find_by_id(suppression_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return None
        row["revoked_at"] = utc_now().isoformat()
        return await self._suppressions.update(suppression_id, row)

    async def get_suppressions(
        self, tenant_id: str, limit: int = 50
    ) -> list[dict]:
        all_rules = await self._suppressions.find_many(
            filters={"tenant_id": tenant_id}, limit=limit * 2
        )
        now = utc_now().isoformat()
        active = [
            r for r in all_rules
            if not r.get("revoked_at")
            and (not r.get("expires_at") or r.get("expires_at", "") > now)
        ]
        return active[:limit]

    async def ping(self) -> bool:
        """Health check — verify the repo layer is responsive."""
        try:
            await self._subjects.count({"tenant_id": "__ping__"})
            return True
        except Exception:
            return False

    # ── Health / metrics helpers ──────────────────────────────────────────

    async def get_identity_health(self, tenant_id: str) -> dict:
        total_subjects = await self._subjects.count({"tenant_id": tenant_id})
        total_aliases = await self._aliases.count({"tenant_id": tenant_id})
        total_clusters = await self._clusters.count({"tenant_id": tenant_id})
        open_conflicts = await self._conflicts.count(
            {"tenant_id": tenant_id, "status": ConflictStatus.OPEN.value}
        )
        recent_merges = await self._merges.find_many(
            filters={"tenant_id": tenant_id}, limit=10
        )
        recent_splits = await self._splits.find_many(
            filters={"tenant_id": tenant_id}, limit=10
        )
        return {
            "tenant_id": tenant_id,
            "total_entities": total_subjects,  # canonical name for API
            "total_subjects": total_subjects,
            "total_aliases": total_aliases,
            "total_clusters": total_clusters,
            "open_conflicts": open_conflicts,
            "recent_merges": len(recent_merges),
            "recent_splits": len(recent_splits),
        }
