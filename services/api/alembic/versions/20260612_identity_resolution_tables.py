"""identity resolution durable tables

Revision ID: 20260612_identity_resolution_tables
Revises: 20260604_agent_control_plane
Create Date: 2026-06-12
"""

from __future__ import annotations

from alembic import op

revision = "20260612_identity_resolution_tables"
down_revision = "20260604_agent_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── identity_subjects ──────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_subjects (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        canonical_entity_id TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT 'user',
        status TEXT NOT NULL DEFAULT 'active',
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_subjects_tenant_entity ON identity_subjects (tenant_id, canonical_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_subjects_tenant_status ON identity_subjects (tenant_id, status)")

    # ── identity_aliases ───────────────────────────────────────────────────
    # Stores hashed signal values only — raw PII is never persisted.
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_aliases (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        canonical_entity_id TEXT NOT NULL,
        alias_type TEXT NOT NULL,
        alias_hash TEXT NOT NULL,
        alias_display_value_redacted TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'sdk',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        confidence_tier TEXT NOT NULL DEFAULT 'WEAK',
        first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked_at TIMESTAMPTZ,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uix_identity_aliases_tenant_type_hash_entity ON identity_aliases (tenant_id, alias_type, alias_hash, canonical_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_aliases_tenant_entity ON identity_aliases (tenant_id, canonical_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_aliases_tenant_type_hash ON identity_aliases (tenant_id, alias_type, alias_hash)")

    # ── identity_signal_observations ──────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_signal_observations (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        canonical_entity_id TEXT NOT NULL,
        signal_type TEXT NOT NULL,
        signal_hash TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_signal_obs_tenant_entity ON identity_signal_observations (tenant_id, canonical_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_signal_obs_tenant_event ON identity_signal_observations (tenant_id, source_event_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_signal_obs_tenant_type ON identity_signal_observations (tenant_id, signal_type, signal_hash)")

    # ── identity_clusters_v2 ───────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_clusters_v2 (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        canonical_entity_id TEXT NOT NULL,
        cluster_status TEXT NOT NULL DEFAULT 'active',
        member_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        confidence_tier TEXT NOT NULL DEFAULT 'WEAK',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_clusters_v2_tenant_entity ON identity_clusters_v2 (tenant_id, canonical_entity_id)")

    # ── identity_edges ─────────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_edges (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        from_entity_id TEXT NOT NULL,
        to_entity_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        status TEXT NOT NULL DEFAULT 'active',
        source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        revoked_at TIMESTAMPTZ,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_edges_tenant_from ON identity_edges (tenant_id, from_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_edges_tenant_to ON identity_edges (tenant_id, to_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_edges_tenant_type ON identity_edges (tenant_id, edge_type, status)")

    # ── identity_merge_events ──────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_merge_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        from_entity_id TEXT NOT NULL,
        into_entity_id TEXT NOT NULL,
        resulting_entity_id TEXT NOT NULL,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        confidence_tier TEXT NOT NULL DEFAULT 'WEAK',
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        actor_type TEXT NOT NULL DEFAULT 'system',
        actor_id TEXT NOT NULL DEFAULT '',
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_merge_events_tenant ON identity_merge_events (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_merge_events_from ON identity_merge_events (tenant_id, from_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_merge_events_into ON identity_merge_events (tenant_id, into_entity_id)")

    # ── identity_split_events ──────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_split_events (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        original_entity_id TEXT NOT NULL,
        resulting_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        reason TEXT NOT NULL DEFAULT '',
        actor_type TEXT NOT NULL DEFAULT 'operator',
        actor_id TEXT NOT NULL DEFAULT '',
        source_merge_event_id TEXT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_split_events_tenant ON identity_split_events (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_split_events_original ON identity_split_events (tenant_id, original_entity_id)")

    # ── identity_conflicts ─────────────────────────────────────────────────
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_conflicts (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        candidate_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        candidate_aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
        conflict_type TEXT NOT NULL DEFAULT 'ambiguous_match',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        status TEXT NOT NULL DEFAULT 'open',
        resolved_at TIMESTAMPTZ,
        resolved_by TEXT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_conflicts_tenant_status ON identity_conflicts (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_conflicts_tenant_created ON identity_conflicts (tenant_id, created_at DESC)")

    # ── identity_resolution_audit ──────────────────────────────────────────
    # Append-only; rows must never be deleted or updated.
    op.execute("""
    CREATE TABLE IF NOT EXISTS identity_resolution_audit (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        canonical_entity_id TEXT NOT NULL,
        candidate_entity_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
        confidence_tier TEXT NOT NULL DEFAULT 'WEAK',
        reason_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
        source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        policy_result TEXT NOT NULL DEFAULT '',
        consent_snapshot JSONB,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_audit_tenant_entity ON identity_resolution_audit (tenant_id, canonical_entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_audit_tenant_created ON identity_resolution_audit (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_identity_audit_tenant_decision ON identity_resolution_audit (tenant_id, decision)")


def downgrade() -> None:
    tables = [
        "identity_resolution_audit",
        "identity_conflicts",
        "identity_split_events",
        "identity_merge_events",
        "identity_edges",
        "identity_clusters_v2",
        "identity_signal_observations",
        "identity_aliases",
        "identity_subjects",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table}")
