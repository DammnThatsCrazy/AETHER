import { describe, it, expect } from 'vitest';
import {
  EnvironmentStartupError,
  getEnvironment,
  isProduction,
  parseEnvironment,
} from '@aether-app/lib/env';

describe('getEnvironment', () => {
  it('returns the explicit test environment', () => {
    expect(getEnvironment()).toBe('test');
  });
});

describe('isProduction', () => {
  it('returns false in the test environment', () => {
    expect(isProduction()).toBe(false);
  });
});

describe('fail-closed startup configuration matrix', () => {
  const local = {
    VITE_AETHER_ENV: 'local',
    VITE_API_BASE_URL: 'http://localhost:8000',
    VITE_AETHER_ENDPOINT: 'http://localhost:8000',
  };
  const production = {
    ...local,
    VITE_AETHER_ENV: 'production',
    VITE_API_BASE_URL: 'https://api.aether.example',
    VITE_AETHER_ENDPOINT: 'https://api.aether.example',
    VITE_AUTH0_DOMAIN: 'tenant.auth0.com',
    VITE_AUTH0_CLIENT_ID: 'client-id',
    VITE_AUTH0_REDIRECT_URI: 'https://app.aether.example/callback',
  };

  it.each([
    ['missing environment name', { ...local, VITE_AETHER_ENV: undefined }],
    ['invalid environment name', { ...local, VITE_AETHER_ENV: 'preview' }],
    ['missing API URL', { ...local, VITE_API_BASE_URL: undefined }],
    ['malformed API URL', { ...local, VITE_API_BASE_URL: 'not a URL' }],
    ['staging with incomplete auth', {
      ...local,
      VITE_AETHER_ENV: 'staging',
      VITE_API_BASE_URL: 'https://staging-api.aether.example',
      VITE_AETHER_ENDPOINT: 'https://staging-api.aether.example',
    }],
    ['production with an insecure API URL', {
      ...production,
      VITE_API_BASE_URL: 'http://api.aether.example',
    }],
  ])('rejects %s before application startup', (_label, input) => {
    expect(() => parseEnvironment(input)).toThrow(EnvironmentStartupError);
  });

  it('accepts a complete secure production configuration', () => {
    expect(parseEnvironment(production).VITE_AETHER_ENV).toBe('production');
  });
});
