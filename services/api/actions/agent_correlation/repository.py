"""Storage for correlation tasks, observations, join keys, and verdicts.

Every row is tenant-owned and every lookup filters by tenant. Verdicts are
append-only: a verdict's ID covers its tenant, observation pair, policy
version, and outcome, so re-running the same decision writes nothing and a
changed decision adds a row instead of rewriting history.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from repositories.repos import BaseRepository
from shared.integration_contracts.correlation import (
    CORRELATION_CONTRACT_VERSION,
    CorrelationObservation,
    CorrelationVerdict,
)

MAX_CANDIDATES_PER_KEY = 200


def _digest(*parts: str) -> str:
    material = json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


class CorrelationTaskRepository(BaseRepository):
    """Tasks agents register through Aether (agent_correlation_tasks)."""

    def __init__(self) -> None:
        super().__init__("agent_correlation_tasks")

    @staticmethod
    def row_id(tenant_id: str, task_ref: str) -> str:
        return "act_" + _digest(tenant_id, task_ref)

    async def save(self, tenant_id: str, task: dict[str, Any]) -> dict[str, Any]:
        return await self.insert(self.row_id(tenant_id, task["task_ref"]), {**task, "tenant_id": tenant_id})

    async def get(self, tenant_id: str, task_ref: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(self.row_id(tenant_id, task_ref))
        return row if row and row.get("tenant_id") == tenant_id else None


class CorrelationObservationRepository(BaseRepository):
    """Canonical observations, as the join rules read them (agent_correlation_observations)."""

    def __init__(self) -> None:
        super().__init__("agent_correlation_observations")

    @staticmethod
    def row_id(tenant_id: str, observation_id: str) -> str:
        return "aco_" + _digest(tenant_id, observation_id)

    async def save(self, obs: CorrelationObservation, *, provider: str, kind: str) -> bool:
        """Store ``obs``; returns False when this observation was already stored."""
        row_id = self.row_id(obs.tenant_id, obs.observation_id)
        if await self.find_by_id(row_id):
            return False
        await self.insert(row_id, {
            "tenant_id": obs.tenant_id,
            "observation_id": obs.observation_id,
            "provider": provider,
            "kind": kind,
            "source_role": obs.source_role,
            "occurred_at": _iso(obs.occurred_at),
            "observation": obs.model_dump(mode="json"),
        })
        return True

    async def get(self, tenant_id: str, observation_id: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(self.row_id(tenant_id, observation_id))
        return row if row and row.get("tenant_id") == tenant_id else None

    async def mark_correlated(self, tenant_id: str, observation_id: str) -> None:
        """Ingestion checkpoint: indexing and correlation finished for this row."""
        await self.update(self.row_id(tenant_id, observation_id), {
            "tenant_id": tenant_id, "correlation_completed_at": _iso(datetime.now(timezone.utc)),
        })

    async def is_correlated(self, tenant_id: str, observation_id: str) -> bool:
        row = await self.get(tenant_id, observation_id)
        return bool(row and row.get("correlation_completed_at"))

    async def get_observation(self, tenant_id: str, observation_id: str) -> Optional[CorrelationObservation]:
        row = await self.get(tenant_id, observation_id)
        return CorrelationObservation.model_validate(row["observation"]) if row else None


class CorrelationKeyIndexRepository(BaseRepository):
    """Equality index from (tenant, key kind, key value) to observations (agent_correlation_keys)."""

    def __init__(self) -> None:
        super().__init__("agent_correlation_keys")

    async def index(self, tenant_id: str, observation_id: str, keys: Iterable[tuple[str, str]]) -> None:
        # Idempotent: a redelivery that resumes an interrupted ingestion replays
        # the index, and an existing key row is left as it is.
        for key_kind, key_value in keys:
            await self.insert_if_absent("ack_" + _digest(tenant_id, key_kind, key_value, observation_id), {
                "tenant_id": tenant_id,
                "key_kind": key_kind,
                "key_value": key_value,
                "observation_id": observation_id,
            }, tenant_id)

    async def observations_for(self, tenant_id: str, key_kind: str, key_value: str) -> list[str]:
        rows = await self.find_many(
            {"tenant_id": tenant_id, "key_kind": key_kind, "key_value": key_value},
            limit=MAX_CANDIDATES_PER_KEY,
        )
        return [r["observation_id"] for r in rows if r.get("tenant_id") == tenant_id]


class CorrelationVerdictRepository(BaseRepository):
    """Append-only join decisions (agent_correlation_verdicts)."""

    def __init__(self) -> None:
        super().__init__("agent_correlation_verdicts")

    @staticmethod
    def row_id(tenant_id: str, left_id: str, right_id: str, verdict: CorrelationVerdict) -> str:
        a, b = sorted((left_id, right_id))
        return "acv_" + _digest(
            tenant_id, a, b, verdict.contract_version, verdict.status, verdict.key_kind or "", verdict.reason
        )

    async def record(
        self,
        tenant_id: str,
        left: CorrelationObservation,
        right: CorrelationObservation,
        verdict: CorrelationVerdict,
    ) -> tuple[str, bool]:
        """Persist ``verdict``; returns (verdict_id, newly_recorded)."""
        row_id = self.row_id(tenant_id, left.observation_id, right.observation_id, verdict)
        if await self.find_by_id(row_id):
            return row_id, False
        await self.insert(row_id, {
            "tenant_id": tenant_id,
            "verdict_id": row_id,
            "policy_version": CORRELATION_CONTRACT_VERSION,
            "left_observation_id": left.observation_id,
            "right_observation_id": right.observation_id,
            "left_role": left.source_role,
            "right_role": right.source_role,
            "decided_at": _iso(datetime.now(timezone.utc)),
            **verdict.model_dump(mode="json"),
        })
        return row_id, True

    async def get(self, tenant_id: str, verdict_id: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(verdict_id)
        return row if row is not None and row.get("tenant_id") == tenant_id else None

    async def mark_projection(self, tenant_id: str, verdict_id: str, report: dict[str, Any]) -> None:
        """Durable projection checkpoint on the verdict row. The decision itself
        stays immutable; only the graph-projection outcome fields change, so a
        failed or partial projection is retried on the next delivery."""
        await self.update(verdict_id, {
            "tenant_id": tenant_id,
            "graph_projection_status": report.get("graph_projection_status"),
            "graph_mutations_persisted": report.get("graph_mutations_persisted", 0),
            "graph_projection_attempts": int(
                ((await self.get(tenant_id, verdict_id)) or {}).get("graph_projection_attempts") or 0) + 1,
            "graph_projected_at": _iso(datetime.now(timezone.utc)),
        })

    async def for_observation(self, tenant_id: str, observation_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for side in ("left_observation_id", "right_observation_id"):
            rows.extend(await self.find_many({"tenant_id": tenant_id, side: observation_id}, limit=500))
        return [r for r in rows if r.get("tenant_id") == tenant_id]


def time_buckets(occurred_at: datetime, window: timedelta) -> tuple[str, ...]:
    """The observation's time bucket and both neighbours, for window lookups."""
    width = max(int(window.total_seconds()), 1)
    bucket = int(occurred_at.timestamp()) // width
    return tuple(f"{width}:{b}" for b in (bucket - 1, bucket, bucket + 1))


def own_time_bucket(occurred_at: datetime, window: timedelta) -> str:
    width = max(int(window.total_seconds()), 1)
    return f"{width}:{int(occurred_at.timestamp()) // width}"
