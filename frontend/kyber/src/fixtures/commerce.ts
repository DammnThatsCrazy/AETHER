/**
 * KYBER fixtures for Agentic Commerce — used in mock mode and Lab replay.
 * Deterministic data that matches the backend wire format.
 */
import type {
  ApprovalRequest,
  Entitlement,
  Facilitator,
  LifecycleTrace,
  PaymentRequirement,
  PolicyDecision,
  ProtectedResource,
  Settlement,
  StablecoinAsset,
} from '@kyber/lib/schemas/commerce';

export const fixtureResources: ProtectedResource[] = [
  {
    resource_id: 'res_fx_ml_predict',
    tenant_id: 'tenant_kyber_mock',
    name: 'Aether ML Inference API',
    resource_class: 'api',
    path_pattern: '/v1/ml/predict',
    owner_service: 'ml',
    description: 'Paid ML inference endpoint',
    price_usd: 0.10,
    accepted_assets: ['USDC'],
    accepted_chains: ['eip155:8453', 'solana:mainnet'],
    approval_required: true,
    entitlement_ttl_seconds: 900,
    active: true,
    registered_at: '2026-04-04T12:00:00Z',
  },
  {
    resource_id: 'res_fx_agent_search',
    tenant_id: 'tenant_kyber_mock',
    name: 'Aether Agent — Web Search Tool',
    resource_class: 'agent_tool',
    path_pattern: '/v1/agent/tools/websearch',
    owner_service: 'agent',
    description: 'Agent web search',
    price_usd: 0.02,
    accepted_assets: ['USDC'],
    accepted_chains: ['eip155:8453'],
    approval_required: true,
    entitlement_ttl_seconds: 300,
    active: true,
    registered_at: '2026-04-04T12:00:00Z',
  },
];

export const fixturePaymentRequirement: PaymentRequirement = {
  challenge_id: 'chg_fx_00001',
  tenant_id: 'tenant_kyber_mock',
  resource_id: 'res_fx_ml_predict',
  amount_usd: 0.10,
  asset_symbol: 'USDC',
  chain: 'eip155:8453',
  recipient: 'treasury:tenant_kyber_mock',
  protocol_version: 'v2',
  expires_at: '2026-04-04T12:10:00Z',
  payment_identifier: 'pid_fx_00001',
  requester_id: 'agent_alpha',
  requester_type: 'agent',
  issued_at: '2026-04-04T12:00:00Z',
};

export const fixturePolicyDecision: PolicyDecision = {
  decision_id: 'pd_fx_00001',
  tenant_id: 'tenant_kyber_mock',
  challenge_id: 'chg_fx_00001',
  outcome: 'require_approval',
  active_rules: [
    'asset_compatibility',
    'chain_compatibility',
    'mandatory_approval_all_spend_classes',
  ],
  denial_reason: null,
  requires_approval: true,
  rationale: 'Day-1 GA: approval required for all spend classes',
  decided_at: '2026-04-04T12:00:01Z',
};

export const fixtureApprovalPending: ApprovalRequest = {
  approval_id: 'apr_fx_pending_01',
  tenant_id: 'tenant_kyber_mock',
  challenge_id: 'chg_fx_00001',
  resource_id: 'res_fx_ml_predict',
  requester_id: 'agent_alpha',
  requester_type: 'agent',
  amount_usd: 0.10,
  asset_symbol: 'USDC',
  chain: 'eip155:8453',
  facilitator_id: null,
  priority: 'normal',
  reason: 'Mandatory approval (Day-1 GA: all spend classes)',
  context: {},
  policy_decision_id: 'pd_fx_00001',
  status: 'pending',
  assigned_to: null,
  escalation_chain: [],
  evidence_bundle_id: null,
  created_at: '2026-04-04T12:00:01Z',
  expires_at: '2026-04-04T13:00:01Z',
  decided_at: null,
  decided_by: null,
  decision_reason: null,
  is_override: false,
};

export const fixtureApprovalCritical: ApprovalRequest = {
  ...fixtureApprovalPending,
  approval_id: 'apr_fx_critical_02',
  priority: 'critical',
  amount_usd: 49.00,
  resource_id: 'res_fx_plan_pro',
  reason: 'Subscription plan purchase — high-value',
};

export const fixtureApprovalApproved: ApprovalRequest = {
  ...fixtureApprovalPending,
  approval_id: 'apr_fx_approved_03',
  status: 'approved',
  decided_at: '2026-04-04T12:05:00Z',
  decided_by: 'ops_alice',
  decision_reason: 'Within budget, routine',
};

export const fixtureSettlement: Settlement = {
  settlement_id: 'set_fx_00001',
  tenant_id: 'tenant_kyber_mock',
  receipt_id: 'rcpt_fx_00001',
  challenge_id: 'chg_fx_00001',
  state: 'settled',
  tx_hash: '0x' + 'a'.repeat(64),
  chain: 'eip155:8453',
  amount_usd: 0.10,
  facilitator_id: 'fac_local_aether',
  attempts: 1,
  settled_at: '2026-04-04T12:05:30Z',
  failure_reason: null,
};

export const fixtureEntitlement: Entitlement = {
  entitlement_id: 'ent_fx_00001',
  tenant_id: 'tenant_kyber_mock',
  holder_id: 'agent_alpha',
  holder_type: 'agent',
  resource_id: 'res_fx_ml_predict',
  scope: 'read',
  status: 'active',
  settlement_id: 'set_fx_00001',
  issued_at: '2026-04-04T12:05:31Z',
  expires_at: '2026-04-04T12:20:31Z',
  reuse_count: 3,
  last_reused_at: '2026-04-04T12:15:00Z',
  revoked_at: null,
  revoked_by: null,
  revoke_reason: null,
  siwx_binding: null,
};

export const fixtureFacilitators: Facilitator[] = [
  {
    facilitator_id: 'fac_local_aether',
    name: 'Aether Local Facilitator',
    endpoint_url: 'internal://aether/verify',
    mode: 'local',
    supported_assets: ['USDC'],
    supported_chains: ['eip155:8453', 'solana:mainnet'],
    health_status: 'healthy',
    avg_latency_ms: 12.3,
    success_rate: 1.0,
    active: true,
  },
  {
    facilitator_id: 'fac_circle_v2',
    name: 'Circle x402 v2 Facilitator',
    endpoint_url: 'https://facilitator.circle.com/v2',
    mode: 'facilitator',
    supported_assets: ['USDC'],
    supported_chains: ['eip155:8453', 'solana:mainnet'],
    health_status: 'healthy',
    avg_latency_ms: 245.7,
    success_rate: 0.995,
    active: true,
  },
];

export const fixtureAssets: StablecoinAsset[] = [
  {
    asset_id: 'ast_usdc_base',
    symbol: 'USDC',
    chain: 'eip155:8453',
    network: 'base-mainnet',
    issuer: 'Circle',
    contract_address: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
    decimals: 6,
    settlement_scheme: 'hybrid',
    active: true,
    risk_score: 0.05,
  },
  {
    asset_id: 'ast_usdc_solana',
    symbol: 'USDC',
    chain: 'solana:mainnet',
    network: 'solana-mainnet',
    issuer: 'Circle',
    contract_address: 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    decimals: 6,
    settlement_scheme: 'hybrid',
    active: true,
    risk_score: 0.05,
  },
];

export const fixtureLifecycleTrace: LifecycleTrace = {
  challenge_id: 'chg_fx_00001',
  tenant_id: 'tenant_kyber_mock',
  requirement: fixturePaymentRequirement,
  policy_decision: fixturePolicyDecision,
  approval: fixtureApprovalApproved,
  authorization: { authorization_id: 'auth_fx_00001', facilitator_id: 'fac_local_aether' },
  receipt: { receipt_id: 'rcpt_fx_00001', verified: true },
  settlement: fixtureSettlement,
  entitlement: fixtureEntitlement,
  grant: { grant_id: 'grt_fx_00001' },
  fulfillment: { fulfillment_id: 'ful_fx_00001', status: 'completed', latency_ms: 42 },
  graph_writes: [
    { kind: 'vertex', label: 'PaymentRequirement', properties: {} },
    { kind: 'vertex', label: 'PolicyDecision', properties: {} },
    { kind: 'vertex', label: 'ApprovalRequest', properties: {} },
    { kind: 'vertex', label: 'PaymentAuthorization', properties: {} },
    { kind: 'vertex', label: 'PaymentReceipt', properties: {} },
    { kind: 'vertex', label: 'Settlement', properties: {} },
    { kind: 'vertex', label: 'Entitlement', properties: {} },
    { kind: 'vertex', label: 'AccessGrant', properties: {} },
  ],
  events_emitted: [
    'aether.commerce.challenge.issued',
    'aether.commerce.approval.requested',
    'aether.commerce.approval.approved',
    'aether.commerce.verification.succeeded',
    'aether.commerce.settlement.completed',
    'aether.commerce.entitlement.granted',
    'aether.commerce.access.granted',
  ],
};

export const fixtureApprovalQueue: ApprovalRequest[] = [
  fixtureApprovalCritical,
  fixtureApprovalPending,
];
