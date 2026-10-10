import { describe, expect, it } from 'vitest';
import type { TenantIntegrationItem } from '@aether-app/features/integrations';
import {
  catalogBaselineCaption,
  tenantConnectionStatus,
} from '@aether-app/features/settings';

function record(partial: Partial<TenantIntegrationItem>): TenantIntegrationItem {
  return {
    id: 'x',
    family: 'x',
    name: null,
    display_name: 'X',
    experience_category: 'advertising_campaigns',
    connected: false,
    enabled: false,
    secret_configured: false,
    sync_status: 'never_synced',
    last_synced_at: null,
    ...partial,
  };
}

describe('features/settings connection-status projection', () => {
  it('never claims connected for an untouched record', () => {
    const s = tenantConnectionStatus(record({}));
    expect(s.label).toBe('Not connected');
    expect(s.indicator).toBe('unknown');
  });

  it('labels a stored-but-disabled secret honestly', () => {
    const s = tenantConnectionStatus(record({ secret_configured: true }));
    expect(s.label).toBe('Credentials saved');
    expect(s.detail).toBe('Not enabled');
  });

  it('maps an active sync to the §6 Syncing word', () => {
    const s = tenantConnectionStatus(record({ enabled: true, sync_status: 'syncing' }));
    expect(s.label).toBe('Syncing');
  });

  it('reads Connected for a configured record with a completed sync', () => {
    const s = tenantConnectionStatus(record({
      enabled: true,
      connected: true,
      sync_status: 'healthy',
      last_synced_at: '2026-09-01T00:00:00Z',
    }));
    expect(s.label).toBe('Connected');
    expect(s.indicator).toBe('healthy');
    expect(s.detail).toBeUndefined();
  });

  it('keeps an enabled but never-synced record Connected with a neutral dot + detail', () => {
    const s = tenantConnectionStatus(record({ enabled: true, connected: true, sync_status: 'never_synced' }));
    expect(s.label).toBe('Connected');
    expect(s.indicator).toBe('unknown');
    expect(s.detail).toBe('Never synced');
  });

  it('labels degraded facts as Needs attention with a truthful reason', () => {
    expect(tenantConnectionStatus(record({ enabled: true, sync_status: 'revoked' })).label).toBe('Needs attention');
    expect(tenantConnectionStatus(record({ enabled: true, sync_status: 'revoked' })).detail).toBe('Credentials were revoked');
    expect(tenantConnectionStatus(record({ enabled: true, sync_status: 'rate_limited' })).indicator).toBe('unhealthy');
    expect(tenantConnectionStatus(record({ enabled: true, sync_status: 'failed' })).label).toBe('Needs attention');
  });

  it('labels a sync_status that never overclaims Ready for live-unknown states', () => {
    const labels = [
      record({}),
      record({ connected: true, sync_status: 'never_synced' }),
      record({ enabled: true, sync_status: 'syncing' }),
      record({ enabled: true, sync_status: 'revoked' }),
    ].map(r => tenantConnectionStatus(r).label);
    expect(labels).not.toContain('Ready');
  });
});

describe('features/settings catalog-baseline captions', () => {
  it('captions common manifest states without asserting tenant readiness', () => {
    expect(catalogBaselineCaption('credential_waiting')).toContain('awaiting provider activation');
    expect(catalogBaselineCaption('partner_live')).toBe('Catalog: live');
    expect(catalogBaselineCaption(undefined)).toBeNull();
    expect(catalogBaselineCaption('')).toBeNull();
  });
});
