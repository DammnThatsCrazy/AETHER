import { describe, expect, it } from 'vitest';
import { buildAmplifyEnvironmentConfig } from './amplify';
import { PRODUCTION_DOMAINS } from './domains';

describe('buildAmplifyEnvironmentConfig', () => {
  it('resolves honest defaults from an empty source: development, no Cognito ids, API falls back to the app origin', () => {
    const config = buildAmplifyEnvironmentConfig({});
    expect(config.environment).toBe('development');
    expect(config.branch).toBe('main');
    expect(config.apiUrl).toBe(PRODUCTION_DOMAINS.aetherApp);
    expect(config.authRegion).toBe('us-east-1');
    expect(config.userPoolId).toBeUndefined();
    expect(config.userPoolClientId).toBeUndefined();
    expect(config.identityPoolId).toBeUndefined();
    expect(config.domains).toEqual(PRODUCTION_DOMAINS);
  });

  it('reads Amplify Hosting and Cognito variables when present', () => {
    const config = buildAmplifyEnvironmentConfig({
      AMPLIFY_ENV: 'production',
      AWS_BRANCH: 'release',
      VITE_API_BASE_URL: 'https://api.olympuslabsml.com',
      VITE_COGNITO_REGION: 'us-west-2',
      VITE_COGNITO_USER_POOL_ID: 'us-west-2_example',
      VITE_COGNITO_USER_POOL_CLIENT_ID: 'client-123',
      VITE_COGNITO_IDENTITY_POOL_ID: 'us-west-2:identity-123',
    });
    expect(config.environment).toBe('production');
    expect(config.branch).toBe('release');
    expect(config.apiUrl).toBe('https://api.olympuslabsml.com');
    expect(config.authRegion).toBe('us-west-2');
    expect(config.userPoolId).toBe('us-west-2_example');
    expect(config.userPoolClientId).toBe('client-123');
    expect(config.identityPoolId).toBe('us-west-2:identity-123');
  });

  it('lets domain overrides flow through into the config', () => {
    const config = buildAmplifyEnvironmentConfig({}, { aetherApp: 'https://app.invalid' });
    expect(config.apiUrl).toBe('https://app.invalid');
    expect(config.domains.aetherApp).toBe('https://app.invalid');
  });
});
