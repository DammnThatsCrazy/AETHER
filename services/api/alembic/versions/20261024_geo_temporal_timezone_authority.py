"""Persist source-asserted timezone facts for exact canonical locations.

Revision ID: 20261024_geo_temporal_timezone_authority
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

The geo_temporal_graph authority stores source-provided IANA timezone
assertions against exact tenant-owned location fact IDs. It does not derive
zones from coordinates, cells, place labels, or geographic hierarchy.
"""

from __future__ import annotations

from alembic import op

revision = "20261024_geo_temporal_timezone_authority"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        -- The location store is JSONB-backed by BaseRepository. Declaring its
        -- bootstrap shape here gives the timezone FK a stable migration-owned
        -- target while remaining compatible with runtime auto-creation.
        CREATE TABLE IF NOT EXISTS location_facts (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS location_facts_tenant_id_uq
            ON location_facts (tenant_id, id);

        CREATE TABLE IF NOT EXISTS geo_temporal_timezone_assertions (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            location_id TEXT GENERATED ALWAYS AS (data->>'location_id') STORED,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            FOREIGN KEY (tenant_id, location_id)
                REFERENCES location_facts (tenant_id, id)
                ON DELETE CASCADE,
            CHECK (length(btrim(tenant_id)) > 0),
            CHECK (length(btrim(location_id)) > 0),
            CHECK (jsonb_typeof(data) = 'object'),
            CHECK (data->>'assertion_state' = 'asserted'),
            CHECK (length(btrim(data->>'timezone_id')) > 0),
            CHECK (length(btrim(data->>'source_provider')) > 0),
            CHECK (length(btrim(data->>'source_record_id')) > 0),
            CHECK (jsonb_typeof(data->'evidence_refs') = 'array'),
            CHECK (jsonb_array_length(data->'evidence_refs') > 0),
            CHECK (length(btrim(data->>'observed_at')) > 0),
            CHECK (length(btrim(data->>'effective_from')) > 0),
            CHECK (length(btrim(data->>'recorded_at')) > 0)
        );
        CREATE INDEX IF NOT EXISTS geo_temporal_timezone_location_asof
            ON geo_temporal_timezone_assertions (
                tenant_id,
                location_id,
                created_at DESC,
                id ASC
            );
        CREATE INDEX IF NOT EXISTS geo_temporal_timezone_effective_asof
            ON geo_temporal_timezone_assertions (
                tenant_id,
                location_id,
                (data->>'effective_from'),
                (data->>'effective_to')
            );

        CREATE OR REPLACE FUNCTION reject_geo_temporal_timezone_assertion_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'geo_temporal_timezone_assertions is immutable';
        END;
        $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS geo_temporal_timezone_assertions_immutable
            ON geo_temporal_timezone_assertions;
        CREATE TRIGGER geo_temporal_timezone_assertions_immutable
            BEFORE UPDATE ON geo_temporal_timezone_assertions
            FOR EACH ROW EXECUTE FUNCTION reject_geo_temporal_timezone_assertion_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS geo_temporal_timezone_assertions_immutable
            ON geo_temporal_timezone_assertions;
        DROP FUNCTION IF EXISTS reject_geo_temporal_timezone_assertion_update();
        DROP INDEX IF EXISTS geo_temporal_timezone_effective_asof;
        DROP INDEX IF EXISTS geo_temporal_timezone_location_asof;
        DROP TABLE IF EXISTS geo_temporal_timezone_assertions;
        DROP INDEX IF EXISTS location_facts_tenant_id_uq;
        """
    )
