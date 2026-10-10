import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UsagePage } from '@kyber/features/model-runtime/UsagePage';
import type { ModelRuntimeAdminApi, UsageResponse } from '@kyber/features/model-runtime/types';

const USAGE_FIXTURE: UsageResponse = {
  period: '2026-08-01 to 2026-08-07',
  totals: { calls: 12480, inputTokens: 230000, outputTokens: 61000, costUsd: 12.34 },
  byModel: [
    { modelId: 'anthropic/claude-sonnet-4-5', calls: 6400, inputTokens: 120000, outputTokens: 32000, costUsd: 6.2 },
    { modelId: 'openai/gpt-4o', calls: 6080, inputTokens: 110000, outputTokens: 29000, costUsd: 6.14 },
  ],
};

let fetchUsage: ReturnType<typeof vi.fn>;

function renderPage() {
  const api: ModelRuntimeAdminApi = {
    fetchRegistry: vi.fn(),
    fetchHealth: vi.fn(),
    fetchEntitlements: vi.fn(),
    fetchUsage: fetchUsage as unknown as ModelRuntimeAdminApi['fetchUsage'],
    fetchTraces: vi.fn(),
  };
  return render(<UsagePage api={api} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  fetchUsage = vi.fn();
});

describe('Kyber Model Runtime Usage page', () => {
  it('shows loading while the usage request is pending', () => {
    fetchUsage.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByRole('status', { name: 'Loading usage' })).toBeInTheDocument();
  });

  it('renders the period label, aggregate totals, and per-model rows from the stub', async () => {
    fetchUsage.mockResolvedValue(USAGE_FIXTURE);
    renderPage();

    await waitFor(() => expect(screen.getByText('Model Runtime Usage')).toBeInTheDocument());
    expect(screen.getByText('Usage period')).toBeInTheDocument();
    expect(screen.getByText('2026-08-01 to 2026-08-07')).toBeInTheDocument();

    for (const label of ['Calls', 'Input tokens', 'Output tokens', 'Cost in USD']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText('12480')).toBeInTheDocument();
    expect(screen.getByText('230000')).toBeInTheDocument();
    expect(screen.getByText('61000')).toBeInTheDocument();

    expect(screen.getByText('anthropic/claude-sonnet-4-5')).toBeInTheDocument();
    expect(screen.getByText('openai/gpt-4o')).toBeInTheDocument();
    expect(screen.getByText('6400')).toBeInTheDocument();
    expect(screen.getByText('6080')).toBeInTheDocument();
    expect(screen.getByText('120000')).toBeInTheDocument();
    expect(screen.getByText('32000')).toBeInTheDocument();
  });

  it('formats costs as USD currency', async () => {
    fetchUsage.mockResolvedValue({
      period: '2026-08-01 to 2026-08-07',
      totals: { calls: 500, inputTokens: 1000, outputTokens: 500, costUsd: 1234.5 },
      byModel: [
        { modelId: 'anthropic/claude-sonnet-4-5', calls: 250, inputTokens: 500, outputTokens: 250, costUsd: 0.5 },
        { modelId: 'openai/gpt-4o', calls: 250, inputTokens: 500, outputTokens: 250, costUsd: 1234 },
      ],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('$1,234.50')).toBeInTheDocument());
    expect(screen.getByText('$0.50')).toBeInTheDocument();
    expect(screen.getByText('$1,234.00')).toBeInTheDocument();
  });

  it('shows the error state and recovers via retry', async () => {
    fetchUsage.mockRejectedValueOnce(new Error('usage unavailable'));
    renderPage();

    await waitFor(() => expect(screen.getByText('Unable to load usage')).toBeInTheDocument());
    expect(screen.getByText('The model-runtime usage endpoint could not be reached. Retry to load it again.')).toBeInTheDocument();

    fetchUsage.mockResolvedValueOnce(USAGE_FIXTURE);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getByText('$12.34')).toBeInTheDocument());
    expect(fetchUsage).toHaveBeenCalledTimes(2);
  });

  it('shows the empty state when no per-model usage exists', async () => {
    fetchUsage.mockResolvedValue({
      period: '2026-08-01 to 2026-08-07',
      totals: { calls: 0, inputTokens: 0, outputTokens: 0, costUsd: 0 },
      byModel: [],
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('No model usage recorded')).toBeInTheDocument());
  });

  it('never renders credential material', async () => {
    fetchUsage.mockResolvedValue(USAGE_FIXTURE);
    renderPage();

    await waitFor(() => expect(screen.getByText('$12.34')).toBeInTheDocument());
    const bodyText = document.body.textContent ?? '';
    expect(bodyText).not.toMatch(/sk-/i);
    expect(bodyText).not.toMatch(/AKIA/i);
    expect(bodyText).not.toMatch(/Bearer/i);
  });
});
