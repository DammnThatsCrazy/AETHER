"""Durable exact ticket and conversation identities for Support360."""

from alembic import op

revision = "20261105_support_case_subjects"
down_revision = "20261104_merge_value_behavior_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE support_case_subjects (
            tenant_id TEXT NOT NULL,
            subject_id UUID NOT NULL,
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('ticket', 'conversation')),
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_provider_identity TEXT NOT NULL,
            source_account_id TEXT NOT NULL,
            source_subject_id TEXT NOT NULL,
            source_case_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            source_occurred_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            connection_verified_at TIMESTAMPTZ NOT NULL,
            evidence_refs JSONB NOT NULL,
            PRIMARY KEY (tenant_id, subject_kind, subject_id),
            UNIQUE (tenant_id, source_connection_id, subject_kind, source_account_id, source_subject_id),
            UNIQUE (tenant_id, source_connection_id, source_account_id, source_event_id),
            FOREIGN KEY (tenant_id, case_id, source_connection_id)
                REFERENCES support_cases (tenant_id, case_id, source_connection_id) ON DELETE CASCADE,
            CHECK (source_occurred_at <= received_at),
            CHECK (connection_verified_at <= received_at)
        );
        CREATE INDEX support_case_subjects_case ON support_case_subjects (tenant_id, case_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE support_case_subjects")
