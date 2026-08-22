"""outbox hash-chain: prev_hash + integrity_hash (LEDGER M4)

Adds the two append-only tamper-evidence columns to ``event_outbox`` that
``services/ingestion/bronze_bulk.py::ingest_many`` populates for every NEW outbox
row, inside its existing transaction, using the table-agnostic hash-chain
primitive ``shared/integrity/hash_chain.py``
(``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md``, Program 1, M4). This
mirrors the Bronze chain added in M2 (``20260824_bronze_hash_chain``), extending
the same per-tenant tamper-evidence to the relay's transactional outbox:

- ``prev_hash``       TEXT (nullable) — the ``integrity_hash`` of the previous
  chained outbox row for the same tenant, or NULL for the first row of a
  tenant's chain.
- ``integrity_hash``  TEXT (nullable) — SHA-256 over the outbox row's canonical
  routing identity (event_id, tenant_id, topic, partition_key, payload_hash)
  folded with ``prev_hash``. Editing any of those hashed fields, deleting a row,
  or reordering the chain is then detectable via ``hash_chain.verify_chain``.
  Volatile relay/ingest state (status, attempt_count, available_at, claimed_at,
  claim_owner, published_at, last_error, created_at/updated_at) is deliberately
  NOT hashed, so the tamper-evidence covers WHAT will be published, not the
  relay's mutable delivery bookkeeping.

PRE-CUTOVER BOUNDARY (deliberate, documented — NOT a defect):
Both columns are NULLABLE and there is NO backfill of historical rows. Every
outbox row written before this migration stays ``prev_hash = NULL`` /
``integrity_hash = NULL``. Ingestion treats a NULL-hash row as "not a chain
anchor": the first new outbox row a tenant enqueues after cutover starts a fresh
chain (its ``prev_hash`` is NULL) rather than attempting to chain onto un-hashed
history, and verification scopes itself to the hashed (post-cutover) rows.
Backfilling the historical outbox is explicitly out of scope for M4 and would be
a separate, offline migration if ever required.

Additive and fully reversible; ``ADD COLUMN IF NOT EXISTS`` keeps the migration
correct whether ``event_outbox`` came from ``20260724_ingestion_v2`` or a runtime
auto-create. No existing data is rewritten.

Revision ID: 20260825_outbox_hash_chain
Revises: 20260824_bronze_hash_chain
Create Date: 2026-08-25
"""

from __future__ import annotations

from alembic import op

revision = "20260825_outbox_hash_chain"
down_revision = "20260824_bronze_hash_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE event_outbox
            ADD COLUMN IF NOT EXISTS prev_hash       TEXT,
            ADD COLUMN IF NOT EXISTS integrity_hash  TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE event_outbox
            DROP COLUMN IF EXISTS integrity_hash,
            DROP COLUMN IF EXISTS prev_hash;
        """
    )
