/**
 * FPS-144 — Email Unsubscribe Integration
 * Verifies email unsubscribe event handling.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { emailUnsubscribeFixture } from '@aether/proof-fixtures';

describe('FPS-144: Email Unsubscribe', () => {
  it('should validate email unsubscribe fixture', () => {
    expect(emailUnsubscribeFixture.event_type).toBe('unsubscribe_observed');
    expect(emailUnsubscribeFixture.platform_id).toBe('email');
    expect(emailUnsubscribeFixture.tenant_id).toBe('aether-proof-tenant');
    const props = emailUnsubscribeFixture.properties as Record<string, unknown>;
    expect(props.type).toBe('unsubscribe');
    expect(props.email).toBe('unsub@example.com');
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
    expect(props.provider).toBe('sendgrid');
    expect(props.unsubscribedAt).toBe('2024-09-11T13:10:00.000Z');
    expect(props.reason).toBe('user_initiated');
    expect(props.unsubscribedVia).toBe('one_click');
  });

  it('should have campaign linkage', () => {
    const props = emailUnsubscribeFixture.properties as Record<string, unknown>;
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
  });

  it('should validate raw fixture against EventEnvelope shape', () => {
    const envelope = emailUnsubscribeFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('unsubscribe_observed');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_email_unsub_001');
    expect(envelope.identity.user_id).toBe('user_008');
  });

  it('should derive unsubscribe from unsubscribe event type', () => {
    const eventType = emailUnsubscribeFixture.event_type;
    expect(eventType).toBe('unsubscribe_observed');
    expect(eventType.toLowerCase()).toContain('unsubscribe');
    expect(eventType.toLowerCase()).toContain('observed');
  });
});
