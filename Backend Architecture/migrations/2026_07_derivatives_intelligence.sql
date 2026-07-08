-- Derivatives Intelligence PR3 graph/profile/campaign projection foundation.
-- Projection tables are tenant-scoped, idempotent, evidence-backed, and do not
-- store credentials or authorize execution.

CREATE TABLE IF NOT EXISTS derivatives_graph_projection_edges (
    tenant_id TEXT NOT NULL,
    edge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    graph_layer TEXT NOT NULL CHECK (graph_layer IN ('H2H','H2A','A2H','A2A','DOMAIN_EXCLUDED')),
    from_ref TEXT NOT NULL,
    to_ref TEXT NOT NULL,
    evidence_class TEXT NOT NULL CHECK (evidence_class IN ('fact','computation','inference','recommendation','insufficient_evidence')),
    source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC(10,9) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    calculation_version TEXT NOT NULL,
    model_version TEXT,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    explanation TEXT NOT NULL,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS derivatives_profile360_summaries (
    tenant_id TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    window_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('loading','empty','partial','stale','error','consent_restricted','entitlement_restricted','reconciliation_warning','complete')),
    position_count INTEGER NOT NULL DEFAULT 0,
    gross_realized_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    net_realized_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    fees NUMERIC(38,18) NOT NULL DEFAULT 0,
    long_bias NUMERIC(38,18) NOT NULL DEFAULT 0,
    short_bias NUMERIC(38,18) NOT NULL DEFAULT 0,
    market_concentration_count INTEGER NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    data_freshness_state TEXT NOT NULL DEFAULT 'partial',
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, subject_ref, window_key)
);

CREATE TABLE IF NOT EXISTS derivatives_campaign_outcomes (
    tenant_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    subject_ref TEXT NOT NULL,
    window_key TEXT NOT NULL,
    trading_account_connections INTEGER NOT NULL DEFAULT 0,
    first_trade_at TIMESTAMPTZ,
    trading_volume NUMERIC(38,18) NOT NULL DEFAULT 0,
    open_notional NUMERIC(38,18) NOT NULL DEFAULT 0,
    realized_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    net_pnl NUMERIC(38,18) NOT NULL DEFAULT 0,
    fees NUMERIC(38,18) NOT NULL DEFAULT 0,
    liquidation_count INTEGER NOT NULL DEFAULT 0,
    attribution_credit TEXT NOT NULL DEFAULT 'not_assigned',
    causal_status TEXT NOT NULL DEFAULT 'not_proven',
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, campaign_id, subject_ref, window_key)
);

CREATE TABLE IF NOT EXISTS derivatives_noesis_evidence_claims (
    tenant_id TEXT NOT NULL,
    claim_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    claim_class TEXT NOT NULL CHECK (claim_class IN ('fact','computation','inference','recommendation','insufficient_evidence')),
    claim_text TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    execution_by_aether BOOLEAN NOT NULL DEFAULT FALSE CHECK (execution_by_aether = FALSE),
    UNIQUE (tenant_id, idempotency_key)
);
