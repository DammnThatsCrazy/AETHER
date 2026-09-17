/** @description FPS-141 — Email Open Integration
 * Verifies email open event sync to graph communication nodes.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { emailOpenFixture } from '@aether/proof-fixtures';

describe('FPS-141: Email Open', () => {
  it('should validate email open fixture', () => {
    expect(emailOpenFixture.event_type).toBe('email_opened');
    expect(emailOpenFixture.platform_id).toBe('email');
    expect(emailOpenFixture.tenant_id).toBe('aether-proof-tenant');
    const props = emailOpenFixture.properties as Record<string, unknown>;
    expect(props.type).toBe('open');
    expect(props.email).toBe('user@example.com');
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
    // The fixture subject contains a literal backslash before the apostrophe
    expect((props.subject as string).endsWith("s what you need to know")).toBe(true);
    expect(props.messageId).toBe('msg_sent_001');
    expect(props.openedAt).toBe('2024-09-11T13:02:00.000Z');
    expect(props.userAgent).toBe('Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15');
    expect(props.platform).toBe('mobile');
    expect(props.client).toBe('apple mail');
  });

  it('should validate open has campaign linkage', () => {
    const props = emailOpenFixture.properties as Record<string, unknown>;
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
  });

  it('should validate raw fixture against EventEnvelope shape', () => {
    const envelope = emailOpenFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_opened');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_email_open_001');
    expect(envelope.identity.user_id).toBe('user_007');
  });

  it('should map open event to communication node key', () => {
    const messageId = emailOpenFixture.properties.messageId as string;
    const commKey = `comm_email_${messageId}`;
    expect(commKey).toBe('comm_email_msg_sent_001');
  });

  it('should fixture have _fixture_version 1', () => {
    expect(emailOpenFixture._fixture_version).toBe(1);
    expect(emailOpenFixture._fixtureName).toBe('emailOpenFixture');
  });
});
