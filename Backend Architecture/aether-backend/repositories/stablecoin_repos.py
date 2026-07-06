"""Durable repositories for Stablecoin Intelligence PR1 foundation."""
from __future__ import annotations
import hashlib
import json
from typing import Any, Optional
from repositories.repos import BaseRepository
from shared.common.common import utc_now

class StablecoinDeploymentRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_deployments")

class StablecoinObservationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_observations")
    @staticmethod
    def observation_key(record: dict[str, Any]) -> str:
        required = ["tenant_id","chain_id","network","deployment_id","transaction_hash"]
        missing = [k for k in required if not record.get(k)]
        if missing:
            raise ValueError(f"missing stablecoin observation identity: {','.join(missing)}")
        idx = record.get("log_or_instruction_index", "")
        raw_key = ":".join(str(record[k]) for k in required) + f":{idx}"
        return hashlib.sha256(raw_key.encode()).hexdigest()[:32]
    async def upsert_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        if not record.get("tenant_id"):
            raise ValueError("tenant_id is required")
        record_id = record.get("observation_id") or self.observation_key(record)
        data = {**record, "observation_id": record_id, "updated_at": utc_now().isoformat()}
        existing = await self.find_by_id(record_id)
        if existing:
            return await self.update(record_id, {**existing, **data})
        data.setdefault("created_at", data["updated_at"])
        return await self.insert(record_id, data)

class StablecoinSupportAssertionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_support_assertions")

class StablecoinReconciliationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_reconciliation_results")

class StablecoinGoldIdentity:
    @staticmethod
    def key(*, tenant_id: str, metric_name: str, metric_version: str, entity_id: str, entity_type: str, canonical_asset_id: str, deployment_id: str, chain_id: str, window_start: str, window_end: str, dimensions: Optional[dict[str, Any]] = None, source: str = "") -> str:
        if not tenant_id:
            raise ValueError("tenant_id is required for tenant-owned Gold stablecoin metrics")
        payload = {"tenant_id": tenant_id, "metric_name": metric_name, "metric_version": metric_version, "entity_id": entity_id, "entity_type": entity_type, "canonical_asset_id": canonical_asset_id, "deployment_id": deployment_id, "chain_id": chain_id, "window_start": window_start, "window_end": window_end, "dimensions": dimensions or {}, "source": source}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:40]

class StablecoinGoldRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("gold_stablecoin_metrics")
    async def materialize_metric(self, **kwargs: Any) -> dict[str, Any]:
        metric_id = StablecoinGoldIdentity.key(**{k: kwargs.get(k, "") for k in ["tenant_id","metric_name","metric_version","entity_id","entity_type","canonical_asset_id","deployment_id","chain_id","window_start","window_end"]}, dimensions=kwargs.get("dimensions"), source=kwargs.get("source", ""))
        data = {**kwargs, "gold_id": metric_id, "materialized_at": utc_now().isoformat()}
        existing = await self.find_by_id(metric_id)
        if existing:
            return await self.update(metric_id, {**existing, **data})
        return await self.insert(metric_id, data)

class StablecoinRemediationAuditRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_remediation_audit")

class StablecoinMarketBenchmarkRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_market_benchmarks")

class StablecoinIdentityLinkRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_identity_links")

class StablecoinGraphProjectionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("stablecoin_graph_projection_outbox")
