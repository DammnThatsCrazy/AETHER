"""Iceberg snapshot writer — hash dedup test."""

from __future__ import annotations

import asyncio

import snapshot_writer   # type: ignore  (loaded via conftest.py)


def test_identical_states_dedupe_by_hash():
    w = snapshot_writer.IcebergSnapshotWriter()
    user_state = {"actor_id": "a1", "consent": {"analytics": True}}
    system_state = {"page": {"path": "/home"}}

    async def _go() -> tuple[str, str]:
        ref1 = await w.write_state_snapshot(
            project_id="p", event_id="e1", event_date="2026-01-01",
            user_state=user_state, system_state=system_state,
        )
        ref2 = await w.write_state_snapshot(
            project_id="p", event_id="e2", event_date="2026-01-01",
            user_state=user_state, system_state=system_state,
        )
        return ref1.hash, ref2.hash

    h1, h2 = asyncio.run(_go())
    assert h1 == h2
    assert len(w._snapshots) == 1   # deduped


def test_different_states_produce_distinct_hashes():
    w = snapshot_writer.IcebergSnapshotWriter()

    async def _go() -> tuple[str, str]:
        a = await w.write_state_snapshot(
            project_id="p", event_id="e1", event_date="2026-01-01",
            user_state={"actor_id": "a1"}, system_state={"page": "/a"},
        )
        b = await w.write_state_snapshot(
            project_id="p", event_id="e2", event_date="2026-01-01",
            user_state={"actor_id": "a1"}, system_state={"page": "/b"},
        )
        return a.hash, b.hash

    ha, hb = asyncio.run(_go())
    assert ha != hb
