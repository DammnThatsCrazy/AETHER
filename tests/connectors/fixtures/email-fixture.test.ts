/**
 * FPS-113 — Email Connector Fixture
 * Verifies Email raw and normalized fixture validation.
 *
 * Email fixtures are stored as inline objects in @aether/proof-fixtures/src/index.ts
 * (emailSentFixture, emailOpenFixture, emailClickFixture, emailBounceFixture,
 * emailUnsubscribeFixture). The loader API (loadRawFixture / loadExpectedNormalized /
 * findFixtureDir) routes through the fixtures/<domain>/ directory on disk, which
 * does not contain individual JSON files for connector domains — only the SDK event
 * keys have single-file JSON fixtures under fixtures/sdk-events/.
 *
 * This test validates the connector fixtures by importing them directly and
 * asserting their shape against the EventEnvelope contract.
 */
import { describe, it, expect } from 'vitest';

import { findFixtureDir } from '@aether/proof-fixtures';
import { EventEnvelope } from '@aether/proof-contracts';
import {
  emailSentFixture,
  emailOpenFixture,
  emailClickFixture,
  emailBounceFixture,
  emailUnsubscribeFixture,
} from '@aether/proof-fixtures';

describe('FPS-113: Email Fixture', () => {
  it('should import email fixtures from @aether/proof-fixtures', () => {
    expect(emailSentFixture).toBeDefined();
    expect(emailOpenFixture).toBeDefined();
    expect(emailClickFixture).toBeDefined();
    expect(emailBounceFixture).toBeDefined();
    expect(emailUnsubscribeFixture).toBeDefined();
  });

  it('should validate emailSentFixture shape', () => {
    const f = emailSentFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.tenant_id).toBe('aether-proof-tenant');
    expect(f.workspace_id).toBe('proof-lab');
    expect(f.platform_id).toBe('email');
    expect(f.environment).toBe('staging');
    expect(f.event_type).toBe('email_sent');
    expect(f.sdk.name).toBe('@aether/email');
    expect(f.sdk.version).toBe('0.1.0-alpha.0');
    expect(f.identity.anonymous_id).toBe('anon_email_001');
    expect(f.identity.user_id).toBe('user_007');
    expect(typeof f.timestamp).toBe('string');
    expect(f.properties.messageId).toBe('msg_sent_001');
    expect(f.properties.email).toBe('user@example.com');
    expect(f.properties.campaignId).toBe('camp_001');
  });

  it('should validate emailOpenFixture shape', () => {
    const f = emailOpenFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.tenant_id).toBe('aether-proof-tenant');
    expect(f.platform_id).toBe('email');
    expect(f.event_type).toBe('email_opened');
    expect(f.sdk.name).toBe('@aether/email');
    expect(f.identity.anonymous_id).toBe('anon_email_open_001');
    expect(f.identity.user_id).toBe('user_007');
    expect(f.properties.messageId).toBe('msg_sent_001');
    expect(f.properties.email).toBe('user@example.com');
    expect(f.properties.platform).toBe('mobile');
    expect(f.properties.client).toBe('apple mail');
  });

  it('should validate emailClickFixture shape', () => {
    const f = emailClickFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.platform_id).toBe('email');
    expect(f.event_type).toBe('email_clicked');
    expect(f.sdk.name).toBe('@aether/email');
    expect(f.identity.anonymous_id).toBe('anon_email_click_001');
    expect(f.identity.user_id).toBe('user_007');
    expect(f.properties.link).toBe('https://example.com/offer');
    expect(f.properties.linkText).toBe('Claim Your Offer');
    expect(f.properties.platform).toBe('mobile');
    expect(f.properties.client).toBe('apple mail');
  });

  it('should validate emailBounceFixture shape', () => {
    const f = emailBounceFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.platform_id).toBe('email');
    expect(f.event_type).toBe('email_bounced');
    expect(f.sdk.name).toBe('@aether/email');
    expect(f.identity.anonymous_id).toBe('anon_email_bounce_001');
    expect(f.properties.reason).toBe('hard_bounce');
    expect(f.properties.status).toBe('5.1.1');
    expect(f.properties.diagnosticCode).toBe('smtp; 550 5.1.1 User unknown');
    expect(f.properties.provider).toBe('sendgrid');
  });

  it('should validate emailUnsubscribeFixture shape', () => {
    const f = emailUnsubscribeFixture;
    expect(f._fixture_version).toBe(1);
    expect(f.platform_id).toBe('email');
    expect(f.event_type).toBe('unsubscribe_observed');
    expect(f.sdk.name).toBe('@aether/email');
    expect(f.identity.anonymous_id).toBe('anon_email_unsub_001');
    expect(f.identity.user_id).toBe('user_008');
    expect(f.properties.reason).toBe('user_initiated');
    expect(f.properties.unsubscribedVia).toBe('one_click');
    expect(f.properties.provider).toBe('sendgrid');
  });

  it('should validate emailSentFixture against EventEnvelope contract', () => {
    const envelope = emailSentFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.workspace_id).toBe('proof-lab');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.environment).toBe('staging');
    expect(envelope.event_type).toBe('email_sent');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_email_001');
    expect(envelope.identity.user_id).toBe('user_007');
    expect(typeof envelope.timestamp).toBe('string');
    expect(envelope.properties).toBeDefined();
  });

  it('should validate emailOpenFixture against EventEnvelope contract', () => {
    const envelope = emailOpenFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_opened');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.identity.anonymous_id).toBe('anon_email_open_001');
    expect(envelope.identity.user_id).toBe('user_007');
  });

  it('should validate emailClickFixture against EventEnvelope contract', () => {
    const envelope = emailClickFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_clicked');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.identity.anonymous_id).toBe('anon_email_click_001');
    expect(envelope.identity.user_id).toBe('user_007');
  });

  it('should validate emailBounceFixture against EventEnvelope contract', () => {
    const envelope = emailBounceFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_bounced');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.identity.anonymous_id).toBe('anon_email_bounce_001');
  });

  it('should validate emailUnsubscribeFixture against EventEnvelope contract', () => {
    const envelope = emailUnsubscribeFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('unsubscribe_observed');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.identity.anonymous_id).toBe('anon_email_unsub_001');
    expect(envelope.identity.user_id).toBe('user_008');
  });
});
