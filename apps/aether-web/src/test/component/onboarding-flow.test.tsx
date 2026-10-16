import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { OnboardingFlow } from '@aether-app/pages/onboarding/onboarding-flow';

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });
const mutation = (result: unknown = {}) => {
  const fn = vi.fn().mockResolvedValue(result);
  return { mutate: fn, isLoading: false, error: null, data: null, reset: vi.fn() };
};

const s = vi.hoisted(() => ({
  status: null as unknown,
  intents: null as unknown,
  plan: null as unknown,
  org: null as unknown,
  temporal: null as unknown,
  integrations: null as unknown,
  readiness: null as unknown,
  firstValue: null as unknown,
  keys: null as unknown,
  sites: null as unknown,
  createSite: vi.fn(),
  createSiteKey: vi.fn(),
  m: {} as Record<string, ReturnType<typeof Object>>,
}));

vi.mock('@aether-app/features/activation/use-activation', () => ({
  useActivationStatus: () => s.status,
  useFirstValue: () => s.firstValue,
  useCompleteActivation: () => s.m.complete,
  useSendTestEvent: () => s.m.sendTest,
  useSelectPlan: () => s.m.selectPlan,
  useSelectSdks: () => s.m.selectSdks,
  useCreateSdkKeys: () => s.m.createSdkKeys,
  ACTIVATION_PLAN_TIERS: ['alpha', 'beta'],
}));
vi.mock('@aether-app/features/activation/use-activation-intents', () => ({
  useActivationIntentsCatalog: () => s.intents,
  useActivationPlan: () => s.plan,
  useSaveActivationIntents: () => s.m.saveIntents,
  useActivationConnectAction: () => s.m.connect,
}));
vi.mock('@aether-app/features/activation/use-tenant-readiness', () => ({ useTenantReadiness: () => s.readiness }));
vi.mock('@aether-app/features/integrations', () => ({ useTenantIntegrations: () => s.integrations }));
vi.mock('@aether-app/features/onboarding/use-workspace-setup', () => ({
  useOrganizationProfile: () => s.org,
  useUpdateOrganizationProfile: () => s.m.updateOrg,
  useTenantTemporalDefaults: () => s.temporal,
  useSaveTenantTimezone: () => s.m.saveTz,
  useTenantProfile: () => settled({ plan: { plan_id: 'alpha' } }),
  useTenantApiKeys: () => s.keys,
  useCreateTenantApiKey: () => s.m.createTenantKey,
  useAnalyticsSummary: () => settled({ total_events: 0, unique_users: 0, total_sessions: 0 }),
  invalidateTenantApiKeys: vi.fn(),
  useSdkSites: () => s.sites,
  useSiteLive: () => settled({ live: false, state: 'awaiting_first_signal' }),
  createSdkSite: (...args: unknown[]) => s.createSite(...args),
  createSitePublishableKey: (...args: unknown[]) => s.createSiteKey(...args),
  SDK_KEY_PERMISSIONS: ['read', 'write', 'ingest', 'analytics'],
}));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: { displayName: 'Owner', email: 'o@example.test' } }) }));
vi.mock('@aether-app/lib/env', () => ({ getEnvironment: () => 'staging' }));

function activation(patch: Record<string, unknown> = {}) {
  return {
    state: 'account_verified',
    selected_plan_tier: null,
    sdk_selection: [],
    created_key_ids: [],
    billing_state: 'billing_pending',
    first_value_evidence: {},
    waiting_reason: null,
    intents: [],
    history: [],
    ...patch,
  };
}

function renderFlow(path = '/activation') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/activation" element={<OnboardingFlow />} />
        <Route path="/home" element={<div>HOME</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.innerWidth = 1280;
  s.status = settled(activation());
  s.intents = settled({
    intents: [
      { token: 'grow_revenue', label: 'Grow revenue', description: 'd', recommended_categories: ['commerce'] },
      { token: 'run_advertising', label: 'Run ad campaigns', description: 'd', recommended_categories: ['advertising_campaigns'] },
    ],
    experience_categories: [],
  });
  s.plan = settled({
    tenant_id: 't',
    needs_selection: false,
    selected_intents: ['grow_revenue'],
    categories: [
      {
        experience_category: 'commerce',
        display_name: 'Commerce',
        recommended_by_intents: ['grow_revenue'],
        connected_count: 0,
        integration_count: 1,
        integrations: [
          {
            key: 'shopify', family: 'shopify', product: 'ingestion', display_name: 'Shopify', experience_category: 'commerce',
            connectable: true, connect_unavailable_reason: null, credential_required: true, authentication: 'api_key',
            accounts_discovery: false, accounts_selection_required: false, sync_initial_backfill: true,
            manifest_readiness: { state: 'x', level: 1 }, connection_state: 'available', next_action: 'create_tenant_integration',
            can_act: true, record: null,
          },
        ],
      },
    ],
  });
  s.org = settled({ name: 'Northpeak' });
  s.temporal = settled({ business_time_zone: 'UTC' });
  s.integrations = settled({ items: [] });
  s.readiness = settled({ tenant_id: 't', ready: false, blocking: [], checks: [{ name: 'events_received', status: 'pending' }] });
  s.firstValue = settled({ state: 'waiting_for_event', ready: false, evidence: {} });
  s.keys = settled({ api_keys: [] });
  s.sites = settled([]);
  s.createSite = vi.fn().mockResolvedValue({ id: 'site_abc', name: 'Web SDK · onboarding', status: 'active' });
  s.createSiteKey = vi.fn().mockResolvedValue({ id: 'pk1', key: 'pk_publishable123', siteId: 'site_abc', snippet: '<script data-key="pk_publishable123" data-site="site_abc"></script>' });
  window.localStorage.clear();
  s.m = {
    complete: mutation({ state: 'complete' }),
    sendTest: mutation({ results: [{ status: 'accepted' }], state: 'event_received' }),
    selectPlan: mutation({ state: 'billing_pending' }),
    selectSdks: mutation({ state: 'sdk_selected' }),
    createSdkKeys: mutation({ keys: [{ id: 'k1', key: 'ak_secretvalue1234', label: 'Web SDK · onboarding' }], state: 'waiting_for_event' }),
    saveIntents: mutation({ intents: ['grow_revenue'] }),
    connect: mutation({ family: 'shopify', action: 'create_tenant_integration', ok: true, connection_state: 'credential_waiting', next_action: 'configure_credential', can_act: true }),
    updateOrg: mutation({ name: 'Northpeak Outdoor' }),
    saveTz: mutation({}),
    createTenantKey: mutation({ id: 'k2', key: 'ak_other', api_key: 'ak_other' }),
  };
});

describe('Workspace onboarding flow', () => {
  it('saves the workspace and goals, then moves to Sources', async () => {
    renderFlow();
    expect(await screen.findByTestId('onboarding-step-workspace')).toBeInTheDocument();
    const next = screen.getByTestId('onboarding-next');
    expect(next).toBeDisabled(); // no goal yet

    await userEvent.clear(screen.getByLabelText('Workspace name'));
    await userEvent.type(screen.getByLabelText('Workspace name'), 'Northpeak Outdoor');
    expect(screen.getAllByText('workspace:northpeak-outdoor').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole('button', { name: /Grow revenue/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Europe/London' }));
    await userEvent.click(next);

    await screen.findByTestId('onboarding-step-sources');
    expect(s.m.updateOrg.mutate).toHaveBeenCalledWith({ name: 'Northpeak Outdoor' });
    expect(s.m.saveIntents.mutate).toHaveBeenCalledWith(['grow_revenue']);
    expect(s.m.saveTz.mutate).toHaveBeenCalledWith({ timezone: 'Europe/London', current: { business_time_zone: 'UTC' } });
  });

  it('saves an edited workspace name even when the profile read failed', async () => {
    s.org = { data: null, isLoading: false, error: 'not found', refetch: vi.fn() };
    renderFlow();
    await screen.findByTestId('onboarding-step-workspace');
    await userEvent.clear(screen.getByLabelText('Workspace name'));
    await userEvent.type(screen.getByLabelText('Workspace name'), 'Ridgeline');
    await userEvent.click(screen.getByRole('button', { name: /Grow revenue/ }));
    await userEvent.click(screen.getByTestId('onboarding-next'));
    await screen.findByTestId('onboarding-step-sources');
    expect(s.m.updateOrg.mutate).toHaveBeenCalledWith({ name: 'Ridgeline' });
  });

  it('lets every SDK be skipped: nothing is preselected and Continue works with none', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'billing_pending', selected_plan_tier: 'alpha', sdk_selection: [] }));
    renderFlow();
    // No SDKs recorded: the flow resumes at Sources, which is itself skippable.
    await screen.findByTestId('onboarding-step-sources');
    await userEvent.click(screen.getByTestId('onboarding-next'));
    await screen.findByTestId('onboarding-step-sdks');
    for (const id of ['web', 'react', 'react-native', 'ios', 'android', 'server']) {
      expect(document.querySelector(`[data-sdk="${id}"]`)).toHaveAttribute('aria-pressed', 'false');
    }
    expect(screen.getByTestId('onboarding-next')).toBeEnabled();
    expect(screen.getByTestId('onboarding-hint')).toHaveTextContent('Optional');
    await userEvent.click(screen.getByTestId('onboarding-next'));
    expect(await screen.findByTestId('onboarding-step-graph')).toBeInTheDocument();
  });

  it('selects every SDK at once, and clears them again', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'billing_pending', selected_plan_tier: 'alpha', sdk_selection: [] }));
    renderFlow();
    // No SDKs recorded: the flow resumes at Sources, which is itself skippable.
    await screen.findByTestId('onboarding-step-sources');
    await userEvent.click(screen.getByTestId('onboarding-next'));
    await screen.findByTestId('onboarding-step-sdks');
    await userEvent.click(screen.getByRole('button', { name: 'Select all' }));
    for (const id of ['web', 'react', 'react-native', 'ios', 'android', 'server']) {
      expect(document.querySelector(`[data-sdk="${id}"]`)).toHaveAttribute('aria-pressed', 'true');
    }
    expect(screen.getByTestId('onboarding-next')).toBeDisabled(); // keys still to issue
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(screen.getByTestId('onboarding-next')).toBeEnabled();
  });

  it('connects a recommended source through the connect-action state machine', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'] }));
    renderFlow();
    await screen.findByTestId('onboarding-step-sources');
    const row = document.querySelector('[data-provider-family="shopify"]') as HTMLElement;
    await userEvent.click(within(row).getByRole('button', { name: 'Connect' }));

    const dialog = await screen.findByTestId('connect-popover');
    await userEvent.click(within(dialog).getByTestId('connect-popover-act'));
    expect(s.m.connect.mutate).toHaveBeenCalledWith({ family: 'shopify', action: 'create_tenant_integration' });

    // The server asked for a credential next: the pop-over collects it.
    const field = await within(dialog).findByPlaceholderText('Paste read-only key');
    await userEvent.type(field, 'shpat_readonly_123');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Verify and connect' }));
    await waitFor(() =>
      expect(s.m.connect.mutate).toHaveBeenCalledWith({ family: 'shopify', action: 'configure_credential', credential: 'shpat_readonly_123' }),
    );
  });

  it('issues a site-bound publishable key for the Web SDK, never a secret', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'billing_pending', selected_plan_tier: 'alpha', sdk_selection: ['web'] }));
    renderFlow();
    await screen.findByTestId('onboarding-step-sdks');

    expect(screen.getByTestId('generate-key-web')).toBeDisabled(); // needs the site address first
    await userEvent.type(screen.getByTestId('site-origin-web'), 'https://www.example.com');
    await userEvent.click(screen.getByTestId('generate-key-web'));

    expect(s.m.selectSdks.mutate).toHaveBeenCalledWith({ platforms: ['web'] });
    expect(s.createSite).toHaveBeenCalledWith({ name: 'Web SDK · onboarding', origins: ['https://www.example.com'] });
    expect(s.createSiteKey).toHaveBeenCalledWith('site_abc', 'Web SDK · onboarding');
    expect(s.m.createSdkKeys.mutate).not.toHaveBeenCalled();
    expect(await screen.findByTestId('raw-key-web')).toHaveTextContent('pk_publishable123');
    expect(screen.getByText(/data-site="site_abc"/)).toBeInTheDocument();

    const next = screen.getByTestId('onboarding-next');
    expect(next).toBeDisabled();
    await userEvent.click(screen.getByLabelText('I have stored this key securely'));
    expect(next).toBeEnabled();
  });

  it('issues a secret ingestion key for the Server SDK through activation', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'billing_pending', selected_plan_tier: 'alpha', sdk_selection: ['server'] }));
    renderFlow();
    await screen.findByTestId('onboarding-step-sdks');
    await userEvent.click(screen.getByTestId('generate-key-server'));
    expect(s.m.selectSdks.mutate).toHaveBeenCalledWith({ platforms: ['server'] });
    expect(s.m.createSdkKeys.mutate).toHaveBeenCalledWith({ count: 1, label: 'Server SDK · onboarding' });
    expect(s.createSiteKey).not.toHaveBeenCalled();
  });

  it('issues post-activation server keys with ingest permissions and the node platform tag', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'event_received', sdk_selection: ['server'], created_key_ids: ['k0'] }));
    renderFlow();
    await screen.findByTestId('onboarding-step-graph');
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    await userEvent.click(await screen.findByTestId('generate-key-server'));
    expect(s.m.createTenantKey.mutate).toHaveBeenCalledWith({ name: 'Server SDK · onboarding', platform: 'node' });
  });

  it('does not count a key on record as stored until the visitor confirms it, and remembers the confirmation', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'waiting_for_event', sdk_selection: ['server'], created_key_ids: ['k9'] }));
    s.keys = settled({ api_keys: [{ id: 'k9', name: 'Server SDK · onboarding', platform: null }] });
    const view = renderFlow();
    await screen.findByTestId('onboarding-step-graph');
    await userEvent.click(screen.getByRole('button', { name: 'Back' }));
    await screen.findByTestId('onboarding-step-sdks');
    expect(screen.getByTestId('onboarding-next')).toBeDisabled();
    await userEvent.click(screen.getByLabelText('I stored this key when it was issued'));
    expect(screen.getByTestId('onboarding-next')).toBeEnabled();
    expect(window.localStorage.getItem('aether:onboarding-key-ack:k9')).toBe('1');
    view.unmount();
  });

  it('opens Home only once first value is proven, completing activation first', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'waiting_for_event', created_key_ids: ['k1'] }));
    const view = renderFlow();
    await screen.findByTestId('onboarding-step-graph');
    expect(screen.getByTestId('onboarding-next')).toBeDisabled();
    expect(document.querySelector('[data-stage="events_received"]')).toHaveAttribute('data-stage-status', 'running');

    s.status = settled(activation({ intents: ['grow_revenue'], state: 'first_value_ready', created_key_ids: ['k1'] }));
    view.rerender(
      <MemoryRouter initialEntries={['/activation']}>
        <Routes>
          <Route path="/activation" element={<OnboardingFlow />} />
          <Route path="/home" element={<div>HOME</div>} />
        </Routes>
      </MemoryRouter>,
    );
    const next = await screen.findByTestId('onboarding-next');
    await waitFor(() => expect(next).toBeEnabled());
    await userEvent.click(next);
    expect(s.m.complete.mutate).toHaveBeenCalled();
    expect(await screen.findByText('HOME')).toBeInTheDocument();
  });

  it('restarts at Workspace for a tester even when activation is complete', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'complete', created_key_ids: ['k1'] }));
    renderFlow('/activation?onboarding=restart');
    expect(await screen.findByTestId('onboarding-step-workspace')).toBeInTheDocument();
    expect(screen.getByText('tester walk-through')).toBeInTheDocument();
  });
});
