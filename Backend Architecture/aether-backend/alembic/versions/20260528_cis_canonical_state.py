"""CIS canonical state — provenance, verification, quarantine, approvals, governance.

Revision ID: cis001a2b3c4d
Revises: d5e6f7a8b9c0
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "cis001a2b3c4d"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cis_provenance_records ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cis_provenance_records (
            provenance_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               TEXT NOT NULL,
            entity_id               TEXT NOT NULL,
            entity_type             TEXT NOT NULL,
            lineage_hash            TEXT NOT NULL,
            origin_agent_id         TEXT,
            generation_model        TEXT,
            retrieval_ids           TEXT[] NOT NULL DEFAULT '{}',
            contamination_score     FLOAT NOT NULL DEFAULT 0.0,
            synthetic_flag          BOOLEAN NOT NULL DEFAULT FALSE,
            synthetic_depth         INTEGER NOT NULL DEFAULT 0,
            parent_provenance_ids   TEXT[] NOT NULL DEFAULT '{}',
            raw_metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS cis_prov_tenant_entity ON cis_provenance_records (tenant_id, entity_id);")
    op.execute("CREATE INDEX IF NOT EXISTS cis_prov_contamination ON cis_provenance_records (tenant_id, contamination_score DESC) WHERE contamination_score > 0.5;")
    op.execute("CREATE INDEX IF NOT EXISTS cis_prov_synthetic ON cis_provenance_records (tenant_id) WHERE synthetic_flag = TRUE;")
    op.execute("CREATE INDEX IF NOT EXISTS cis_prov_created ON cis_provenance_records (tenant_id, created_at DESC);")

    # ── cis_verification_states ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cis_verification_states (
            entity_id               TEXT NOT NULL,
            tenant_id               TEXT NOT NULL,
            verification_epoch      INTEGER NOT NULL DEFAULT 0,
            verification_score      FLOAT NOT NULL DEFAULT 0.0,
            last_verified_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            verifier_agent_id       TEXT,
            status                  TEXT NOT NULL DEFAULT 'unverified',
            PRIMARY KEY (entity_id, tenant_id),
            CONSTRAINT cis_verif_status_check CHECK (
                status IN ('unverified', 'verified', 'contested', 'revoked')
            )
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS cis_verif_tenant_status ON cis_verification_states (tenant_id, status);")

    # ── cis_quarantine_records ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cis_quarantine_records (
            quarantine_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            mutation_id             TEXT NOT NULL,
            tenant_id               TEXT NOT NULL,
            risk_score              FLOAT NOT NULL,
            risk_band               TEXT NOT NULL,
            originating_agent_id    TEXT,
            entity_id               TEXT NOT NULL,
            entity_type             TEXT NOT NULL,
            proposed_changes        JSONB NOT NULL DEFAULT '{}'::jsonb,
            status                  TEXT NOT NULL DEFAULT 'quarantined',
            initiated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at             TIMESTAMPTZ,
            resolved_by             TEXT,
            resolution_reason       TEXT,
            CONSTRAINT cis_quar_status_check CHECK (
                status IN ('quarantined', 'released', 'escalated', 'rejected')
            )
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS cis_quar_tenant_status ON cis_quarantine_records (tenant_id, status, initiated_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS cis_quar_mutation ON cis_quarantine_records (mutation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS cis_quar_open ON cis_quarantine_records (tenant_id, initiated_at DESC) WHERE status = 'quarantined';")

    # ── cis_mutation_approvals ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cis_mutation_approvals (
            approval_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            mutation_id             TEXT NOT NULL,
            tenant_id               TEXT NOT NULL,
            decision                TEXT NOT NULL,
            reviewer_id             TEXT NOT NULL,
            reason                  TEXT,
            risk_score_at_review    FLOAT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT cis_approval_decision_check CHECK (
                decision IN ('approved', 'rejected')
            )
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS cis_approval_mutation ON cis_mutation_approvals (mutation_id);")
    op.execute("CREATE INDEX IF NOT EXISTS cis_approval_tenant ON cis_mutation_approvals (tenant_id, created_at DESC);")

    # ── cis_tenant_governance_state ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS cis_tenant_governance_state (
            tenant_id               TEXT PRIMARY KEY,
            health_score            FLOAT NOT NULL DEFAULT 100.0,
            drift_score             FLOAT NOT NULL DEFAULT 0.0,
            contamination_index     FLOAT NOT NULL DEFAULT 0.0,
            retrieval_integrity     FLOAT NOT NULL DEFAULT 1.0,
            provenance_coverage     FLOAT NOT NULL DEFAULT 0.0,
            quarantine_queue_depth  INTEGER NOT NULL DEFAULT 0,
            last_computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata                JSONB NOT NULL DEFAULT '{}'::jsonb
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cis_tenant_governance_state;")
    op.execute("DROP TABLE IF EXISTS cis_mutation_approvals;")
    op.execute("DROP TABLE IF EXISTS cis_quarantine_records;")
    op.execute("DROP TABLE IF EXISTS cis_verification_states;")
    op.execute("DROP TABLE IF EXISTS cis_provenance_records;")
