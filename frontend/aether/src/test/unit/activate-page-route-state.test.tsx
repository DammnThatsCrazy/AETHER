import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { ActivatePage } from '@aether-app/pages/activation/activate-page';

// Route-state evidence for the WS-3 /activate row in the
// FRONTEND-ROUTE-STATE-MATRIX ledger (empty/error/populated automation).
// ActivatePage (activate-page.tsx) is the intent-driven guided activation
// wizard served at /activate. Its three data hooks gate the states asserted
// here: useActivationStatus (error -> "Failed to load activation status"),
// useActivationIntentsCatalog (empty -> "No activation intents available"),
// and useActivationPlan (drives the recommended connect plan section). The
// proven activation step components it re-uses (./activation-page) consume the
// same use-activation hooks, so the full hook surface is stubbed.
const state = vi.hoisted(() => ({
  status: {} as Record<string, unknown>,
  catalog: {} as Record<string, unknown>,
  plan: {} as Record<string, unknown>,
  mutation: {} as Record<string, unknown>,
  firstValue: {} as Record<string, unknown>,
  createKeys: {} as Record<string, unknown>,
  sendEvent: {} as Record<string, unknown>,
}));

const NOT_STARTED = {
  state: 'not_started',
  selected_plan_tier: null,
  sdk_selection: [],
  created_key_ids: [],
  billing_state: 'billing_pending',
  first_value_evidence: {},
  waiting_reason: null,
  history: [],
};

vi.mock('@aether-app/features/activation/use-activation', () => ({
  ACTIVATION_PLAN_TIERS: ['P1', 'P2', 'P3', 'P4'],
  activationStateLabel: (s: string) => s,
  activationCapabilityState: () => 'provisioning',
  useActivationStatus: () => state.status,
  useSelectPlan: () => state.mutation,
  useSelectSdks: () => state.mutation,
  useCreateSdkKeys: () => state.createKeys,
  useSendTestEvent: () => state.sendEvent,
  useFirstValue: () => state.firstValue,
  useCompleteActivation: () => state.mutation,
}));

vi.mock('@aether-app/features/activation/use-activation-intents', () => ({
  useActivationIntentsCatalog: () => state.catalog,
  useActivationPlan: () => state.plan,
  useActivationConnectAction: () => state.mutation,
  useSaveActivationIntents: () => state.mutation,
}));

function renderActivate() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <ActivatePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('/activate — ActivatePage route states', () => {
  beforeEach(() => {
    state.status = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.catalog = { data: { intents: [] }, isLoading: false, error: null, refetch: vi.fn() };
    state.plan = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.mutation = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
    state.firstValue = { data: null, isLoading: false, error: null, refetch: vi.fn() };
    state.createKeys = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
    state.sendEvent = { mutate: vi.fn(), isLoading: false, error: null, data: null, reset: vi.fn() };
  });

  it('renders the successful-empty state when the intent catalog is empty', async () => {
    state.status = { data: NOT_STARTED, isLoading: false, error: null, refetch: vi.fn() };
    state.catalog = { data: { intents: [] }, isLoading: false, error: null, refetch: vi.fn() };
    renderActivate();
    expect(await screen.findByText('No activation intents available')).toBeInTheDocument();
    expect(screen.queryByText('Failed to load activation status')).not.toBeInTheDocument();
  });

  it('renders the unavailable state and never a successful empty when the status read fails', async () => {
    state.status = { data: null, isLoading: false, error: 'activation service offline', refetch: vi.fn() };
    renderActivate();
    expect(await screen.findByText('Failed to load activation status')).toBeInTheDocument();
    expect(screen.queryByText('No activation intents available')).not.toBeInTheDocument();
  });

  it('renders the populated intent picker when intents are available', async () => {
    state.status = { data: NOT_STARTED, isLoading: false, error: null, refetch: vi.fn() };
    state.catalog = {
      data: {
        intents: [
          { token: 'grow_revenue', label: 'Grow revenue', description: 'Expand revenue streams' },
          { token: 'engage_customers', label: 'Engage customers', description: 'Deepen customer relationships' },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    state.plan = {
      data: { needs_selection: true, selected_intents: [], categories: [] },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    };
    renderActivate();
    expect(await screen.findByText('Grow revenue')).toBeInTheDocument();
    expect(screen.getByText('Engage customers')).toBeInTheDocument();
    expect(screen.queryByText('No activation intents available')).not.toBeInTheDocument();
  });
});
