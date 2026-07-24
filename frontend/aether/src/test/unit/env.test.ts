import { describe, it, expect } from 'vitest';
import { getEnvironment, getRuntimeMode, isProduction } from '@aether-app/lib/env';

describe('getEnvironment', () => {
  it('returns the explicit test environment', () => {
    expect(getEnvironment()).toBe('test');
  });
});

describe('getRuntimeMode', () => {
  it('keeps the test environment on the live data path', () => {
    expect(getRuntimeMode()).toBe('live');
  });
});

describe('isProduction', () => {
  it('returns false in the test environment', () => {
    expect(isProduction()).toBe(false);
  });
});
