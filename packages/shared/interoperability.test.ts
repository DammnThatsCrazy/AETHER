import { describe, expect, it } from 'vitest';
import {
  ASSET_LEG_TYPES,
  INTEROP_ACTOR_EDGE_LAYER_MAP,
  INTEROP_DOMAIN_EDGE_LAYER_MAP,
  INTEROP_EDGE_LAYER_MAP,
  INTEROP_ENTITY_KINDS,
  INTEROP_IMPLEMENTATION_STATUSES,
  INTEROP_LEGAL_TRANSITIONS,
  INTEROP_MESSAGE_STATUSES,
  INTEROP_PROVIDER_KINDS,
  INTEROP_TERMINAL_STATES,
  isInteropDecimalString,
  isLegalTransition,
  validateAssetLeg,
  validateInteropMessage,
  validateLifecycleTransition,
  validateSecurityPolicySnapshot,
  type InteropMessageStatus,
} from './interoperability';

const VALID_EVIDENCE = {
  evidence_class: 'fact',
  source_refs: ['chain:log:0xabc:1'],
  source_event_ids: ['evt-1'],
  confidence: '1.0',
  valid_time: '2026-07-08T00:00:00Z',
  recorded_time: '2026-07-08T00:00:01Z',
  explanation: 'decoded source-chain dispatch log',
};

const VALID_MESSAGE = {
  interop_message_id: 'msg-1',
  tenant_id: 'public',
  tenant_scope: 'public',
  idempotency_key: 'idem-msg-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  schema_version: '1.0.0',
  provider_id: 'layerzero_v2',
  provider_kind: 'layerzero_v2',
  protocol_product: 'messaging',
  correlation_key: 'lz2:0xguid',
  provider_message_refs: [{ alias_type: 'guid', alias_value: '0xguid', canonical: true }],
  source: {
    network_id: 'ethereum-mainnet',
    native_chain_id: '1',
    transaction_hash: '0xsrc',
    block_number: '123',
  },
  path_id: 'path-1-42161',
  status: 'delivered',
  technical_outcome: 'success',
  asset_leg_ids: [],
  delivery_attempt_ids: ['da-1'],
  confidence: '0.99',
  data_freshness: 'live',
};

const VALID_SNAPSHOT = {
  security_snapshot_id: 'snap-1',
  tenant_id: 'public',
  idempotency_key: 'idem-snap-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  provider_id: 'layerzero_v2',
  path_id: 'path-1-42161',
  verification_model: 'external_verifier_set',
  required_verifier_ids: ['dvn-a', 'dvn-b'],
  optional_verifier_ids: [],
  delivery_actor_ids: ['exec-1'],
  module_addresses: { send_library: '0xsend', receive_library: '0xrecv' },
  content_hash: 'sha256:abc',
  captured_at: '2026-07-08T00:00:00Z',
};

const VALID_ASSET_LEG = {
  asset_leg_id: 'leg-1',
  tenant_id: 'tenant-a',
  idempotency_key: 'idem-leg-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  interop_message_id: 'msg-1',
  leg_type: 'burn',
  network_id: 'ethereum-mainnet',
  amount_decimal: '25.5',
  observed_at: '2026-07-08T00:00:00Z',
};

const VALID_TRANSITION = {
  transition_id: 'tr-1',
  tenant_id: 'public',
  idempotency_key: 'idem-tr-1',
  evidence: VALID_EVIDENCE,
  execution_by_aether: false,
  interop_message_id: 'msg-1',
  from_status: 'verified',
  to_status: 'delivered',
  observed_at: '2026-07-08T00:00:00Z',
};

describe('interop lifecycle FSM', () => {
  it('defines a transition list for every message status', () => {
    for (const status of INTEROP_MESSAGE_STATUSES) {
      expect(INTEROP_LEGAL_TRANSITIONS[status]).toBeDefined();
      expect(Array.isArray(INTEROP_LEGAL_TRANSITIONS[status])).toBe(true);
    }
    expect(Object.keys(INTEROP_LEGAL_TRANSITIONS).sort()).toEqual([...INTEROP_MESSAGE_STATUSES].sort());
  });

  it('only references known statuses as transition targets', () => {
    for (const targets of Object.values(INTEROP_LEGAL_TRANSITIONS)) {
      for (const target of targets) {
        expect(INTEROP_MESSAGE_STATUSES).toContain(target);
      }
    }
  });

  it('keeps terminal states terminal', () => {
    for (const terminal of INTEROP_TERMINAL_STATES) {
      expect(INTEROP_LEGAL_TRANSITIONS[terminal]).toEqual([]);
    }
    for (const [state, targets] of Object.entries(INTEROP_LEGAL_TRANSITIONS)) {
      if (targets.length === 0) {
        expect(INTEROP_TERMINAL_STATES).toContain(state as InteropMessageStatus);
      }
    }
  });

  it('answers legality queries correctly', () => {
    expect(isLegalTransition('delivered', 'executed')).toBe(true);
    expect(isLegalTransition('verified', 'delivered')).toBe(true);
    expect(isLegalTransition('failed', 'recovered')).toBe(true);
    expect(isLegalTransition('settled', 'delivered')).toBe(false);
    expect(isLegalTransition('discovered', 'delivered')).toBe(false);
    expect(isLegalTransition('refunded', 'failed')).toBe(false);
  });
});

describe('validateInteropMessage', () => {
  it('accepts a fully-valid public message', () => {
    const result = validateInteropMessage(VALID_MESSAGE);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects non-object input', () => {
    for (const bad of [null, undefined, 'x', 7, []]) {
      expect(validateInteropMessage(bad).valid).toBe(false);
    }
  });

  it('rejects execution_by_aether true or missing', () => {
    expect(validateInteropMessage({ ...VALID_MESSAGE, execution_by_aether: true }).valid).toBe(false);
    const { execution_by_aether: _dropped, ...withoutFlag } = VALID_MESSAGE;
    expect(validateInteropMessage(withoutFlag).valid).toBe(false);
  });

  it('rejects unknown status, provider kind, and tenant scope', () => {
    expect(validateInteropMessage({ ...VALID_MESSAGE, status: 'in_flight' }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, provider_kind: 'layerzero_v1' }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, tenant_scope: 'global' }).valid).toBe(false);
  });

  it('requires correlation key, source endpoint, and array fields', () => {
    expect(validateInteropMessage({ ...VALID_MESSAGE, correlation_key: '' }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, source: undefined }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, asset_leg_ids: 'none' }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, delivery_attempt_ids: null }).valid).toBe(false);
  });

  it('validates fee decimals only when present', () => {
    expect(validateInteropMessage({ ...VALID_MESSAGE, fee_total_decimal: '0.004' }).valid).toBe(true);
    expect(validateInteropMessage({ ...VALID_MESSAGE, fee_total_decimal: 0.004 }).valid).toBe(false);
    expect(validateInteropMessage({ ...VALID_MESSAGE, fee_total_decimal: '4e-3' }).valid).toBe(false);
  });
});

describe('validateSecurityPolicySnapshot', () => {
  it('accepts a fully-valid snapshot', () => {
    const result = validateSecurityPolicySnapshot(VALID_SNAPSHOT);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('requires content hash and verifier arrays', () => {
    expect(validateSecurityPolicySnapshot({ ...VALID_SNAPSHOT, content_hash: '' }).valid).toBe(false);
    expect(validateSecurityPolicySnapshot({ ...VALID_SNAPSHOT, required_verifier_ids: 'dvn-a' }).valid).toBe(false);
    expect(validateSecurityPolicySnapshot({ ...VALID_SNAPSHOT, delivery_actor_ids: null }).valid).toBe(false);
  });

  it('rejects unknown verification models', () => {
    expect(validateSecurityPolicySnapshot({ ...VALID_SNAPSHOT, verification_model: 'dvn' }).valid).toBe(false);
  });
});

describe('validateAssetLeg', () => {
  it('accepts a fully-valid asset leg', () => {
    const result = validateAssetLeg(VALID_ASSET_LEG);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects unknown leg types and non-decimal amounts', () => {
    expect(validateAssetLeg({ ...VALID_ASSET_LEG, leg_type: 'teleport' }).valid).toBe(false);
    expect(validateAssetLeg({ ...VALID_ASSET_LEG, amount_decimal: 25.5 }).valid).toBe(false);
    expect(validateAssetLeg({ ...VALID_ASSET_LEG, amount_atomic: 'many' }).valid).toBe(false);
  });
});

describe('validateLifecycleTransition', () => {
  it('accepts a legal transition', () => {
    const result = validateLifecycleTransition(VALID_TRANSITION);
    expect(result.errors).toEqual([]);
    expect(result.valid).toBe(true);
  });

  it('rejects illegal transitions with a named error', () => {
    const result = validateLifecycleTransition({
      ...VALID_TRANSITION, from_status: 'settled', to_status: 'delivered',
    });
    expect(result.valid).toBe(false);
    expect(result.errors.join(' ')).toContain('illegal lifecycle transition');
  });

  it('rejects unknown statuses', () => {
    expect(validateLifecycleTransition({ ...VALID_TRANSITION, from_status: 'shipped' }).valid).toBe(false);
    expect(validateLifecycleTransition({ ...VALID_TRANSITION, to_status: 'landed' }).valid).toBe(false);
  });

  it('rejects execution_by_aether true', () => {
    expect(validateLifecycleTransition({ ...VALID_TRANSITION, execution_by_aether: true }).valid).toBe(false);
  });
});

describe('interop graph edge layer maps', () => {
  it('classifies actor edges into the four relationship layers only', () => {
    expect(Object.values(INTEROP_ACTOR_EDGE_LAYER_MAP)).not.toContain('DOMAIN_EXCLUDED');
    for (const layer of Object.values(INTEROP_ACTOR_EDGE_LAYER_MAP)) {
      expect(['H2H', 'H2A', 'A2H', 'A2A']).toContain(layer);
    }
  });

  it('keeps every domain edge excluded from actor layers', () => {
    expect(Object.values(INTEROP_DOMAIN_EDGE_LAYER_MAP).every((layer) => layer === 'DOMAIN_EXCLUDED')).toBe(true);
  });

  it('merges actor and domain maps without collisions', () => {
    const total = Object.keys(INTEROP_ACTOR_EDGE_LAYER_MAP).length
      + Object.keys(INTEROP_DOMAIN_EDGE_LAYER_MAP).length;
    expect(Object.keys(INTEROP_EDGE_LAYER_MAP)).toHaveLength(total);
    expect(INTEROP_EDGE_LAYER_MAP.RELAYED_FOR).toBe('A2H');
    expect(INTEROP_EDGE_LAYER_MAP.VERIFIED_BY).toBe('DOMAIN_EXCLUDED');
  });
});

describe('interop canonical enums', () => {
  it('exports unique entity kinds', () => {
    expect(new Set(INTEROP_ENTITY_KINDS).size).toBe(INTEROP_ENTITY_KINDS.length);
    expect(INTEROP_ENTITY_KINDS).toContain('interop_message');
    expect(INTEROP_ENTITY_KINDS).toContain('security_policy_snapshot');
  });

  it('keeps runtime enum arrays unique', () => {
    for (const values of [
      INTEROP_MESSAGE_STATUSES, INTEROP_PROVIDER_KINDS, ASSET_LEG_TYPES, INTEROP_IMPLEMENTATION_STATUSES,
    ]) {
      expect(new Set(values).size).toBe(values.length);
    }
  });

  it('never claims live status for unimplemented providers by default', () => {
    expect(INTEROP_IMPLEMENTATION_STATUSES).toContain('scaffolded');
    expect(INTEROP_IMPLEMENTATION_STATUSES).toContain('credential_gated');
  });

  it('validates decimal strings strictly', () => {
    expect(isInteropDecimalString('10.25')).toBe(true);
    expect(isInteropDecimalString('-3')).toBe(true);
    expect(isInteropDecimalString('1e5')).toBe(false);
    expect(isInteropDecimalString(10.25)).toBe(false);
  });
});
