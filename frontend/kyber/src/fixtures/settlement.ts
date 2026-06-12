/**
 * KYBER fixtures — Settlement domain.
 * Deterministic scenarios for Lab replay, mock mode, and tests.
 */
import type { Settlement } from '@kyber/lib/schemas/commerce';
import { fixtureSettlement } from './commerce';

export { fixtureSettlement };

export const fixtureSettlementPending: Settlement = {
  ...fixtureSettlement,
  settlement_id: 'set_fx_pending_02',
  state: 'pending',
  tx_hash: '0x' + 'b'.repeat(64),
  settled_at: null,
  failure_reason: null,
  attempts: 0,
};

export const fixtureSettlementVerifying: Settlement = {
  ...fixtureSettlement,
  settlement_id: 'set_fx_verifying_03',
  state: 'verifying',
  tx_hash: '0x' + 'c'.repeat(64),
  settled_at: null,
  failure_reason: null,
  attempts: 1,
};

export const fixtureSettlementFailed: Settlement = {
  ...fixtureSettlement,
  settlement_id: 'set_fx_failed_04',
  state: 'failed',
  tx_hash: '0x' + 'd'.repeat(64),
  settled_at: null,
  failure_reason: 'Transaction reverted on-chain',
  attempts: 3,
};

export const fixtureSettlementDisputed: Settlement = {
  ...fixtureSettlement,
  settlement_id: 'set_fx_disputed_05',
  state: 'disputed',
  tx_hash: '0x' + 'e'.repeat(64),
  settled_at: null,
  failure_reason: 'Amount mismatch — manual review required',
  attempts: 2,
};

export const fixtureSettlementList: Settlement[] = [
  fixtureSettlement,
  fixtureSettlementVerifying,
  fixtureSettlementFailed,
];

export const fixtureStuckSettlements = [
  {
    settlement_id: 'set_fx_stuck_01',
    state: 'pending',
    created_at: '2026-04-04T11:00:00Z',
    age_seconds: 3850,
    resource_id: 'res_fx_ml_predict',
    amount: 0.10,
  },
];
