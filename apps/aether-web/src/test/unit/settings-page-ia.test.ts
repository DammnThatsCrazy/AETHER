import { describe, expect, it } from 'vitest';
import {
  resolveSettingsSection,
  SETTINGS_NAV,
} from '@aether-app/pages/settings/settings-page';

// Settings-shell IA contract: every nav entry resolves to its own section and
// /settings/data-exchange is a real, dedicated section — never the api-keys
// fall-through (the pre-convergence defect where the Data Exchange route
// rendered the API Keys section with a Data Exchange card mounted underneath).
describe('Settings shell IA', () => {
  it('every SETTINGS_NAV entry maps to its own section via the resolver', () => {
    for (const item of SETTINGS_NAV) {
      expect(resolveSettingsSection(item.to)).toBe(item.section);
    }
  });

  it('exposes Data Exchange as a dedicated nav section, not an index/end route', () => {
    const dx = SETTINGS_NAV.find(item => item.section === 'data-exchange');
    expect(dx).toBeDefined();
    expect(dx?.to).toBe('/settings/data-exchange');
    expect(dx?.label).toBe('Data Exchange');
    expect(dx?.end).toBeUndefined();
  });

  it('resolves /settings/data-exchange (and nested paths) to the data-exchange section', () => {
    expect(resolveSettingsSection('/settings/data-exchange')).toBe('data-exchange');
    expect(resolveSettingsSection('/settings/data-exchange/transfers')).toBe('data-exchange');
    // Regression guard: this route previously fell through to the api-keys index.
    expect(resolveSettingsSection('/settings/data-exchange')).not.toBe('api-keys');
  });

  it('keeps /settings as the api-keys index and unknown paths falling back safely', () => {
    expect(resolveSettingsSection('/settings')).toBe('api-keys');
    expect(resolveSettingsSection('/settings/api-keys')).toBe('api-keys');
    expect(resolveSettingsSection('/settings/unknown')).toBe('api-keys');
  });

  it('resolves the sibling section routes distinctly', () => {
    expect(resolveSettingsSection('/settings/integrations')).toBe('integrations');
    expect(resolveSettingsSection('/settings/integrations/connectors')).toBe('integrations');
    expect(resolveSettingsSection('/settings/sdk-fleet')).toBe('sdk-fleet');
    expect(resolveSettingsSection('/settings/notifications')).toBe('notifications');
    expect(
      resolveSettingsSection('/settings/notification-preferences'),
    ).toBe('notification-preferences');
    expect(resolveSettingsSection('/settings/webhooks')).toBe('webhooks');
  });
});
