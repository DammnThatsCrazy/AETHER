"""ingestion v2 — typed Bronze SDK events + transactional outbox

Additive tables for PR 5 (typed Bronze + transactional outbox + /v1/batch V2):

- ``bronze_sdk_events`` — the durable Bronze tier for SDK ingestion. This is the
  SAME table the V1 path already writes to via ``BronzeRepository("sdk_events")``
  (BaseRepository shape: ``id`` / ``data`` / ``tenant_id`` / ``created_at`` /
  ``updated_at``). This migration ADDS the typed convenience columns V2 populates
  and a real composite-unique index. Because the V1 path may have already
  auto-created the minimal table at runtime, every typed column is added with
  ``ADD COLUMN IF NOT EXISTS`` so the migration is correct whether the table is
  fresh or pre-existing. DB uniqueness — ``(tenant_id, event_id, schema_version)``
  — is the correctness source for idempotent ingestion (Redis is no longer a
  correctness dependency).

- ``event_outbox`` — the transactional outbox. V2 writes one row per accepted
  event in the SAME transaction as the Bronze insert. A later relay worker
  (PR 6) claims ``pending`` rows via the ``(status, available_at, created_at)``
  claim index and publishes them to the bus, then marks them ``published``.
  Statuses: pending / claimed / published / retry / dead_letter.

Both tables follow the BaseRepository shape so the runtime JSONB repositories and
this migration agree. Composite uniqueness is expressed as UNIQUE INDEXes (which
back ``ON CONFLICT`` upserts and are idempotent via ``IF NOT EXISTS``). Purely
additive; no destructive changes. Fully reversible.

Revision ID: 20260724_ingestion_v2
Revises: 20260722_trust_plane
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op

revision = "20260724_ingestion_v2"
down_revision = "20260722_trust_plane"
branch_labels = None
depends_on = None


# ── bronze_sdk_events ────────────────────────────────────────────────────────
# CREATE handles a fresh database; the ADD COLUMN IF NOT EXISTS block upgrades a
# table that the V1 BaseRepository path already auto-created with the minimal
# (id/data/tenant_id/created_at/updated_at) shape.
_BRONZE_CREATE = """
CREATE TABLE IF NOT EXISTS bronze_sdk_events (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenant_id TEXT,
    event_id TEXT,
    schema_version TEXT,
    batch_id TEXT,
    event_type TEXT,
    event_family TEXT,
    event_timestamp TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    session_id TEXT,
    anonymous_id TEXT,
    user_id TEXT,
    entity_id TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_bytes INTEGER,
    payload_hash TEXT,
    source TEXT,
    source_tag TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_BRONZE_COLUMNS = {
    "data": "JSONB NOT NULL DEFAULT '{}'::jsonb",
    "tenant_id": "TEXT",
    "event_id": "TEXT",
    "schema_version": "TEXT",
    "batch_id": "TEXT",
    "event_type": "TEXT",
    "event_family": "TEXT",
    "event_timestamp": "TIMESTAMPTZ",
    "received_at": "TIMESTAMPTZ",
    "session_id": "TEXT",
    "anonymous_id": "TEXT",
    "user_id": "TEXT",
    "entity_id": "TEXT",
    "payload": "JSONB NOT NULL DEFAULT '{}'::jsonb",
    "payload_bytes": "INTEGER",
    "payload_hash": "TEXT",
    "source": "TEXT",
    "source_tag": "TEXT",
    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
    "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
}

_BRONZE_INDEXES = [
    # Composite idempotency key — backs ON CONFLICT (tenant_id, event_id,
    # schema_version) DO NOTHING for bulk ingest.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_bronze_sdk_events_key "
    "ON bronze_sdk_events (tenant_id, event_id, schema_version);",
    "CREATE INDEX IF NOT EXISTS ix_bronze_sdk_events_tenant_received "
    "ON bronze_sdk_events (tenant_id, received_at DESC);",
    "CREATE INDEX IF NOT EXISTS ix_bronze_sdk_events_batch "
    "ON bronze_sdk_events (batch_id);",
]


# ── event_outbox ─────────────────────────────────────────────────────────────
_OUTBOX_CREATE = """
CREATE TABLE IF NOT EXISTS event_outbox (
    id TEXT PRIMARY KEY,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenant_id TEXT,
    event_id TEXT,
    topic TEXT,
    partition_key TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    claim_owner TEXT,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_OUTBOX_COLUMNS = {
    "data": "JSONB NOT NULL DEFAULT '{}'::jsonb",
    "tenant_id": "TEXT",
    "event_id": "TEXT",
    "topic": "TEXT",
    "partition_key": "TEXT",
    "payload": "JSONB NOT NULL DEFAULT '{}'::jsonb",
    "status": "TEXT NOT NULL DEFAULT 'pending'",
    "attempt_count": "INTEGER NOT NULL DEFAULT 0",
    "available_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
    "claimed_at": "TIMESTAMPTZ",
    "claim_owner": "TEXT",
    "published_at": "TIMESTAMPTZ",
    "last_error": "TEXT",
    "created_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
    "updated_at": "TIMESTAMPTZ NOT NULL DEFAULT now()",
}

_OUTBOX_INDEXES = [
    # One outbox row per (tenant, event, topic) — backs ON CONFLICT
    # (tenant_id, event_id, topic) DO NOTHING so a re-ingested event is never
    # re-queued for publish.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_event_outbox_key "
    "ON event_outbox (tenant_id, event_id, topic);",
    # Relay claim index: fetch the oldest available pending/retry rows.
    "CREATE INDEX IF NOT EXISTS ix_event_outbox_claim "
    "ON event_outbox (status, available_at, created_at);",
]

_DROP_INDEXES = [
    "DROP INDEX IF EXISTS ix_event_outbox_claim;",
    "DROP INDEX IF EXISTS ux_event_outbox_key;",
    "DROP INDEX IF EXISTS ix_bronze_sdk_events_batch;",
    "DROP INDEX IF EXISTS ix_bronze_sdk_events_tenant_received;",
    "DROP INDEX IF EXISTS ux_bronze_sdk_events_key;",
]


def upgrade() -> None:
    op.execute(_BRONZE_CREATE)
    for col, ddl in _BRONZE_COLUMNS.items():
        op.execute(f"ALTER TABLE bronze_sdk_events ADD COLUMN IF NOT EXISTS {col} {ddl};")
    for ddl in _BRONZE_INDEXES:
        op.execute(ddl)

    op.execute(_OUTBOX_CREATE)
    for col, ddl in _OUTBOX_COLUMNS.items():
        op.execute(f"ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS {col} {ddl};")
    for ddl in _OUTBOX_INDEXES:
        op.execute(ddl)


def downgrade() -> None:
    for ddl in _DROP_INDEXES:
        op.execute(ddl)
    # event_outbox is new in this migration — safe to drop entirely.
    op.execute("DROP TABLE IF EXISTS event_outbox;")
    # bronze_sdk_events predates this migration (V1 owns the BaseRepository
    # shape). Only drop the typed columns this migration added; never drop the
    # table or the id/data/tenant_id/created_at/updated_at base columns.
    _base = {"id", "data", "tenant_id", "created_at", "updated_at"}
    for col in _BRONZE_COLUMNS:
        if col in _base:
            continue
        op.execute(f"ALTER TABLE bronze_sdk_events DROP COLUMN IF EXISTS {col};")
