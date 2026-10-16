import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { TenantLanding } from '@aether-app/app/tenant-landing';
import { ActivationPage } from '@aether-app/pages/activation/activation-page';

const state = vi.hoisted(() => ({
  onboarding: {} as Record<string, unknown>,
  status: {} as Record<string, unknown>,
  firstValue: {} as Record<string, unknown>,
  mutation: {} as Record<string, unknown>,
  createKeys: {} as Record<string, unknown>,
  sendEvent: {} as Record<string, unknown>,
}));

// TenantLanding derives its decision from the onboarding completion signal and
// renders HomePage on completion. Stub HomePage so this test asserts the routing
// decision, not the (separately tested) workspace panels.
vi.mock('@aether-app/pages/home/home-page', () => ({
  HomePage: () => <div>HOME WORKSPACE</div>,
}));

vi.mock('@aether-app/features/onboarding/use-onboarding', () => ({
  useOnboardingStatus: () => state.onboarding,
}));

// Fully replace the activation feature module: the page consumes only these
// hooks plus three pure helpers, so no real API client is loaded in this test.
vi.mock('@aether-app/features/activation/use-activation', () => ({
  ACTIVATION_PLAN_TIERS: ['P1', 'P2', 'P3', 'P4'],
  activationStateLabel: (s: string) => s,
  activationCapabilityState: () => 'provisioning',
  useActivationStatus: () => state.status,
  useFirstValue: () => state.firstValue,
  useSelectPlan: () => state.mutation,
  useSelectSdks: () => state.mutation,
  useCreateSdkKeys: () => state.createKeys,
  useSendTestEvent: () => state.sendEvent,
  useCompleteActivation: () => state.mutation,
}));

function ActivationRoute() {
  const location = useLocation();
  return <div>ACTIVATION ROUTE{location.search}</div>;
}

function renderLanding(initial = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/" element={<TenantLanding />} />
          <Route path="/activation" element={<ActivationRoute />} />
          <Route path="/home" element={<div>HOME ROUTE</div>} />
          <Route path="/explore" element={<div>EXPLORE WORKSPACE</div>} />
          <Route path="/settings" element={<div>SETTINGS ROUTE</div>} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

function renderActivation() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <ActivationPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

const settled = (data: unknown) => ({ data, isLoading: false, error: null, refetch: vi.fn() });

describe('Tenant landing routing', () => {
  beforeEach(() => {
    state.onboarding = settled(null);
    state.status = settled(null);
  });

  it('routes a tenant whose activation is incomplete to the workspace onboarding', () => {
    state.status = settled({ state: 'waiting_for_event' });
    state.onboarding = settled({ plan: { status: 'in_progress' } });
    renderLanding('/');
    expect(screen.getByText('ACTIVATION ROUTE')).toBeInTheDocument();
    expect(screen.queryByText('HOME ROUTE')).not.toBeInTheDocument();
  });

  it('routes a tenant with completed self-serve activation to Home', () => {
    state.status = settled({ state: 'complete' });
    renderLanding('/');
    expect(screen.getByText('HOME ROUTE')).toBeInTheDocument();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('EXPLORE WORKSPACE')).not.toBeInTheDocument();
  });

  it('routes an operator-onboarded tenant whose plan is live to Home', () => {
    state.status = settled({ state: 'account_verified' });
    state.onboarding = settled({ plan: { status: 'live' } });
    renderLanding('/');
    expect(screen.getByText('HOME ROUTE')).toBeInTheDocument();
  });

  it('waits for the operator-plan read before sending an incomplete tenant to onboarding', () => {
    state.status = settled({ state: 'waiting_for_event' });
    state.onboarding = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    const view = renderLanding('/');
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('HOME ROUTE')).not.toBeInTheDocument();
    view.unmount();

    // The plan read settles as live: the tenant is complete after all.
    state.onboarding = settled({ plan: { status: 'live' } });
    renderLanding('/');
    expect(screen.getByText('HOME ROUTE')).toBeInTheDocument();
  });

  it('sends a tester back through onboarding with ?onboarding=restart', () => {
    state.status = settled({ state: 'complete' });
    renderLanding('/?onboarding=restart');
    expect(screen.getByText('ACTIVATION ROUTE?onboarding=restart')).toBeInTheDocument();
    expect(screen.queryByText('HOME ROUTE')).not.toBeInTheDocument();
  });

  it('shows a loading state without misrouting while status resolves', () => {
    state.status = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderLanding('/');
    expect(document.querySelector('.animate-pulse, .aether-skeleton')).not.toBeNull();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('SETTINGS ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('HOME WORKSPACE')).not.toBeInTheDocument();
  });

  it('never routes to /settings on a status error', () => {
    state.status = { data: null, isLoading: false, error: 'activation offline', refetch: vi.fn() };
    state.onboarding = { data: null, isLoading: false, error: 'onboarding offline', refetch: vi.fn() };
    renderLanding('/');
    expect(screen.getByText('HOME WORKSPACE')).toBeInTheDocument();
    expect(screen.queryByText('SETTINGS ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
  });
});

// Classic activation flow data-truth states. ActivationPage is no longer routed
// on its own: /activation now serves the guided ActivatePage (route-state
// evidence in activate-page-route-state.test.tsx) and re-uses these proven
// plan/SDK/keys/test-event/first-value steps as its "Finish activation" tail.
// This block keeps that classic container honest (loading / error / empty /
// populated) since ActivatePage composes those steps.
describe('Classic activation flow data-truth states (ActivatePage finish tail)', () => {
  beforeEach(() => {
    state.status = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.firstValue = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.mutation = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
    state.createKeys = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
    state.sendEvent = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
  });

  it('renders loading without any activation step conclusions', () => {
    state.status = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderActivation();
    expect(document.querySelector('.animate-pulse, .aether-skeleton')).not.toBeNull();
    expect(screen.queryByText(/Choose your plan/)).not.toBeInTheDocument();
  });

  it('renders a status failure as unavailable, never as an empty flow', () => {
    state.status = { data: null, isLoading: false, error: 'activation service offline', refetch: vi.fn() };
    renderActivation();
    expect(screen.getByText('Failed to load activation status')).toBeInTheDocument();
    expect(screen.queryByText(/Choose your plan/)).not.toBeInTheDocument();
  });

  it('renders a successful not-started state as the empty entry point', () => {
    state.status = {
      data: {
        state: 'not_started',
        selected_plan_tier: null,
        sdk_selection: [],
        created_key_ids: [],
        billing_state: 'billing_pending',
        first_value_evidence: {},
        waiting_reason: null,
        history: [],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderActivation();
    expect(screen.getByText(/Choose your plan/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /complete activation/i })).toBeDisabled();
  });

  it('renders backend-populated first-value-ready state with completion enabled', () => {
    state.status = {
      data: {
        state: 'first_value_ready',
        selected_plan_tier: 'P2',
        sdk_selection: ['web'],
        created_key_ids: ['a1b2c3d4e5f6'],
        billing_state: 'billing_active',
        first_value_evidence: { events_observed: 3 },
        waiting_reason: null,
        history: [],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.firstValue = {
      data: { state: 'first_value_ready', ready: true, evidence: { events_observed: 3 } },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderActivation();
    expect(screen.getByRole('button', { name: /complete activation/i })).not.toBeDisabled();
    expect(screen.getByText('events_observed')).toBeInTheDocument();
  });
});
