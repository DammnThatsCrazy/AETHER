import { describe, expect, it } from 'vitest';

import {
  ActionRuntimeTransitionError,
  graphContextContractVersion,
  resolveCapabilityState,
  validateCanonicalGraphQuery,
  type GraphContext,
  type RuntimeDecisionStatus,
} from './index';

describe('graph runtime public package surface', () => {
  it('exposes graph context contracts and validators from the package barrel', () => {
    const context: GraphContext | null = null;
    expect(context).toBeNull();
    expect(graphContextContractVersion).toBe('1');
    expect(validateCanonicalGraphQuery(null).valid).toBe(false);
  });

  it('exposes unambiguous action runtime aliases and guards', () => {
    const status: RuntimeDecisionStatus = 'pending_approval';
    expect(status).toBe('pending_approval');
    expect(resolveCapabilityState({ entitled: false, permitted: false, ready: false })).toBe('not_entitled');
    expect(new ActionRuntimeTransitionError('unauthorized', 'denied').code).toBe('unauthorized');
  });
});
