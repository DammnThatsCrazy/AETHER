"""Preserve server-owned communication consent lineage.

Revision ID: 20261018_comms_consent_lineage
Revises: 20261015_tenant_owned_row_keys
Create Date: 2026-10-18

The new nullable fields carry provider-recipient identity evidence and the
server consent receipt decision made at connector ingress. Historical rows are
left unknown; no current consent state is backfilled onto past messages.
"""

from alembic import op

revision = "20261018_comms_consent_lineage"
down_revision = "20261015_tenant_owned_row_keys"
branch_labels = None
depends_on = None


_COLUMNS: tuple[tuple[str, str], ...] = (
    ("provider_recipient_id", "TEXT"),
    ("provider_profile_id", "TEXT"),
    ("sender_identity_binding_id", "TEXT"),
    ("sender_identity_evidence_source", "TEXT"),
    ("recipient_identity_binding_id", "TEXT"),
    ("consent_purpose", "TEXT"),
    ("consent_subject_id", "TEXT"),
    ("consent_evaluation_state", "TEXT"),
    ("consent_identity_binding_id", "TEXT"),
    ("consent_authority", "TEXT"),
)


def upgrade() -> None:
    for column, column_type in _COLUMNS:
        op.execute(
            f"ALTER TABLE silver_comms_facts ADD COLUMN IF NOT EXISTS {column} {column_type};"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_comms_provider_recipient "
        "ON silver_comms_facts "
        "(tenant_id, provider, provider_account_id, provider_recipient_id, occurred_at DESC) "
        "WHERE provider_recipient_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS silver_comms_provider_recipient;")
    for column, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE silver_comms_facts DROP COLUMN IF EXISTS {column};")
