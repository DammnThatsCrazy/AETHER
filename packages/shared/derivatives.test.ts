import { describe, expect, it } from 'vitest';
import {
  DERIVATIVES_ACTOR_EDGE_LAYER_MAP,
  DERIVATIVES_DOMAIN_EDGE_LAYER_MAP,
  DERIVATIVES_EDGE_LAYER_MAP,
  DERIVATIVES_ENTITY_KINDS,
  DEFAULT_CONSENT_STATE,
  EXPLICIT_OPT_IN_PURPOSES,
} from './index';

describe('derivatives PR1 contracts', () => {
  it('classifies every derivatives graph edge explicitly', () => {
    expect(Object.values(DERIVATIVES_ACTOR_EDGE_LAYER_MAP)).not.toContain('DOMAIN_EXCLUDED');
    expect(Object.values(DERIVATIVES_DOMAIN_EDGE_LAYER_MAP).every((layer) => layer === 'DOMAIN_EXCLUDED')).toBe(true);
    expect(DERIVATIVES_EDGE_LAYER_MAP.HOLDS_POSITION).toBe('DOMAIN_EXCLUDED');
    expect(DERIVATIVES_EDGE_LAYER_MAP.DELEGATES_TRADING_TO).toBe('H2A');
  });

  it('exports canonical derivatives entity kinds', () => {
    expect(DERIVATIVES_ENTITY_KINDS).toContain('derivative_market');
    expect(DERIVATIVES_ENTITY_KINDS).toContain('venue_credential_reference');
  });

  it('keeps financial activity explicit opt-in and default disabled', () => {
    expect(EXPLICIT_OPT_IN_PURPOSES).toContain('financial_activity');
    expect(DEFAULT_CONSENT_STATE.financial_activity).toBe(false);
  });
});
