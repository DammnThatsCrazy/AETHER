"""provider credential versions — durable multi-slot credential authority

Additive JSONB table backing the durable, encrypted, multi-slot provider-
credential authority (``services/providers/credentials/authority.py``). Follows
the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at) so the runtime repository and this migration agree. Every slot
invariant is enforced with partial/expression indexes over the JSONB ``data``.

data fields:  services/providers/credentials/schema.py::CREDENTIAL_VERSION_FIELDS
state machine: pending | active | previous | revoked | test_failed | tombstoned

Invariants (Postgres backstop; the authority enforces the same in code so the
in-memory local path behaves identically):
  * at most one ACTIVE version per (tenant, provider, environment, slot)
  * at most one PREVIOUS (bounded webhook-secret overlap) version per slot
  * version identity unique per (tenant, provider, environment, slot, version)

Purely additive and fully reversible. The legacy single-slot
``provider_api_keys`` table is left untouched.

Revision ID: 20260812_provider_credential_versions
Revises: 20260811_demo_seed_core
Create Date: 2026-08-12
"""

from __future__ import annotations

from alembic import op

revision = "20260812_provider_credential_versions"
down_revision = "20260811_demo_seed_core"
branch_labels = None
depends_on = None

# Literal tuple (not just an f-string) so the storage-policy inventory extractor
# (scripts/release/check_storage_policies.py) discovers this table and requires a
# matching policy in config/storage_policies.yaml.
_TABLES = ("provider_credential_versions",)
TABLE = _TABLES[0]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # Tenant scan (BaseRepository populates the tenant_id column on insert).
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant ON {TABLE} (tenant_id);")
    # Slot-coordinate scan.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_{TABLE}_slot ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'),
            (data->>'environment'), (data->>'slot_name')
        );
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_state ON {TABLE} ((data->>'state'));")
    # At most one ACTIVE version per slot.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_{TABLE}_active ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'),
            (data->>'environment'), (data->>'slot_name')
        ) WHERE data->>'state' = 'active';
        """
    )
    # At most one PREVIOUS (bounded overlap) version per slot.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_{TABLE}_previous ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'),
            (data->>'environment'), (data->>'slot_name')
        ) WHERE data->>'state' = 'previous';
        """
    )
    # Version identity unique per slot.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_{TABLE}_version ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'), (data->>'environment'),
            (data->>'slot_name'), (data->>'credential_version')
        );
        """
    )
    # Overlap-expiry sweep support.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_{TABLE}_overlap_exp ON {TABLE} (
            (data->>'rotation_overlap_expires_at')
        ) WHERE data->>'state' = 'previous';
        """
    )
    # Maintain updated_at (function created by an earlier migration).
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_updated BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(f"DROP TABLE IF EXISTS {TABLE};")
