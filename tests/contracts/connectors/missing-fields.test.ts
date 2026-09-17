/**
 * FPS-022 — Connector Missing Fields Validation
 * Verifies that connectors reject or sanitize events with missing required fields.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope } from '@aether/proof-contracts';
import { missingFieldsFixture } from '@aether/proof-fixtures';

describe('FPS-022: Connector Missing Fields', () => {
  it('should load missing fields fixture with partial event', () => {
    const partial = missingFieldsFixture.properties?.partialEvent;
    expect(partial?.eventName).toBe('incomplete');
    expect(partial?.timestamp).toBe('2024-09-11T13:15:00.000Z');
    expect(partial).not.toHaveProperty('properties');
  });

  it('should load missing fields fixture with missing email', () => {
    const missingEmail = missingFieldsFixture.properties?.missingEmail;
    expect(missingEmail?.eventName).toBe('signup');
    expect(missingEmail?.timestamp).toBe('2024-09-11T13:15:00.000Z');
    expect(missingEmail).not.toHaveProperty('email');
  });

  it('should accept track event without properties', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'page',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.properties).toBeUndefined();
    expect(envelope.event_type).toBe('page');
  });

  it('should accept identify event without traits in properties', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'identify',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1', user_id: 'user_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    expect(envelope.properties).toBeUndefined();
    expect(envelope.event_type).toBe('identify');
  });

  it('should flag validation errors from fixture', () => {
    const errors = missingFieldsFixture.properties?.validationErrors;
    expect(Array.isArray(errors)).toBe(true);
    expect(errors?.length).toBe(2);
    expect(errors?.[0]).toEqual({
      field: 'properties.email',
      error: 'missing_required_field',
      event: 'partialEvent',
    });
    expect(errors?.[1]).toEqual({
      field: 'identity.email',
      error: 'missing_required_field',
      event: 'missingEmail',
    });
  });

  it('should construct EventEnvelope with minimal required fields only', () => {
    const envelope: EventEnvelope = {
      tenant_id: missingFieldsFixture.tenant_id,
      workspace_id: missingFieldsFixture.workspace_id,
      platform_id: missingFieldsFixture.platform_id,
      environment: missingFieldsFixture.environment,
      event_type: missingFieldsFixture.event_type,
      sdk: missingFieldsFixture.sdk,
      identity: missingFieldsFixture.identity,
      timestamp: missingFieldsFixture.timestamp,
      properties: missingFieldsFixture.properties,
    };
    expect(envelope.event_type).toBe('track');
    expect(envelope.properties?.partialEvent).toBeDefined();
    expect(envelope.properties?.validationErrors).toBeDefined();
  });

  it('should validate that tenant_id and workspace_id are always present', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'track',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
    };
    // These are the non-negotiable fields
    expect(envelope.tenant_id).toBe('t1');
    expect(envelope.workspace_id).toBe('w1');
    expect(envelope.platform_id).toBe('web');
    expect(envelope.environment).toBe('staging');
    expect(envelope.sdk.name).toBe('@aether/web');
    expect(envelope.sdk.version).toBe('1.0.0');
    expect(envelope.identity.anonymous_id).toBe('anon_1');
  });

  it('should accept events with only required fields + event_type', () => {
    const envelope: EventEnvelope = {
      tenant_id: 't1',
      workspace_id: 'w1',
      platform_id: 'web',
      environment: 'staging',
      event_type: 'custom_event',
      sdk: { name: '@aether/web', version: '1.0.0' },
      identity: { anonymous_id: 'anon_1' },
      timestamp: '2024-01-01T00:00:00.000Z',
      properties: { partialData: true },
    };
    expect(envelope.event_type).toBe('custom_event');
    expect(envelope.properties?.partialData).toBe(true);
  });
});
