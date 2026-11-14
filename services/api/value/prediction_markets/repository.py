"""Tenant-scoped, immutable prediction-market observation store.

One row per observation *occurrence*. Resubmitting the content of a market's
latest observation is an idempotent retry; any other content is a new row, even
when it repeats an earlier value, so a quote that moves 0.40 -> 0.60 -> 0.40 is
stored three times and latest / as-of reads follow the observed sequence. Reads
are tenant-exact and may be made as of an instant (``received_at``, which is
server-assigned and strictly increasing per market).

The ``observation_sha256`` key column holds an occurrence key: the content
digest for a market's first observation, and otherwise a digest chained to the
predecessor's key. Concurrent identical retries therefore compute the same key
and collapse on the primary key, while a return to an earlier value has a
different predecessor and gets its own row.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
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
_TICK = timedelta(microseconds=1)


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def observation_sha256(observation: MarketObservation) -> str:
    return _payload_sha256(observation_to_payload(observation))


def occurrence_key(content_sha256: str, predecessor_key: Optional[str]) -> str:
    """Key of one observation occurrence, chained to the market's previous one."""
    if predecessor_key is None:
        return content_sha256
    material = json.dumps([content_sha256, predecessor_key], separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _next_received_at(previous: Optional[datetime]) -> datetime:
    # Strictly after the predecessor, so a clock step back cannot reorder reads.
    now = datetime.now(timezone.utc)
    return now if previous is None or now > previous else previous + _TICK


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
        content = observation_sha256(observation)
        venue = observation.venue.value
        payload = observation_to_payload(observation)
        pool = await self._pool()
        if pool is None:
            previous = self._latest_local(tenant_id, venue, observation.market_ref)
            if previous is not None and _payload_sha256(previous[2]) == content:
                return observation, False
            key = occurrence_key(content, previous[1] if previous else None)
            local_key = (tenant_id, venue, observation.market_ref, key)
            if local_key in self._local:
                return observation, False
            self._local[local_key] = {
                "received_at": _next_received_at(previous[0] if previous else None),
                "data": payload,
            }
            return observation, True
        async with pool.acquire() as conn:
            async with conn.transaction():
                previous = await conn.fetchrow(
                    """
                    SELECT observation_sha256, received_at, data
                    FROM prediction_market_observations
                    WHERE tenant_id=$1 AND venue=$2 AND market_ref=$3
                    ORDER BY received_at DESC, observation_sha256 DESC LIMIT 1
                    """,
                    tenant_id,
                    venue,
                    observation.market_ref,
                )
                if previous is not None and _payload_sha256(_json_object(previous["data"])) == content:
                    return observation, False
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
                    occurrence_key(content, previous["observation_sha256"] if previous else None),
                    observation.status.value,
                    _next_received_at(previous["received_at"] if previous else None),
                    json.dumps(payload),
                )
        return observation, inserted is not None

    def _latest_local(
        self, tenant_id: str, venue: str, market_ref: str
    ) -> Optional[tuple[datetime, str, dict[str, Any]]]:
        rows = [
            (row["received_at"], key, row["data"])
            for (t, v, m, key), row in self._local.items()
            if t == tenant_id and v == venue and m == market_ref
        ]
        return max(rows, key=lambda r: (r[0], r[1]), default=None)

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
                (row["received_at"], key, row["data"])
                for (t, v, m, key), row in self._local.items()
                if t == tenant_id and v == venue.value and m == market_ref
            ]
            if as_of is not None:
                rows = [r for r in rows if r[0] <= as_of]
            if not rows:
                return None
            received_at, _, data = max(rows, key=lambda r: (r[0], r[1]))
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
