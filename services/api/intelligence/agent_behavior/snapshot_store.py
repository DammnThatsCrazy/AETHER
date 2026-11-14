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
from shared.temporal.instant import coerce_utc_lenient

TABLE = "agent_behavior_snapshots"
WINDOW_READ_PAGE = 200
WINDOW_READ_MAX_PAGES = 25  # 5,000 windows: over 13 years of daily snapshots


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
        """The ``limit`` chronologically latest windows, oldest first.

        ``find_many`` orders by insertion time and cannot sort by window
        bounds, so limiting there would drop the real latest windows whenever
        older windows were backfilled after newer ones. The agent's rows are
        read in pages (one row per window, bounded) and ordered by window
        instant before the limit applies."""
        filters = {"tenant_id": tenant_id, "agent_ref": agent_ref}
        rows: list[dict[str, Any]] = []
        for page in range(WINDOW_READ_MAX_PAGES):
            batch = await self.find_many(filters=filters, limit=WINDOW_READ_PAGE, offset=page * WINDOW_READ_PAGE)
            rows.extend(r for r in batch if r.get("tenant_id") == tenant_id)
            if len(batch) < WINDOW_READ_PAGE:
                break

        def instant(value: Any) -> float:
            at = coerce_utc_lenient(value)
            return at.timestamp() if at is not None else float("-inf")

        def chronological(r: dict[str, Any]) -> tuple[float, float]:
            return (instant(r["window_end"]), instant(r["window_start"]))

        rows.sort(key=chronological)
        return rows[-max(1, min(limit, 200)):]

    async def delete_by_agent(self, tenant_id: str, agent_ref: str) -> int:
        count = 0
        for row in await self.windows(tenant_id, agent_ref, limit=200):
            if await self.delete(row["id"]):
                count += 1
        return count

    async def purge_before(self, tenant_id: str, agent_ref: str, window_end: str) -> int:
        cutoff = coerce_utc_lenient(window_end)
        if cutoff is None:
            raise ValueError(f"invalid window_end: {window_end!r}")
        count = 0
        for row in await self.windows(tenant_id, agent_ref, limit=200):
            row_end = coerce_utc_lenient(row["window_end"])
            if row_end is not None and row_end < cutoff and await self.delete(row["id"]):
                count += 1
        return count


def compute_window_snapshot(
    facts: Iterable[AgentFact], agent_ref: str, window: tuple[str, str],
) -> dict[str, Any]:
    """Snapshot of the facts inside ``[window[0], window[1])``.

    Bounds and fact times are compared as parsed UTC instants: as strings,
    ``...Z`` and ``...+00:00`` or a date-only bound order wrongly."""
    start, end = coerce_utc_lenient(window[0]), coerce_utc_lenient(window[1])
    if start is None or end is None:
        raise ValueError(f"invalid behavior window: {window!r}")
    inside = []
    for f in facts:
        at = coerce_utc_lenient(f.occurred_at)
        if at is not None and start <= at < end:
            inside.append(f)
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


async def calibration_over_stored_windows(
    repo: BehaviorSnapshotRepository, tenant_id: str, agent_ref: str,
) -> dict[str, Any]:
    """Forward-coverage diagnostic over this agent's stored windows (never calibration)."""
    from intelligence.agent_behavior.calibration import forward_coverage

    rows = await repo.windows(tenant_id, agent_ref)
    return forward_coverage([[r["snapshot"] for r in rows]])
