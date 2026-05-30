import { describe, it, expect } from 'vitest';
import { getEnvironment, getRuntimeMode, isLocalMocked, isProduction, isMockAuthAllowed } from '@aether-app/lib/env';

// In jsdom test environment VITE_* vars are unset; Zod defaults to 'local-mocked'.

describe('getEnvironment', () => {
  it('returns local-mocked in the default test environment', () => {
    expect(getEnvironment()).toBe('local-mocked');
  });
});

describe('getRuntimeMode', () => {
  it('returns mocked when environment is local-mocked', () => {
    expect(getRuntimeMode()).toBe('mocked');
  });
});

describe('isLocalMocked', () => {
  it('returns true in local-mocked environment', () => {
    expect(isLocalMocked()).toBe(true);
  });
});

describe('isProduction', () => {
  it('returns false in local-mocked environment', () => {
    expect(isProduction()).toBe(false);
  });
});

describe('isMockAuthAllowed', () => {
  it('allows mock auth in local-mocked environment', () => {
    expect(isMockAuthAllowed()).toBe(true);
  });
});
