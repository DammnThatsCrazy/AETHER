import { describe, expect, it } from 'vitest';
import {
  connectorSavePostcondition,
  connectorTestPostcondition,
} from '@aether-app/pages/connectors/connector-config-modal';
import { rewardActionPostcondition } from '@aether-app/pages/rewards/approval-queue-page';

describe('tenant operational postconditions', () => {
  it('requires the connector save result to match the requested connector and state', () => {
    expect(connectorSavePostcondition(
      { connector_type: 'shopify', enabled: true },
      'shopify',
      true,
    )).toBeNull();
    expect(connectorSavePostcondition(
      { connector_type: 'slack', enabled: true },
      'shopify',
      true,
    )).toContain('different connector');
    expect(connectorSavePostcondition(
      { connector_type: 'shopify', enabled: false },
      'shopify',
      true,
    )).toContain('does not match');
  });

  it('treats a resolved connector test with ok false as a failed postcondition', () => {
    expect(connectorTestPostcondition(
      { connector_type: 'shopify', ok: true, status: 'ok' },
      'shopify',
    )).toBeNull();
    expect(connectorTestPostcondition(
      { connector_type: 'shopify', ok: false, status: 'not_configured', detail: 'credential missing' },
      'shopify',
    )).toBe('credential missing');
  });

  it('requires reward mutations to return the same action in the exact terminal state', () => {
    expect(rewardActionPostcondition({ id: 'action-1', status: 'ready' }, 'action-1', 'ready')).toBeNull();
    expect(rewardActionPostcondition({ id: 'action-2', status: 'ready' }, 'action-1', 'ready'))
      .toContain('different action ID');
    expect(rewardActionPostcondition({ id: 'action-1', status: 'pending_approval' }, 'action-1', 'ready'))
      .toContain('expected ready');
  });
});
