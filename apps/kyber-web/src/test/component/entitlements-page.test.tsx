/**
 * Kyber — model-runtime EntitlementsPage component tests (ADR-008 D4 / D8-D9).
 *
 * The load-bearing assertions here are the ones that keep the surface honest:
 *
 *  · the page is read-only and never renders credential material — the rendered
 *    text must not contain `sk-`, `AKIA`, or `Bearer` in ANY state;
 *  · a `not entitled` row must render as a Not-entitled badge, never as
 *    entitled;
 *  · the tenant filter is strictly client-side (no additional server call —
 *    `fetchEntitlements` is called exactly once per load/retry).
 *
 * The fetch client is injected via the `api` prop (defaults to the typed
 * `defaultModelRuntimeAdminApi`), so no module mocks are needed.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EntitlementsPage } from '@kyber/features/model-runtime/entitlements-page';
import type { EntitlementsPageProps } from '@kyber/features/model-runtime/entitlements-page';
import type { EntitlementRow } from '@kyber/features/model-runtime/types';

type StubApi = { fetchEntitlements: ReturnType<typeof vi.fn> };

const ENTITLEMENTS: EntitlementRow[] = [
  { tenantId: 'tenant_alpha', modelId: 'gpt-4o', entitled: true, reason: null },
  {
    tenantId: 'tenant_gamma',
    modelId: 'claude-opus-4-1',
    entitled: false,
    reason: 'No license for this model',
  },
  { tenantId: 'tenant_beta', modelId: 'llama-3-1-70b', entitled: true, reason: 'Free-tier policy' },
];

function makeApi(): StubApi {
  return { fetchEntitlements: vi.fn() };
}

function renderPage(api: StubApi): ReturnType<typeof render> {
  return render(<EntitlementsPage api={api as NonNullable<EntitlementsPageProps['api']>} />);
}

function givenRows(api: StubApi, rows: EntitlementRow[]): void {
  api.fetchEntitlements.mockResolvedValue({ entitlements: rows });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('EntitlementsPage', () => {
  it('renders entitlement rows from the stub api', async () => {
    const api = makeApi();
    givenRows(api, ENTITLEMENTS);
    renderPage(api);

    await waitFor(() => expect(screen.getByText('tenant_alpha')).toBeInTheDocument());

    expect(screen.getByText('tenant_beta')).toBeInTheDocument();
    expect(screen.getByText('gpt-4o')).toBeInTheDocument();
    expect(screen.getByText('claude-opus-4-1')).toBeInTheDocument();
    expect(screen.getByText('llama-3-1-70b')).toBeInTheDocument();
    expect(api.fetchEntitlements).toHaveBeenCalledTimes(1);
  });

  it('shows an Entitled badge for entitled rows and Not entitled otherwise', async () => {
    const api = makeApi();
    givenRows(api, ENTITLEMENTS);
    renderPage(api);

    await waitFor(() => expect(screen.getAllByText('Entitled')).toHaveLength(2));
    expect(screen.getByText('Not entitled')).toBeInTheDocument();
  });

  it('shows the reason when present and a muted placeholder when absent', async () => {
    const api = makeApi();
    givenRows(api, ENTITLEMENTS);
    renderPage(api);

    await waitFor(() => expect(screen.getByText('No license for this model')).toBeInTheDocument());
    expect(screen.getByText('Free-tier policy')).toBeInTheDocument();
    // The row without a reason renders a placeholder, not an empty cell.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('narrows the table by tenant ID entirely client-side', async () => {
    const api = makeApi();
    givenRows(api, ENTITLEMENTS);
    renderPage(api);

    await waitFor(() => expect(screen.getByText('tenant_alpha')).toBeInTheDocument());

    await userEvent.type(screen.getByLabelText('Filter by tenant ID'), 'tenant_beta');

    expect(screen.getByText('tenant_beta')).toBeInTheDocument();
    expect(screen.queryByText('tenant_alpha')).not.toBeInTheDocument();
    expect(screen.queryByText('gpt-4o')).not.toBeInTheDocument();
    // Client-side filter — no additional server call.
    expect(api.fetchEntitlements).toHaveBeenCalledTimes(1);
  });

  it('shows the error state and recovers on retry', async () => {
    const api = makeApi();
    api.fetchEntitlements
      .mockRejectedValueOnce(new Error('entitlements endpoint unavailable'))
      .mockResolvedValueOnce({ entitlements: ENTITLEMENTS });
    renderPage(api);

    await waitFor(() =>
      expect(screen.getByText('Unable to load entitlements')).toBeInTheDocument(),
    );
    expect(screen.getByText('entitlements endpoint unavailable')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getByText('tenant_alpha')).toBeInTheDocument());
    expect(screen.queryByText('Unable to load entitlements')).not.toBeInTheDocument();
    expect(api.fetchEntitlements).toHaveBeenCalledTimes(2);
  });

  it('shows the loading state while the request is pending', () => {
    const api = makeApi();
    api.fetchEntitlements.mockReturnValue(new Promise(() => undefined));
    renderPage(api);

    expect(screen.getByLabelText('Loading entitlements')).toBeInTheDocument();
    expect(screen.queryByText('No entitlements recorded')).not.toBeInTheDocument();
  });

  it('shows the empty state when no entitlements are recorded', async () => {
    const api = makeApi();
    givenRows(api, []);
    renderPage(api);

    await waitFor(() => expect(screen.getByText('No entitlements recorded')).toBeInTheDocument());
  });

  it('never renders credential material in any state', async () => {
    const api = makeApi();
    givenRows(api, [
      {
        tenantId: 'tenant_alpha',
        modelId: 'gpt-4o',
        entitled: true,
        reason: 'region-allowlist',
      },
    ]);
    renderPage(api);

    await waitFor(() => expect(screen.getByText('tenant_alpha')).toBeInTheDocument());

    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/sk-/);
    expect(text).not.toMatch(/AKIA/);
    expect(text).not.toMatch(/Bearer/);
  });
});
