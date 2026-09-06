import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { SdkFleetSection } from '@aether-app/pages/settings/sdk-fleet-section';
import { WebhooksSection } from '@aether-app/pages/settings/webhooks-section';
import { NotificationPreferencesSection } from '@aether-app/pages/settings/notification-preferences-section';

// Route-state evidence for the WS-1 Settings-shell sub-routes that the
// FRONTEND-ROUTE-STATE-MATRIX ledger requires (empty/error automation). The
// integrations and connectors routes are covered by their own test files:
//   /settings/integrations            -> settings-integrations-section.test.tsx
//   /settings/integrations/connectors -> connectors-page.test.tsx
// This file covers the remaining three sections. Each route renders its section
// through SettingsPage (settings-page.tsx); assertions here target the exact
// subtree that route mounts, using the sections' real empty/error copy.
const state = vi.hoisted(() => ({
  fleet: 'empty' as 'empty' | 'error' | 'populated',
  webhooks: 'empty' as 'empty' | 'error' | 'populated',
  prefs: 'ok' as 'ok' | 'error',
}));

vi.mock('@aether-app/features/sdk', () => ({
  useSdkFleet: () => {
    if (state.fleet === 'error') {
      return { data: undefined, isLoading: false, error: new Error('sdk offline'), refetch: vi.fn() };
    }
    if (state.fleet === 'populated') {
      return {
        data: {
          total_instances: 3, healthy_count: 2, degraded_count: 1, unhealthy_count: 0,
          silent_count: 1, avg_health_score: 80, platforms: { ios: 2 }, versions: { '1.2.0': 3 },
        },
        isLoading: false, error: null, refetch: vi.fn(),
      };
    }
    return {
      data: { total_instances: 0, healthy_count: 0, degraded_count: 0, unhealthy_count: 0, silent_count: 0, avg_health_score: 0, platforms: {}, versions: {} },
      isLoading: false, error: null, refetch: vi.fn(),
    };
  },
  useSilentSdks: () => ({ data: [], isLoading: false }),
  useSdkManifest: () => ({ data: null, isLoading: false }),
  useSdkRollout: () => ({ data: null, isLoading: false }),
  useRollbackManifest: () => ({ mutate: vi.fn(), isLoading: false }),
  usePublishManifest: () => ({ mutate: vi.fn(), isLoading: false }),
}));

vi.mock('@aether-app/features/account', () => ({
  useMeProfile: () => ({ data: { tenant_id: 'tenant-local', is_admin: false }, isLoading: false, error: null }),
}));

vi.mock('@aether-app/features/account/use-notification-webhooks', () => ({
  useWebhooks: () => {
    if (state.webhooks === 'error') {
      return { data: undefined, isLoading: false, error: new Error('webhooks offline'), refetch: vi.fn() };
    }
    if (state.webhooks === 'populated') {
      return {
        data: [{ id: 'wh_1', url: 'https://example.test/hook', events: ['entity.created'], enabled: true }],
        isLoading: false, error: null, refetch: vi.fn(),
      };
    }
    return { data: [], isLoading: false, error: null, refetch: vi.fn() };
  },
  useCreateWebhook: () => ({ mutate: vi.fn(), isLoading: false }),
  useDeleteWebhook: () => ({ mutate: vi.fn(), isLoading: false }),
  useTestWebhook: () => ({ mutate: vi.fn(), isLoading: false }),
}));

vi.mock('@aether-app/features/notifications/use-notification-preferences', () => ({
  useNotificationPreferences: () => {
    if (state.prefs === 'error') {
      return { data: undefined, isLoading: false, error: new Error('prefs offline'), refetch: vi.fn() };
    }
    return {
      data: {
        timezone: 'UTC',
        quiet_hours: { start: '22:00', end: '08:00' },
        digest: { enabled: true, frequency: 'daily', send_time: '08:00' },
      },
      isLoading: false, error: null, refetch: vi.fn(),
    };
  },
  useUpdateNotificationPreferences: () => ({ mutate: vi.fn(), isLoading: false }),
}));

function renderAt(section: ReactElement, route: string) {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter initialEntries={[route]}>{section}</MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe('/settings/sdk-fleet — SdkFleetSection route states', () => {
  it('renders the successful-empty state when no SDK is reporting', async () => {
    state.fleet = 'empty';
    renderAt(<SdkFleetSection />, '/settings/sdk-fleet');
    expect(await screen.findByText('No SDKs reporting yet')).toBeInTheDocument();
    expect(screen.queryByText('Failed to load SDK fleet')).not.toBeInTheDocument();
  });

  it('renders the unavailable state and never a successful empty when the read fails', async () => {
    state.fleet = 'error';
    renderAt(<SdkFleetSection />, '/settings/sdk-fleet');
    expect(await screen.findByText('Failed to load SDK fleet')).toBeInTheDocument();
    expect(screen.queryByText('No SDKs reporting yet')).not.toBeInTheDocument();
  });

  it('renders the populated fleet overview', async () => {
    state.fleet = 'populated';
    renderAt(<SdkFleetSection />, '/settings/sdk-fleet');
    expect(await screen.findByText('By platform')).toBeInTheDocument();
    expect(screen.queryByText('No SDKs reporting yet')).not.toBeInTheDocument();
  });
});

describe('/settings/webhooks — WebhooksSection route states', () => {
  it('renders the successful-empty state when no endpoint is configured', async () => {
    state.webhooks = 'empty';
    renderAt(<WebhooksSection />, '/settings/webhooks');
    expect(await screen.findByText('No webhook endpoints')).toBeInTheDocument();
    expect(screen.queryByText(/Failed to load webhooks/)).not.toBeInTheDocument();
  });

  it('renders the unavailable state and never a successful empty when the read fails', async () => {
    state.webhooks = 'error';
    renderAt(<WebhooksSection />, '/settings/webhooks');
    expect(await screen.findByText('Failed to load webhooks — check your connection')).toBeInTheDocument();
    expect(screen.queryByText('No webhook endpoints')).not.toBeInTheDocument();
  });

  it('renders configured endpoints when present', async () => {
    state.webhooks = 'populated';
    renderAt(<WebhooksSection />, '/settings/webhooks');
    expect(await screen.findByText('https://example.test/hook')).toBeInTheDocument();
    expect(screen.getByText('entity.created')).toBeInTheDocument();
    expect(screen.queryByText('No webhook endpoints')).not.toBeInTheDocument();
  });
});

describe('/settings/notification-preferences — NotificationPreferencesSection route states', () => {
  it('renders the preferences form from a successful read (no empty concept)', async () => {
    state.prefs = 'ok';
    renderAt(<NotificationPreferencesSection />, '/settings/notification-preferences');
    expect(await screen.findByText('Notification Preferences')).toBeInTheDocument();
    expect(screen.queryByText('Failed to load notification preferences')).not.toBeInTheDocument();
  });

  it('renders the unavailable state when the read fails', async () => {
    state.prefs = 'error';
    renderAt(<NotificationPreferencesSection />, '/settings/notification-preferences');
    expect(await screen.findByText('Failed to load notification preferences')).toBeInTheDocument();
  });
});
