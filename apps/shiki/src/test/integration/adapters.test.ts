import { describe, it, expect } from 'vitest';
import { getAdapterMode, createAdapter } from '@shiki/lib/adapters';

describe('Adapter switching', () => {
  it('returns mocked mode in local-mocked environment', () => {
    // Default VITE_SHIKI_ENV is local-mocked
    expect(getAdapterMode()).toBe('mocked');
  });

  it('createAdapter returns mock implementation in mocked mode', () => {
    const mock = { getData: () => 'mock-data' };
    const live = { getData: () => 'live-data' };
    const adapter = createAdapter(mock, live);
    expect(adapter.getData()).toBe('mock-data');
  });
});
