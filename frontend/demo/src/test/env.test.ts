import { describe, expect, it } from 'vitest';
import { DEMO_ENVIRONMENTS, assertDemoEnv } from '@demo/lib/env';

describe('demo environment contract', () => {
  it('rejects an unset VITE_DEMO_ENV instead of defaulting to mocked mode', () => {
    expect(() => assertDemoEnv(undefined)).toThrow(/VITE_DEMO_ENV is required and has no default/);
    expect(() => assertDemoEnv('')).toThrow(/VITE_DEMO_ENV is required and has no default/);
  });

  it('rejects values that are not canonical demo profiles', () => {
    expect(() => assertDemoEnv('production')).toThrow(/is not a demo profile/);
  });

  it('accepts only the canonical demo profiles', () => {
    expect([...DEMO_ENVIRONMENTS]).toEqual(['local-mocked', 'demo-static', 'demo-live']);
    for (const value of DEMO_ENVIRONMENTS) expect(assertDemoEnv(value)).toBe(value);
  });
});
