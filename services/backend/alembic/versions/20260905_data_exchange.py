"""Data Exchange Plane tables: data_artifacts + data_exchange_saved_mappings + report_renders

Metadata-only schema for the governed tenant import/export plane (M1–M5).
Payload bytes live in the shared ObjectStore, never Postgres; these tables hold
envelope metadata (data_artifacts), saved import mappings
(data_exchange_saved_mappings) and PDF report render state (report_renders).
SQL is string-identical to the ``SCHEMA_SQL`` constants in
``repositories/data_artifacts.py``, ``services/data_exchange/saved_mappings.py``
and ``services/reports/service.py``.

Revision ID: 20260905_data_exchange
Revises: 20260904_merge_communication360_head
Create Date: 2026-09-05
"""

from __future__ import annotations

from alembic import op

revision = "20260905_data_exchange"
down_revision = "20260904_merge_communication360_head"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── data_artifacts (M1) ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS data_artifacts (
        artifact_id TEXT NOT NULL,
        tenant_id TEXT NOT NULL,
        direction TEXT NOT NULL,
        artifact_type TEXT NOT NULL,
        job_id TEXT,
        canonical_id TEXT,
        source_or_destination JSONB NOT NULL DEFAULT '{}'::jsonb,
        object_key TEXT NOT NULL,
        filename TEXT NOT NULL,
        format TEXT NOT NULL,
        content_type TEXT NOT NULL,
        size_bytes BIGINT NOT NULL,
        sha256 TEXT NOT NULL,
        schema_version TEXT,
        classification TEXT NOT NULL,
        encryption JSONB NOT NULL DEFAULT '{}'::jsonb,
        manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL,
        created_by TEXT,
        correlation_id TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ,
        deleted_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id, artifact_id)
    );
    CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_direction
        ON data_artifacts (tenant_id, direction);
    CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_status
        ON data_artifacts (tenant_id, status);
    CREATE INDEX IF NOT EXISTS ix_data_artifacts_tenant_canonical
        ON data_artifacts (tenant_id, canonical_id);
    """)

    # ── data_exchange_saved_mappings (M3) ───────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS data_exchange_saved_mappings (
        mapping_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        name TEXT NOT NULL,
        import_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        fields JSONB NOT NULL DEFAULT '[]'::jsonb,
        identity_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        temporal_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        currency_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        geographic_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        consent_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        unknown_field_policy TEXT NOT NULL DEFAULT 'error',
        created_by TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_data_exchange_saved_mappings_tenant_name
        ON data_exchange_saved_mappings (tenant_id, name);
    CREATE INDEX IF NOT EXISTS ix_data_exchange_saved_mappings_tenant_import
        ON data_exchange_saved_mappings (tenant_id, import_id);
    """)

    # ── report_renders (M5) ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS report_renders (
        report_id TEXT NOT NULL,
        artifact_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        object_key TEXT NOT NULL,
        template TEXT NOT NULL,
        filename TEXT NOT NULL,
        status TEXT NOT NULL,
        size_bytes BIGINT NOT NULL DEFAULT 0,
        sha256 TEXT NOT NULL DEFAULT '',
        rendered_at TIMESTAMPTZ,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS ix_report_renders_tenant_report
        ON report_renders (tenant_id, report_id);
    CREATE INDEX IF NOT EXISTS ix_report_renders_tenant_artifact
        ON report_renders (tenant_id, artifact_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_renders")
    op.execute("DROP TABLE IF EXISTS data_exchange_saved_mappings")
    op.execute("DROP TABLE IF EXISTS data_artifacts")
