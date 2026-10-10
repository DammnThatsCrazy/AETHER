"""
Aether Shared — CIS Provenance Tracker
Tracks canonical provenance for all epistemic entities: nodes, edges,
generations, retrievals, summarizations, and synthetic derivations.

Storage: Postgres `cis_provenance_records` table (canonical state).
Falls back to in-memory when AETHER_ENV=local.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.cis.provenance")


# ─────────────────────────────────────────────────────────────────────────────
# Domain types
# ─────────────────────────────────────────────────────────────────────────────

class EntityType:
    NODE = "node"
    EDGE = "edge"
    GENERATION = "generation"
    RETRIEVAL = "retrieval"
    SUMMARY = "summary"
    SYNTHETIC = "synthetic"


@dataclass
class ProvenanceRecord:
    entity_id: str
    entity_type: str
    tenant_id: str
    lineage_hash: str
    contamination_score: float = 0.0
    synthetic_flag: bool = False
    synthetic_depth: int = 0
    origin_agent_id: Optional[str] = None
    generation_model: Optional[str] = None
    retrieval_ids: list[str] = field(default_factory=list)
    parent_provenance_ids: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    provenance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Lineage hasher
# ─────────────────────────────────────────────────────────────────────────────

class LineageHasher:
    """Deterministic SHA256 hash over a provenance chain for tamper detection."""

    @staticmethod
    def hash(
        entity_id: str,
        entity_type: str,
        parent_ids: list[str],
        tenant_id: str,
        generation_model: Optional[str] = None,
    ) -> str:
        payload = json.dumps(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "parent_ids": sorted(parent_ids),
                "tenant_id": tenant_id,
                "generation_model": generation_model or "",
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic lineage detector
# ─────────────────────────────────────────────────────────────────────────────

class SyntheticLineageDetector:
    """Flags entities whose provenance chain contains too many synthetic ancestors."""

    def __init__(self, max_synthetic_depth: int = 3) -> None:
        self.max_synthetic_depth = max_synthetic_depth

    def is_deeply_synthetic(self, record: ProvenanceRecord) -> bool:
        return record.synthetic_flag and record.synthetic_depth >= self.max_synthetic_depth

    def compute_synthetic_depth(
        self,
        parent_records: list[ProvenanceRecord],
    ) -> int:
        if not parent_records:
            return 0
        max_parent_depth = max(
            (r.synthetic_depth for r in parent_records if r.synthetic_flag),
            default=0,
        )
        return max_parent_depth + 1


# ─────────────────────────────────────────────────────────────────────────────
# Provenance tracker (storage)
# ─────────────────────────────────────────────────────────────────────────────

class ProvenanceTracker:
    """
    Writes and queries provenance records.

    In-memory fallback for AETHER_ENV=local; asyncpg for staging/production.
    """

    def __init__(self) -> None:
        self._store: dict[str, ProvenanceRecord] = {}  # in-memory: entity_id → record
        self._pool: Optional[Any] = None

    async def _get_pool(self) -> Optional[Any]:
        if self._pool is not None:
            return self._pool
        try:
            from repositories.repos import get_pool
            self._pool = await get_pool()
        except Exception:
            pass
        return self._pool

    def _is_local(self) -> bool:
        return os.getenv("AETHER_ENV", "local").lower() == "local"

    async def record(self, rec: ProvenanceRecord) -> None:
        if self._is_local():
            self._store[rec.entity_id] = rec
            return
        pool = await self._get_pool()
        if pool is None:
            self._store[rec.entity_id] = rec
            return
        try:
            await pool.execute(
                """
                INSERT INTO cis_provenance_records (
                    provenance_id, tenant_id, entity_id, entity_type,
                    lineage_hash, origin_agent_id, generation_model,
                    retrieval_ids, contamination_score, synthetic_flag,
                    synthetic_depth, parent_provenance_ids, raw_metadata,
                    created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                          $11, $12, $13, $14, $14)
                ON CONFLICT (provenance_id) DO NOTHING
                """,
                rec.provenance_id,
                rec.tenant_id,
                rec.entity_id,
                rec.entity_type,
                rec.lineage_hash,
                rec.origin_agent_id,
                rec.generation_model,
                rec.retrieval_ids,
                rec.contamination_score,
                rec.synthetic_flag,
                rec.synthetic_depth,
                rec.parent_provenance_ids,
                json.dumps(rec.raw_metadata),
                rec.created_at,
            )
        except Exception as e:
            logger.error(f"ProvenanceTracker.record failed: {e}")
            self._store[rec.entity_id] = rec

    async def get(self, entity_id: str, tenant_id: str) -> Optional[ProvenanceRecord]:
        if self._is_local():
            rec = self._store.get(entity_id)
            return rec if (rec and rec.tenant_id == tenant_id) else None
        pool = await self._get_pool()
        if pool is None:
            return self._store.get(entity_id)
        try:
            row = await pool.fetchrow(
                "SELECT * FROM cis_provenance_records WHERE entity_id=$1 AND tenant_id=$2",
                entity_id,
                tenant_id,
            )
            if row is None:
                return None
            return ProvenanceRecord(
                provenance_id=str(row["provenance_id"]),
                tenant_id=row["tenant_id"],
                entity_id=row["entity_id"],
                entity_type=row["entity_type"],
                lineage_hash=row["lineage_hash"],
                origin_agent_id=row["origin_agent_id"],
                generation_model=row["generation_model"],
                retrieval_ids=list(row["retrieval_ids"] or []),
                contamination_score=float(row["contamination_score"]),
                synthetic_flag=bool(row["synthetic_flag"]),
                synthetic_depth=int(row["synthetic_depth"]),
                parent_provenance_ids=list(row["parent_provenance_ids"] or []),
                raw_metadata=json.loads(row["raw_metadata"] or "{}"),
                created_at=row["created_at"].isoformat(),
            )
        except Exception as e:
            logger.error(f"ProvenanceTracker.get failed: {e}")
            return None

    async def update_contamination_score(
        self, entity_id: str, tenant_id: str, score: float
    ) -> None:
        if self._is_local():
            rec = self._store.get(entity_id)
            if rec and rec.tenant_id == tenant_id:
                rec.contamination_score = score
            return
        pool = await self._get_pool()
        if pool is None:
            return
        try:
            await pool.execute(
                """
                UPDATE cis_provenance_records
                SET contamination_score=$1, updated_at=now()
                WHERE entity_id=$2 AND tenant_id=$3
                """,
                score,
                entity_id,
                tenant_id,
            )
        except Exception as e:
            logger.error(f"ProvenanceTracker.update_contamination_score failed: {e}")

    def store_snapshot(self) -> list[ProvenanceRecord]:
        """Test helper — returns all in-memory records."""
        return list(self._store.values())
