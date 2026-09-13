"""
Aether Shared — CIS Cache Provenance Extension
Extends CacheClient with provenance-tagged set/get operations.

All cached retrieval/context artifacts are wrapped with a provenance
envelope so contamination state can be traced through the cache layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shared.cache.cache import CacheClient, TTL
from shared.logger.logger import get_logger

logger = get_logger("aether.cis.cache_provenance")

_PROVENANCE_SUFFIX = ":__cis_prov"


@dataclass
class ProvenanceMeta:
    provenance_id: str
    tenant_id: str
    contamination_score: float
    lineage_hash: str
    tagged_at: str


class ProvenanceCacheClient(CacheClient):
    """
    CacheClient subclass adding provenance tagging for CIS.

    Usage:
        client = ProvenanceCacheClient()
        await client.connect()
        await client.set_with_provenance(key, value, provenance_id=..., ...)
        meta = await client.get_provenance(key)
    """

    async def set_with_provenance(
        self,
        key: str,
        value: str,
        provenance_id: str,
        tenant_id: str,
        contamination_score: float = 0.0,
        lineage_hash: str = "",
        ttl: int = TTL.PREDICTION,
    ) -> None:
        # Store the value itself
        await self.set(key, value, ttl)
        # Store provenance sidecar at key:__cis_prov
        prov_key = f"aether:cis:provenance:{key}"
        prov_meta = {
            "provenance_id": provenance_id,
            "tenant_id": tenant_id,
            "contamination_score": contamination_score,
            "lineage_hash": lineage_hash,
            "tagged_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.set(prov_key, json.dumps(prov_meta), ttl)

    async def get_provenance(self, key: str) -> Optional[ProvenanceMeta]:
        prov_key = f"aether:cis:provenance:{key}"
        raw = await self.get(prov_key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return ProvenanceMeta(
                provenance_id=data["provenance_id"],
                tenant_id=data["tenant_id"],
                contamination_score=float(data.get("contamination_score", 0.0)),
                lineage_hash=data.get("lineage_hash", ""),
                tagged_at=data.get("tagged_at", ""),
            )
        except Exception as e:
            logger.debug(f"get_provenance parse error for key={key}: {e}")
            return None

    async def get_json_with_provenance(
        self, key: str
    ) -> tuple[Optional[Any], Optional[ProvenanceMeta]]:
        raw = await self.get(key)
        prov = await self.get_provenance(key)
        if raw is None:
            return None, prov
        try:
            return json.loads(raw), prov
        except Exception:
            return raw, prov
