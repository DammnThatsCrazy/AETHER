import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { HomePage } from '@aether-app/pages/home/home-page';
import type { ModelRegistryModel } from '@aether-app/features/model-selection/types';

const mocks = vi.hoisted(() => ({
  getModels: vi.fn(),
  setTenantDefault: vi.fn(),
  logout: vi.fn(),
}));

// The workspace home already hosts outcome/decision panels; stub them so this
// suite asserts the model-routing surface, not those separately-covered panels.
vi.mock('@aether-app/components/outcome-ledger-panel', () => ({
  OutcomeLedgerPanel: () => <div>OUTCOME LEDGER</div>,
}));

vi.mock('@aether-app/components/decision-intelligence-panel', () => ({
  DecisionIntelligencePanel: () => <div>DECISION INTELLIGENCE</div>,
}));

// Authenticated tenant context — the panel's `tenantId` label derives from this.
vi.mock('@aether-app/features/auth', () => ({
  useAuth: () => ({
    user: { id: 'tenant-t1', email: 'owner@example.test', displayName: 'Tenant Owner' },
    logout: mocks.logout,
  }),
}));

// Deterministic typed client (C13-F) so the real panel exercises the
// model-list/default contract without hitting the network in jsdom.
vi.mock('@aether-app/features/model-selection/types', () => ({
  defaultModelSelectionApi: {
    getModels: mocks.getModels,
    setTenantDefault: mocks.setTenantDefault,
  },
}));

const MODELS: ModelRegistryModel[] = [
  {
    modelId: 'claude-sonnet-5',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['chat', 'tool_use'],
    inputCostPerMTok: 3,
    outputCostPerMTok: 15,
  },
  {
    modelId: 'gpt-4o-mini',
    provider: 'openai',
    status: 'beta',
    capabilities: ['chat', 'vision'],
    inputCostPerMTok: 0.15,
    outputCostPerMTok: 0.6,
  },
];

function renderHome() {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('HomePage model-routing surface (ADR-008 D9 / enableModelHarness)', () => {
  beforeEach(() => {
    vi.unstubAllEnvs();
    mocks.getModels.mockReset();
    mocks.setTenantDefault.mockReset();
    mocks.logout.mockReset();
    mocks.getModels.mockResolvedValue({
      models: MODELS,
      tenantDefaultModel: 'claude-sonnet-5',
    });
    mocks.setTenantDefault.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders nothing and fires no model-runtime request when the flag is OFF', () => {
    renderHome();
    expect(screen.queryByText('Model routing preference')).not.toBeInTheDocument();
    expect(mocks.getModels).not.toHaveBeenCalled();
    expect(mocks.setTenantDefault).not.toHaveBeenCalled();
  }, 15_000);

  describe('flag ON', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_FEATURE_FLAGS', JSON.stringify({ enableModelHarness: true }));
    });

    it('mounts the panel and triggers the model-list API on the tenant home', async () => {
      renderHome();

      // The tenant-facing surface is present and populated from the model
      // registry — the flag now has a real user-visible effect.
      expect(await screen.findByText('Model routing preference')).toBeInTheDocument();
      expect(await screen.findByText('claude-sonnet-5')).toBeInTheDocument();
      expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument();
      expect(mocks.getModels).toHaveBeenCalledTimes(1);
    }, 15_000);

    it('labels the surface with the authenticated tenant id', async () => {
      renderHome();
      expect(await screen.findByLabelText('Model routing preference for tenant-t1')).toBeInTheDocument();
    }, 15_000);

    it('lets the tenant change their default from the home page', async () => {
      const user = userEvent.setup();
      renderHome();

      const gptRow = (await screen.findByText('gpt-4o-mini')).closest('li') as HTMLElement;
      await user.click(within(gptRow).getByRole('button', { name: 'Set as default' }));

      await waitFor(() => {
        expect(mocks.setTenantDefault).toHaveBeenCalledTimes(1);
        expect(mocks.setTenantDefault).toHaveBeenCalledWith('gpt-4o-mini');
      });
      expect(within(gptRow).getByText('Default')).toBeInTheDocument();
    }, 15_000);
  });
});
