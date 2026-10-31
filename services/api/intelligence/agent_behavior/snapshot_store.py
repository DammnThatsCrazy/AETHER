"""Stored BehaviorSnapshots and drift over stored windows (WO-100, WO-101).

Snapshots are derived caches (ADR-AB-002): the row key is a hash of
(tenant, agent, window, snapshot version), so recomputing the same window from
the same facts overwrites the same row with identical content. Deleting rows
loses no evidence. Every read is tenant-scoped.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Optional

from intelligence.agent_behavior.dynamics import SNAPSHOT_VERSION, detect_drift, snapshot
from intelligence.agent_behavior.facts import AgentFact
from intelligence.agent_behavior.model import build_behavior_model
from repositories.repos import BaseRepository

TABLE = "agent_behavior_snapshots"


def snapshot_id(tenant_id: str, agent_ref: str, window: tuple[str, str]) -> str:
    material = json.dumps([tenant_id, agent_ref, list(window), SNAPSHOT_VERSION], separators=(",", ":"))
    return "abs_" + hashlib.sha256(material.encode()).hexdigest()[:40]


class BehaviorSnapshotRepository(BaseRepository):
    """Tenant-scoped store of window snapshots (table ``agent_behavior_snapshots``)."""

    def __init__(self) -> None:
        super().__init__(TABLE)

    async def put(self, tenant_id: str, agent_ref: str, snap: dict[str, Any]) -> dict[str, Any]:
        window = tuple(snap["window"])
        sid = snapshot_id(tenant_id, agent_ref, window)
        row = {
            "id": sid, "tenant_id": tenant_id, "agent_ref": agent_ref,
            "window_start": window[0], "window_end": window[1],
            "snapshot_version": SNAPSHOT_VERSION, "snapshot": snap,
        }
        existing = await self.find_by_id(sid)
        if existing and existing.get("tenant_id") == tenant_id:
            return await self.update(sid, row)
        return await self.insert(sid, row)

    async def windows(self, tenant_id: str, agent_ref: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "agent_ref": agent_ref}, limit=max(1, min(limit, 200)),
        )
        rows = [r for r in rows if r.get("tenant_id") == tenant_id]
        return sorted(rows, key=lambda r: (r["window_end"], r["window_start"]))

    async def delete_by_agent(self, tenant_id: str, agent_ref: str) -> int:
        count = 0
        for row in await self.windows(tenant_id, agent_ref, limit=200):
            if await self.delete(row["id"]):
                count += 1
        return count

    async def purge_before(self, tenant_id: str, agent_ref: str, window_end: str) -> int:
        count = 0
        for row in await self.windows(tenant_id, agent_ref, limit=200):
            if row["window_end"] < window_end and await self.delete(row["id"]):
                count += 1
        return count


def compute_window_snapshot(
    facts: Iterable[AgentFact], agent_ref: str, window: tuple[str, str],
) -> dict[str, Any]:
    """Snapshot of the facts inside ``[window[0], window[1])``."""
    inside = [f for f in facts if window[0] <= f.occurred_at < window[1]]
    return snapshot(build_behavior_model(inside, agent_ref), window)


async def record_window(
    repo: BehaviorSnapshotRepository, tenant_id: str, agent_ref: str,
    facts: Iterable[AgentFact], window: tuple[str, str],
) -> dict[str, Any]:
    tenant_facts = [f for f in facts if f.tenant_id == tenant_id]
    snap = compute_window_snapshot(tenant_facts, agent_ref, window)
    await repo.put(tenant_id, agent_ref, snap)
    return snap


async def drift_over_stored_windows(
    repo: BehaviorSnapshotRepository, tenant_id: str, agent_ref: str,
    config_changes: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Compare the two most recent stored windows; fewer than two means unknown."""
    rows = await repo.windows(tenant_id, agent_ref)
    if len(rows) < 2:
        return {"status": "insufficient_windows", "windows": len(rows),
                "note": "drift needs at least two stored windows"}
    baseline, recent = rows[-2]["snapshot"], rows[-1]["snapshot"]
    return detect_drift(baseline, recent, config_changes)
