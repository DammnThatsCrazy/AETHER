"""Journey persistence must serialize asyncpg UUID values.

DSR erasure rebuilds journeys (``JourneyCompiler.rebuild_affected_by_consent_change``).
On Postgres the activity/session identifiers read back from ``canonical_activity``
are ``uuid.UUID`` objects, and the JSONB id-list columns were encoded with a bare
``json.dumps``. Every erasure then failed its measurement step with
``Object of type UUID is not JSON serializable`` and retried until dead-lettered.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager

from services.measurement.repositories.journey_repo import JourneyRepository


class _RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[tuple] = []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


class _RecordingPool:
    def __init__(self, conn: _RecordingConnection) -> None:
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def test_create_version_encodes_uuid_identifier_lists():
    conn = _RecordingConnection()
    repo = JourneyRepository()

    async def _pool():
        return _RecordingPool(conn)

    repo._pool = _pool  # type: ignore[method-assign]
    activity_id, session_id = uuid.uuid4(), uuid.uuid4()

    asyncio.run(repo.create_version({
        "tenant_id": "tenant-a",
        "profile_id": "subject-1",
        "event_ids": [activity_id],
        "session_ids": [session_id],
        "conversion_ids": [uuid.uuid4()],
        "touchpoint_ids": [],
        "channel_sequence": ["direct"],
    }))

    insert = next(args for sql, args in conn.executed if "INSERT INTO journey_versions" in sql)
    encoded = [value for value in insert if isinstance(value, str) and value.startswith("[")]
    assert json.dumps([str(activity_id)]) in encoded
    assert json.dumps([str(session_id)]) in encoded
