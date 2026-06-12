/**
 * KYBER fixtures — Entitlements domain.
 * Deterministic scenarios for Lab replay, mock mode, and tests.
 */
import type { Entitlement } from '@kyber/lib/schemas/commerce';
import { fixtureEntitlement } from './commerce';

export { fixtureEntitlement };

export const fixtureEntitlementReused: Entitlement = {
  ...fixtureEntitlement,
  entitlement_id: 'ent_fx_reused_02',
  reuse_count: 12,
  last_reused_at: '2026-04-04T12:18:00Z',
};

export const fixtureEntitlementExpired: Entitlement = {
  ...fixtureEntitlement,
  entitlement_id: 'ent_fx_expired_03',
  status: 'expired',
  expires_at: '2026-04-04T11:00:00Z',
  reuse_count: 5,
  last_reused_at: '2026-04-04T10:55:00Z',
};

export const fixtureEntitlementRevoked: Entitlement = {
  ...fixtureEntitlement,
  entitlement_id: 'ent_fx_revoked_04',
  status: 'revoked',
  revoked_at: '2026-04-04T12:30:00Z',
  revoked_by: 'ops_alice',
  revoke_reason: 'Agent decommissioned',
  reuse_count: 2,
};

export const fixtureEntitlementSiwxBound: Entitlement = {
  ...fixtureEntitlement,
  entitlement_id: 'ent_fx_siwx_05',
  siwx_binding: 'session_abc123',
  holder_type: 'user',
  holder_id: 'user_wallet_0xabc',
  reuse_count: 1,
};

export const fixtureEntitlementList: Entitlement[] = [
  fixtureEntitlement,
  fixtureEntitlementReused,
  fixtureEntitlementExpired,
];
