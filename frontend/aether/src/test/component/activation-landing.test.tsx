import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
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

function renderLanding(initial = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[initial]}>
        <Routes>
          <Route path="/" element={<TenantLanding />} />
          <Route path="/activation" element={<div>ACTIVATION ROUTE</div>} />
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

describe('Tenant landing routing', () => {
  beforeEach(() => {
    state.onboarding = { data: null, isLoading: false, error: null, refetch: vi.fn() };
  });

  it('routes an incomplete tenant to /activation', () => {
    state.onboarding = {
      data: { plan: { status: 'in_progress' } },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderLanding('/');
    expect(screen.getByText('ACTIVATION ROUTE')).toBeInTheDocument();
    expect(screen.queryByText('HOME WORKSPACE')).not.toBeInTheDocument();
  });

  it('renders the workspace home for a completed tenant', () => {
    state.onboarding = {
      data: { plan: { status: 'live' } },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderLanding('/');
    expect(screen.getByText('HOME WORKSPACE')).toBeInTheDocument();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
  });

  it('shows a loading state without misrouting while status resolves', () => {
    state.onboarding = { data: null, isLoading: true, error: null, refetch: vi.fn() };
    renderLanding('/');
    expect(document.querySelector('.animate-pulse')).not.toBeNull();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('SETTINGS ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('HOME WORKSPACE')).not.toBeInTheDocument();
  });

  it('never routes to /settings on a status error', () => {
    state.onboarding = { data: null, isLoading: false, error: 'onboarding offline', refetch: vi.fn() };
    renderLanding('/');
    expect(screen.getByText('HOME WORKSPACE')).toBeInTheDocument();
    expect(screen.queryByText('SETTINGS ROUTE')).not.toBeInTheDocument();
    expect(screen.queryByText('ACTIVATION ROUTE')).not.toBeInTheDocument();
  });
});

describe('Activation route data-truth states', () => {
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
    expect(document.querySelector('.animate-pulse')).not.toBeNull();
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
