"""consent-aware integrations control-plane seed tables

Additive PR-0 schema for the consent-aware SDK/connector/commerce workstream.
The revision completes the durable contract surface for receipts, manifests,
detection, connector decisions, suppression, webhook quarantine, privacy action
outbox, and DSR execution steps. Existing ``consent_receipts`` deployments are
upgraded in-place with ``ADD COLUMN IF NOT EXISTS`` so no consent evidence is
discarded. Raw secrets are never stored; raw webhook evidence is represented by
an encrypted reference plus hash and expiry metadata.

Revision ID: 20260730_consent_control_plane_seed
Revises: 20260729_graph_mutation_ledger
Create Date: 2026-07-30
"""

from __future__ import annotations

from alembic import op

revision = "20260730_consent_control_plane_seed"
down_revision = "20260729_graph_mutation_ledger"
branch_labels = None
depends_on = None

RECEIPT_COLUMNS = {
    "receipt_id": "TEXT",
    "provider": "TEXT",
    "mode": "TEXT",
    "lawful_basis": "TEXT",
    "denied_at": "TIMESTAMPTZ",
    "gpc_observed": "BOOLEAN",
    "dnt_observed": "BOOLEAN",
    "provider_consent_id": "TEXT",
    "idempotency_key": "TEXT",
    "legal_hold": "BOOLEAN NOT NULL DEFAULT FALSE",
}

JSONB_TABLES = {
    "consent_receipt_history": ("receipt_id", "purpose", "policy_version"),
    "tenant_processing_profiles": ("profile_version", "status", "policy_version"),
    "integration_policy_manifests": ("manifest_version", "status", "policy_version"),
    "detected_integrations": ("provider", "capability", "policy_manifest_version"),
    "connector_policy_decisions": ("decision_id", "connector_type", "policy_version"),
    "data_inventory_fields": ("field_name", "data_category", "policy_version"),
    "suppression_ledger": ("channel", "scope", "purpose"),
    "webhook_quarantine": ("connector_type", "reason_code", "expires_at"),
    "privacy_action_outbox": ("action_type", "status", "available_at"),
    "dsr_execution_steps": ("dsr_request_id", "step_name", "status"),
}


def _jsonb_table(name: str) -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {name} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            idempotency_key TEXT,
            subject_id TEXT,
            anonymous_id TEXT,
            provider TEXT,
            purpose TEXT,
            policy_version TEXT,
            legal_hold BOOLEAN NOT NULL DEFAULT FALSE,
            expires_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, idempotency_key)
        );
    """


def upgrade() -> None:
    for column, ddl_type in RECEIPT_COLUMNS.items():
        op.execute(f"ALTER TABLE consent_receipts ADD COLUMN IF NOT EXISTS {column} {ddl_type};")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_consent_receipts_tenant_idempotency ON consent_receipts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_consent_receipts_tenant_provider ON consent_receipts (tenant_id, provider);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_consent_receipts_tenant_policy ON consent_receipts (tenant_id, policy_version);")

    for table, indexed_fields in JSONB_TABLES.items():
        op.execute(_jsonb_table(table))
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_subject ON {table} (tenant_id, subject_id) WHERE subject_id IS NOT NULL;")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_anonymous ON {table} (tenant_id, anonymous_id) WHERE anonymous_id IS NOT NULL;")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_provider ON {table} (tenant_id, provider) WHERE provider IS NOT NULL;")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_purpose ON {table} (tenant_id, purpose) WHERE purpose IS NOT NULL;")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_policy ON {table} (tenant_id, policy_version) WHERE policy_version IS NOT NULL;")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_expires ON {table} (tenant_id, expires_at) WHERE expires_at IS NOT NULL;")
        for field in indexed_fields:
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{field}_json ON {table} ((data->>'{field}'));")

    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_quarantine_expiry ON webhook_quarantine (tenant_id, expires_at) WHERE expires_at IS NOT NULL AND legal_hold = FALSE;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_privacy_action_outbox_claim ON privacy_action_outbox (tenant_id, (data->>'status'), expires_at, created_at);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_dsr_execution_steps_request ON dsr_execution_steps (tenant_id, (data->>'dsr_request_id'), (data->>'status'));")


def downgrade() -> None:
    for table in reversed(tuple(JSONB_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table};")
    for index in (
        "uix_consent_receipts_tenant_idempotency",
        "ix_consent_receipts_tenant_provider",
        "ix_consent_receipts_tenant_policy",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index};")
    for column in reversed(tuple(RECEIPT_COLUMNS)):
        op.execute(f"ALTER TABLE consent_receipts DROP COLUMN IF EXISTS {column};")
