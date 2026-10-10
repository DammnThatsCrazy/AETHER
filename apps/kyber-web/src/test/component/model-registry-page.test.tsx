import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelRegistryPage } from '@kyber/features/model-runtime/ModelRegistryPage';
import type {
  ModelRuntimeAdminApi,
  RegistryModel,
} from '@kyber/features/model-runtime/types';

const mocks = vi.hoisted(() => ({
  fetchRegistry: vi.fn(),
}));

// C14-F owns types.ts. This suite always injects a stub api, but we stub the
// default typed client module anyway so we never depend on C14-F's file at
// runtime (the sibling aether pattern).
vi.mock('@kyber/features/model-runtime/types', () => ({
  defaultModelRuntimeAdminApi: {
    fetchRegistry: mocks.fetchRegistry,
    fetchHealth: vi.fn(),
    fetchEntitlements: vi.fn(),
    fetchUsage: vi.fn(),
    fetchTraces: vi.fn(),
  },
}));

const MODELS: RegistryModel[] = [
  {
    modelId: 'openai/gpt-4o',
    provider: 'openai',
    status: 'stable',
    capabilities: ['chat', 'vision'],
    inputCostPerMTok: 2.5,
    outputCostPerMTok: 10,
  },
  {
    modelId: 'anthropic/claude-sonnet-5',
    provider: 'anthropic',
    status: 'recommended',
    capabilities: ['chat', 'tool_use', 'thinking'],
    inputCostPerMTok: 3,
    outputCostPerMTok: 15,
  },
  {
    modelId: 'anthropic/claude-haiku-4-5',
    provider: 'anthropic',
    status: 'beta',
    capabilities: ['chat'],
    inputCostPerMTok: 1,
    outputCostPerMTok: 5,
  },
];

function createApi(overrides: Partial<ModelRuntimeAdminApi> = {}): ModelRuntimeAdminApi {
  return {
    fetchRegistry: mocks.fetchRegistry,
    fetchHealth: vi.fn(),
    fetchEntitlements: vi.fn(),
    fetchUsage: vi.fn(),
    fetchTraces: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchRegistry.mockResolvedValue({ models: MODELS });
});

describe('Kyber Model Registry page', () => {
  it('shows the loading state while the registry request is pending', () => {
    mocks.fetchRegistry.mockReturnValue(new Promise(() => undefined));
    render(<ModelRegistryPage api={createApi()} />);
    expect(screen.getByRole('status', { name: 'Loading registry' })).toBeInTheDocument();
  });

  it('renders models grouped by provider from the stub api', async () => {
    render(<ModelRegistryPage api={createApi()} />);
    await waitFor(() => expect(screen.getByText('anthropic/claude-sonnet-5')).toBeInTheDocument());

    for (const header of ['Provider', 'Model', 'Status', 'Capabilities', 'Cost']) {
      expect(screen.getByRole('columnheader', { name: header })).toBeInTheDocument();
    }

    // Rows are grouped by provider (anthropic group contiguous, then openai).
    const rows = screen.getAllByRole('row');
    const bodyText = rows.slice(1).map((r) => r.textContent ?? '');
    const haikuIndex = bodyText.findIndex((t) => t.includes('anthropic/claude-haiku-4-5'));
    const sonnetIndex = bodyText.findIndex((t) => t.includes('anthropic/claude-sonnet-5'));
    expect(haikuIndex).toBeGreaterThan(-1);
    expect(sonnetIndex).toBeGreaterThan(haikuIndex);
    expect(bodyText[sonnetIndex]).toContain('anthropic');
    expect(bodyText[sonnetIndex + 1]).toContain('openai');
    expect(bodyText[sonnetIndex + 1]).toContain('openai/gpt-4o');
  });

  it('renders status badges, capability chips, and display-only costs', async () => {
    render(<ModelRegistryPage api={createApi()} />);
    await waitFor(() => expect(screen.getByText('anthropic/claude-sonnet-5')).toBeInTheDocument());

    expect(screen.getByText('recommended')).toBeInTheDocument();
    expect(screen.getByText('stable')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();

    expect(screen.getAllByText('chat').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText('tool_use')).toBeInTheDocument();
    expect(screen.getByText('thinking')).toBeInTheDocument();
    expect(screen.getByText('vision')).toBeInTheDocument();

    expect(screen.getByText('$1.00 in · $5.00 out / 1M tokens')).toBeInTheDocument();
    expect(screen.getByText('$3.00 in · $15.00 out / 1M tokens')).toBeInTheDocument();
    expect(screen.getByText('$2.50 in · $10.00 out / 1M tokens')).toBeInTheDocument();
  });

  it('shows the empty state when no models are registered', async () => {
    mocks.fetchRegistry.mockResolvedValue({ models: [] });
    render(<ModelRegistryPage api={createApi()} />);
    await waitFor(() => expect(screen.getByText('No models registered')).toBeInTheDocument());
  });

  it('shows the error state and retry re-calls the api', async () => {
    mocks.fetchRegistry.mockRejectedValueOnce(new Error('registry unavailable'));
    const api = createApi();
    render(<ModelRegistryPage api={api} />);
    await waitFor(() => expect(screen.getByText('Unable to load registry')).toBeInTheDocument());
    expect(mocks.fetchRegistry).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByText('anthropic/claude-sonnet-5')).toBeInTheDocument());
    expect(mocks.fetchRegistry).toHaveBeenCalledTimes(2);
  });

  it('never renders credential material', async () => {
    render(<ModelRegistryPage api={createApi()} />);
    await waitFor(() => expect(screen.getByText('anthropic/claude-sonnet-5')).toBeInTheDocument());
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/sk-/i);
    expect(text).not.toMatch(/AKIA/i);
    expect(text).not.toMatch(/Bearer/i);
  });
});
