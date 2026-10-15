"""Silver fact tables — normalized projection layer for the medallion pipeline.

Revision ID: 9a1b2c3d4e5f
Revises: (latest)
Create Date: 2026-06-22

Silver tables receive evidence-backed projections from Bronze (raw events).
All tables share:
  - tenant_id + fact_id as composite uniqueness key
  - source_event_id for lineage back to Bronze
  - consent_snapshot_id for audit trail
  - privacy_class for governance routing
  - idempotency key for safe replay
"""

from __future__ import annotations

from alembic import op

revision = "9a1b2c3d4e5f"
down_revision = None  # attach to migration chain after identity_suppression
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Shared DDL helper
# ---------------------------------------------------------------------------

_SILVER_COMMON = """
    fact_id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    tenant_id            TEXT         NOT NULL,
    source_event_id      UUID         NOT NULL,
    source_event_type    TEXT         NOT NULL,
    actor_id             TEXT,
    user_id              TEXT,
    anonymous_id         TEXT,
    org_id               TEXT,
    occurred_at          TIMESTAMPTZ  NOT NULL,
    received_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    consent_snapshot_id  TEXT,
    privacy_class        TEXT         NOT NULL DEFAULT 'behavioral',
    idempotency_key      TEXT,
    payload              JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now()
"""


def _create_silver_table(table: str, extra_cols: str = "", extra_indices: str = "") -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {_SILVER_COMMON}
            {(',' + extra_cols) if extra_cols else ''},
            PRIMARY KEY (tenant_id, fact_id)
        );
        CREATE INDEX IF NOT EXISTS {table}_source_event ON {table} (source_event_id);
        CREATE INDEX IF NOT EXISTS {table}_user ON {table} (tenant_id, user_id) WHERE user_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS {table}_actor ON {table} (tenant_id, actor_id) WHERE actor_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS {table}_occurred ON {table} (tenant_id, occurred_at DESC);
        {extra_indices}
    """


def upgrade() -> None:
    # --- Exposure facts ---
    op.execute(_create_silver_table(
        "silver_exposure_facts",
        """
        content_type        TEXT,
        content_id          TEXT,
        recommendation_id   TEXT,
        position            INTEGER,
        score               NUMERIC(10,6),
        model_version       TEXT,
        campaign_id         TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_exposure_facts_content ON silver_exposure_facts (tenant_id, content_id, occurred_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS silver_exposure_facts_idem ON silver_exposure_facts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """,
    ))

    # --- Outcome facts ---
    op.execute(_create_silver_table(
        "silver_outcome_facts",
        """
        outcome_type        TEXT NOT NULL,
        goal_id             TEXT,
        recommendation_id   TEXT,
        value_amount        NUMERIC(20,4),
        value_currency      TEXT,
        succeeded           BOOLEAN
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_outcome_facts_goal ON silver_outcome_facts (tenant_id, goal_id) WHERE goal_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS silver_outcome_facts_idem ON silver_outcome_facts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """,
    ))

    # --- Revenue / subscription facts ---
    op.execute(_create_silver_table(
        "silver_revenue_facts",
        """
        revenue_type        TEXT NOT NULL,
        amount              NUMERIC(20,4) NOT NULL,
        currency            TEXT NOT NULL DEFAULT 'USD',
        product_id          TEXT,
        plan_id             TEXT,
        subscription_id     TEXT,
        invoice_id          TEXT,
        mrr_delta           NUMERIC(20,4),
        arr_delta           NUMERIC(20,4),
        payment_method      TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_revenue_facts_sub ON silver_revenue_facts (tenant_id, subscription_id) WHERE subscription_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS silver_revenue_facts_idem ON silver_revenue_facts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """,
    ))

    # --- Friction facts ---
    op.execute(_create_silver_table(
        "silver_friction_facts",
        """
        friction_type       TEXT NOT NULL,
        element_selector    TEXT,
        page_url            TEXT,
        scroll_depth_pct    NUMERIC(5,2),
        form_id             TEXT,
        field_name          TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_friction_facts_page ON silver_friction_facts (tenant_id, page_url) WHERE page_url IS NOT NULL;
        """,
    ))

    # --- Account activity facts (B2B) ---
    op.execute(_create_silver_table(
        "silver_account_activity_facts",
        """
        activity_type       TEXT NOT NULL,
        workspace_id        TEXT,
        member_id           TEXT,
        role                TEXT,
        integration_id      TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_account_activity_facts_workspace ON silver_account_activity_facts (tenant_id, workspace_id) WHERE workspace_id IS NOT NULL;
        """,
    ))

    # --- Server operation facts ---
    op.execute(_create_silver_table(
        "silver_server_operation_facts",
        """
        operation_type      TEXT NOT NULL,
        method              TEXT,
        path                TEXT,
        status_code         INTEGER,
        duration_ms         INTEGER,
        error_code          TEXT,
        dependency          TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_server_op_path ON silver_server_operation_facts (tenant_id, path) WHERE path IS NOT NULL;
        """,
    ))

    # --- Identity evidence facts ---
    op.execute(_create_silver_table(
        "silver_identity_evidence_facts",
        """
        event_kind          TEXT NOT NULL,
        identity_method     TEXT,
        mfa_type            TEXT,
        device_id           TEXT,
        confidence          NUMERIC(5,4),
        linked_actor_id     TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_identity_ev_device ON silver_identity_evidence_facts (tenant_id, device_id) WHERE device_id IS NOT NULL;
        """,
    ))

    # --- Agent execution facts ---
    op.execute(_create_silver_table(
        "silver_agent_execution_facts",
        """
        agent_id            TEXT,
        task_id             TEXT,
        model_id            TEXT,
        prompt_tokens       INTEGER,
        completion_tokens   INTEGER,
        cost_usd            NUMERIC(12,6),
        outcome             TEXT,
        grounding_sources   INTEGER,
        human_override      BOOLEAN NOT NULL DEFAULT false
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_agent_exec_agent ON silver_agent_execution_facts (tenant_id, agent_id) WHERE agent_id IS NOT NULL;
        """,
    ))

    # --- Web3 transaction facts ---
    op.execute(_create_silver_table(
        "silver_web3_transaction_facts",
        """
        tx_hash             TEXT,
        chain_id            TEXT,
        contract_address    TEXT,
        from_address        TEXT,
        to_address          TEXT,
        value_wei           TEXT,
        status              TEXT,
        token_address       TEXT,
        allowance_amount    TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_web3_tx_hash ON silver_web3_transaction_facts (tenant_id, tx_hash) WHERE tx_hash IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS silver_web3_tx_idem ON silver_web3_transaction_facts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """,
    ))

    # --- x402 flow facts ---
    op.execute(_create_silver_table(
        "silver_x402_flow_facts",
        """
        flow_type           TEXT NOT NULL,
        resource_id         TEXT,
        payment_required    BOOLEAN,
        amount              NUMERIC(20,4),
        currency            TEXT,
        settled             BOOLEAN,
        settlement_tx_hash  TEXT
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS silver_x402_flow_idem ON silver_x402_flow_facts (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
        """,
    ))

    # --- Data quality facts ---
    op.execute(_create_silver_table(
        "silver_data_quality_facts",
        """
        schema_version      TEXT,
        sdk_version         TEXT,
        missing_fields      TEXT[],
        unknown_fields      TEXT[],
        rejection_reason    TEXT
        """,
    ))

    # --- Communications facts ---
    op.execute(_create_silver_table(
        "silver_comms_facts",
        """
        comms_type          TEXT NOT NULL,
        channel             TEXT,
        campaign_id         TEXT,
        message_id          TEXT,
        support_case_id     TEXT,
        deliverability      TEXT
        """,
        """
        CREATE INDEX IF NOT EXISTS silver_comms_campaign ON silver_comms_facts (tenant_id, campaign_id) WHERE campaign_id IS NOT NULL;
        """,
    ))


def downgrade() -> None:
    tables = [
        "silver_exposure_facts",
        "silver_outcome_facts",
        "silver_revenue_facts",
        "silver_friction_facts",
        "silver_account_activity_facts",
        "silver_server_operation_facts",
        "silver_identity_evidence_facts",
        "silver_agent_execution_facts",
        "silver_web3_transaction_facts",
        "silver_x402_flow_facts",
        "silver_data_quality_facts",
        "silver_comms_facts",
    ]
    for t in reversed(tables):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")
