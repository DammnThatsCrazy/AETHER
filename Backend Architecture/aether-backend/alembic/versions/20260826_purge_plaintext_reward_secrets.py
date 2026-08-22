"""purge plaintext reward webhook secrets from durable rows

Idempotent scrub of any plaintext ``signing_secret`` left in
``tenant_reward_rail_configs.config``, ``reward_delivery_jobs``, and reward
audit ``before_state`` / ``after_state`` snapshots. As of the credential-only
reward webhook migration, submitted secrets are dual-written into the
credential authority and rows persist only a ``secret_ref``; this migration
removes any plaintext written by older code paths.

Schema note: ``tenant_reward_rail_configs`` and ``reward_audit_log`` are
explicit-column tables (created by ``20260613_reward_enablement``) — the
former stores rail settings in a ``config`` JSONB column, the latter stores
snapshots in ``before_state`` / ``after_state`` JSONB columns — so the scrub
targets those columns directly, NOT a ``data`` column. ``reward_delivery_jobs``
is a BaseRepository (``data`` JSONB) table created at runtime, so it is guarded
and only scrubbed if the table exists.

Runs only when the tables exist (guarded with to_regclass), so it is safe on a
fresh database that never had them. Reversible as a no-op — plaintext is not
restorable, and by policy must not be.

Revision ID: 20260826_purge_plaintext_reward_secrets
Revises: 20260825_credential_audit_history
Create Date: 2026-08-26
"""

from __future__ import annotations

from alembic import op

revision = "20260826_purge_plaintext_reward_secrets"
down_revision = "20260825_credential_audit_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rail configs: strip signing_secret from the explicit `config` JSONB column.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.tenant_reward_rail_configs') IS NOT NULL THEN
            UPDATE tenant_reward_rail_configs
            SET config = config #- '{signing_secret}'
            WHERE config ? 'signing_secret';
          END IF;
        END $$;
        """
    )
    # Durable outbox jobs: strip provider_config.signing_secret.
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.reward_delivery_jobs') IS NOT NULL THEN
            UPDATE reward_delivery_jobs
            SET data = data #- '{provider_config,signing_secret}'
            WHERE data #> '{provider_config,signing_secret}' IS NOT NULL;
          END IF;
        END $$;
        """
    )
    # Reward audit snapshots: strip signing secrets from the explicit
    # before_state / after_state JSONB columns (config.signing_secret and any
    # top-level signing_secret inside a snapshot).
    op.execute(
        """
        DO $$
        BEGIN
          IF to_regclass('public.reward_audit_log') IS NOT NULL THEN
            UPDATE reward_audit_log
            SET after_state = (after_state #- '{config,signing_secret}')
                              #- '{signing_secret}',
                before_state = (before_state #- '{config,signing_secret}')
                               #- '{signing_secret}'
            WHERE after_state #> '{config,signing_secret}' IS NOT NULL
               OR after_state ? 'signing_secret'
               OR before_state #> '{config,signing_secret}' IS NOT NULL
               OR before_state ? 'signing_secret';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Plaintext removal is intentionally irreversible.
    pass
