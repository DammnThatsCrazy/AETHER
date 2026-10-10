/**
 * Kyber — model-routing decision traces page (ADR-008 D8/D9).
 *
 * The load-bearing tests are the honesty ones: every column renders the
 * backend's own vocabulary (mode as-is, latency as `N ms`, booleans as
 * Yes/No), the requested → selected decision reads as one cell, and the
 * rendered surface never carries credential or request-body material — the
 * trace fields are identifiers / statuses / latencies only. The stub api is
 * injected through the `api` prop, so the real typed client and the real zod
 * shape are never needed; the module under test is the component itself.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { TracesPage } from '@kyber/features/model-runtime/TracesPage';
import type {
  ModelRuntimeAdminApi,
  RoutingTrace,
} from '@kyber/features/model-runtime/types';

const TRACES: RoutingTrace[] = [
  {
    traceId: 'trace_alpha_001',
    correlationId: 'corr_9f2c',
    tenantId: 'tenant_alpha',
    profileId: 'profile_risk_scoring',
    requestedModel: 'anthropic/claude-sonnet-4-5',
    selectedModel: 'anthropic/claude-sonnet-4-5',
    mode: 'primary',
    entitled: true,
    fallback: false,
    status: 'completed',
    latencyMs: 123,
    createdAt: '2026-08-08T10:00:00.000Z',
  },
  {
    traceId: 'trace_beta_002',
    correlationId: null,
    tenantId: 'tenant_beta',
    profileId: 'profile_agent_ops',
    requestedModel: null,
    selectedModel: 'gpt-4o',
    mode: 'fallback',
    entitled: false,
    fallback: true,
    status: 'degraded',
    latencyMs: 540,
    createdAt: '2026-08-08T09:59:00.000Z',
  },
];

function createApi(
  overrides: Partial<Pick<ModelRuntimeAdminApi, 'fetchTraces'>> = {},
): Pick<ModelRuntimeAdminApi, 'fetchTraces'> {
  return {
    fetchTraces: vi.fn().mockResolvedValue({ traces: TRACES }),
    ...overrides,
  };
}

describe('TracesPage (Kyber model-runtime admin)', () => {
  it('renders routing decision trace rows from the stub', async () => {
    render(<TracesPage api={createApi()} />);

    await waitFor(() => expect(screen.getByText('trace_alpha_001')).toBeInTheDocument());
    expect(screen.getByText('trace_beta_002')).toBeInTheDocument();
    expect(screen.getByText('corr_9f2c')).toBeInTheDocument();
    expect(screen.getByText('tenant_alpha')).toBeInTheDocument();
    expect(screen.getByText('profile_agent_ops')).toBeInTheDocument();
    expect(screen.getByText('primary')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('degraded')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Model routing decision traces' })).toBeInTheDocument();
  });

  it('renders requested → selected model in a single column', async () => {
    render(<TracesPage api={createApi()} />);

    await waitFor(() => expect(screen.getByText('trace_alpha_001')).toBeInTheDocument());
    expect(
      screen.getByText('anthropic/claude-sonnet-4-5 → anthropic/claude-sonnet-4-5'),
    ).toBeInTheDocument();
    // A null requestedModel renders a placeholder — the cell still reads as a decision.
    expect(screen.getByText('— → gpt-4o')).toBeInTheDocument();
  });

  it('renders entitled and fallback booleans as Yes/No', async () => {
    render(<TracesPage api={createApi()} />);

    await waitFor(() => expect(screen.getByText('trace_alpha_001')).toBeInTheDocument());
    // Row 1: entitled Yes + fallback No; Row 2: entitled No + fallback Yes.
    expect(screen.getAllByText('Yes')).toHaveLength(2);
    expect(screen.getAllByText('No')).toHaveLength(2);
  });

  it('shows the loading state while the traces request is pending', () => {
    const pending = new Promise<never>(() => undefined);
    render(<TracesPage api={createApi({ fetchTraces: vi.fn().mockReturnValue(pending) })} />);
    expect(screen.getByLabelText('Loading traces')).toBeInTheDocument();
  });

  it('shows the error state with a retry that recovers', async () => {
    const fetchTraces = vi
      .fn()
      .mockRejectedValueOnce(new Error('traces unavailable'))
      .mockResolvedValueOnce({ traces: TRACES });
    render(<TracesPage api={createApi({ fetchTraces })} />);

    await waitFor(() => expect(screen.getByText('Unable to load traces')).toBeInTheDocument());
    expect(screen.getByText('traces unavailable')).toBeInTheDocument();
    expect(fetchTraces).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getByText('trace_alpha_001')).toBeInTheDocument());
    expect(screen.queryByText('Unable to load traces')).not.toBeInTheDocument();
    expect(fetchTraces).toHaveBeenCalledTimes(2);
  });

  it('shows the empty state when no routing traces exist', async () => {
    render(
      <TracesPage
        api={createApi({ fetchTraces: vi.fn().mockResolvedValue({ traces: [] }) })}
      />,
    );

    await waitFor(() => expect(screen.getByText('No routing traces')).toBeInTheDocument());
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('never renders credentials or request bodies in the traces surface', async () => {
    render(<TracesPage api={createApi()} />);

    await waitFor(() => expect(screen.getByText('trace_alpha_001')).toBeInTheDocument());
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/sk-/);
    expect(text).not.toMatch(/AKIA/);
    expect(text).not.toMatch(/Bearer/);
  });
});
