import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeProvider } from '@aether/ui';
import { ModelSelectionPanel } from '@aether-app/features/model-selection/ModelSelectionPanel';
import type { TenantModelSelectionApi } from '@aether-app/features/model-selection/types';

const models = [
  {
    modelId: 'claude-sonnet-5',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['chat', 'tool_use', 'thinking'],
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

function renderPanel(api: { getModels: ReturnType<typeof vi.fn>; setTenantDefault: ReturnType<typeof vi.fn> }) {
  return render(
    <ThemeProvider>
      <ModelSelectionPanel api={api as TenantModelSelectionApi} />
    </ThemeProvider>,
  );
}

describe('ModelSelectionPanel (enableModelHarness)', () => {
  let stubApi: { getModels: ReturnType<typeof vi.fn>; setTenantDefault: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    vi.unstubAllEnvs();
    stubApi = { getModels: vi.fn(), setTenantDefault: vi.fn() };
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('renders nothing and fires no requests when the flag is OFF', () => {
    const { container } = renderPanel(stubApi);
    expect(container).toBeEmptyDOMElement();
    expect(stubApi.getModels).not.toHaveBeenCalled();
  }, 15_000);

  describe('flag ON', () => {
    beforeEach(() => {
      vi.stubEnv('VITE_FEATURE_FLAGS', JSON.stringify({ enableModelHarness: true }));
    });

    it('renders models with provider chips, status badges, capability tags and display-only cost', async () => {
      stubApi.getModels.mockResolvedValue({ models, tenantDefaultModel: 'claude-sonnet-5' });
      renderPanel(stubApi);

      expect(await screen.findByText('claude-sonnet-5')).toBeInTheDocument();
      expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument();
      expect(screen.getByText('anthropic')).toBeInTheDocument();
      expect(screen.getByText('openai')).toBeInTheDocument();
      expect(screen.getByText('recommended')).toBeInTheDocument();
      expect(screen.getByText('beta')).toBeInTheDocument();
      expect(screen.getByText('tool_use')).toBeInTheDocument();
      expect(screen.getByText('thinking')).toBeInTheDocument();
      expect(screen.getByText('vision')).toBeInTheDocument();
      expect(screen.getAllByText(/in · .*out \/ 1M tokens/)).toHaveLength(models.length);
      expect(stubApi.getModels).toHaveBeenCalledTimes(1);
    }, 15_000);

    it('highlights the current tenant default', async () => {
      stubApi.getModels.mockResolvedValue({ models, tenantDefaultModel: 'claude-sonnet-5' });
      renderPanel(stubApi);

      const defaultRow = (await screen.findByText('claude-sonnet-5')).closest('li');
      expect(defaultRow).not.toBeNull();
      expect(defaultRow).toHaveAttribute('aria-current', 'true');
      expect(within(defaultRow as HTMLElement).getByText('Default')).toBeInTheDocument();
      expect(screen.getAllByText('Default')).toHaveLength(1);
      expect(screen.getAllByRole('button', { name: 'Set as default' })).toHaveLength(models.length);
    }, 15_000);

    it('calls setTenantDefault with the clicked modelId', async () => {
      const user = userEvent.setup();
      stubApi.getModels.mockResolvedValue({ models, tenantDefaultModel: 'claude-sonnet-5' });
      stubApi.setTenantDefault.mockResolvedValue(undefined);
      renderPanel(stubApi);

      const gptRow = (await screen.findByText('gpt-4o-mini')).closest('li') as HTMLElement;
      await user.click(within(gptRow).getByRole('button', { name: 'Set as default' }));

      await waitFor(() => {
        expect(stubApi.setTenantDefault).toHaveBeenCalledTimes(1);
        expect(stubApi.setTenantDefault).toHaveBeenCalledWith('gpt-4o-mini');
      });
      expect(within(gptRow).getByText('Default')).toBeInTheDocument();
    }, 15_000);

    it('shows a loading skeleton while the fetch is pending', () => {
      stubApi.getModels.mockReturnValue(new Promise(() => {}));
      renderPanel(stubApi);

      expect(screen.getByLabelText('Loading models')).toBeInTheDocument();
      expect(screen.queryByText('claude-sonnet-5')).not.toBeInTheDocument();
    }, 15_000);

    it('shows an inline error state on fetch failure and retries', async () => {
      const user = userEvent.setup();
      stubApi.getModels.mockRejectedValueOnce(new Error('offline'));
      renderPanel(stubApi);

      expect(await screen.findByText('Unable to load models')).toBeInTheDocument();

      stubApi.getModels.mockResolvedValueOnce({ models, tenantDefaultModel: null });
      await user.click(screen.getByRole('button', { name: 'Retry' }));

      expect(await screen.findByText('claude-sonnet-5')).toBeInTheDocument();
      expect(stubApi.getModels).toHaveBeenCalledTimes(2);
    }, 15_000);

    it('renders an empty state when no models are returned', async () => {
      stubApi.getModels.mockResolvedValue({ models: [], tenantDefaultModel: null });
      renderPanel(stubApi);

      expect(await screen.findByText('No models available')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Set as default' })).not.toBeInTheDocument();
    }, 15_000);
  });
});
