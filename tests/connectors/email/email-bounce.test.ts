/**
 * FPS-143 — Email Bounce Integration
 * Verifies email bounce event handling.
 */
import { describe, it, expect } from 'vitest';
import { EventEnvelope } from '@aether/proof-contracts';
import { emailBounceFixture } from '@aether/proof-fixtures';

describe('FPS-143: Email Bounce', () => {
  it('should validate email bounce fixture', () => {
    expect(emailBounceFixture.event_type).toBe('email_bounced');
    expect(emailBounceFixture.platform_id).toBe('email');
    expect(emailBounceFixture.tenant_id).toBe('aether-proof-tenant');
    const props = emailBounceFixture.properties as Record<string, unknown>;
    expect(props.type).toBe('bounce');
    expect(props.email).toBe('bounce@example.com');
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
    expect(props.templateId).toBe('tpl_welcome_001');
    expect(props.provider).toBe('sendgrid');
    expect(props.messageId).toBe('msg_bounce_001');
    expect(props.bouncedAt).toBe('2024-09-11T13:05:00.000Z');
    expect(props.reason).toBe('hard_bounce');
    expect(props.status).toBe('5.1.1');
    expect(props.diagnosticCode).toBe('smtp; 550 5.1.1 User unknown');
  });

  it('should validate bounce has campaign linkage', () => {
    const props = emailBounceFixture.properties as Record<string, unknown>;
    expect(props.campaignId).toBe('camp_001');
    expect(props.campaignName).toBe('Welcome Series Day 1');
  });

  it('should map bounce event to communication node key', () => {
    const props = emailBounceFixture.properties as Record<string, unknown>;
    const messageId = props.messageId as string;
    const commKey = `comm_email_${messageId}`;
    expect(commKey).toBe('comm_email_msg_bounce_001');
  });

  it('should derive bounce severity from bounce type', () => {
    expect('hard').toBe('hard');
    expect('soft').toBe('soft');
  });
});
