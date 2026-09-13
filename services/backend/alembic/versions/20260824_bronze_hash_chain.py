"""bronze hash-chain: prev_hash + integrity_hash (LEDGER M2)

Adds the two append-only tamper-evidence columns to ``bronze_sdk_events`` that
``services/ingestion/bronze_bulk.py::ingest_many`` populates for every NEW row,
inside its existing transaction, using the table-agnostic hash-chain primitive
``shared/integrity/hash_chain.py``
(``docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md``, Program 1, M2):

- ``prev_hash``       TEXT (nullable) — the ``integrity_hash`` of the previous
  chained row for the same tenant, or NULL for the first row of a tenant's
  chain.
- ``integrity_hash``  TEXT (nullable) — SHA-256 over the row's canonical event
  identity (tenant_id, event_id, schema_version, event_type, event_timestamp,
  payload_hash) folded with ``prev_hash``. Editing any of those hashed fields,
  deleting a row, or reordering the chain is then detectable via
  ``hash_chain.verify_chain``.

PRE-CUTOVER BOUNDARY (deliberate, documented — NOT a defect):
Both columns are NULLABLE and there is NO backfill of historical rows. Every
row written before this migration stays ``prev_hash = NULL`` /
``integrity_hash = NULL``. Ingestion treats a NULL-hash row as "not a chain
anchor": the first new row a tenant ingests after cutover starts a fresh chain
(its ``prev_hash`` is NULL) rather than attempting to chain onto un-hashed
history, and verification scopes itself to the hashed (post-cutover) rows.
Backfilling the historical Bronze tier is explicitly out of scope for M2 and
would be a separate, offline migration if ever required.

Additive and fully reversible; ``ADD COLUMN IF NOT EXISTS`` keeps the migration
correct whether ``bronze_sdk_events`` came from ``20260724_ingestion_v2`` or a
runtime auto-create. No existing data is rewritten.

Revision ID: 20260824_bronze_hash_chain
Revises: 20260823_touchpoint_conversion_fields
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op

revision = "20260824_bronze_hash_chain"
down_revision = "20260823_touchpoint_conversion_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bronze_sdk_events
            ADD COLUMN IF NOT EXISTS prev_hash       TEXT,
            ADD COLUMN IF NOT EXISTS integrity_hash  TEXT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE bronze_sdk_events
            DROP COLUMN IF EXISTS integrity_hash,
            DROP COLUMN IF EXISTS prev_hash;
        """
    )
