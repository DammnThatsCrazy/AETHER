"""Stablecoin graph projection outbox helpers.

This module does not write directly to Neptune. It creates deterministic,
tenant-scoped projection records that a graph worker can replay idempotently.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinGraphProjectionRepository
from shared.common.common import utc_now


@dataclass(frozen=True)
class StablecoinGraphProjection:
    projection_id: str
    tenant_id: str
    observation_id: str
    vertices: list[Mapping[str, Any]]
    edges: list[Mapping[str, Any]]
    provenance: Mapping[str, Any]


class StablecoinGraphProjector:
    def __init__(self, repo: StablecoinGraphProjectionRepository | None = None) -> None:
        self.repo = repo or StablecoinGraphProjectionRepository()

    @staticmethod
    def _stable_id(*parts: Any) -> str:
        return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:40]

    def build_projection(self, observation: Mapping[str, Any]) -> StablecoinGraphProjection:
        tenant_id = str(observation.get("tenant_id", ""))
        observation_id = str(observation.get("observation_id", ""))
        if not tenant_id or not observation_id:
            raise ValueError("tenant_id and observation_id are required for stablecoin graph projection")
        deployment_id = observation.get("deployment_id", "unknown")
        asset_id = observation.get("canonical_asset_id", "unknown")
        chain_id = observation.get("chain_id", "unknown")
        tx_hash = observation.get("transaction_hash", "unknown")
        from_wallet = str(observation.get("from_address", "") or "unknown_from")
        to_wallet = str(observation.get("to_address", "") or "unknown_to")
        vertices = [
            {"id": self._stable_id(tenant_id, "stablecoin", asset_id), "kind": "Stablecoin", "tenant_id": tenant_id, "asset_id": asset_id},
            {"id": self._stable_id(tenant_id, "deployment", deployment_id), "kind": "StablecoinDeployment", "tenant_id": tenant_id, "deployment_id": deployment_id},
            {"id": self._stable_id(tenant_id, "observation", observation_id), "kind": "StablecoinObservation", "tenant_id": tenant_id, "observation_id": observation_id},
            {"id": self._stable_id(tenant_id, "wallet", chain_id, from_wallet.lower()), "kind": "Wallet", "tenant_id": tenant_id, "address": from_wallet.lower()},
            {"id": self._stable_id(tenant_id, "wallet", chain_id, to_wallet.lower()), "kind": "Wallet", "tenant_id": tenant_id, "address": to_wallet.lower()},
        ]
        edges = [
            {"id": self._stable_id(tenant_id, observation_id, "uses_asset"), "type": "USES_ASSET", "from": vertices[2]["id"], "to": vertices[1]["id"], "tenant_id": tenant_id},
            {"id": self._stable_id(tenant_id, observation_id, "observed_on", chain_id), "type": "OBSERVED_ON", "from": vertices[2]["id"], "to": chain_id, "tenant_id": tenant_id},
            {"id": self._stable_id(tenant_id, observation_id, "sent_to"), "type": "SENT_TO", "from": vertices[3]["id"], "to": vertices[4]["id"], "tenant_id": tenant_id, "transaction_hash": tx_hash},
        ]
        return StablecoinGraphProjection(
            projection_id=self._stable_id(tenant_id, observation_id, "stablecoin_projection_v1"),
            tenant_id=tenant_id,
            observation_id=observation_id,
            vertices=vertices,
            edges=edges,
            provenance={"source": observation.get("source"), "evidence_id": observation.get("evidence_id")},
        )

    async def enqueue_projection(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        projection = self.build_projection(observation)
        record = {
            "projection_id": projection.projection_id,
            "tenant_id": projection.tenant_id,
            "observation_id": projection.observation_id,
            "vertices": [dict(v) for v in projection.vertices],
            "edges": [dict(e) for e in projection.edges],
            "provenance": dict(projection.provenance),
            "status": "queued",
            "created_at": utc_now().isoformat(),
        }
        existing = await self.repo.find_by_id(projection.projection_id)
        return await self.repo.update(projection.projection_id, {**existing, **record}) if existing else await self.repo.insert(projection.projection_id, record)
