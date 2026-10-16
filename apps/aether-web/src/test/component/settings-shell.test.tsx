import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import {
  SETTINGS_GROUPS,
  SETTINGS_NAV,
  SettingsPage,
  resolveSettingsView,
  settingsTabHref,
} from '@aether-app/pages/settings/settings-page';

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });
const failed = (error = 'offline') => ({ data: undefined, isLoading: false, error, refetch: vi.fn() });
const loading = () => ({ data: undefined, isLoading: true, error: null, refetch: vi.fn() });

const s = vi.hoisted(() => ({
  org: null as unknown,
  temporal: null as unknown,
  me: null as unknown,
  usage: null as unknown,
  members: null as null | (() => Promise<unknown>),
  invitations: null as null | (() => Promise<unknown>),
}));

vi.mock('@aether-app/pages/settings/api-keys-section', () => ({ ApiKeysSection: () => <div>API KEYS SECTION</div> }));
vi.mock('@aether-app/pages/settings/integrations-section', () => ({ IntegrationsSection: () => <div>INTEGRATIONS SECTION</div> }));
vi.mock('@aether-app/pages/settings/sdk-fleet-section', () => ({ SdkFleetSection: () => <div>SDK FLEET SECTION</div> }));
vi.mock('@aether-app/pages/settings/notifications-section', () => ({ NotificationsSection: () => <div>CHANNELS SECTION</div> }));
vi.mock('@aether-app/pages/settings/notification-preferences-section', () => ({ NotificationPreferencesSection: () => <div>PREFERENCES SECTION</div> }));
vi.mock('@aether-app/pages/settings/webhooks-section', () => ({ WebhooksSection: () => <div>WEBHOOKS SECTION</div> }));
vi.mock('@aether-app/pages/settings/data-exchange-section', () => ({ DataExchangeGate: () => <div>DATA EXCHANGE SECTION</div> }));
vi.mock('@aether-app/components/outcome-ledger-panel', () => ({ OutcomeLedgerPanel: () => <div>OUTCOME LEDGER</div> }));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { id: 'u1', displayName: 'Owner' } }) }));
vi.mock('@aether-app/features/onboarding/use-workspace-setup', () => ({
  useOrganizationProfile: () => s.org,
  useTenantTemporalDefaults: () => s.temporal,
}));
vi.mock('@aether-app/features/account', () => ({
  useMeProfile: () => s.me,
  useUsage: () => s.usage,
}));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    organization: {
      members: () => s.members!(),
      invitations: () => s.invitations!(),
    },
  },
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderAt(route: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[route]}>
        <SettingsPage />
        <LocationProbe />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  queryCache.invalidatePrefix('settings:');
  s.org = settled({ organization_id: 'o1', tenant_id: 't1', name: 'Northpeak', slug: 'northpeak', description: null, owner_user_id: 'u1', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' });
  s.temporal = settled({ business_time_zone: 'Europe/London' });
  s.me = settled({ tenant_id: 't1', name: 'Osaze', contact_email: 'owner@example.test', plan: { plan_id: 'p', display_name: 'Growth', monthly_quota: 100, burst_rpm: 10 }, billing: { subscription_status: 'active', current_period_end: '2026-11-01T00:00:00Z' }, api_key_count: 1, is_admin: true });
  s.usage = settled({ period_start: '2026-10-01T00:00:00Z', period_end: '2026-10-31T00:00:00Z', events_used: 400, events_quota: 1000, rpm_peak: 12, rpm_limit: 600, overage_events: 0, days_remaining: 15 });
  s.members = () => Promise.resolve({ data: [{ member_id: 'm1', tenant_id: 't1', user_id: 'u1', email: 'owner@example.test', display_name: 'Osaze', role: 'owner', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }], pagination: {}, meta: {} });
  s.invitations = () => Promise.resolve([]);
});

describe('Settings shell IA (design grouping)', () => {
  it('puts every existing /settings section in exactly one design group', () => {
    for (const item of SETTINGS_NAV) {
      const owners = SETTINGS_GROUPS.filter(g => g.tabs.some(t => t.kind === 'section' && t.section === item.section));
      expect(owners, item.section).toHaveLength(1);
      const tab = owners[0]!.tabs.find(t => t.kind === 'section' && t.section === item.section)!;
      expect(settingsTabHref(tab)).toBe(item.to);
    }
  });

  it('resolves section routes as before and reads ?section only on the index', () => {
    expect(resolveSettingsView('/settings', '')).toMatchObject({ section: 'api-keys', hub: null });
    expect(resolveSettingsView('/settings', '').group.id).toBe('connections');
    expect(resolveSettingsView('/settings/webhooks', '?section=billing')).toMatchObject({ section: 'webhooks', hub: null });
    expect(resolveSettingsView('/settings', '?section=billing')).toMatchObject({ section: null, hub: 'billing' });
    expect(resolveSettingsView('/settings', '?section=nope')).toMatchObject({ section: 'api-keys', hub: null });
    expect(resolveSettingsView('/settings/notification-preferences', '').group.id).toBe('personal');
  });
});

describe('SettingsPage', () => {
  it('keeps /settings as the API keys index inside Connections & Data', () => {
    renderAt('/settings');
    expect(screen.getByText('API KEYS SECTION')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Connections & Data' })).toBeInTheDocument();
    expect(document.querySelector('[data-settings-group="connections"]')).toHaveAttribute('aria-current', 'page');
    expect(document.querySelector('[data-settings-group="workspace"]')).not.toHaveAttribute('aria-current');
  });

  it('switches design tabs through the real section routes', async () => {
    renderAt('/settings/integrations');
    expect(screen.getByText('INTEGRATIONS SECTION')).toBeInTheDocument();
    const tabs = within(screen.getByRole('navigation', { name: 'Settings' }));
    await userEvent.click(tabs.getByRole('link', { name: 'Webhooks' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/settings/webhooks');
    expect(tabs.getByRole('link', { name: /Imports/ })).toHaveAttribute('href', '/imports');
  });

  it('opens a design group from the rail', async () => {
    renderAt('/settings');
    await userEvent.click(screen.getByRole('link', { name: 'Security & Governance' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/settings?section=security');
    expect(screen.getByTestId('settings-security')).toBeInTheDocument();
    expect(screen.getByText('Authentication').closest('div')?.parentElement).toHaveTextContent('Not available yet');
    await userEvent.click(document.querySelector('[data-settings-link="/audit-exports"]') as HTMLElement);
    expect(screen.getByTestId('location')).toHaveTextContent('/audit-exports');
  });

  it('shows the workspace from the organization profile, and an unavailable read as unavailable', () => {
    renderAt('/settings?section=workspace');
    expect(screen.getByText('Northpeak')).toBeInTheDocument();
    expect(screen.getByText('Europe/London')).toBeInTheDocument();

    s.org = failed();
    renderAt('/settings?section=workspace');
    expect(screen.getByText('Workspace details are unavailable right now.')).toBeInTheDocument();
  });

  it('renders loading, populated and failed member reads distinctly', async () => {
    let resolveMembers: (value: unknown) => void = () => {};
    s.members = () => new Promise(resolve => { resolveMembers = resolve; });
    const view = renderAt('/settings?section=members');
    expect(screen.getByText(/Loading members/)).toBeInTheDocument();
    resolveMembers({ data: [{ member_id: 'm1', tenant_id: 't1', user_id: 'u1', email: 'owner@example.test', display_name: 'Osaze', role: 'owner', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }], pagination: {}, meta: {} });
    expect(await screen.findByText('Osaze')).toBeInTheDocument();
    expect(screen.getByText('Members · 1')).toBeInTheDocument();
    expect(await screen.findByText('No pending invitations.')).toBeInTheDocument();
    view.unmount();

    queryCache.invalidatePrefix('settings:');
    s.members = () => Promise.reject(new Error('members offline'));
    renderAt('/settings?section=members');
    expect(await screen.findByText('Members are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByText('No members are recorded for this workspace.')).not.toBeInTheDocument();
  });

  it('shows plan and usage from real reads and links to the billing pages', async () => {
    renderAt('/settings?section=billing');
    expect(screen.getByText('Growth')).toBeInTheDocument();
    expect(screen.getByText('400 of 1,000')).toBeInTheDocument();
    expect(screen.getByText('OUTCOME LEDGER')).toBeInTheDocument();
    await userEvent.click(document.querySelector('[data-settings-link="/billing"]') as HTMLElement);
    expect(screen.getByTestId('location')).toHaveTextContent('/billing');
  });

  it('keeps billing reads honest while loading', () => {
    s.me = loading();
    s.usage = failed();
    renderAt('/settings?section=billing');
    expect(screen.getByText(/Loading plan details/)).toBeInTheDocument();
    expect(screen.getByText('Usage figures are unavailable right now.')).toBeInTheDocument();
  });

  it('switches the real theme from Personal and keeps notification tabs on their routes', async () => {
    renderAt('/settings?section=personal');
    expect(screen.getByText('owner@example.test')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('theme-dark'));
    expect(screen.getByTestId('theme-dark')).toHaveAttribute('aria-pressed', 'true');
    const tabs = within(screen.getByRole('navigation', { name: 'Settings' }));
    expect(tabs.getByRole('link', { name: 'Notifications' })).toHaveAttribute('href', '/settings/notification-preferences');
    expect(tabs.getByRole('link', { name: 'Channels' })).toHaveAttribute('href', '/settings/notifications');
  });
});
