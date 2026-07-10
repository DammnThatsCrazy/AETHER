import { describe, expect, it } from 'vitest';
import {
  isDecimalString,
  PEG_STATUSES,
  STABLECOIN_ACTOR_EDGE_LAYER_MAP,
  STABLECOIN_CAPABILITIES,
  STABLECOIN_DEPLOYMENT_TYPES,
  STABLECOIN_DOMAIN_EDGE_LAYER_MAP,
  STABLECOIN_EDGE_LAYER_MAP,
  STABLECOIN_ENTITY_KINDS,
  STABLECOIN_FINALITY_STATUSES,
  STABLECOIN_OBSERVATION_TYPES,
  SUPPORT_ASSERTION_STATUSES,
  validateStablecoinDeployment,
  validateStablecoinObservation,
  validateStablecoinSupportAssertion,
} from './stablecoin-intelligence';

const VALID_EVIDENCE = {
  evidence_class: 'fact',
  source_refs: ['bronze:row:1'],
  source_event_ids: ['evt-1'],
  confidence: '1.0',
  valid_time: '2026-07-08T00:00:00Z',
  recorded_time: '2026-07-08T00:00:01Z',
  explanation: 'observed on-chain transfer log',
};

const VALID_OBSERVATION = {
  observation_id: 'obs-1',
  tenant_id: 'tenant-a',
  idempotency_key: 'idem-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  observation_type: 'transfer',
  deployment_id: 'dep-usdc-base',
  canonical_asset_id: 'asset-usdc',
  chain_id: 'eip155:8453',
  transaction_hash: '0xabc',
  amount_atomic: '1000000',
  amount_decimal: '1.000000',
  finality_status: 'finalized',
  classification_confidence: '0.98',
  observed_at: '2026-07-08T00:00:00Z',
  ingested_at: '2026-07-08T00:00:02Z',
};

const VALID_DEPLOYMENT = {
  deployment_id: 'dep-usdc-base',
  canonical_asset_id: 'asset-usdc',
  chain_id: 'eip155:8453',
  network: 'base-mainnet',
  token_standard: 'erc20',
  contract_or_mint: '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
  decimals: 6,
  deployment_type: 'canonical',
  issuer_verified: true,
  active: true,
  testnet: false,
  first_seen_at: '2026-01-01T00:00:00Z',
  global_reference: true,
};

const VALID_ASSERTION = {
  assertion_id: 'sa-1',
  tenant_id: 'tenant-a',
  idempotency_key: 'idem-sa-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  subject_entity_ref: { kind: 'organization', id: 'org-1' },
  deployment_id: 'dep-usdc-base',
  capability: 'accept_payment',
  support_status: 'production_active',
  environment: 'production',
  evidence_type: 'observed_settlement',
  successful_observation_count: 12,
  failed_observation_count: 0,
  confidence: '0.9',
};

describe('stablecoin decimal strings', () => {
  it('accepts canonical decimal strings', () => {
    for (const value of ['0', '1', '-1', '1.5', '-0.000001', '123456789.123456789']) {
      expect(isDecimalString(value)).toBe(true);
    }
  });

  it('rejects non-decimal values', () => {
    for (const value of ['1e5', 'abc', '', '1.', '.5', '1.5.5', NaN, 1.5, null, undefined, {}]) {
      expect(isDecimalString(value)).toBe(false);
    }
  });
});

describe('validateStablecoinObservation', () => {
  it('accepts a fully-valid observation', () => {
    const result = validateStablecoinObservation(VALID_OBSERVATION);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects non-object input', () => {
    for (const bad of [null, undefined, 'x', 5, []]) {
      expect(validateStablecoinObservation(bad).valid).toBe(false);
    }
  });

  it('rejects execution_by_aether true or missing', () => {
    const asExecuted = validateStablecoinObservation({ ...VALID_OBSERVATION, execution_by_aether: true });
    expect(asExecuted.valid).toBe(false);
    expect(asExecuted.errors.join(' ')).toContain('execution_by_aether');

    const { execution_by_aether: _dropped, ...withoutFlag } = VALID_OBSERVATION;
    expect(validateStablecoinObservation(withoutFlag).valid).toBe(false);
  });

  it('rejects binary-number amounts', () => {
    const result = validateStablecoinObservation({ ...VALID_OBSERVATION, amount_decimal: 1.5 });
    expect(result.valid).toBe(false);
    expect(result.errors.join(' ')).toContain('amount_decimal');
  });

  it('rejects unknown observation_type and finality_status', () => {
    expect(validateStablecoinObservation({ ...VALID_OBSERVATION, observation_type: 'trade' }).valid).toBe(false);
    expect(validateStablecoinObservation({ ...VALID_OBSERVATION, finality_status: 'done' }).valid).toBe(false);
  });

  it('requires every mandatory identity field', () => {
    for (const field of [
      'observation_id', 'tenant_id', 'idempotency_key', 'deployment_id',
      'canonical_asset_id', 'chain_id', 'transaction_hash', 'observed_at', 'ingested_at',
    ]) {
      const result = validateStablecoinObservation({ ...VALID_OBSERVATION, [field]: '' });
      expect(result.valid).toBe(false);
      expect(result.errors.join(' ')).toContain(field);
    }
  });
});

describe('validateStablecoinDeployment', () => {
  it('accepts a fully-valid deployment', () => {
    const result = validateStablecoinDeployment(VALID_DEPLOYMENT);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects out-of-range or fractional decimals', () => {
    for (const decimals of [-1, 37, 6.5, '6', null]) {
      expect(validateStablecoinDeployment({ ...VALID_DEPLOYMENT, decimals }).valid).toBe(false);
    }
  });

  it('rejects unknown deployment types and missing contract identity', () => {
    expect(validateStablecoinDeployment({ ...VALID_DEPLOYMENT, deployment_type: 'shadow' }).valid).toBe(false);
    expect(validateStablecoinDeployment({ ...VALID_DEPLOYMENT, contract_or_mint: '' }).valid).toBe(false);
  });

  it('requires the global_reference marker', () => {
    expect(validateStablecoinDeployment({ ...VALID_DEPLOYMENT, global_reference: false }).valid).toBe(false);
  });
});

describe('validateStablecoinSupportAssertion', () => {
  it('accepts a fully-valid support assertion', () => {
    const result = validateStablecoinSupportAssertion(VALID_ASSERTION);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects unknown capability and support_status', () => {
    expect(validateStablecoinSupportAssertion({ ...VALID_ASSERTION, capability: 'stake' }).valid).toBe(false);
    expect(validateStablecoinSupportAssertion({ ...VALID_ASSERTION, support_status: 'live' }).valid).toBe(false);
  });

  it('rejects negative or fractional observation counts', () => {
    expect(validateStablecoinSupportAssertion({ ...VALID_ASSERTION, successful_observation_count: -1 }).valid).toBe(false);
    expect(validateStablecoinSupportAssertion({ ...VALID_ASSERTION, failed_observation_count: 1.5 }).valid).toBe(false);
  });

  it('rejects execution_by_aether true', () => {
    expect(validateStablecoinSupportAssertion({ ...VALID_ASSERTION, execution_by_aether: true }).valid).toBe(false);
  });
});

describe('stablecoin graph edge layer maps', () => {
  it('classifies actor edges into the four relationship layers only', () => {
    const layers = new Set(Object.values(STABLECOIN_ACTOR_EDGE_LAYER_MAP));
    expect(Object.values(STABLECOIN_ACTOR_EDGE_LAYER_MAP)).not.toContain('DOMAIN_EXCLUDED');
    for (const layer of layers) {
      expect(['H2H', 'H2A', 'A2H', 'A2A']).toContain(layer);
    }
  });

  it('keeps every domain edge excluded from actor layers', () => {
    expect(Object.values(STABLECOIN_DOMAIN_EDGE_LAYER_MAP).every((layer) => layer === 'DOMAIN_EXCLUDED')).toBe(true);
  });

  it('merges actor and domain maps without key collisions', () => {
    const actorKeys = Object.keys(STABLECOIN_ACTOR_EDGE_LAYER_MAP);
    const domainKeys = Object.keys(STABLECOIN_DOMAIN_EDGE_LAYER_MAP);
    expect(Object.keys(STABLECOIN_EDGE_LAYER_MAP)).toHaveLength(actorKeys.length + domainKeys.length);
    expect(STABLECOIN_EDGE_LAYER_MAP.TRANSFERRED_STABLECOIN).toBe('DOMAIN_EXCLUDED');
    expect(STABLECOIN_EDGE_LAYER_MAP.REQUESTED_STABLECOIN_PAYMENT).toBe('A2H');
  });
});

describe('stablecoin canonical enums', () => {
  it('exports unique, non-empty entity kinds', () => {
    expect(STABLECOIN_ENTITY_KINDS.length).toBeGreaterThan(0);
    expect(new Set(STABLECOIN_ENTITY_KINDS).size).toBe(STABLECOIN_ENTITY_KINDS.length);
    expect(STABLECOIN_ENTITY_KINDS).toContain('stablecoin_deployment');
  });

  it('keeps runtime enum arrays unique and unknown-terminated', () => {
    for (const values of [
      STABLECOIN_OBSERVATION_TYPES, STABLECOIN_FINALITY_STATUSES, SUPPORT_ASSERTION_STATUSES,
      STABLECOIN_CAPABILITIES, PEG_STATUSES, STABLECOIN_DEPLOYMENT_TYPES,
    ]) {
      expect(new Set(values).size).toBe(values.length);
      expect(values).toContain('unknown');
    }
  });
});
