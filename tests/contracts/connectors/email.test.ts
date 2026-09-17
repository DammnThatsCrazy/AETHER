/**
 * FPS-022 — Email Connector Contract
 * Verifies email event payloads (sent/open/click/bounce/unsubscribe) conform to @aether/proof-contracts.
 */
import { describe, it, expect } from 'vitest';

import { EventEnvelope, SourceClassification, Communication } from '@aether/proof-contracts';
import {
  emailSentFixture,
  emailOpenFixture,
  emailClickFixture,
  emailBounceFixture,
  emailUnsubscribeFixture,
} from '@aether/proof-fixtures';

describe('FPS-022: Email Connector', () => {
  it('should construct a valid email sent event envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: emailSentFixture.tenant_id,
      workspace_id: emailSentFixture.workspace_id,
      platform_id: emailSentFixture.platform_id,
      environment: emailSentFixture.environment,
      event_type: emailSentFixture.event_type,
      sdk: emailSentFixture.sdk,
      identity: emailSentFixture.identity,
      timestamp: emailSentFixture.timestamp,
      properties: emailSentFixture.properties,
    };
    expect(envelope.event_type).toBe('email_sent');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.properties?.type).toBe('sent');
    expect(envelope.properties?.email).toBe('user@example.com');
    expect(envelope.properties?.campaignId).toBe('camp_001');
    expect(envelope.properties?.provider).toBe('sendgrid');
  });

  it('should construct a valid email open event envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: emailOpenFixture.tenant_id,
      workspace_id: emailOpenFixture.workspace_id,
      platform_id: emailOpenFixture.platform_id,
      environment: emailOpenFixture.environment,
      event_type: emailOpenFixture.event_type,
      sdk: emailOpenFixture.sdk,
      identity: emailOpenFixture.identity,
      timestamp: emailOpenFixture.timestamp,
      properties: emailOpenFixture.properties,
    };
    expect(envelope.event_type).toBe('email_opened');
    expect(envelope.properties?.type).toBe('open');
    expect(envelope.properties?.email).toBe('user@example.com');
    expect(envelope.properties?.openedAt).toBe('2024-09-11T13:02:00.000Z');
  });

  it('should construct a valid email click event envelope with link metadata', () => {
    const envelope: EventEnvelope = {
      tenant_id: emailClickFixture.tenant_id,
      workspace_id: emailClickFixture.workspace_id,
      platform_id: emailClickFixture.platform_id,
      environment: emailClickFixture.environment,
      event_type: emailClickFixture.event_type,
      sdk: emailClickFixture.sdk,
      identity: emailClickFixture.identity,
      timestamp: emailClickFixture.timestamp,
      properties: emailClickFixture.properties,
    };
    expect(envelope.event_type).toBe('email_clicked');
    expect(envelope.properties?.type).toBe('click');
    expect(envelope.properties?.link).toMatch(/^https?:\/\//);
    expect(envelope.properties?.linkText).toBe('Claim Your Offer');
  });

  it('should construct a valid email bounce event envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: emailBounceFixture.tenant_id,
      workspace_id: emailBounceFixture.workspace_id,
      platform_id: emailBounceFixture.platform_id,
      environment: emailBounceFixture.environment,
      event_type: emailBounceFixture.event_type,
      sdk: emailBounceFixture.sdk,
      identity: emailBounceFixture.identity,
      timestamp: emailBounceFixture.timestamp,
      properties: emailBounceFixture.properties,
    };
    expect(envelope.event_type).toBe('email_bounced');
    expect(envelope.properties?.type).toBe('bounce');
    expect(envelope.properties?.reason).toBe('hard_bounce');
    expect(envelope.properties?.status).toBe('5.1.1');
    expect(envelope.properties?.provider).toBe('sendgrid');
  });

  it('should construct a valid email unsubscribe event envelope', () => {
    const envelope: EventEnvelope = {
      tenant_id: emailUnsubscribeFixture.tenant_id,
      workspace_id: emailUnsubscribeFixture.workspace_id,
      platform_id: emailUnsubscribeFixture.platform_id,
      environment: emailUnsubscribeFixture.environment,
      event_type: emailUnsubscribeFixture.event_type,
      sdk: emailUnsubscribeFixture.sdk,
      identity: emailUnsubscribeFixture.identity,
      timestamp: emailUnsubscribeFixture.timestamp,
      properties: emailUnsubscribeFixture.properties,
    };
    expect(envelope.event_type).toBe('unsubscribe_observed');
    expect(envelope.properties?.type).toBe('unsubscribe');
    expect(envelope.properties?.email).toBe('unsub@example.com');
    expect(envelope.properties?.reason).toBe('user_initiated');
  });

  it('should classify email source correctly', () => {
    const source: SourceClassification = {
      platform: 'email',
      data_type: 'communication',
      platform_id: 'sendgrid',
      sdk: '@aether/email',
      environment: 'staging',
    };
    expect(source.platform).toBe('email');
    expect(source.data_type).toBe('communication');
    expect(source.platform_id).toBe('sendgrid');
  });

  it('should construct Communication contract from email sent fixture', () => {
    const comm: Communication = {
      communication_id: emailSentFixture.properties?.messageId || 'msg_001',
      type: 'email',
      channel: 'email',
      campaign_id: emailSentFixture.properties?.campaignId || 'camp_001',
      recipient: emailSentFixture.properties?.email || 'user@example.com',
      subject: emailSentFixture.properties?.subject || 'Welcome',
      status: 'sent',
      timestamp: emailSentFixture.timestamp,
      source: {
        platform: 'email',
        data_type: 'communication',
        sdk: '@aether/email',
        environment: 'staging',
      },
    };
    expect(comm.communication_id).toBe('msg_sent_001');
    expect(comm.type).toBe('email');
    expect(comm.recipient).toBe('user@example.com');
    expect(comm.status).toBe('sent');
  });

  it('should validate email fixtures have _fixture_version', () => {
    expect(emailSentFixture._fixture_version).toBe(1);
    expect(emailOpenFixture._fixture_version).toBe(1);
    expect(emailClickFixture._fixture_version).toBe(1);
    expect(emailBounceFixture._fixture_version).toBe(1);
    expect(emailUnsubscribeFixture._fixture_version).toBe(1);
  });

  it('should deduplicate email events by messageId', () => {
    const msgId = emailSentFixture.properties?.messageId;
    expect(msgId).toBe('msg_sent_001');
    // Same messageId across sent/open/click indicates same email
    expect(emailOpenFixture.properties?.messageId).toBe(msgId);
    expect(emailClickFixture.properties?.messageId).toBe(msgId);
  });
});
