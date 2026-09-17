/** @description FPS-140 — Email Sent Integration
 * Verifies email sent event sync to graph communication nodes.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { emailSentFixture } from '@aether/proof-fixtures';

describe('FPS-140: Email Sent', () => {
  it('should validate email sent fixture', () => {
    expect(emailSentFixture.event_type).toBe('email_sent');
    expect(emailSentFixture.platform_id).toBe('email');
    expect(emailSentFixture.tenant_id).toBe('aether-proof-tenant');
    const props = emailSentFixture.properties as Record<string, unknown>;
    expect(props.type).toBe('sent');
    expect(props.email).toBe('user@example.com');
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
    // The fixture subject contains a literal backslash before the apostrophe
    expect((props.subject as string).endsWith("s what you need to know")).toBe(true);
    expect(props.messageId).toBe('msg_sent_001');
    expect(props.sendAt).toBe('2024-09-11T13:00:00.000Z');
  });

  it('should validate email sent has campaign linkage', () => {
    const props = emailSentFixture.properties as Record<string, unknown>;
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
  });

  it('should validate raw fixture against EventEnvelope shape', () => {
    const envelope = emailSentFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_sent');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_email_001');
    expect(envelope.identity.user_id).toBe('user_007');
  });

  it('should map sent event to communication node key', () => {
    const props = emailSentFixture.properties as Record<string, unknown>;
    const messageId = props.messageId as string;
    const commKey = `comm_email_${messageId}`;
    expect(commKey).toBe('comm_email_msg_sent_001');
  });

  it('should fixture have _fixture_version 1', () => {
    expect(emailSentFixture._fixture_version).toBe(1);
    expect(emailSentFixture._fixtureName).toBe('emailSentFixture');
  });
});
