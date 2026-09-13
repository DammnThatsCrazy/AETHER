"""Iceberg snapshot writer.

State snapshots are content-addressed by sha256 and deduped via a Redis
bloom filter before write. In production, writes go to Apache Iceberg
tables on S3 (`event_snapshots`, `exposures`, `agent_reasoning`). The stub
keeps an in-memory store so unit tests can run end-to-end.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SnapshotRef:
    table: str          # 'event_snapshots' | 'exposures' | 'agent_reasoning'
    hash: str
    uri: str            # 'iceberg://aether_snapshots/<table>/<hash>'


class IcebergSnapshotWriter:
    """Writes hash-addressed snapshots. Replace stub with PyIceberg in prod."""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict] = {}      # hash -> payload
        self._exposures: list[dict] = []
        self._reasoning: list[dict] = []
        self._seen_hashes: set[str] = set()

    # -- 4. state_snapshot ----------------------------------------------------

    async def write_state_snapshot(
        self,
        *,
        project_id: str,
        event_id: str,
        event_date: str,
        user_state: dict,
        system_state: dict,
    ) -> SnapshotRef:
        payload = {
            "project_id": project_id,
            "user_state": user_state,
            "system_state": system_state,
        }
        h = _sha256_json(payload)
        if h not in self._seen_hashes:
            self._snapshots[h] = {
                "snapshot_hash": h,
                "event_date": event_date,
                "project_id": project_id,
                "user_state": user_state,
                "system_state": system_state,
                "captured_at": _now(),
            }
            self._seen_hashes.add(h)
        # event_id is intentionally NOT used in the hash — identical states
        # across events dedupe to a single row. The pointer below uses the
        # hash, so dedup is preserved.
        del event_id  # quiet linters
        return SnapshotRef(
            table="event_snapshots",
            hash=h,
            uri=f"iceberg://aether_snapshots/event_snapshots/{h}",
        )

    # -- 5. exposure ----------------------------------------------------------

    async def write_exposures(
        self,
        *,
        project_id: str,
        event_id: str,
        event_date: str,
        impressions: Iterable[dict],
    ) -> Optional[str]:
        rows = list(impressions)
        if not rows:
            return None
        for row in rows:
            self._exposures.append({
                "event_id": event_id,
                "event_date": event_date,
                "project_id": project_id,
                "surface": row.get("surface"),
                "item_id": row.get("itemId"),
                "position": row.get("position"),
                "viewable_ms": row.get("viewableMs"),
                "viewport_pct": row.get("viewportPct"),
                "clicked": bool(row.get("clicked", False)),
                "captured_at": _now(),
            })
        return f"iceberg://aether_snapshots/exposures/{event_id}"

    # -- 15. agent_reasoning --------------------------------------------------

    async def write_agent_reasoning(
        self,
        *,
        event_id: str,
        event_date: str,
        agent_id: str,
        reasoning_text: str,
        tool_calls: list[dict],
        prompt_hash: str,
    ) -> str:
        self._reasoning.append({
            "event_id": event_id,
            "event_date": event_date,
            "agent_id": agent_id,
            "reasoning_text": reasoning_text,
            "tool_calls": tool_calls,
            "prompt_hash": prompt_hash,
            "captured_at": _now(),
        })
        return f"iceberg://aether_snapshots/agent_reasoning/{event_id}"
