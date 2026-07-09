import { http, HttpResponse } from 'msw';

// Requests use relative paths (/v1/...) which resolve to the Vite dev server origin.
const API = '';

const mockProfile = {
  data: {
    tenant_id: 'tenant_demo_001',
    name: 'Alex Reeves',
    contact_email: 'alex@acme.io',
    email: 'alex@acme.io',
    plan: {
      plan_id: 'P2',
      display_name: 'Professional',
      monthly_quota: 100_000,
      burst_rpm: 500,
    },
    billing: {
      subscription_status: 'active',
      current_period_end: new Date(Date.now() + 12 * 86400 * 1000).toISOString(),
      stripe_customer_id: 'cus_mock',
    },
    api_key_count: 3,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockUsage = {
  data: {
    period_start: new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString(),
    period_end: new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).toISOString(),
    events_used: 73_450,
    events_quota: 100_000,
    rpm_peak: 182,
    rpm_limit: 500,
    overage_events: 0,
    days_remaining: 12,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockApiKeys = {
  data: {
    tenant_id: 'tenant_demo_001',
    api_keys: [
      { id: 'key_001', name: 'Production SDK', tier: 'P2', permissions: ['read', 'ingest'], last_used_at: new Date(Date.now() - 2 * 3600_000).toISOString() },
      { id: 'key_002', name: 'Analytics Dashboard', tier: 'P2', permissions: ['read', 'analytics'], last_used_at: new Date(Date.now() - 3 * 86400_000).toISOString() },
      { id: 'key_003', name: 'Staging', tier: 'P2', permissions: ['read', 'write', 'ingest'], last_used_at: null },
    ],
    count: 3,
    total: 3,
    limit: 20,
    offset: 0,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockPlans = {
  data: {
    plans: [
      { plan_id: 'P1', display_name: 'Hobbyist', price_monthly: 99, monthly_quota: 25_000, burst_rpm: 100, features: ['10 services', 'Community support', 'Web SDK'] },
      { plan_id: 'P2', display_name: 'Professional', price_monthly: 499, monthly_quota: 100_000, burst_rpm: 500, features: ['19 services', 'Email support', 'All SDKs', 'Analytics dashboard'] },
      { plan_id: 'P3', display_name: 'Growth Intelligence', price_monthly: 1499, monthly_quota: 250_000, burst_rpm: 1200, features: ['29 services', 'Priority support', 'ML models', 'Campaign intelligence'] },
      { plan_id: 'P4', display_name: 'Protocol Master', price_monthly: 3999, monthly_quota: 500_000, burst_rpm: 3000, features: ['34 services', 'Dedicated support', 'Custom SLAs', 'Agent layer'] },
    ],
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

const mockInvoices = {
  data: {
    invoices: [
      { id: 'inv_001', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-04-01', period_end: '2026-04-30', invoice_url: null },
      { id: 'inv_002', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-03-01', period_end: '2026-03-31', invoice_url: null },
      { id: 'inv_003', amount: 49900, currency: 'usd', status: 'paid', period_start: '2026-02-01', period_end: '2026-02-28', invoice_url: null },
    ],
    count: 3,
  },
  status: 'ok',
  timestamp: new Date().toISOString(),
};

// ── External agent telemetry — deployments ──────────────────────────────────
// Deterministic fixtures: fixed ISO timestamps, no Date.now()-derived values.
const MOCK_AGENT_DEPLOYMENTS = [
  {
    id: 'dep_discord_support_001',
    tenant_id: 'tenant_demo_001',
    agent_id: 'agent_support_v2',
    display_name: 'Support Bot — Discord',
    description: 'Customer support agent deployed to the community Discord server.',
    external_platform: 'discord_bot',
    environment: 'production',
    status: 'active',
    consent_mode: 'platform_managed',
    allowed_event_families: ['agent.message', 'agent.session', 'agent.feedback'],
    required_consent_purposes: ['analytics'],
    capability_scopes: ['observe:conversations', 'observe:reactions'],
    event_count_24h: 4210,
    accepted_count_24h: 4102,
    rejected_count_24h: 61,
    error_count_24h: 12,
    consent_blocked_count_24h: 35,
    health_score: 0.97,
    first_seen_at: '2026-05-02T09:15:00.000Z',
    last_seen_at: '2026-07-08T21:42:00.000Z',
    last_event_at: '2026-07-08T21:42:00.000Z',
    created_at: '2026-05-01T14:00:00.000Z',
    updated_at: '2026-07-01T10:30:00.000Z',
  },
  {
    id: 'dep_shopify_concierge_002',
    tenant_id: 'tenant_demo_001',
    agent_id: 'agent_concierge_v1',
    display_name: 'Shopping Concierge — Shopify',
    description: 'Product recommendation agent embedded in the storefront.',
    external_platform: 'shopify_app',
    environment: 'production',
    status: 'paused',
    consent_mode: 'tenant_managed',
    allowed_event_families: ['agent.recommendation', 'agent.session'],
    required_consent_purposes: ['analytics', 'personalization'],
    capability_scopes: ['observe:recommendations'],
    event_count_24h: 0,
    accepted_count_24h: 0,
    rejected_count_24h: 0,
    error_count_24h: 0,
    consent_blocked_count_24h: 0,
    health_score: null,
    first_seen_at: '2026-04-11T08:00:00.000Z',
    last_seen_at: '2026-07-06T16:05:00.000Z',
    last_event_at: '2026-07-06T16:05:00.000Z',
    created_at: '2026-04-10T12:00:00.000Z',
    updated_at: '2026-07-07T09:00:00.000Z',
  },
  {
    id: 'dep_mcp_research_003',
    tenant_id: 'tenant_demo_001',
    agent_id: 'agent_research_v3',
    display_name: 'Research Assistant — MCP',
    description: 'Internal research agent exposed via an MCP server.',
    external_platform: 'mcp_server',
    environment: 'staging',
    status: 'error',
    consent_mode: 'aether_managed',
    allowed_event_families: ['agent.tool_call', 'agent.session'],
    required_consent_purposes: [],
    capability_scopes: ['observe:tool_calls'],
    event_count_24h: 812,
    accepted_count_24h: 640,
    rejected_count_24h: 118,
    error_count_24h: 54,
    consent_blocked_count_24h: 0,
    health_score: 0.62,
    first_seen_at: '2026-06-20T11:30:00.000Z',
    last_seen_at: '2026-07-08T19:10:00.000Z',
    last_event_at: '2026-07-08T19:10:00.000Z',
    created_at: '2026-06-20T11:00:00.000Z',
    updated_at: '2026-07-08T19:10:00.000Z',
  },
];

const MOCK_DEPLOYMENT_ACTIVITY: Record<string, unknown[]> = {
  dep_discord_support_001: [
    { id: 'act_001', deployment_id: 'dep_discord_support_001', action: 'created', actor: 'alex@acme.io', request_id: 'req_a1', occurred_at: '2026-05-01T14:00:00.000Z' },
    { id: 'act_002', deployment_id: 'dep_discord_support_001', action: 'updated', actor: 'alex@acme.io', request_id: 'req_a2', occurred_at: '2026-07-01T10:30:00.000Z' },
  ],
  dep_shopify_concierge_002: [
    { id: 'act_003', deployment_id: 'dep_shopify_concierge_002', action: 'created', actor: 'alex@acme.io', request_id: 'req_b1', occurred_at: '2026-04-10T12:00:00.000Z' },
    { id: 'act_004', deployment_id: 'dep_shopify_concierge_002', action: 'paused', actor: 'alex@acme.io', request_id: 'req_b2', occurred_at: '2026-07-07T09:00:00.000Z' },
  ],
  dep_mcp_research_003: [
    { id: 'act_005', deployment_id: 'dep_mcp_research_003', action: 'created', actor: 'alex@acme.io', request_id: 'req_c1', occurred_at: '2026-06-20T11:00:00.000Z' },
    { id: 'act_006', deployment_id: 'dep_mcp_research_003', action: 'errored', actor: 'system', request_id: 'req_c2', occurred_at: '2026-07-08T19:10:00.000Z' },
  ],
};

const LIFECYCLE_STATUS: Record<string, string> = {
  pause: 'paused',
  reactivate: 'active',
  revoke: 'revoked',
  archive: 'archived',
};

function findDeployment(id: string | readonly string[] | undefined) {
  return MOCK_AGENT_DEPLOYMENTS.find(d => d.id === String(id));
}

// ── Payment rail observability ───────────────────────────────────────────────
// Deterministic fixtures: fixed ISO timestamps, no Date.now()-derived values.
// One funding session per named provider; coinbase carries the conflict
// reconciliation, stripe the sdk_only one, and moonpay is not configured
// (its session is a historical record from before the adapter was removed).
const MOCK_FUNDING_SESSIONS = [
  {
    id: 'fs_privy_onramp_001',
    tenant_id: 'tenant_demo_001',
    provider: 'privy',
    provider_detail: 'stripe',
    flow_type: 'fiat_onramp',
    rail: 'card',
    status: 'completed',
    provider_status: 'onramp_completed',
    status_reason: null,
    reconciliation_state: 'matched',
    actor_kind: 'human',
    user_id: 'user_0001',
    agent_id: null,
    org_id: null,
    session_id: 'sess_web_101',
    device_id: 'dev_ios_001',
    journey_id: 'jrn_onboarding_001',
    campaign_id: 'camp_q3_funding',
    source_asset: null,
    source_chain: null,
    source_amount: '100.00',
    fiat_currency: 'USD',
    destination_asset: 'USDC',
    destination_chain: 'base',
    destination_amount: '99.20',
    destination_address: '0xa1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0',
    fee_amount: '0.80',
    fee_currency: 'USD',
    provider_session_id: 'privy_sess_8842',
    provider_transaction_id: 'privy_tx_5521',
    provider_customer_ref: 'privy_cust_301',
    deposit_address_id: null,
    virtual_account_id: null,
    tx_hash: '0x1f2e3d4c5b6a79880716253443526170f0e1d2c3b4a5968778695a4b3c2d1e0f',
    idempotency_key: 'idem_privy_8842',
    occurred_at: '2026-07-08T14:05:00.000Z',
    created_at: '2026-07-08T14:05:04.000Z',
    updated_at: '2026-07-08T14:07:11.000Z',
  },
  {
    id: 'fs_stripe_onramp_002',
    tenant_id: 'tenant_demo_001',
    provider: 'stripe',
    provider_detail: null,
    flow_type: 'crypto_onramp',
    rail: 'card',
    status: 'pending',
    provider_status: null,
    status_reason: null,
    reconciliation_state: 'sdk_only',
    actor_kind: 'human',
    user_id: 'user_0002',
    agent_id: null,
    org_id: null,
    session_id: 'sess_web_204',
    device_id: 'dev_web_014',
    journey_id: 'jrn_deposit_014',
    campaign_id: null,
    source_asset: null,
    source_chain: null,
    source_amount: '250.00',
    fiat_currency: 'USD',
    destination_asset: 'ETH',
    destination_chain: 'ethereum',
    destination_amount: '0.0561',
    destination_address: '0xb2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1',
    fee_amount: null,
    fee_currency: null,
    provider_session_id: 'cs_crypto_991',
    provider_transaction_id: null,
    provider_customer_ref: null,
    deposit_address_id: null,
    virtual_account_id: null,
    tx_hash: null,
    idempotency_key: 'idem_stripe_0991',
    occurred_at: '2026-07-08T18:22:00.000Z',
    created_at: '2026-07-08T18:22:02.000Z',
    updated_at: '2026-07-08T18:22:02.000Z',
  },
  {
    id: 'fs_coinbase_offramp_003',
    tenant_id: 'tenant_demo_001',
    provider: 'coinbase',
    provider_detail: null,
    flow_type: 'offramp',
    rail: 'ach',
    status: 'failed',
    provider_status: 'transaction_failed',
    status_reason: 'aml_review',
    reconciliation_state: 'conflict',
    actor_kind: 'agent',
    user_id: null,
    agent_id: 'agent_treasury_v1',
    org_id: 'org_acme',
    session_id: null,
    device_id: null,
    journey_id: 'jrn_treasury_007',
    campaign_id: null,
    source_asset: 'USDC',
    source_chain: 'base',
    source_amount: '5000.00',
    fiat_currency: 'USD',
    destination_asset: null,
    destination_chain: null,
    destination_amount: '4998.10',
    destination_address: null,
    fee_amount: '1.90',
    fee_currency: 'USD',
    provider_session_id: 'cb_sess_4410',
    provider_transaction_id: 'cb_tx_7702',
    provider_customer_ref: 'cb_cust_118',
    deposit_address_id: null,
    virtual_account_id: null,
    tx_hash: '0x9f8e7d6c5b4a39281706f5e4d3c2b1a09f8e7d6c5b4a39281706f5e4d3c2b1a0',
    idempotency_key: 'idem_coinbase_4410',
    occurred_at: '2026-07-07T09:45:00.000Z',
    created_at: '2026-07-07T09:45:03.000Z',
    updated_at: '2026-07-08T06:15:40.000Z',
  },
  {
    id: 'fs_moonpay_onramp_004',
    tenant_id: 'tenant_demo_001',
    provider: 'moonpay',
    provider_detail: null,
    flow_type: 'fiat_onramp',
    rail: 'moonpay',
    status: 'completed',
    provider_status: 'completed',
    status_reason: null,
    reconciliation_state: 'stale',
    actor_kind: 'human',
    user_id: 'user_0003',
    agent_id: null,
    org_id: null,
    session_id: 'sess_web_311',
    device_id: null,
    journey_id: null,
    campaign_id: 'camp_spring_promo',
    source_asset: null,
    source_chain: null,
    source_amount: '75.00',
    fiat_currency: 'EUR',
    destination_asset: 'USDC',
    destination_chain: 'polygon',
    destination_amount: '74.10',
    destination_address: '0xc3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2',
    fee_amount: '2.10',
    fee_currency: 'EUR',
    provider_session_id: 'mp_sess_2208',
    provider_transaction_id: 'mp_tx_6644',
    provider_customer_ref: null,
    deposit_address_id: null,
    virtual_account_id: null,
    tx_hash: null,
    idempotency_key: 'idem_moonpay_2208',
    occurred_at: '2026-06-15T11:20:00.000Z',
    created_at: '2026-06-15T11:20:05.000Z',
    updated_at: '2026-06-15T11:24:30.000Z',
  },
  {
    id: 'fs_bridge_deposit_005',
    tenant_id: 'tenant_demo_001',
    provider: 'bridge',
    provider_detail: null,
    flow_type: 'bank_deposit',
    rail: 'wire',
    status: 'completed',
    provider_status: 'payment_processed',
    status_reason: null,
    reconciliation_state: 'matched',
    actor_kind: 'org',
    user_id: null,
    agent_id: null,
    org_id: 'org_acme',
    session_id: null,
    device_id: null,
    journey_id: null,
    campaign_id: null,
    source_asset: null,
    source_chain: null,
    source_amount: '25000.00',
    fiat_currency: 'USD',
    destination_asset: 'USDC',
    destination_chain: 'ethereum',
    destination_amount: '24985.00',
    destination_address: '0xd4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3',
    fee_amount: '15.00',
    fee_currency: 'USD',
    provider_session_id: null,
    provider_transaction_id: 'bridge_tx_3307',
    provider_customer_ref: 'bridge_cust_042',
    deposit_address_id: null,
    virtual_account_id: 'va_bridge_017',
    tx_hash: '0x7a6b5c4d3e2f10897a6b5c4d3e2f10897a6b5c4d3e2f10897a6b5c4d3e2f1089',
    idempotency_key: 'idem_bridge_3307',
    occurred_at: '2026-07-08T07:30:00.000Z',
    created_at: '2026-07-08T07:30:06.000Z',
    updated_at: '2026-07-08T08:01:12.000Z',
  },
];

const MOCK_RECONCILIATION_RECORDS = [
  {
    id: 'rec_001',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_privy_onramp_001',
    provider: 'privy',
    state: 'matched',
    last_source: 'webhook',
    sdk_event_id: 'evt_sdk_7001',
    provider_event_id: 'evt_privy_9001',
    discrepancies: null,
    first_observed_at: '2026-07-08T14:05:04.000Z',
    last_checked_at: '2026-07-08T14:07:11.000Z',
    resolved_at: '2026-07-08T14:07:11.000Z',
    created_at: '2026-07-08T14:05:04.000Z',
    updated_at: '2026-07-08T14:07:11.000Z',
  },
  {
    id: 'rec_002',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_stripe_onramp_002',
    provider: 'stripe',
    state: 'sdk_only',
    last_source: 'sdk',
    sdk_event_id: 'evt_sdk_7002',
    provider_event_id: null,
    discrepancies: null,
    first_observed_at: '2026-07-08T18:22:02.000Z',
    last_checked_at: '2026-07-08T23:30:00.000Z',
    resolved_at: null,
    created_at: '2026-07-08T18:22:02.000Z',
    updated_at: '2026-07-08T23:30:00.000Z',
  },
  {
    id: 'rec_003',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_coinbase_offramp_003',
    provider: 'coinbase',
    state: 'conflict',
    last_source: 'polling',
    sdk_event_id: 'evt_sdk_7003',
    provider_event_id: 'evt_cb_9103',
    discrepancies: [
      { field: 'status', sdk_value: 'completed', provider_value: 'failed' },
      { field: 'destination_amount', sdk_value: '4998.10', provider_value: '0.00' },
    ],
    first_observed_at: '2026-07-07T09:45:03.000Z',
    last_checked_at: '2026-07-08T06:15:40.000Z',
    resolved_at: null,
    created_at: '2026-07-07T09:45:03.000Z',
    updated_at: '2026-07-08T06:15:40.000Z',
  },
  {
    id: 'rec_004',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_moonpay_onramp_004',
    provider: 'moonpay',
    state: 'stale',
    last_source: 'sdk',
    sdk_event_id: 'evt_sdk_7004',
    provider_event_id: null,
    discrepancies: null,
    first_observed_at: '2026-06-15T11:20:05.000Z',
    last_checked_at: '2026-06-16T11:20:00.000Z',
    resolved_at: null,
    created_at: '2026-06-15T11:20:05.000Z',
    updated_at: '2026-06-16T11:20:00.000Z',
  },
  {
    id: 'rec_005',
    tenant_id: 'tenant_demo_001',
    funding_session_id: 'fs_bridge_deposit_005',
    provider: 'bridge',
    state: 'matched',
    last_source: 'webhook',
    sdk_event_id: null,
    provider_event_id: 'evt_bridge_9305',
    discrepancies: null,
    first_observed_at: '2026-07-08T07:30:06.000Z',
    last_checked_at: '2026-07-08T08:01:12.000Z',
    resolved_at: '2026-07-08T08:01:12.000Z',
    created_at: '2026-07-08T07:30:06.000Z',
    updated_at: '2026-07-08T08:01:12.000Z',
  },
];

const MOCK_PAYMENT_RAIL_HEALTH = [
  {
    tenant_id: 'tenant_demo_001',
    provider: 'privy',
    configured: true,
    enabled: true,
    webhook_verified_24h: 182,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 41,
    sessions_completed_24h: 38,
    sessions_failed_24h: 1,
    sessions_unresolved: 0,
    reconciliation_matched_rate: 0.982,
    reconciliation_conflicts: 0,
    last_event_at: '2026-07-08T14:07:11.000Z',
    last_poll_at: '2026-07-08T23:45:00.000Z',
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'stripe',
    configured: true,
    enabled: true,
    webhook_verified_24h: 96,
    webhook_rejected_24h: 2,
    sessions_observed_24h: 18,
    sessions_completed_24h: 14,
    sessions_failed_24h: 0,
    sessions_unresolved: 3,
    reconciliation_matched_rate: 0.941,
    reconciliation_conflicts: 0,
    last_event_at: '2026-07-08T18:22:02.000Z',
    last_poll_at: null,
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'coinbase',
    configured: true,
    enabled: true,
    webhook_verified_24h: 44,
    webhook_rejected_24h: 11,
    sessions_observed_24h: 9,
    sessions_completed_24h: 5,
    sessions_failed_24h: 3,
    sessions_unresolved: 1,
    reconciliation_matched_rate: 0.706,
    reconciliation_conflicts: 2,
    last_event_at: '2026-07-08T06:15:40.000Z',
    last_poll_at: '2026-07-08T22:10:00.000Z',
    status: 'degraded',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'moonpay',
    configured: false,
    enabled: false,
    webhook_verified_24h: 0,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 0,
    sessions_completed_24h: 0,
    sessions_failed_24h: 0,
    sessions_unresolved: 0,
    reconciliation_matched_rate: null,
    reconciliation_conflicts: 0,
    last_event_at: '2026-06-15T11:24:30.000Z',
    last_poll_at: null,
    status: 'not_configured',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    provider: 'bridge',
    configured: true,
    enabled: true,
    webhook_verified_24h: 12,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 3,
    sessions_completed_24h: 3,
    sessions_failed_24h: 0,
    sessions_unresolved: 0,
    reconciliation_matched_rate: 1,
    reconciliation_conflicts: 0,
    last_event_at: '2026-07-08T08:01:12.000Z',
    last_poll_at: '2026-07-08T23:00:00.000Z',
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
];

const MOCK_PROVIDER_ADAPTER_STATUS: Record<string, unknown> = {
  privy: {
    provider: 'privy',
    status: 'configured',
    display_name: 'Privy (production)',
    provider_account_ref: 'privy_app_301',
    environment: 'production',
    webhook_configured: true,
    polling_configured: true,
    last_synced_at: '2026-07-08T23:45:00.000Z',
  },
  stripe: {
    provider: 'stripe',
    status: 'configured',
    display_name: 'Stripe crypto onramp',
    provider_account_ref: 'acct_stripe_991',
    environment: 'production',
    webhook_configured: true,
    polling_configured: false,
    last_synced_at: '2026-07-08T23:40:00.000Z',
  },
  coinbase: {
    provider: 'coinbase',
    status: 'error',
    display_name: 'Coinbase onramp/offramp',
    provider_account_ref: 'cb_org_118',
    environment: 'production',
    webhook_configured: true,
    polling_configured: true,
    last_synced_at: '2026-07-08T22:10:00.000Z',
  },
  moonpay: {
    provider: 'moonpay',
    status: 'not_configured',
    display_name: null,
    provider_account_ref: null,
    environment: null,
    webhook_configured: false,
    polling_configured: false,
    last_synced_at: null,
  },
  bridge: {
    provider: 'bridge',
    status: 'configured',
    display_name: 'Bridge virtual accounts',
    provider_account_ref: 'bridge_biz_042',
    environment: 'production',
    webhook_configured: true,
    polling_configured: true,
    last_synced_at: '2026-07-08T23:00:00.000Z',
  },
};

const FUNDING_SESSION_FILTER_KEYS = ['provider', 'status', 'flow_type', 'rail', 'reconciliation_state'] as const;

// ── AI outcome efficiency ─────────────────────────────────────────────────────
// Deterministic fixtures: fixed ISO timestamps, no Date.now()-derived values.
// Two currencies (USD + EUR — never merged), one unknown-cost invocation
// (selected_cost null, cost_basis 'unknown' — displayed as "unknown", never 0),
// and one waste finding per detector family.
const MOCK_AI_SUMMARY = {
  totals_by_currency: { USD: 1240.5, EUR: 96.4 },
  invocation_count: 18234,
  completed_workflow_count: 512,
  cost_per_invocation_by_currency: { USD: 0.0681, EUR: 0.0129 },
  failed_execution_cost_by_currency: { USD: 84.2, EUR: 1.8 },
  retry_waste_cost_by_currency: { USD: 41.7, EUR: 0.6 },
  cache_utilization_rate: 0.34,
  human_correction_rate: 0.06,
  outcome_attribution_coverage: 0.72,
  cost_coverage: 0.91,
};

const MOCK_AI_INVOCATIONS = [
  {
    invocation_id: 'inv_openai_support_001',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-08T14:05:00.000Z',
    trace_id: 'trace_support_8801',
    workflow_run_id: 'wf_support_2026_07_08_001',
    task_type: 'support_reply',
    use_case: 'customer_support',
    provider: 'openai',
    model: 'gpt-4o-mini',
    model_version: '2026-05-01',
    status: 'succeeded',
    error_code: null,
    input_tokens: 1820,
    output_tokens: 410,
    cached_input_tokens: 1200,
    latency_ms: 1240,
    retry_count: 0,
    selected_cost: 0.0042,
    cost_basis: 'billed',
    currency: 'USD',
    quality_score: 0.92,
    human_reviewed: false,
    human_corrected: false,
    data_quality_status: 'complete',
  },
  {
    invocation_id: 'inv_anthropic_plan_002',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-08T14:05:12.000Z',
    trace_id: 'trace_support_8801',
    workflow_run_id: 'wf_support_2026_07_08_001',
    task_type: 'workflow_planning',
    use_case: 'customer_support',
    provider: 'anthropic',
    model: 'claude-sonnet-4',
    model_version: null,
    status: 'succeeded',
    error_code: null,
    input_tokens: 3400,
    output_tokens: 960,
    cached_input_tokens: 2800,
    latency_ms: 2110,
    retry_count: 0,
    selected_cost: 0.0388,
    cost_basis: 'calculated',
    currency: 'USD',
    quality_score: 0.88,
    human_reviewed: true,
    human_corrected: false,
    data_quality_status: 'complete',
  },
  {
    invocation_id: 'inv_mistral_embed_003',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-08T09:30:00.000Z',
    trace_id: 'trace_catalog_5501',
    workflow_run_id: 'wf_catalog_eur_2026_07_08_001',
    task_type: 'embedding',
    use_case: 'catalog_search',
    provider: 'mistral',
    model: 'mistral-embed',
    model_version: null,
    status: 'succeeded',
    error_code: null,
    input_tokens: null,
    output_tokens: null,
    cached_input_tokens: null,
    latency_ms: 320,
    retry_count: 0,
    selected_cost: 0.0009,
    cost_basis: 'provider_reported',
    currency: 'EUR',
    quality_score: null,
    human_reviewed: false,
    human_corrected: false,
    data_quality_status: 'complete',
  },
  {
    invocation_id: 'inv_openai_unknown_004',
    tenant_id: 'tenant_demo_001',
    observed_at: '2026-07-07T22:15:00.000Z',
    trace_id: 'trace_support_8622',
    workflow_run_id: 'wf_support_2026_07_07_002',
    task_type: 'support_reply',
    use_case: 'customer_support',
    provider: 'openai',
    model: 'gpt-4o',
    model_version: null,
    status: 'failed',
    error_code: 'provider_timeout',
    input_tokens: 2100,
    output_tokens: null,
    cached_input_tokens: null,
    latency_ms: 30000,
    retry_count: 2,
    selected_cost: null,
    cost_basis: 'unknown',
    currency: 'USD',
    quality_score: null,
    human_reviewed: false,
    human_corrected: false,
    data_quality_status: 'suspect',
  },
];

const MOCK_AI_WORKFLOWS = [
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_support_2026_07_08_001',
    total_invocations: 4,
    successful_invocations: 4,
    failed_invocations: 0,
    total_retries: 0,
    total_latency_ms: 5210,
    total_model_cost: 0.31,
    tool_cost: 0.02,
    retrieval_cost: 0.01,
    fully_loaded_cost: 0.34,
    currency: 'USD',
    cost_coverage: 1,
    quality_score: 0.9,
    human_reviewed: true,
    human_corrected: false,
    technical_success: true,
    qualified_outcome_count: 1,
    attributed_value: 42,
    first_observed_at: '2026-07-08T14:05:00.000Z',
    last_observed_at: '2026-07-08T14:06:40.000Z',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_support_2026_07_07_002',
    total_invocations: 3,
    successful_invocations: 1,
    failed_invocations: 2,
    total_retries: 4,
    total_latency_ms: 64100,
    total_model_cost: null,
    tool_cost: null,
    retrieval_cost: null,
    fully_loaded_cost: null,
    currency: 'USD',
    cost_coverage: 0.33,
    quality_score: null,
    human_reviewed: false,
    human_corrected: true,
    technical_success: false,
    qualified_outcome_count: 0,
    attributed_value: null,
    first_observed_at: '2026-07-07T22:15:00.000Z',
    last_observed_at: '2026-07-07T22:18:10.000Z',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
  {
    tenant_id: 'tenant_demo_001',
    workflow_run_id: 'wf_catalog_eur_2026_07_08_001',
    total_invocations: 12,
    successful_invocations: 12,
    failed_invocations: 0,
    total_retries: 1,
    total_latency_ms: 4020,
    total_model_cost: 12.1,
    tool_cost: 0.2,
    retrieval_cost: 0.1,
    fully_loaded_cost: 12.4,
    currency: 'EUR',
    cost_coverage: 1,
    quality_score: 0.81,
    human_reviewed: false,
    human_corrected: false,
    technical_success: true,
    qualified_outcome_count: 2,
    attributed_value: 118,
    first_observed_at: '2026-07-08T09:30:00.000Z',
    last_observed_at: '2026-07-08T09:34:20.000Z',
    computed_at: '2026-07-09T00:00:00.000Z',
  },
];

const MOCK_AI_MODELS = [
  {
    provider: 'openai',
    model: 'gpt-4o-mini',
    invocations: 11204,
    cost_by_currency: { USD: 401.2 },
    avg_latency_ms: 1180,
    success_rate: 0.991,
    avg_quality: 0.9,
  },
  {
    provider: 'anthropic',
    model: 'claude-sonnet-4',
    invocations: 4820,
    cost_by_currency: { USD: 812.6 },
    avg_latency_ms: 2240,
    success_rate: 0.987,
    avg_quality: 0.93,
  },
  {
    provider: 'mistral',
    model: 'mistral-embed',
    invocations: 2210,
    cost_by_currency: { EUR: 96.4 },
    avg_latency_ms: 310,
    success_rate: 0.999,
    avg_quality: null,
  },
];

const MOCK_AI_WASTE_FINDINGS = [
  {
    detector: 'retry_waste',
    severity: 'high',
    title: 'Retry storms on gpt-4o support replies',
    description: 'Timeout-driven retries re-run full prompts without backoff, tripling spend on failed workflows.',
    evidence_refs: ['inv_openai_unknown_004', 'wf_support_2026_07_07_002', 'trace_support_8622'],
    estimated_monthly_waste: 41.7,
    currency: 'USD',
    candidate_action: 'Add exponential backoff and cap retries at 1 for support_reply tasks.',
  },
  {
    detector: 'model_overqualification',
    severity: 'medium',
    title: 'gpt-4o used for template filling',
    description: 'Low-complexity template tasks score identically on gpt-4o-mini at a fraction of the cost.',
    evidence_refs: ['inv_openai_support_001', 'wf_support_2026_07_08_001'],
    estimated_monthly_waste: 118.2,
    currency: 'USD',
    candidate_action: 'Route support_reply template tasks to gpt-4o-mini.',
  },
  {
    detector: 'deterministic_replacement_candidate',
    severity: 'medium',
    title: 'Currency formatting handled by LLM',
    description: 'A pure formatting step is invoked per workflow and is fully deterministic.',
    evidence_refs: ['wf_support_2026_07_08_001'],
    estimated_monthly_waste: 22.5,
    currency: 'USD',
    candidate_action: 'Replace the formatting invocation with a deterministic function.',
  },
  {
    detector: 'cache_opportunity',
    severity: 'low',
    title: 'Repeated identical catalog embedding prompts',
    description: 'Catalog search re-embeds unchanged product descriptions on every run.',
    evidence_refs: ['inv_mistral_embed_003', 'wf_catalog_eur_2026_07_08_001'],
    estimated_monthly_waste: 9.6,
    currency: 'EUR',
    candidate_action: 'Cache embeddings keyed by content hash.',
  },
  {
    detector: 'failed_workflow_concentration',
    severity: 'high',
    title: 'Failed-execution cost concentrated in one workflow',
    description: 'The support escalation workflow accounts for most failed-execution cost; part of its spend has unknown cost basis.',
    evidence_refs: ['wf_support_2026_07_07_002'],
    estimated_monthly_waste: null,
    currency: 'USD',
    candidate_action: 'Investigate provider timeouts on gpt-4o before rerouting.',
  },
];

const MOCK_AI_RECOMMENDATIONS = [
  {
    detector: 'model_overqualification',
    severity: 'medium',
    title: 'Route support_reply template tasks to gpt-4o-mini',
    description: 'Quality parity observed across 1,204 sampled invocations; projected 29% cost reduction for the task family.',
    evidence_refs: ['inv_openai_support_001', 'wf_support_2026_07_08_001'],
    estimated_monthly_waste: 118.2,
    currency: 'USD',
    candidate_action: 'Propose default model gpt-4o-mini for task_type support_reply.',
  },
  {
    detector: 'cache_opportunity',
    severity: 'low',
    title: 'Enable prompt caching for workflow planning',
    description: 'Planning prompts share an identical 2.8k-token prefix across runs.',
    evidence_refs: ['inv_anthropic_plan_002'],
    estimated_monthly_waste: 14.9,
    currency: 'USD',
    candidate_action: 'Propose cached prompt prefix for workflow_planning tasks.',
  },
];

const AI_INVOCATION_FILTER_KEYS = ['provider', 'model', 'status', 'task_type', 'workflow_run_id'] as const;

export const handlers = [
  http.get(`${API}/v1/me`, () => HttpResponse.json(mockProfile)),
  http.get(`${API}/v1/me/usage`, () => HttpResponse.json(mockUsage)),
  http.get(`${API}/v1/me/api-keys`, () => HttpResponse.json(mockApiKeys)),
  http.delete(`${API}/v1/me/api-keys/:id`, ({ params }) =>
    HttpResponse.json({ data: { revoked: true, id: params.id }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/me/api-keys`, async ({ request }) => {
    const body = await request.json() as { name: string; permissions?: string[] };
    return HttpResponse.json({
      data: {
        api_key: `ak_${Math.random().toString(36).slice(2, 26)}`,
        key: `ak_${Math.random().toString(36).slice(2, 26)}`,
        id: `key_new_${Date.now()}`,
        name: body.name,
        tier: 'P2',
        permissions: body.permissions ?? ['read'],
        message: 'Store this key securely — it will not be shown again.',
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    });
  }),
  http.get(`${API}/v1/billing/plans`, () => HttpResponse.json(mockPlans)),
  http.get(`${API}/v1/billing/invoices`, () => HttpResponse.json(mockInvoices)),
  http.post(`${API}/v1/billing/checkout`, () =>
    HttpResponse.json({ data: { session_id: 'cs_mock', url: '', mocked: true }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/billing/portal`, () =>
    HttpResponse.json({ data: { url: '', mocked: true }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/contact/enterprise`, () =>
    HttpResponse.json({ data: { received: true, message: "Thank you — we'll be in touch within 2 business days." }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/register`, async ({ request }) => {
    const body = await request.json() as { email?: string };
    return HttpResponse.json({ data: { message: 'Check your email for a verification code.', email: body.email ?? 'user@example.com' }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.post(`${API}/v1/auth/verify-email`, () =>
    HttpResponse.json({ data: { api_key: 'ak_mock_dev_key_from_otp_verify', tenant_id: 'tenant_demo_001', name: 'Alex Reeves', message: 'Verified' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/login`, async ({ request }) => {
    const body = await request.json() as { email?: string };
    return HttpResponse.json({ data: { api_key: 'ak_mock_login_key', tenant_id: 'tenant_demo_001', email: body.email }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/billing/plans`, () => HttpResponse.json(mockPlans)),

  // ── Users / entities ─────────────────────────────────────────────────────────
  http.get(`${API}/v1/entities`, () =>
    HttpResponse.json({
      data: {
        entities: Array.from({ length: 10 }, (_, i) => ({
          id: `user_${String(i + 1).padStart(4, '0')}`,
          kind: 'user',
          label: `User ${i + 1}`,
          email: `user${i + 1}@example.com`,
          trust_score: Math.round(65 + Math.random() * 30),
          created_at: new Date(Date.now() - (i + 1) * 7 * 86400_000).toISOString(),
        })),
        total: 10,
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/entities/search`, () =>
    HttpResponse.json({ data: { results: [], total: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/entities/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { id: params.entityId, kind: 'user', label: `User ${params.entityId}`, trust_score: 78 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Profile ───────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/profile/:userId/summary`, ({ params }) =>
    HttpResponse.json({
      data: {
        user_id: params.userId,
        name: `User ${String(params.userId).slice(-4)}`,
        email: `user@example.com`,
        trust_score: 78,
        risk_level: 'low',
        profile_completeness: 0.82,
        last_seen: new Date(Date.now() - 3600_000).toISOString(),
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId`, ({ params }) =>
    HttpResponse.json({
      data: {
        user_id: params.userId,
        name: `User ${String(params.userId).slice(-4)}`,
        email: `user@example.com`,
        trust_score: 78,
        risk_level: 'low',
        devices: [],
        sessions: [],
        timeline: [],
        intelligence: {},
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId/timeline`, ({ params }) =>
    HttpResponse.json({ user_id: params.userId, events: [], count: 0 }),
  ),
  http.get(`${API}/v1/profile/:userId/sessions`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, sessions: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/devices`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, devices: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/platforms`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, platforms: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/journeys`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, journeys: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/wallets`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, wallets: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/financials`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, accounts: [], total_balance_usd: 0, computed_at: new Date().toISOString() }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/rewards`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, campaigns: [], total_earned_usd: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/identifiers`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, identifiers: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/intelligence`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, signals: [], risk_level: 'low', trust_score: 78 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/relationships`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, relationships: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/provenance`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, sources: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/protocols`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, protocols: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/lake/:domain`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, domain: params.domain, records: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/profile/:userId/social-intelligence`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.userId,
        kind: 'social_intelligence',
        window: '30d',
        items: [],
        summary: {
          total_followers_deduped: 0,
          influence_level: 'none',
          engagement_rate: 0,
          platforms_connected: 0,
        },
        provenance: { sources: [] },
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/:userId/retarget-recommendations`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.userId,
        kind: 'retarget_recommendations',
        items: [],
        pagination: { limit: 20, count: 0, has_more: false },
        provenance: { sources: ['retarget_recommendations'] },
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/profile/resolve`, () =>
    HttpResponse.json({ data: { resolved_user_id: 'user_0001' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Recommendations ───────────────────────────────────────────────────────────
  http.post(`${API}/v1/recommendations/:recommendationId/approve`, ({ params }) =>
    HttpResponse.json({ data: { recommendation_id: params.recommendationId, status: 'approved' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/recommendations/:recommendationId/reject`, ({ params }) =>
    HttpResponse.json({ data: { recommendation_id: params.recommendationId, status: 'rejected' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Geo ───────────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/geo/summary`, () =>
    HttpResponse.json({ data: null, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/geo/entities`, () =>
    HttpResponse.json({ data: null, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Campaigns ─────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/campaigns`, () =>
    HttpResponse.json({ data: { campaigns: [], total: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/campaigns/:campaignId`, ({ params }) =>
    HttpResponse.json({ data: { campaign_id: params.campaignId, name: 'Mock Campaign', status: 'draft' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/campaigns`, async ({ request }) => {
    const body = await request.json() as { name: string };
    return HttpResponse.json({ data: { campaign_id: `camp_${Date.now()}`, name: body.name, status: 'draft' }, status: 'ok', timestamp: new Date().toISOString() });
  }),

  // ── Behavioral / Expectations / Attribution ───────────────────────────────────
  http.get(`${API}/v1/behavioral/entity/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, signals: [] }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/expectations/entity/:entityId/explain`, ({ params }) =>
    HttpResponse.json({
      data: {
        entity_id: params.entityId,
        explanation: 'No anomalies detected.',
        signals: [],
        confidence: 0.9,
        computed_at: new Date().toISOString(),
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/attribution/journey/:userId`, ({ params }) =>
    HttpResponse.json({ data: { user_id: params.userId, touchpoints: [], journeys: [], count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Graph ─────────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/entities/:entityId/graph`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, nodes: [], edges: [], node_count: 0, edge_count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/resolution/cluster/:entityId`, ({ params }) =>
    HttpResponse.json({ data: { entity_id: params.entityId, cluster_id: `cluster_${params.entityId}`, members: [], size: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/graph/traverse`, () =>
    HttpResponse.json({ data: { nodes: [], edges: [], node_count: 0 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Settings ──────────────────────────────────────────────────────────────────
  http.get(`${API}/v1/me/settings`, () =>
    HttpResponse.json({ data: { notifications: true, theme: 'dark', timezone: 'UTC' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.patch(`${API}/v1/me/settings`, async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    return HttpResponse.json({ data: body, status: 'ok', timestamp: new Date().toISOString() });
  }),

  // ── Auth refresh ──────────────────────────────────────────────────────────────
  http.post(`${API}/v1/auth/refresh`, () =>
    HttpResponse.json({ data: { access_token: 'mock_refreshed_token', expires_in: 3600 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/auth/token`, () =>
    HttpResponse.json({ data: { access_token: 'mock_access_token', refresh_token: 'mock_refresh', expires_in: 3600 }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Data Quality / Intelligence Quality (tenant-facing) ─────────────────────────
  http.get(`${API}/v1/data-quality/overview`, () =>
    HttpResponse.json({ data: {
      score: {
        tenant_id: 'tenant_demo_001', scope: 'tenant',
        event_quality_score: 0.96, schema_stability_score: 0.97, identity_resolution_score: 0.93,
        graph_quality_score: 0.94, profile_quality_score: 0.92, recommendation_quality_score: 0.9,
        outcome_feedback_quality_score: 0.91, playbook_quality_score: 0.9,
        overall_intelligence_quality_score: 0.929, status: 'healthy',
      },
      dimensions: {
        event_quality_score: { score: 0.96, status: 'healthy' },
        schema_stability_score: { score: 0.97, status: 'healthy' },
        identity_resolution_score: { score: 0.93, status: 'healthy' },
        graph_quality_score: { score: 0.94, status: 'healthy' },
        profile_quality_score: { score: 0.92, status: 'healthy' },
        recommendation_quality_score: { score: 0.9, status: 'healthy' },
        outcome_feedback_quality_score: { score: 0.91, status: 'healthy' },
        playbook_quality_score: { score: 0.9, status: 'healthy' },
      },
      open_drift_event_count: 0, drift_by_severity: {},
    }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/events`, () =>
    HttpResponse.json({ data: { dimension: 'event_quality_score', event_volume: 1000000, schema_validation_failure_rate: 0.004, duplicate_event_count: 210, late_arriving_event_count: 95, quality_score: 0.96, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/recommendations`, () =>
    HttpResponse.json({ data: { dimension: 'recommendation_quality_score', success_rate: 0.71, low_confidence_recommendation_rate: 0.11, suppression_rate: 0.09, quality_score: 0.9, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/graph`, () =>
    HttpResponse.json({ data: { dimension: 'graph_quality_score', orphaned_vertices: 73, dangling_edges: 12, missing_expected_edges: 41, quality_score: 0.94, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/data-quality/:dimension`, ({ params }) =>
    HttpResponse.json({ data: { dimension: params.dimension, quality_score: 0.92, status: 'healthy' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── Integrations / Connectors ───────────────────────────────────────────────
  http.get(`${API}/v1/integrations/connectors`, () =>
    HttpResponse.json({ data: { items: [
      { connector_type: 'slack', label: 'Slack', category: 'messaging', description: 'Ingest Slack activity.', premium: false, enabled: false, sync_status: 'never_synced', requires_secret: true, secret_configured: false },
      { connector_type: 'webhook', label: 'Generic Signed Webhook', category: 'webhook', description: 'Ingest events via HMAC-signed webhook.', premium: false, enabled: true, sync_status: 'healthy', requires_secret: false, secret_configured: false },
      { connector_type: 'shopify', label: 'Shopify', category: 'commerce', description: 'Ingest orders and customers.', premium: false, enabled: false, sync_status: 'never_synced', requires_secret: true, secret_configured: false },
      { connector_type: 'stripe', label: 'Stripe (ingestion)', category: 'billing', description: 'Ingest payment events.', premium: false, enabled: false, sync_status: 'never_synced', requires_secret: true, secret_configured: false },
      { connector_type: 'hubspot', label: 'HubSpot', category: 'crm', description: 'Ingest contacts and deals.', premium: true, enabled: false, sync_status: 'never_synced', requires_secret: true, secret_configured: false },
      { connector_type: 'segment', label: 'Segment', category: 'product_analytics', description: 'Ingest track/identify events.', premium: false, enabled: false, sync_status: 'never_synced', requires_secret: false, secret_configured: false },
    ] }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  http.put(`${API}/v1/integrations/connectors/:connectorType`, () =>
    HttpResponse.json({ data: { ok: true }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.post(`${API}/v1/integrations/connectors/:connectorType/test`, () =>
    HttpResponse.json({ data: { ok: true, message: 'Connection test passed.' }, status: 'ok', timestamp: new Date().toISOString() }),
  ),

  // ── External agent telemetry — deployments ───────────────────────────────────
  http.get(`${API}/v1/agent/deployments`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const platform = url.searchParams.get('platform');
    let deployments = MOCK_AGENT_DEPLOYMENTS;
    if (status) deployments = deployments.filter(d => d.status === status);
    if (platform) deployments = deployments.filter(d => d.external_platform === platform);
    return HttpResponse.json({ data: { deployments }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.post(`${API}/v1/agent/deployments`, async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    const created = {
      id: `dep_new_${String(MOCK_AGENT_DEPLOYMENTS.length + 1).padStart(3, '0')}`,
      tenant_id: 'tenant_demo_001',
      agent_id: String(body.agent_id ?? 'agent_new'),
      display_name: String(body.display_name ?? 'New deployment'),
      description: body.description ? String(body.description) : null,
      external_platform: String(body.external_platform ?? 'unknown'),
      environment: String(body.environment ?? 'production'),
      status: 'active',
      consent_mode: String(body.consent_mode ?? 'tenant_managed'),
      allowed_event_families: (body.allowed_event_families as string[] | undefined) ?? [],
      required_consent_purposes: (body.required_consent_purposes as string[] | undefined) ?? [],
      capability_scopes: (body.capability_scopes as string[] | undefined) ?? [],
      event_count_24h: 0,
      accepted_count_24h: 0,
      rejected_count_24h: 0,
      error_count_24h: 0,
      consent_blocked_count_24h: 0,
      health_score: null,
      first_seen_at: null,
      last_seen_at: null,
      last_event_at: null,
      created_at: '2026-07-09T00:00:00.000Z',
      updated_at: '2026-07-09T00:00:00.000Z',
    };
    MOCK_AGENT_DEPLOYMENTS.push(created as unknown as typeof MOCK_AGENT_DEPLOYMENTS[number]);
    return HttpResponse.json({ data: created, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/agent/deployments/:id`, ({ params }) => {
    const deployment = findDeployment(params.id);
    if (!deployment) {
      return HttpResponse.json({ message: 'Deployment not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return HttpResponse.json({ data: deployment, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.patch(`${API}/v1/agent/deployments/:id`, async ({ params, request }) => {
    const deployment = findDeployment(params.id);
    if (!deployment) {
      return HttpResponse.json({ message: 'Deployment not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    const body = await request.json() as Record<string, unknown>;
    Object.assign(deployment, body, { updated_at: '2026-07-09T00:00:00.000Z' });
    return HttpResponse.json({ data: deployment, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.post(`${API}/v1/agent/deployments/:id/:action`, ({ params }) => {
    const nextStatus = LIFECYCLE_STATUS[String(params.action)];
    const deployment = findDeployment(params.id);
    if (!deployment || !nextStatus) {
      return HttpResponse.json({ message: 'Deployment or action not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    deployment.status = nextStatus;
    deployment.updated_at = '2026-07-09T00:00:00.000Z';
    return HttpResponse.json({ data: deployment, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/agent/deployments/:id/health`, ({ params }) => {
    const deployment = findDeployment(params.id);
    if (!deployment) {
      return HttpResponse.json({ message: 'Deployment not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return HttpResponse.json({
      data: {
        event_count_24h: deployment.event_count_24h,
        accepted_count_24h: deployment.accepted_count_24h,
        rejected_count_24h: deployment.rejected_count_24h,
        error_count_24h: deployment.error_count_24h,
        consent_blocked_count_24h: deployment.consent_blocked_count_24h,
        health_score: deployment.health_score,
      },
      status: 'ok',
      timestamp: new Date().toISOString(),
    });
  }),
  http.get(`${API}/v1/agent/deployments/:id/activity`, ({ params }) =>
    HttpResponse.json({
      data: { entries: MOCK_DEPLOYMENT_ACTIVITY[String(params.id)] ?? [] },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),

  // ── Payment rail observability ────────────────────────────────────────────────
  http.get(`${API}/v1/integrations/providers/payment-rails/sessions`, ({ request }) => {
    const url = new URL(request.url);
    let sessions = MOCK_FUNDING_SESSIONS;
    for (const key of FUNDING_SESSION_FILTER_KEYS) {
      const value = url.searchParams.get(key);
      if (value) sessions = sessions.filter(s => s[key] === value);
    }
    return HttpResponse.json({ data: { sessions }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/integrations/providers/payment-rails/sessions/:sessionId`, ({ params }) => {
    const session = MOCK_FUNDING_SESSIONS.find(s => s.id === String(params.sessionId));
    if (!session) {
      return HttpResponse.json({ message: 'Funding session not found', code: 'NOT_FOUND' }, { status: 404 });
    }
    return HttpResponse.json({ data: session, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/integrations/providers/payment-rails/reconciliation`, () =>
    HttpResponse.json({
      data: { records: MOCK_RECONCILIATION_RECORDS },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),
  http.get(`${API}/v1/integrations/providers/payment-rails/health`, () =>
    HttpResponse.json({ data: MOCK_PAYMENT_RAIL_HEALTH, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/integrations/providers/:provider/status`, ({ params }) => {
    const adapterStatus = MOCK_PROVIDER_ADAPTER_STATUS[String(params.provider)];
    if (!adapterStatus) {
      return HttpResponse.json({ message: 'Unknown payment rail provider', code: 'NOT_FOUND' }, { status: 404 });
    }
    return HttpResponse.json({ data: adapterStatus, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.post(`${API}/v1/integrations/providers/:provider/sync`, ({ params }) =>
    HttpResponse.json({
      data: { provider: params.provider, sync_requested: true, requested_at: '2026-07-09T00:00:00.000Z' },
      status: 'ok',
      timestamp: new Date().toISOString(),
    }),
  ),

  // ── AI outcome efficiency ─────────────────────────────────────────────────────
  http.get(`${API}/v1/economic/ai/summary`, () =>
    HttpResponse.json({ data: MOCK_AI_SUMMARY, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/economic/ai/invocations`, ({ request }) => {
    const url = new URL(request.url);
    let invocations = MOCK_AI_INVOCATIONS;
    for (const key of AI_INVOCATION_FILTER_KEYS) {
      const value = url.searchParams.get(key);
      if (value) invocations = invocations.filter(i => i[key] === value);
    }
    return HttpResponse.json({ data: { invocations }, status: 'ok', timestamp: new Date().toISOString() });
  }),
  http.get(`${API}/v1/economic/ai/workflows`, () =>
    HttpResponse.json({ data: { workflows: MOCK_AI_WORKFLOWS }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/economic/ai/models`, () =>
    HttpResponse.json({ data: { models: MOCK_AI_MODELS }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/economic/ai/waste`, () =>
    HttpResponse.json({ data: { findings: MOCK_AI_WASTE_FINDINGS }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
  http.get(`${API}/v1/economic/ai/recommendations`, () =>
    HttpResponse.json({ data: { recommendations: MOCK_AI_RECOMMENDATIONS }, status: 'ok', timestamp: new Date().toISOString() }),
  ),
];
