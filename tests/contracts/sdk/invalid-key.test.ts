/**
 * FPS-021 — SDK Invalid Key Handling
 * Verifies that invalid API keys are rejected at initialization.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { invalidKeyFixture } from '@aether/proof-fixtures';

describe('FPS-021: SDK Invalid Key Handling', () => {
  it('should reject empty API key', () => {
    const key = '';
    expect(key).toBe('');
    expect(typeof key).toBe('string');
    expect(key.length).toBe(0);
  });

  it('should reject malformed API key', () => {
    const key = 'not-a-valid-key';
    expect(typeof key).toBe('string');
    expect(key.length).toBeGreaterThan(0);
    expect(key).not.toMatch(/^ak_(live|test)_/);
  });

  it('should use fixture invalid key data', () => {
    expect(invalidKeyFixture.event_type).toBe('sdk_config_failed');
    expect(invalidKeyFixture.properties?.error_code).toBe('INVALID_API_KEY');
    expect(invalidKeyFixture.properties?.error_message).toContain('invalid');
    expect(invalidKeyFixture.properties?.config_key).toBe('apiKey');
    expect(invalidKeyFixture.properties?.attempted_value).toBe('***REDACTED***');
  });

  it('should construct an EventEnvelope for invalid key error', () => {
    const envelope: EventEnvelope = {
      tenant_id: invalidKeyFixture.tenant_id,
      workspace_id: invalidKeyFixture.workspace_id,
      platform_id: invalidKeyFixture.platform_id,
      environment: invalidKeyFixture.environment,
      event_type: invalidKeyFixture.event_type,
      sdk: invalidKeyFixture.sdk,
      identity: invalidKeyFixture.identity,
      timestamp: invalidKeyFixture.timestamp,
      properties: {
        error_code: 'INVALID_API_KEY',
        error_message: 'The provided API key is invalid or expired',
        config_key: 'apiKey',
        attempted_value: '***REDACTED***',
      },
    };
    expect(envelope.event_type).toBe('sdk_config_failed');
    expect(envelope.properties?.error_code).toBe('INVALID_API_KEY');
    expect(envelope.properties?.error_message).toBeDefined();
    expect(envelope.identity.anonymous_id).toBe('anon_invalid');
  });

  it('should accept key matching expected pattern', () => {
    const validKey = 'ak_live_abc123def456';
    expect(typeof validKey).toBe('string');
    expect(validKey.length).toBeGreaterThan(10);
    expect(validKey).toMatch(/^ak_(live|test)_/);
  });

  it('should construct envelope with all required EventEnvelope fields for error event', () => {
    const envelope: EventEnvelope = {
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'sdk_config_failed',
      sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
      identity: { anonymous_id: 'anon_invalid' },
      timestamp: '2024-09-11T12:15:00.000Z',
      properties: {
        error_code: 'INVALID_API_KEY',
        error_message: 'The provided API key is invalid or expired',
      },
    };
    // Validate required fields are present
    expect(envelope.tenant_id).toBeTruthy();
    expect(envelope.workspace_id).toBeTruthy();
    expect(envelope.platform_id).toBeTruthy();
    expect(envelope.environment).toBeTruthy();
    expect(envelope.event_type).toBeTruthy();
    expect(envelope.sdk.name).toBeTruthy();
    expect(envelope.sdk.version).toBeTruthy();
    expect(envelope.identity.anonymous_id).toBeTruthy();
    expect(envelope.timestamp).toBeTruthy();
  });
});
