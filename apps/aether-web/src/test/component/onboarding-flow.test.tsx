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

  it('issues one key per SDK and holds Continue until the key is stored', async () => {
    s.status = settled(activation({ intents: ['grow_revenue'], state: 'billing_pending', selected_plan_tier: 'alpha', sdk_selection: ['web'] }));
    renderFlow();
    await screen.findByTestId('onboarding-step-sdks');

    await userEvent.click(screen.getByTestId('generate-key-web'));
    expect(s.m.selectSdks.mutate).toHaveBeenCalledWith({ platforms: ['web'] });
    expect(s.m.createSdkKeys.mutate).toHaveBeenCalledWith({ count: 1, label: 'Web SDK · onboarding' });
    expect(await screen.findByTestId('raw-key-web')).toHaveTextContent('ak_secretvalue1234');

    const next = screen.getByTestId('onboarding-next');
    expect(next).toBeDisabled();
    await userEvent.click(screen.getByLabelText('I have stored this key securely'));
    expect(next).toBeEnabled();
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
