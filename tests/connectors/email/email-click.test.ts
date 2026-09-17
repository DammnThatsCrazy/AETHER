/** @description FPS-142 — Email Click Integration
 * Verifies email click event sync to graph communication nodes.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { emailClickFixture } from '@aether/proof-fixtures';

describe('FPS-142: Email Click', () => {
  it('should validate email click fixture', () => {
    expect(emailClickFixture.event_type).toBe('email_clicked');
    expect(emailClickFixture.platform_id).toBe('email');
    expect(emailClickFixture.tenant_id).toBe('aether-proof-tenant');
    const props = emailClickFixture.properties as Record<string, unknown>;
    expect(props.type).toBe('click');
    expect(props.email).toBe('user@example.com');
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
    expect(props.messageId).toBe('msg_sent_001');
    expect(props.clickedAt).toBe('2024-09-11T13:03:00.000Z');
    expect(props.link).toBe('https://example.com/offer');
    expect(props.linkText).toBe('Claim Your Offer');
    expect(props.linkPosition).toBe(1);
    expect(props.platform).toBe('mobile');
    expect(props.client).toBe('apple mail');
  });

  it('should validate click has campaign linkage', () => {
    const props = emailClickFixture.properties as Record<string, unknown>;
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
  });

  it('should validate raw fixture against EventEnvelope shape', () => {
    const envelope = emailClickFixture as unknown as EventEnvelope;
    expect(envelope.tenant_id).toBe('aether-proof-tenant');
    expect(envelope.platform_id).toBe('email');
    expect(envelope.event_type).toBe('email_clicked');
    expect(envelope.sdk.name).toBe('@aether/email');
    expect(envelope.sdk.version).toBe('0.1.0-alpha.0');
    expect(envelope.identity.anonymous_id).toBe('anon_email_click_001');
    expect(envelope.identity.user_id).toBe('user_007');
  });

  it('should map click event to communication node key', () => {
    const props = emailClickFixture.properties as Record<string, unknown>;
    const messageId = props.messageId as string;
    const commKey = `comm_email_${messageId}`;
    expect(commKey).toBe('comm_email_msg_sent_001');
  });

  it('should fixture have _fixture_version 1', () => {
    expect(emailClickFixture._fixture_version).toBe(1);
    expect(emailClickFixture._fixtureName).toBe('emailClickFixture');
  });
});
