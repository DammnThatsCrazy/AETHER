"""Fix campaign_resolution_reviews unique constraint to partial index on open status.

Revision ID: cr002fixreview
Revises: cr001a2b3c4d
Create Date: 2026-06-27
"""

from alembic import op

revision = "cr002fixreview"
down_revision = "cr001a2b3c4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The original UNIQUE (tenant_id, evidence_hash, status) constraint allows
    # multiple rows per (tenant_id, evidence_hash) as long as statuses differ.
    # This causes a uniqueness violation when a resolved review is re-resolved:
    # the second resolution attempt produces another 'resolved' row.
    # Replace with a partial index that only enforces uniqueness for open reviews.
    op.execute("""
        ALTER TABLE campaign_resolution_reviews
            DROP CONSTRAINT IF EXISTS
                campaign_resolution_reviews_tenant_id_evidence_hash_status_key;
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS crr_open_dedup_idx
            ON campaign_resolution_reviews (tenant_id, evidence_hash)
            WHERE status = 'open';
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS crr_open_dedup_idx;")
    op.execute("""
        ALTER TABLE campaign_resolution_reviews
            ADD CONSTRAINT campaign_resolution_reviews_tenant_id_evidence_hash_status_key
            UNIQUE (tenant_id, evidence_hash, status);
    """)
