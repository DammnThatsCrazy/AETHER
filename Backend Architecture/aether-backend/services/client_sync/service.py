"""Client-sync read service — cursor parsing + gap-free replay."""
from __future__ import annotations

from typing import Optional

from shared.common.common import utc_now
from shared.client_sync.models import ClientSyncResponse, SyncEvent

from repositories.client_sync_repo import get_client_sync_repository


def _parse_seq(cursor: Optional[str]) -> int:
    """Cursor is ``{epoch_ms}:{seq}``; only ``seq`` drives ordering/replay."""
    if not cursor:
        return 0
    tail = cursor.rsplit(":", 1)[-1]
    try:
        return max(0, int(tail))
    except ValueError:
        return 0


def _fmt_cursor(seq: int) -> str:
    ms = int(utc_now().timestamp() * 1000)
    return f"{ms}:{seq}"


async def read(scope_key: str, cursor: Optional[str], limit: int = 200) -> dict:
    repo = get_client_sync_repository()
    cursor_seq = _parse_seq(cursor)

    # A cursor that predates the earliest retained event forces a bounded resync.
    if cursor_seq > 0:
        min_seq = await repo.min_seq(scope_key)
        if min_seq > 0 and cursor_seq + 1 < min_seq:
            max_seq = await repo.max_seq(scope_key)
            return ClientSyncResponse(
                events=[], cursor=_fmt_cursor(max_seq), has_more=False, reset=True
            ).model_dump(mode="json")

    rows = await repo.read_since(scope_key, cursor_seq, limit)
    events = [SyncEvent(**r) for r in rows]
    last_seq = events[-1].seq if events else cursor_seq
    return ClientSyncResponse(
        events=events,
        cursor=_fmt_cursor(last_seq),
        has_more=len(events) == limit,
        reset=False,
    ).model_dump(mode="json")
