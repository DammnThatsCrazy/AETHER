"""Tenant-owned row keys: backfill row tenants and key per-tenant records by tenant

``BaseRepository.insert``/``update`` now replace a row only when its
``tenant_id`` column matches the writing tenant, and graph vertex writes keep a
vertex's owner. This brings existing rows in line, idempotently:

1. Every ``(id, data jsonb, tenant_id)`` table: a row whose ``tenant_id`` column
   is empty takes the tenant its JSON names (``tenant_id`` or ``tenantId``,
   only when the two do not disagree). This covers ``event_envelopes``, whose
   writer stored the tenant only as ``tenantId``. Rows naming no tenant are
   left as they are; they stay unreadable to tenant-scoped reads.
2. Seeded web3 registry rows (``source = 'seed'``) that still have no tenant
   become the shared ``system`` rows the registries already read.
3. ``behavior_profiles`` / ``journey_chains``: rows whose JSON tenant differs
   from the column are deleted (the profile workers recompute them); the rest
   are re-keyed ``{tenant}:{entity}`` and journey chains take the chain id
   ``journey_chain:{tenant}:{entity}``.
4. ``event_envelopes`` rows are re-keyed ``{tenant}:{envelope id}``, keeping
   the envelope id in ``envelope_id``.
5. x402 commerce rows (``20260827_commerce_tables`` plus
   ``commerce_signer_refs``) are re-keyed ``{tenant}:{object id}``, the tenant
   being the one the row's JSON names. Demo-seed rows keep their tenant-unique
   ids.
6. ``graph_vertices``: ``chain:`` and card catalog (``card_program:``,
   ``card_issuer:``, ``payment_network:``) vertices become ``platform`` owned.

Runtime-created tables are skipped when absent. A re-key never overwrites a row
already stored under the new id; run the migration again after the rollout to
pick up rows old workers wrote mid-deploy.

Downgrade is a no-op: deleted contaminated rows cannot be restored, and moving
re-keyed rows back could collide with rows written under the bare ids.

Revision ID: 20261015_tenant_owned_row_keys
Revises: 20261012_merge_source_access_heads
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

revision = "20261015_tenant_owned_row_keys"
down_revision = "20261012_merge_source_access_heads"
branch_labels = None
depends_on = None

# Global tables whose rows are not tenant-owned (repositories opt out of the
# ownership check); their tenant column is left as written.
_GLOBAL = (
    "users", "tenants", "first_admin_bootstrap",
    "dune_bronze_records", "dune_silver_records", "dune_gold_records",
    "dune_feeder_stats", "dune_feeder_configs", "dune_feeder_runs",
)

_WEB3_SEEDED = (
    "web3_chains", "web3_protocols", "web3_apps", "web3_tokens",
    "web3_market_venues", "web3_governance_spaces",
)

_COMMERCE = (
    "commerce_challenges", "commerce_approvals", "commerce_entitlements",
    "commerce_settlements", "commerce_resources", "commerce_policies",
    "commerce_facilitators", "commerce_assets", "commerce_authorizations",
    "commerce_receipts", "commerce_grants", "commerce_fulfillments",
    "commerce_treasuries", "commerce_budget_policies", "commerce_signer_refs",
)

_PLATFORM_VERTEX_PREFIXES = ("chain:", "card_program:", "card_issuer:", "payment_network:")


def _if_table(table: str, body: str) -> str:
    return f"""
        DO $$
        BEGIN
          IF to_regclass('{table}') IS NOT NULL THEN
            {body}
          END IF;
        END $$;
    """


def _backfill_tenant_from_json() -> str:
    excluded = ", ".join(f"'{t}'" for t in _GLOBAL)
    return f"""
        DO $$
        DECLARE t text;
        BEGIN
          FOR t IN
            SELECT c.table_name FROM information_schema.columns c
            WHERE c.table_schema = current_schema()
              AND c.column_name = 'data' AND c.data_type = 'jsonb'
              AND c.table_name NOT IN ({excluded})
              AND EXISTS (
                SELECT 1 FROM information_schema.columns k
                WHERE k.table_schema = c.table_schema AND k.table_name = c.table_name
                  AND k.column_name = 'tenant_id' AND k.data_type = 'text')
          LOOP
            EXECUTE format(
              'UPDATE %I SET tenant_id = COALESCE(NULLIF(data->>''tenant_id'', ''''), data->>''tenantId'')
               WHERE (tenant_id IS NULL OR tenant_id = '''')
                 AND COALESCE(NULLIF(data->>''tenant_id'', ''''), NULLIF(data->>''tenantId'', '''')) IS NOT NULL
                 AND (COALESCE(data->>''tenant_id'', '''') = ''''
                      OR COALESCE(data->>''tenantId'', '''') = ''''
                      OR data->>''tenant_id'' = data->>''tenantId'')',
              t);
          END LOOP;
        END $$;
    """


def _seed_rows_to_system(table: str) -> str:
    return _if_table(table, f"""
            UPDATE {table}
            SET tenant_id = 'system',
                data = data || jsonb_build_object('tenant_id', 'system')
            WHERE (tenant_id IS NULL OR tenant_id = '')
              AND COALESCE(data->>'tenant_id', '') = ''
              AND COALESCE(data->>'tenantId', '') = ''
              AND data->>'source' = 'seed';""")


def _rekey_profile_rows(table: str, old_key: str, extra: str) -> str:
    """Delete contaminated rows, then move ``old_key`` rows to ``{tenant}:{entity}``."""
    new_id = f"{table}.tenant_id || ':' || ({table}.data->>'entity_id')"
    return _if_table(table, f"""
            DELETE FROM {table}
            WHERE COALESCE(data->>'tenant_id', '') <> COALESCE(tenant_id, '');
            DELETE FROM {table}
            WHERE {old_key} AND COALESCE(tenant_id, '') <> ''
              AND EXISTS (SELECT 1 FROM {table} AS keyed WHERE keyed.id = {new_id});
            UPDATE {table}
            SET id = {new_id},
                data = data || jsonb_build_object('id', {new_id}{extra})
            WHERE {old_key} AND COALESCE(tenant_id, '') <> ''
              AND data->>'entity_id' IS NOT NULL;""")


def _rekey_envelopes() -> str:
    new_id = "event_envelopes.tenant_id || ':' || event_envelopes.id"
    return _if_table("event_envelopes", f"""
            UPDATE event_envelopes
            SET id = {new_id},
                data = data || jsonb_build_object(
                    'id', {new_id}, 'envelope_id', id, 'tenant_id', tenant_id)
            WHERE COALESCE(tenant_id, '') <> ''
              AND NOT (data ? 'envelope_id')
              AND NOT EXISTS (
                SELECT 1 FROM event_envelopes AS keyed WHERE keyed.id = {new_id});""")


def _rekey_commerce(table: str) -> str:
    owner = f"{table}.data->>'tenant_id'"
    new_id = f"{owner} || ':' || {table}.id"
    return _if_table(table, f"""
            UPDATE {table}
            SET tenant_id = {owner},
                id = {new_id},
                data = data || jsonb_build_object('id', {new_id})
            WHERE COALESCE({owner}, '') <> ''
              AND left(id, length({owner}) + 1) <> {owner} || ':'
              AND COALESCE(data->>'data_origin', '') <> 'synthetic_seed'
              AND NOT EXISTS (SELECT 1 FROM {table} AS keyed WHERE keyed.id = {new_id});""")


def _platform_vertices() -> str:
    prefixes = " OR ".join(f"vertex_id LIKE '{p}%'" for p in _PLATFORM_VERTEX_PREFIXES)
    return _if_table("graph_vertices", f"""
            UPDATE graph_vertices
            SET tenant_id = 'platform',
                properties = properties
                    || jsonb_build_object('tenantId', 'platform', 'tenant_id', 'platform'),
                updated_at = NOW()
            WHERE ({prefixes})
              AND (tenant_id IS DISTINCT FROM 'platform'
                   OR properties->>'tenantId' IS DISTINCT FROM 'platform'
                   OR properties->>'tenant_id' IS DISTINCT FROM 'platform');""")


def upgrade() -> None:
    op.execute(_backfill_tenant_from_json())
    for table in _WEB3_SEEDED:
        op.execute(_seed_rows_to_system(table))
    op.execute(_rekey_profile_rows(
        "behavior_profiles", "behavior_profiles.id = behavior_profiles.data->>'entity_id'", "",
    ))
    op.execute(_rekey_profile_rows(
        "journey_chains", "journey_chains.id LIKE 'chain:%'",
        ", 'chain_id', 'journey_chain:' || journey_chains.tenant_id"
        " || ':' || (journey_chains.data->>'entity_id')",
    ))
    op.execute(_rekey_envelopes())
    for table in _COMMERCE:
        op.execute(_rekey_commerce(table))
    op.execute(_platform_vertices())


def downgrade() -> None:
    """No-op: contaminated rows were deleted and re-keyed rows may collide with bare ids."""
