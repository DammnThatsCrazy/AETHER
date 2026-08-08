"""provider_evidence — provider-attested access evidence

Additive table for PR 3 (Agent Access Intelligence, Phase A, monoprompt §9.6). A row
records what a PROVIDER reported about an agent's access to a capability, attributed to
that provider. It is provider-attested, NOT platform-verified — nothing in this platform
authenticates a third-party publisher — so no column here (and no field in the JSONB
payload) implies verification. `verification_status` carries the provider's own claim,
drawn from the existing `ProviderVerificationStatus` enum in
`services/agentic_observability/provider_framework.py`.

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at) so the runtime JSONB repository and this migration agree. Expression indexes
cover only what the API actually filters — `provider_id` and `capability_id` from
`GET /v1/capability-providers/evidence` (via `_ScopedRepo.list_for_tenant` →
`BaseRepository.find_many`, which filters `data->>'key'`) — deliberately NOT
`publisher_ref`, which is written but never queried and whose index in
`20260806_capability_declarations` had to be corrected by `20260807`. Purely additive;
fully reversible.

Revision ID: 20260808_provider_evidence
Revises: 20260807_capability_declaration_indexes
Create Date: 2026-08-08
"""

from __future__ import annotations

from alembic import op

revision = "20260808_provider_evidence"
down_revision = "20260807_capability_declaration_indexes"
branch_labels = None
depends_on = None

_TABLE = "provider_evidence"

# `id` is the deterministic `evidence_id` (`ev_` + sha256 over tenant|provider_id|
# capability_id|external_account_id), so re-capturing one provider claim upserts a single
# row rather than accumulating rows that would each carry their own status.
#
# The table name is written LITERALLY in the DDL below, not interpolated. The storage-policy
# gate (scripts/release/check_storage_policies.py) discovers tables by scanning migrations
# for literal `CREATE TABLE IF NOT EXISTS <name>` plus list/dict table constants; a name
# interpolated from a plain string constant is invisible to it, so the table would appear
# to have no policy and the policy would appear to describe no table.
_DDL = """
    CREATE TABLE IF NOT EXISTS provider_evidence (
        id TEXT PRIMARY KEY,
        tenant_id TEXT,
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""


def upgrade() -> None:
    op.execute(_DDL)
    # Tenant scoping is on every read (`_ScopedRepo.list_for_tenant`) and is also the DSR
    # erasure key (`delete_by_entity(entity_field="tenant_id")`).
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant ON {_TABLE} (tenant_id);")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_provider "
        f"ON {_TABLE} ((data->>'provider_id'));"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_capability "
        f"ON {_TABLE} ((data->>'capability_id'));"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE};")
