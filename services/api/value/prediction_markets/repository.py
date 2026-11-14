"""Tenant-scoped, immutable prediction-market observation store.

One row per distinct normalized observation. Resubmitting identical content is
idempotent; changed content is a new row. Reads are tenant-exact and may be
made as of an instant (``received_at``, which is server-assigned).
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import get_pool
from value.prediction_markets.models import (
    MarketObservation,
    MarketVenue,
    observation_from_payload,
    observation_to_payload,
)

_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"
_LOCAL_STORE: dict[tuple[str, str, str, str], dict[str, Any]] = {}


def observation_sha256(observation: MarketObservation) -> str:
    canonical = json.dumps(
        observation_to_payload(observation), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("stored observation is not an object")
    return value


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return value.astimezone(timezone.utc)


class PredictionMarketObservationRepository:
    def __init__(self) -> None:
        self._local = _LOCAL_STORE

    async def _pool(self) -> Any:
        return None if _LOCAL else await get_pool()

    async def record(
        self, tenant_id: str, observation: MarketObservation
    ) -> tuple[MarketObservation, bool]:
        """Persist an observation; returns (observation, newly_recorded)."""
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        digest = observation_sha256(observation)
        venue = observation.venue.value
        key = (tenant_id, venue, observation.market_ref, digest)
        received_at = datetime.now(timezone.utc)
        payload = observation_to_payload(observation)
        pool = await self._pool()
        if pool is None:
            if key in self._local:
                return observation, False
            self._local[key] = {"received_at": received_at, "data": payload}
            return observation, True
        async with pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO prediction_market_observations (
                    tenant_id, venue, market_ref, observation_sha256,
                    status, received_at, data
                ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                ON CONFLICT (tenant_id, venue, market_ref, observation_sha256)
                DO NOTHING
                RETURNING observation_sha256
                """,
                tenant_id,
                venue,
                observation.market_ref,
                digest,
                observation.status.value,
                received_at,
                json.dumps(payload),
            )
        return observation, inserted is not None

    async def latest(
        self,
        tenant_id: str,
        venue: MarketVenue,
        market_ref: str,
        *,
        as_of: Optional[datetime] = None,
    ) -> Optional[tuple[MarketObservation, datetime]]:
        if not tenant_id or not market_ref:
            return None
        as_of = _utc(as_of)
        pool = await self._pool()
        if pool is None:
            rows = [
                (row["received_at"], row["data"])
                for (t, v, m, _), row in self._local.items()
                if t == tenant_id and v == venue.value and m == market_ref
            ]
            if as_of is not None:
                rows = [r for r in rows if r[0] <= as_of]
            if not rows:
                return None
            received_at, data = max(rows, key=lambda r: r[0])
            return observation_from_payload(data), received_at
        query = """SELECT received_at, data FROM prediction_market_observations
                   WHERE tenant_id=$1 AND venue=$2 AND market_ref=$3"""
        args: list[Any] = [tenant_id, venue.value, market_ref]
        if as_of is not None:
            query += " AND received_at <= $4"
            args.append(as_of)
        query += " ORDER BY received_at DESC, observation_sha256 DESC LIMIT 1"
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
        if row is None:
            return None
        return observation_from_payload(_json_object(row["data"])), row["received_at"]
