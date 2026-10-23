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
  user: { id: 'u1', displayName: 'Owner', email: 'person@example.test' } as { id: string; displayName: string; email: string } | null,
  updateProfile: vi.fn(),
  putTimezone: vi.fn(),
  changeMemberRole: vi.fn(),
  removeMember: vi.fn(),
  invite: vi.fn(),
  revokeInvitation: vi.fn(),
  sessions: vi.fn(),
  revokeSession: vi.fn(),
  revokeOtherSessions: vi.fn(),
}));

vi.mock('@aether-app/pages/settings/api-keys-section', () => ({ ApiKeysSection: () => <div>API KEYS SECTION</div> }));
vi.mock('@aether-app/pages/settings/integrations-section', () => ({ IntegrationsSection: () => <div>INTEGRATIONS SECTION</div> }));
vi.mock('@aether-app/pages/settings/sdk-fleet-section', () => ({ SdkFleetSection: () => <div>SDK FLEET SECTION</div> }));
vi.mock('@aether-app/pages/settings/notifications-section', () => ({ NotificationsSection: () => <div>CHANNELS SECTION</div> }));
vi.mock('@aether-app/pages/settings/notification-preferences-section', () => ({ NotificationPreferencesSection: () => <div>PREFERENCES SECTION</div> }));
vi.mock('@aether-app/pages/settings/webhooks-section', () => ({ WebhooksSection: () => <div>WEBHOOKS SECTION</div> }));
vi.mock('@aether-app/pages/settings/data-exchange-section', () => ({ DataExchangeGate: () => <div>DATA EXCHANGE SECTION</div> }));
vi.mock('@aether-app/components/outcome-ledger-panel', () => ({ OutcomeLedgerPanel: () => <div>OUTCOME LEDGER</div> }));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: s.user }) }));
// Reads are stubbed; the real write hooks run against the mocked transport below.
vi.mock('@aether-app/features/onboarding/use-workspace-setup', async importOriginal => ({
  ...(await importOriginal<object>()),
  useOrganizationProfile: () => s.org,
  useTenantTemporalDefaults: () => s.temporal,
}));
vi.mock('@aether-app/features/account', async importOriginal => ({
  ...(await importOriginal<object>()),
  useMeProfile: () => s.me,
  useUsage: () => s.usage,
}));
vi.mock('@aether-app/lib/api/rest/client', () => ({
  restClient: { put: (...args: unknown[]) => s.putTimezone(...args), get: vi.fn() },
}));
vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    organization: {
      members: () => s.members!(),
      invitations: () => s.invitations!(),
      updateProfile: (body: unknown) => s.updateProfile(body),
      changeMemberRole: (id: string, role: string) => s.changeMemberRole(id, role),
      removeMember: (id: string) => s.removeMember(id),
      invite: (body: unknown) => s.invite(body),
      revokeInvitation: (id: string) => s.revokeInvitation(id),
    },
    me: {
      sessions: (params: unknown) => s.sessions(params),
      revokeSession: (id: string) => s.revokeSession(id),
      revokeOtherSessions: () => s.revokeOtherSessions(),
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

const member = (id: string, name: string, role: string) => ({
  member_id: id, tenant_id: 't1', user_id: `user-${id}`, email: `${name.toLowerCase()}@example.test`, display_name: name,
  role, status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
});
const invitation = (id: string, email: string) => ({
  invitation_id: id, tenant_id: 't1', email, role: 'member', status: 'pending', invited_by: 'u1',
  expires_at: '2026-11-01T00:00:00Z', revoked_at: null, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
});
const session = (id: string, status = 'active', device = 'Chrome on macOS') => ({
  id, tenant_id: 't1', status, credential_class: 'human_session', metadata: { device_name: device },
  last_seen_at: new Date().toISOString(), absolute_expires_at: '2026-11-01T00:00:00Z',
});

beforeEach(() => {
  queryCache.invalidatePrefix('settings:');
  queryCache.invalidatePrefix('me-sessions-');
  vi.spyOn(console, 'error').mockImplementation(() => {});
  s.user = { id: 'u1', displayName: 'Owner', email: 'person@example.test' };
  for (const fn of [s.updateProfile, s.putTimezone, s.changeMemberRole, s.removeMember, s.invite, s.revokeInvitation, s.sessions, s.revokeSession, s.revokeOtherSessions]) fn.mockReset();
  s.sessions.mockResolvedValue({ sessions: [], count: 0, total: 0, limit: 20, offset: 0 });
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
    const view = renderAt('/settings?section=workspace');
    expect(screen.getByTestId('workspace-name')).toHaveValue('Northpeak');
    expect(screen.getByTestId('tz-Europe/London')).toHaveAttribute('aria-pressed', 'true');
    view.unmount();

    s.org = failed();
    s.temporal = failed();
    renderAt('/settings?section=workspace');
    expect(screen.getByText('Workspace details are unavailable right now.')).toBeInTheDocument();
    expect(screen.getByText('Not stored for this workspace')).toBeInTheDocument();
    expect(screen.queryByTestId('workspace-save')).not.toBeInTheDocument();
  });

  it('renders loading, populated and failed member reads distinctly', async () => {
    let resolveMembers: (value: unknown) => void = () => {};
    s.members = () => new Promise(resolve => { resolveMembers = resolve; });
    const view = renderAt('/settings?section=members');
    expect(screen.getByText(/Loading members/)).toBeInTheDocument();
    resolveMembers({ data: [{ member_id: 'm1', tenant_id: 't1', user_id: 'u1', email: 'owner@example.test', display_name: 'Osaze', role: 'owner', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' }], pagination: {}, meta: {} });
    expect(await screen.findByText('Osaze')).toBeInTheDocument();
    expect(screen.getByText('Members · 1')).toBeInTheDocument();
    expect(screen.getByText('Owner', { selector: 'span' })).toBeInTheDocument();
    // The owner row has no role chips and no Remove.
    expect(document.querySelector('[data-testid="remove-m1"]')).toBeNull();
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
    // The outcome ledger moved to Value; Billing links there instead of embedding it.
    expect(screen.queryByText('OUTCOME LEDGER')).not.toBeInTheDocument();
    expect(document.querySelector('[data-settings-link="/value-review?tab=outcomes"]')).not.toBeNull();
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
    // A person-backed sign-in shows the person, not the tenant name.
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByText('Owner')).toBeInTheDocument();
    expect(screen.getByText('person@example.test')).toBeInTheDocument();
    expect(screen.queryByText('Osaze')).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId('theme-dark'));
    expect(screen.getByTestId('theme-dark')).toHaveAttribute('aria-pressed', 'true');
    const tabs = within(screen.getByRole('navigation', { name: 'Settings' }));
    expect(tabs.getByRole('link', { name: 'Notifications' })).toHaveAttribute('href', '/settings/notification-preferences');
    expect(tabs.getByRole('link', { name: 'Channels' })).toHaveAttribute('href', '/settings/notifications');
  });
});

describe('Settings writes', () => {
  it('labels a workspace-account sign-in honestly instead of calling the tenant name a person', () => {
    s.user = { id: 't1', displayName: 'Osaze', email: 'owner@example.test' };
    renderAt('/settings?section=personal');
    expect(screen.getByText('Signed in as')).toBeInTheDocument();
    expect(screen.getByText(/no personal name is reported/)).toBeInTheDocument();
    expect(screen.queryByText('Name')).not.toBeInTheDocument();
  });

  it('saves the workspace name and timezone through the existing endpoints', async () => {
    s.updateProfile.mockResolvedValue({ name: 'Northpeak Labs' });
    s.putTimezone.mockResolvedValue({ data: { business_time_zone: 'UTC' } });
    renderAt('/settings?section=workspace');
    // Slug, status and created are muted meta, not rows.
    expect(screen.getByText('Slug northpeak · active · created 2026-08-01')).toBeInTheDocument();
    const save = screen.getByTestId('workspace-save');
    expect(save).toBeDisabled();
    const name = screen.getByTestId('workspace-name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Northpeak Labs');
    await userEvent.click(screen.getByTestId('tz-UTC'));
    await userEvent.click(save);
    expect(s.updateProfile).toHaveBeenCalledWith({ name: 'Northpeak Labs' });
    expect(s.putTimezone).toHaveBeenCalledWith(
      '/v1/tenants/temporal-defaults',
      expect.anything(),
      expect.objectContaining({ business_time_zone: 'UTC', default_display_time_zone: 'UTC' }),
    );
    expect(await screen.findByText('Workspace settings saved.')).toBeInTheDocument();
  });

  it('shows a refused workspace save plainly and keeps the edit', async () => {
    s.updateProfile.mockRejectedValue(new Error("Organization role 'viewer' cannot perform this action"));
    renderAt('/settings?section=workspace');
    const name = screen.getByTestId('workspace-name');
    await userEvent.clear(name);
    await userEvent.type(name, 'Renamed');
    await userEvent.click(screen.getByTestId('workspace-save'));
    expect(await screen.findByText(/The workspace name was not saved\. Organization role 'viewer' cannot perform this action/)).toBeInTheDocument();
    expect(name).toHaveValue('Renamed');
    expect(s.putTimezone).not.toHaveBeenCalled();
  });

  it('changes a member role and shows a refused change plainly', async () => {
    s.members = () => Promise.resolve({ data: [member('m1', 'Osaze', 'owner'), member('m2', 'Lucia', 'member')], pagination: {}, meta: {} });
    s.changeMemberRole.mockResolvedValueOnce(member('m2', 'Lucia', 'admin'));
    renderAt('/settings?section=members');
    await userEvent.click(await screen.findByTestId('role-m2-admin'));
    expect(s.changeMemberRole).toHaveBeenCalledWith('m2', 'admin');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    s.changeMemberRole.mockRejectedValueOnce(new Error("Organization role 'member' cannot perform this action"));
    await userEvent.click(screen.getByTestId('role-m2-viewer'));
    expect(await screen.findByRole('alert')).toHaveTextContent("Could not change Lucia's role. Organization role 'member' cannot perform this action");
  });

  it('removes a member only after an inline confirmation, and reports a failure', async () => {
    s.members = () => Promise.resolve({ data: [member('m1', 'Osaze', 'owner'), member('m2', 'Lucia', 'member')], pagination: {}, meta: {} });
    const confirmSpy = vi.spyOn(window, 'confirm');
    s.removeMember.mockRejectedValueOnce(new Error('Authenticated principal is not an active organization member'));
    renderAt('/settings?section=members');
    await userEvent.click(await screen.findByTestId('remove-m2'));
    expect(s.removeMember).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('remove-m2-cancel'));
    expect(screen.queryByTestId('remove-m2-confirm')).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId('remove-m2'));
    await userEvent.click(screen.getByTestId('remove-m2-confirm'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not remove Lucia. Authenticated principal is not an active organization member');

    s.removeMember.mockResolvedValueOnce({ member_id: 'm2', removed: true });
    await userEvent.click(screen.getByTestId('remove-m2-confirm'));
    expect(s.removeMember).toHaveBeenLastCalledWith('m2');
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('opens Invitations from People and sends an invite with the chosen role', async () => {
    s.invite.mockResolvedValue({ ...invitation('v9', 'new@example.test'), token: 'tok_once' });
    renderAt('/settings?section=members');
    await userEvent.click(screen.getByTestId('members-invite'));
    expect(screen.getByTestId('location')).toHaveTextContent('/settings?section=invitations');
    expect(within(screen.getByRole('navigation', { name: 'Settings' })).getByRole('link', { name: 'Invitations' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('invite-send')).toBeDisabled();
    await userEvent.type(screen.getByTestId('invite-email'), 'new@example.test');
    await userEvent.click(screen.getByTestId('invite-role-viewer'));
    await userEvent.click(screen.getByTestId('invite-send'));
    expect(s.invite).toHaveBeenCalledWith({ email: 'new@example.test', role: 'viewer' });
    expect(await screen.findByTestId('invite-created')).toHaveTextContent('tok_once');
    expect(screen.getByTestId('invite-email')).toHaveValue('');
  });

  it('reports a refused invite plainly', async () => {
    s.invite.mockRejectedValue(new Error('An active invitation already exists for this email'));
    renderAt('/settings?section=invitations');
    await userEvent.type(screen.getByTestId('invite-email'), 'dup@example.test');
    await userEvent.click(screen.getByTestId('invite-send'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not invite dup@example.test. An active invitation already exists for this email');
    expect(screen.queryByTestId('invite-created')).not.toBeInTheDocument();
  });

  it('revokes a pending invitation after confirming, and reports a failure', async () => {
    s.invitations = () => Promise.resolve([invitation('v1', 'priya@example.test')]);
    s.revokeInvitation.mockRejectedValueOnce(new Error('Only a pending invitation can be revoked'));
    renderAt('/settings?section=invitations');
    expect(await screen.findByText('Pending invitations · 1')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('revoke-v1'));
    await userEvent.click(screen.getByTestId('revoke-v1-confirm'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not revoke the invitation for priya@example.test. Only a pending invitation can be revoked');

    s.revokeInvitation.mockResolvedValueOnce({ ...invitation('v1', 'priya@example.test'), status: 'revoked' });
    s.invitations = () => Promise.resolve([]);
    await userEvent.click(screen.getByTestId('revoke-v1-confirm'));
    expect(s.revokeInvitation).toHaveBeenLastCalledWith('v1');
    expect(await screen.findByText('No pending invitations.')).toBeInTheDocument();
  });

  it('lists sessions on Personal → Sessions and signs one out after confirming', async () => {
    s.sessions.mockResolvedValue({ sessions: [session('s1'), session('s2', 'active', 'Firefox on Linux'), session('s3', 'revoked')], count: 3, total: 3, limit: 20, offset: 0 });
    s.revokeSession.mockResolvedValue({ revoked: true, id: 's2' });
    renderAt('/settings?section=sessions');
    expect(within(screen.getByRole('navigation', { name: 'Settings' })).getByRole('link', { name: 'Sessions' })).toHaveAttribute('aria-current', 'page');
    expect(await screen.findByText('Firefox on Linux')).toBeInTheDocument();
    expect(screen.getByText('Sessions · 3')).toBeInTheDocument();
    // Revoked sessions cannot be signed out again.
    expect(document.querySelector('[data-testid="session-revoke-s3"]')).toBeNull();
    await userEvent.click(screen.getByTestId('session-revoke-s2'));
    expect(s.revokeSession).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('session-revoke-s2-confirm'));
    expect(s.revokeSession).toHaveBeenCalledWith('s2');
    expect(await screen.findByText('Signed out Firefox on Linux.')).toBeInTheDocument();
  });

  it('reports a failed session sign-out plainly', async () => {
    s.sessions.mockResolvedValue({ sessions: [session('s1')], count: 1, total: 1, limit: 20, offset: 0 });
    s.revokeSession.mockRejectedValue(new Error('Session s1 not found'));
    renderAt('/settings?section=sessions');
    await userEvent.click(await screen.findByTestId('session-revoke-s1'));
    await userEvent.click(screen.getByTestId('session-revoke-s1-confirm'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign out that session. Session s1 not found');
  });

  it('signs out everywhere else, and reports when the server refuses', async () => {
    s.sessions.mockResolvedValue({ sessions: [session('s1'), session('s2')], count: 2, total: 2, limit: 20, offset: 0 });
    s.revokeOtherSessions.mockRejectedValueOnce(new Error('A human session credential is required'));
    renderAt('/settings?section=sessions');
    await userEvent.click(await screen.findByTestId('sessions-revoke-others'));
    await userEvent.click(screen.getByTestId('sessions-revoke-others-confirm'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not sign out the other sessions. A human session credential is required');

    s.revokeOtherSessions.mockResolvedValueOnce({ revoked_count: 1 });
    await userEvent.click(screen.getByTestId('sessions-revoke-others-confirm'));
    expect(await screen.findByText('Signed out 1 other session.')).toBeInTheDocument();
  });

  it('shows the API limits under API keys from the usage read', () => {
    renderAt('/settings');
    const limits = screen.getByTestId('settings-api-limits').parentElement!;
    expect(within(limits).getByText('http://localhost:8000/v1')).toBeInTheDocument();
    expect(within(limits).getByText('12 of 600 per minute')).toBeInTheDocument();
    expect(within(limits).getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2');
  });

  it('keeps the API rate limit honest when usage is unavailable or unmeasured', () => {
    s.usage = failed();
    const view = renderAt('/settings');
    expect(screen.getByText('Rate limit figures are unavailable right now.')).toBeInTheDocument();
    view.unmount();
    s.usage = settled({ period_start: '2026-10-01T00:00:00Z', period_end: '2026-10-31T00:00:00Z', events_used: null, events_quota: 1000, rpm_peak: null, rpm_limit: 600, overage_events: 0, days_remaining: 15 });
    renderAt('/settings');
    expect(screen.getByText('600 per minute · peak not measured yet')).toBeInTheDocument();
  });
});
