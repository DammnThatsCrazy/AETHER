"""identity verification challenges + evidence tables

Revision ID: 20260903_identity_verification
Revises: 20260902_graph_pg_backend
Create Date: 2026-09-03
"""

from __future__ import annotations

from alembic import op

revision = "20260903_identity_verification"
down_revision = "20260902_graph_pg_backend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── identity_verification_challenges ───────────────────────────────────
    # Single-use ownership-verification challenges (OTP / magic link). The raw
    # secret is never stored — only its HMAC digest lives in data->>'secret_digest'.
    # BaseRepository-compatible JSONB `data` column (NOT a `payload` column).
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_verification_challenges (
        id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_challenges_tenant "
        "ON identity_verification_challenges (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_challenges_identifier "
        "ON identity_verification_challenges ((data->>'identifier_hash'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_challenges_state "
        "ON identity_verification_challenges ((data->>'state'))"
    )

    # ── identity_verification_evidence ─────────────────────────────────────
    # Durable proof that an identifier's ownership was verified. Append-style:
    # rows are revoked (status='revoked') rather than deleted.
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_verification_evidence (
        id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_evidence_tenant "
        "ON identity_verification_evidence (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_evidence_identifier "
        "ON identity_verification_evidence ((data->>'identifier_hash'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_evidence_status "
        "ON identity_verification_evidence ((data->>'status'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_identity_verification_evidence_entity "
        "ON identity_verification_evidence ((data->>'canonical_entity_id'))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_verification_evidence")
    op.execute("DROP TABLE IF EXISTS identity_verification_challenges")
