import { describe, expect, it } from 'vitest';
import { DEMO_ENVIRONMENTS, parseDemoConfig } from '@demo/lib/env';

const valid = {
  VITE_DEMO_ENV: 'local',
  VITE_API_BASE_URL: 'http://localhost:8000',
  VITE_DEMO_TENANT_ID: 'demo',
  VITE_DEMO_SEED_NAMESPACE: 'aether-demo',
  VITE_AETHER_URL: 'http://localhost:5173',
  VITE_KYBER_URL: 'http://localhost:5174',
};

describe('demo environment contract', () => {
  it('accepts only the live runtime vocabulary', () => {
    expect([...DEMO_ENVIRONMENTS]).toEqual(['local', 'staging', 'production', 'test']);
    expect(parseDemoConfig(valid).environment).toBe('local');
  });

  it.each([
    ['VITE_DEMO_ENV', undefined],
    ['VITE_API_BASE_URL', undefined],
    ['VITE_DEMO_TENANT_ID', undefined],
    ['VITE_DEMO_SEED_NAMESPACE', undefined],
    ['VITE_AETHER_URL', undefined],
    ['VITE_KYBER_URL', undefined],
  ])('fails closed when %s is missing', (name, value) => {
    expect(() => parseDemoConfig({ ...valid, [name]: value })).toThrow(`${name} is required`);
  });

  it('rejects the former browser fixture profiles', () => {
    for (const environment of ['local-mocked', 'demo-static', 'demo-live']) {
      expect(() => parseDemoConfig({ ...valid, VITE_DEMO_ENV: environment })).toThrow(/invalid/);
    }
  });

  it('requires secure production URLs', () => {
    expect(() => parseDemoConfig({
      ...valid,
      VITE_DEMO_ENV: 'production',
      VITE_API_BASE_URL: 'http://api.invalid',
      VITE_AETHER_URL: 'https://aether.invalid',
      VITE_KYBER_URL: 'https://kyber.invalid',
    })).toThrow(/HTTPS/);
  });
});
