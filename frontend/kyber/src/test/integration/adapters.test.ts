import { describe, it, expect } from 'vitest';
import { getAdapterMode, createAdapter } from '@kyber/lib/adapters';

describe('Adapter switching', () => {
  it('returns live mode in the explicit test environment', () => {
    expect(getAdapterMode()).toBe('live');
  });

  it('createAdapter returns the live implementation', () => {
    const mock = { getData: () => 'mock-data' };
    const live = { getData: () => 'live-data' };
    const adapter = createAdapter(mock, live);
    expect(adapter.getData()).toBe('live-data');
  });
});
