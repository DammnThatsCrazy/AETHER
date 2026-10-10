"""A6 Reward Enablement — durable storage for campaigns, rules, decisions,
proofs, action payloads, receipts, audit log, rail configs, and contract registry.

Revision ID: 20260613_reward_enablement
Revises: 20260612_identity_resolution_tables
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op

revision = "20260613_reward_enablement"
down_revision = "20260612_identity_resolution_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── reward_campaigns ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_campaigns (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               TEXT NOT NULL,
            project_id              TEXT,
            name                    TEXT NOT NULL,
            description             TEXT,
            status                  TEXT NOT NULL DEFAULT 'active',
            start_time              TIMESTAMPTZ,
            end_time                TIMESTAMPTZ,
            reward_objective        TEXT,
            default_execution_mode  TEXT NOT NULL DEFAULT 'recommend_only',
            default_rail            TEXT NOT NULL DEFAULT 'recommend_only',
            attribution_model       TEXT NOT NULL DEFAULT 'last_touch',
            fraud_policy_id         TEXT,
            consent_policy_id       TEXT,
            budget_policy           JSONB NOT NULL DEFAULT '{}'::jsonb,
            external_campaign_ref   TEXT,
            created_by              TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at             TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS rc_tenant_status_idx ON reward_campaigns (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS rc_project_idx ON reward_campaigns (project_id) WHERE archived_at IS NULL")

    # ── reward_rules ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_rules (
            id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                       TEXT NOT NULL,
            campaign_id                     UUID NOT NULL REFERENCES reward_campaigns(id) ON DELETE CASCADE,
            name                            TEXT NOT NULL,
            description                     TEXT,
            event_types                     TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            required_channel                TEXT,
            required_properties             JSONB NOT NULL DEFAULT '{}'::jsonb,
            min_attribution_weight          NUMERIC(5,4) NOT NULL DEFAULT 0.0,
            min_attribution_confidence      NUMERIC(5,4) NOT NULL DEFAULT 0.0,
            max_fraud_score                 NUMERIC(6,2) NOT NULL DEFAULT 40.0,
            identity_confidence_min         NUMERIC(5,4) NOT NULL DEFAULT 0.0,
            wallet_binding_confidence_min   NUMERIC(5,4) NOT NULL DEFAULT 0.0,
            requires_wallet                 BOOLEAN NOT NULL DEFAULT FALSE,
            requires_account                BOOLEAN NOT NULL DEFAULT FALSE,
            requires_consent_purposes       TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            cooldown_seconds                INT NOT NULL DEFAULT 86400,
            max_per_user                    INT NOT NULL DEFAULT 1,
            max_total_uses                  INT,
            reward_amount                   NUMERIC(36,18),
            reward_unit                     TEXT,
            reward_currency                 TEXT,
            reward_metadata                 JSONB NOT NULL DEFAULT '{}'::jsonb,
            execution_mode                  TEXT NOT NULL DEFAULT 'recommend_only',
            rail                            TEXT NOT NULL DEFAULT 'recommend_only',
            priority                        INT NOT NULL DEFAULT 0,
            active                          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS rr_campaign_priority_idx ON reward_rules (campaign_id, priority, active)")
    op.execute("CREATE INDEX IF NOT EXISTS rr_tenant_idx ON reward_rules (tenant_id, active)")
    op.execute("CREATE INDEX IF NOT EXISTS rr_event_types_gin ON reward_rules USING GIN (event_types)")

    # ── reward_eligibility_decisions ────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_eligibility_decisions (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id                   TEXT NOT NULL,
            project_id                  TEXT,
            campaign_id                 UUID REFERENCES reward_campaigns(id),
            rule_id                     UUID REFERENCES reward_rules(id),
            event_id                    TEXT,
            journey_id                  TEXT,
            identity_cluster_id         TEXT,
            actor_id                    TEXT,
            user_id                     TEXT,
            account_ref                 TEXT,
            wallet_address              TEXT,
            attribution_result_id       TEXT,
            fraud_decision_id           TEXT,
            consent_snapshot_id         TEXT,
            eligible                    BOOLEAN NOT NULL,
            decision                    TEXT NOT NULL,
            decision_reason             TEXT,
            denial_reason               TEXT,
            attribution_weight          NUMERIC(5,4),
            attribution_confidence      NUMERIC(5,4),
            fraud_score                 NUMERIC(6,2),
            identity_confidence         NUMERIC(5,4),
            wallet_binding_confidence   NUMERIC(5,4),
            execution_mode              TEXT,
            rail                        TEXT,
            idempotency_key             TEXT,
            decision_version            INT NOT NULL DEFAULT 1,
            policy_version              TEXT,
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at                  TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS red_idempotency_uq
        ON reward_eligibility_decisions (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS red_tenant_decision_idx ON reward_eligibility_decisions (tenant_id, decision, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS red_campaign_idx ON reward_eligibility_decisions (campaign_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS red_wallet_idx ON reward_eligibility_decisions (wallet_address, tenant_id)")

    # ── reward_action_payloads ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_action_payloads (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           TEXT NOT NULL,
            decision_id         UUID REFERENCES reward_eligibility_decisions(id),
            campaign_id         UUID REFERENCES reward_campaigns(id),
            rule_id             UUID REFERENCES reward_rules(id),
            rail                TEXT NOT NULL,
            execution_mode      TEXT NOT NULL,
            payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            payload_hash        TEXT,
            signature           TEXT,
            status              TEXT NOT NULL DEFAULT 'created',
            delivery_attempts   INT NOT NULL DEFAULT 0,
            last_delivery_error TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            delivered_at        TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS rap_tenant_status_idx ON reward_action_payloads (tenant_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS rap_decision_idx ON reward_action_payloads (decision_id)")

    # ── reward_proofs ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_proofs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           TEXT NOT NULL,
            decision_id         UUID REFERENCES reward_eligibility_decisions(id),
            campaign_id         UUID REFERENCES reward_campaigns(id),
            rule_id             UUID REFERENCES reward_rules(id),
            wallet_address      TEXT NOT NULL,
            chain_id            INT,
            vm_type             TEXT NOT NULL DEFAULT 'evm',
            contract_address    TEXT,
            program_id          TEXT,
            amount              NUMERIC(36,18),
            unit                TEXT,
            nonce               TEXT NOT NULL,
            expiry              INT NOT NULL,
            message_hash        TEXT,
            signature           TEXT,
            proof_format        TEXT NOT NULL DEFAULT 'eip191',
            signer_key_ref      TEXT,
            signer_address      TEXT,
            status              TEXT NOT NULL DEFAULT 'created',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at          TIMESTAMPTZ NOT NULL,
            used_at             TIMESTAMPTZ,
            revoked_at          TIMESTAMPTZ
        )
    """)
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS rp_nonce_uq ON reward_proofs (nonce)")
    op.execute("CREATE INDEX IF NOT EXISTS rp_tenant_idx ON reward_proofs (tenant_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS rp_wallet_idx ON reward_proofs (wallet_address, status)")
    op.execute("CREATE INDEX IF NOT EXISTS rp_decision_idx ON reward_proofs (decision_id)")

    # ── reward_execution_receipts ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_execution_receipts (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               TEXT NOT NULL,
            decision_id             UUID REFERENCES reward_eligibility_decisions(id),
            action_payload_id       UUID REFERENCES reward_action_payloads(id),
            proof_id                UUID REFERENCES reward_proofs(id),
            rail                    TEXT NOT NULL,
            execution_mode          TEXT NOT NULL,
            external_execution_id   TEXT,
            tx_hash                 TEXT,
            chain_id                INT,
            provider                TEXT,
            status                  TEXT NOT NULL DEFAULT 'unknown',
            receipt_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
            observed_at             TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS rer_tenant_idx ON reward_execution_receipts (tenant_id, status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS rer_decision_idx ON reward_execution_receipts (decision_id)")

    # ── reward_audit_log (append-only) ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS reward_audit_log (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       TEXT NOT NULL,
            actor_type      TEXT,
            actor_id        TEXT,
            action          TEXT NOT NULL,
            target_type     TEXT,
            target_id       TEXT,
            before_state    JSONB,
            after_state     JSONB,
            reason          TEXT,
            request_id      TEXT,
            ip_hash         TEXT,
            user_agent_hash TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ral_tenant_idx ON reward_audit_log (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ral_target_idx ON reward_audit_log (tenant_id, target_type, target_id)")

    # ── tenant_reward_rail_configs ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_reward_rail_configs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id           TEXT NOT NULL,
            rail                TEXT NOT NULL,
            enabled             BOOLEAN NOT NULL DEFAULT FALSE,
            config              JSONB NOT NULL DEFAULT '{}'::jsonb,
            secret_ref          TEXT,
            webhook_url         TEXT,
            contract_address    TEXT,
            chain_id            INT,
            vm_type             TEXT,
            provider            TEXT,
            verification_method TEXT,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_verified_at    TIMESTAMPTZ,
            status              TEXT NOT NULL DEFAULT 'pending_verification',
            UNIQUE (tenant_id, rail)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS trrc_tenant_idx ON tenant_reward_rail_configs (tenant_id, enabled)")

    # ── tenant_contract_registry ────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_contract_registry (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               TEXT NOT NULL,
            chain_id                INT NOT NULL,
            contract_address        TEXT NOT NULL,
            contract_name           TEXT NOT NULL,
            abi_ref                 TEXT,
            verification_status     TEXT NOT NULL DEFAULT 'pending',
            allowed_campaign_ids    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
            oracle_signer_address   TEXT NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (tenant_id, chain_id, contract_address)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS tcr_tenant_idx ON tenant_contract_registry (tenant_id, verification_status)")

    # ── updated_at triggers ─────────────────────────────────────────────────
    _tables_with_updated_at = [
        "reward_campaigns",
        "reward_rules",
        "reward_action_payloads",
        "tenant_reward_rail_configs",
        "tenant_contract_registry",
    ]
    for tbl in _tables_with_updated_at:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated ON {tbl}")
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated "
            f"BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    _tables_with_updated_at = [
        "reward_campaigns",
        "reward_rules",
        "reward_action_payloads",
        "tenant_reward_rail_configs",
        "tenant_contract_registry",
    ]
    for tbl in _tables_with_updated_at:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated ON {tbl}")

    op.execute("DROP TABLE IF EXISTS tenant_contract_registry")
    op.execute("DROP TABLE IF EXISTS tenant_reward_rail_configs")
    op.execute("DROP TABLE IF EXISTS reward_audit_log")
    op.execute("DROP TABLE IF EXISTS reward_execution_receipts")
    op.execute("DROP TABLE IF EXISTS reward_proofs")
    op.execute("DROP TABLE IF EXISTS reward_action_payloads")
    op.execute("DROP TABLE IF EXISTS reward_eligibility_decisions")
    op.execute("DROP TABLE IF EXISTS reward_rules")
    op.execute("DROP TABLE IF EXISTS reward_campaigns")
