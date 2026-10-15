/**
 * KYBER provider-connections — route-state coverage for the manifest-driven
 * operator surface.
 *
 * Renders the real `ProviderConnectionsPage` and proves each data state the
 * route can be in, keyed off the real hooks (`useProviderCatalog` /
 * `useProviderOverview` / `useProviderRuntimeHealth`). Only the `@aether/ui`
 * query primitive and the frontend feature flag are mocked, so the page's own
 * state branching (loading → error → empty/populated → disabled) is what is
 * under test.
 *
 *   · loading — catalog in flight renders the status loader, never the empty
 *     or error copy;
 *   · empty — a manifest with zero providers renders "No providers in the
 *     catalog", NOT an error (an empty registry is a real, successful state);
 *   · error — a failed catalog fetch renders the ErrorState and never the
 *     catalog table;
 *   · populated — manifest entries render as rows (display name + identity),
 *     and no error/empty copy is shown;
 *   · gated — with `enableProviderRuntime` off, the page renders the honest
 *     disabled state rather than mounting a dead surface.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ThemeProvider, ToastProvider } from '@aether/ui';
import { ProviderConnectionsPage } from '@kyber/pages/provider-connections';

const state = vi.hoisted(() => ({
  catalog: 'empty' as 'loading' | 'empty' | 'error' | 'populated',
  flagEnabled: true,
}));

const VALID_ENTRY = {
  identity: 'payments.stripe.payouts',
  display_name: 'Stripe Payouts',
  category: 'payments',
  readiness: { level: 4, state: 'sandbox_validated' },
  availability: {
    environments: { local: true, integration: true, staging: false, production: false },
  },
  authentication: { type: 'oauth2' },
  capabilities: { auth: true, account: true, pull: true, webhook: false, report: false, stream: false, reconciliation: false },
  certification_state: 'certified',
} as const;

vi.mock('@aether/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@aether/ui')>();
  return {
    ...actual,
    useQuery: ({ key }: { key?: string }) => {
      // The page's three hooks query under these exact keys; everything else
      // (ThemeProvider/ToastProvider internals) gets a benign idle response.
      if (key === 'kyber-provider-connections:catalog') {
        if (state.catalog === 'loading') {
          return { data: null, isLoading: true, error: null, refetch: vi.fn() };
        }
        if (state.catalog === 'error') {
          return { data: null, isLoading: false, error: 'provider backend offline', refetch: vi.fn() };
        }
        if (state.catalog === 'empty') {
          return { data: { providers: [], issues: [] }, isLoading: false, error: null, refetch: vi.fn() };
        }
        return { data: { providers: [VALID_ENTRY], issues: [] }, isLoading: false, error: null, refetch: vi.fn() };
      }
      // Overview + health: benign idle so the cards simply don't render.
      return { data: null, isLoading: false, error: null, refetch: vi.fn() };
    },
  };
});

vi.mock('@kyber/lib/featureFlags', () => ({
  isFeatureEnabled: (flag: string) => (flag === 'enableProviderRuntime' ? state.flagEnabled : false),
}));

function renderPage() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <ProviderConnectionsPage />
      </ToastProvider>
    </ThemeProvider>,
  );
}

describe('ProviderConnectionsPage route states', () => {
  it('renders the loading state while the catalog is in flight', () => {
    state.catalog = 'loading';
    state.flagEnabled = true;
    renderPage();
    expect(screen.getByRole('status')).toBeTruthy();
    expect(screen.queryByText('No providers in the catalog')).toBeNull();
    expect(screen.queryByText('Unable to load the provider catalog')).toBeNull();
  });

  it('renders the successful-empty state when the registry returns zero providers', () => {
    state.catalog = 'empty';
    state.flagEnabled = true;
    renderPage();
    expect(screen.getByText('No providers in the catalog')).toBeTruthy();
    expect(screen.queryByText('Unable to load the provider catalog')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('renders the error state when the catalog fetch fails', () => {
    state.catalog = 'error';
    state.flagEnabled = true;
    renderPage();
    expect(screen.getByText('Unable to load the provider catalog')).toBeTruthy();
    expect(screen.getByText('provider backend offline')).toBeTruthy();
    expect(screen.queryByText('No providers in the catalog')).toBeNull();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('renders populated manifest entries as catalog rows', () => {
    state.catalog = 'populated';
    state.flagEnabled = true;
    renderPage();
    expect(screen.getByText('Stripe Payouts')).toBeTruthy();
    expect(screen.getByText('payments.stripe.payouts')).toBeTruthy();
    expect(screen.queryByText('Unable to load the provider catalog')).toBeNull();
    expect(screen.queryByText('No providers in the catalog')).toBeNull();
  });

  it('renders the honest disabled state when the runtime flag is off', () => {
    state.flagEnabled = false;
    renderPage();
    expect(screen.getByText('Provider Runtime UI is disabled')).toBeTruthy();
    expect(screen.queryByText('Provider catalog')).toBeNull();
  });
});
