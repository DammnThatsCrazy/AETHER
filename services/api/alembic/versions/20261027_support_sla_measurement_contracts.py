"""Append-only tenant registered support SLA measurement contract revisions.

Revision ID: 20261027_support_sla_measurement_contracts
Revises: 20261024_merge_360_surface_authorities
"""

from alembic import op

revision = "20261027_support_sla_measurement_contracts"
down_revision = "20261024_merge_360_surface_authorities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS support_sla_measurement_contracts (
            contract_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_provider_identity TEXT NOT NULL,
            source_sla_id TEXT NOT NULL,
            source_policy_id TEXT NOT NULL,
            source_policy_version TEXT NOT NULL,
            timer_kind TEXT NOT NULL CHECK (timer_kind IN ('first_response','resolution','custom')),
            custom_timer_name TEXT,
            registered_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            FOREIGN KEY (tenant_id, case_id, source_connection_id)
                REFERENCES support_cases (tenant_id, case_id, source_connection_id)
                ON DELETE CASCADE,
            UNIQUE (tenant_id, case_id, source_connection_id,
                    source_sla_id, source_policy_id, source_policy_version,
                    timer_kind, custom_timer_name)
        );
        CREATE INDEX support_sla_contract_case_read
            ON support_sla_measurement_contracts
                (tenant_id, case_id, source_connection_id, registered_at DESC);
        CREATE OR REPLACE FUNCTION reject_support_sla_contract_mutation()
        RETURNS trigger AS $$ BEGIN
            RAISE EXCEPTION 'support_sla_measurement_contracts is append-only';
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER support_sla_contract_append_only
            BEFORE UPDATE ON support_sla_measurement_contracts
            FOR EACH ROW EXECUTE FUNCTION reject_support_sla_contract_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS support_sla_measurement_contracts;")
    op.execute("DROP FUNCTION IF EXISTS reject_support_sla_contract_mutation();")
