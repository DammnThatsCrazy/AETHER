/**
 * KYBER fixtures — Protected Resources domain.
 * Deterministic scenarios for Lab replay, mock mode, and tests.
 */
import type { ProtectedResource, PreflightResult } from '@kyber/lib/schemas/commerce';
import { fixtureResources } from './commerce';

export { fixtureResources };

export const fixtureResourceServicePlan: ProtectedResource = {
  resource_id: 'res_fx_plan_pro',
  tenant_id: 'tenant_kyber_mock',
  name: 'Aether Pro Plan',
  resource_class: 'service_plan',
  path_pattern: '/v1/subscriptions/pro',
  owner_service: 'billing',
  description: 'Monthly Pro subscription plan',
  price_usd: 49.00,
  accepted_assets: ['USDC'],
  accepted_chains: ['eip155:8453', 'solana:mainnet'],
  approval_required: true,
  entitlement_ttl_seconds: 2592000,
  active: true,
  registered_at: '2026-04-04T12:00:00Z',
};

export const fixtureResourcePricedEndpoint: ProtectedResource = {
  resource_id: 'res_fx_data_stream',
  tenant_id: 'tenant_kyber_mock',
  name: 'Real-time Data Stream',
  resource_class: 'priced_endpoint',
  path_pattern: '/v1/data/stream',
  owner_service: 'analytics',
  description: 'Per-call data streaming endpoint',
  price_usd: 0.005,
  accepted_assets: ['USDC'],
  accepted_chains: ['eip155:8453'],
  approval_required: false,
  entitlement_ttl_seconds: 60,
  active: true,
  registered_at: '2026-04-04T12:00:00Z',
};

export const fixtureResourceInactive: ProtectedResource = {
  ...fixtureResources[0]!,
  resource_id: 'res_fx_deprecated',
  name: 'Deprecated API v1',
  active: false,
};

export const fixtureResourceList: ProtectedResource[] = [
  ...fixtureResources,
  fixtureResourceServicePlan,
  fixtureResourcePricedEndpoint,
];

export const fixturePreflightGranted: PreflightResult = {
  can_access: true,
  reason: 'active_entitlement',
  resource_id: 'res_fx_ml_predict',
  holder_id: 'agent_alpha',
  existing_entitlement_id: 'ent_fx_00001',
  price_quote_usd: null,
  accepted_assets: ['USDC'],
  accepted_chains: ['eip155:8453', 'solana:mainnet'],
  approval_required: true,
  challenge_url: null,
};

export const fixturePreflightDenied: PreflightResult = {
  can_access: false,
  reason: 'payment_required',
  resource_id: 'res_fx_ml_predict',
  holder_id: 'agent_beta',
  existing_entitlement_id: null,
  price_quote_usd: 0.10,
  accepted_assets: ['USDC'],
  accepted_chains: ['eip155:8453', 'solana:mainnet'],
  approval_required: true,
  challenge_url: '/v1/x402/challenge',
};
