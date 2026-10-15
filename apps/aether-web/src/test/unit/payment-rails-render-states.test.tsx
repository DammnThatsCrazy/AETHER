import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider, queryCache } from '@aether/ui';
import {
  fundingSessionStatuses,
  reconciliationStates,
} from '@aether/shared';
import type { FundingSessionStatus, ReconciliationState } from '@aether/shared';
import { PaymentRailsPage } from '@aether-app/pages/payment-rails';
import {
  ReconciliationStateBadge,
  SessionStatusBadge,
  ProviderHealthBadge,
  formatMatchedRate,
  formatNativeAmount,
  type ProviderHealthStatus,
} from '@aether-app/pages/payment-rails/payment-rails-shared';

/**
 * E2 + E3 — render-state coverage the page test does not assert.
 *
 * E2 (provider last-signal / freshness): the closest existing analog to a
 * "provider heartbeat / last-successful cycle" is the health card's last-event
 * timestamp and matched-rate. The invariant under test is the same one the
 * backend evaluator enforces: UNKNOWN must render as "—", never a misleading 0 or
 * a fabricated date. A measured 0 (e.g. a genuine 0% matched rate) is DISTINCT
 * from unknown and must still render as "0.0%".
 *
 * E3 (delivery-lifecycle + repair-outcome): every reconciliation state and
 * session status must render its own distinct badge (a not-yet-matched / stale /
 * conflicted delivery can never read as matched), an out-of-contract provider
 * health status must fail safe to not_configured (never "live"), and the repair
 * control must honestly surface the `error` outcome (the branch the existing
 * suite does not cover).
 */

// See payment-rails-page.test.tsx: the shared queryCache leaks an unhandled
// rejection via `promise.finally` when a fetcher rejects even though the UI
// handles it. Patch it test-locally so error-path renders stay quiet.
beforeAll(() => {
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

// ── E2 · formatters: unknown ("—") is never a measured zero ───────────────────
describe('E2 · payment-rail formatters — unknown vs measured zero', () => {
  it('matched rate: null/undefined → "—", but a real 0 → "0.0%"', () => {
    expect(formatMatchedRate(null)).toBe('—');
    expect(formatMatchedRate(undefined)).toBe('—');
    // A measured 0% is a fact, not an absence — it must NOT collapse to "—".
    expect(formatMatchedRate(0)).toBe('0.0%');
    expect(formatMatchedRate(0.982)).toBe('98.2%');
  });

  it('native amount: null → "—", but "0.00" is a real amount → "0.00 USD"', () => {
    expect(formatNativeAmount(null, 'USD')).toBe('—');
    expect(formatNativeAmount(undefined, 'USD')).toBe('—');
    expect(formatNativeAmount('0.00', 'USD')).toBe('0.00 USD');
    expect(formatNativeAmount('100', null)).toBe('100'); // amount known, unit unknown
  });
});

// ── E3 · delivery-lifecycle badges: every state is distinct + safe fallback ───
describe('E3 · delivery-lifecycle badges', () => {
  it('renders a distinct badge label for every reconciliation state', () => {
    for (const state of reconciliationStates as readonly ReconciliationState[]) {
      const { getByText, unmount } = render(<ReconciliationStateBadge state={state} />);
      expect(getByText(state)).toBeInTheDocument();
      unmount();
    }
  });

  it('renders every funding session status, including `unresolved`', () => {
    for (const status of fundingSessionStatuses as readonly FundingSessionStatus[]) {
      const { getByText, unmount } = render(<SessionStatusBadge status={status} />);
      expect(getByText(status)).toBeInTheDocument();
      unmount();
    }
  });

  it('maps an out-of-contract provider health status to not_configured, never live', () => {
    // Simulate a server sending a status outside the 4-value contract (the cast
    // stands in for malformed wire data). resolveCapabilityState returns null for
    // it, and the badge falls back to not_configured — it can never read as live.
    const { container } = render(
      <ProviderHealthBadge status={'totally_unknown' as ProviderHealthStatus} />,
    );
    expect(container.querySelector('[data-capability-state="not_configured"]')).not.toBeNull();
    expect(container.querySelector('[data-capability-state="partner_live"]')).toBeNull();
  });
});

// ── E2 + E3 · full-page render harness (mocks the api module) ─────────────────
const mocks = vi.hoisted(() => ({
  fetchFundingSessions: vi.fn(),
  fetchFundingSession: vi.fn(),
  fetchReconciliationRecords: vi.fn(),
  fetchPaymentRailHealth: vi.fn(),
  fetchProviderStatus: vi.fn(),
  syncProviderStatus: vi.fn(),
  repairCanonicalBacklog: vi.fn(),
  // The page mounts useTenantDiagnostics (credential/endpoint/polling/backlog
  // readiness panel), which calls fetchTenantDiagnostics on mount. The api
  // module mock MUST export it or the hook's useQuery rejects with an
  // "export not defined" unhandled rejection that fails the whole vitest run
  // even though assertions pass. Default resolves to the not-configured shape
  // so these render-state tests exercise the page without a diagnostics panel.
  fetchTenantDiagnostics: vi.fn(),
}));

vi.mock('@aether-app/features/payment-rails/api', () => mocks);

function health(overrides: Record<string, unknown>) {
  return {
    tenant_id: 't_1',
    provider: 'privy',
    configured: true,
    enabled: true,
    webhook_verified_24h: 5,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 3,
    sessions_completed_24h: 2,
    sessions_failed_24h: 0,
    sessions_unresolved: 0,
    reconciliation_matched_rate: null,
    reconciliation_conflicts: 0,
    last_event_at: null,
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <ToastProvider>
      <PaymentRailsPage />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  queryCache.invalidatePrefix('payment-rails');
  mocks.fetchFundingSessions.mockResolvedValue({ sessions: [], notConfigured: false });
  mocks.fetchFundingSession.mockResolvedValue(null);
  mocks.fetchReconciliationRecords.mockResolvedValue([]);
  mocks.fetchProviderStatus.mockResolvedValue({ provider: 'privy', status: 'configured' });
  mocks.syncProviderStatus.mockResolvedValue({ sync_requested: true });
  mocks.fetchTenantDiagnostics.mockResolvedValue({ diagnostics: null, notConfigured: false });
});

describe('E2 · provider last-signal rendering (fresh vs unknown)', () => {
  it('renders "—" for unknown last-event / matched-rate, never a fabricated 0%', async () => {
    // Both configured providers have NO last event and NO matched rate (unknown).
    mocks.fetchPaymentRailHealth.mockResolvedValue({
      providers: [
        health({ provider: 'privy', last_event_at: null, reconciliation_matched_rate: null }),
        health({ provider: 'coinbase', last_event_at: null, reconciliation_matched_rate: null }),
      ],
      notConfigured: false,
    });
    renderPage();
    // Wait for the configured cards to render (Sync button only shows when configured).
    await waitFor(() => expect(screen.getAllByText('Sync status').length).toBeGreaterThan(0));
    // Unknown freshness/rate render as em-dashes...
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    // ...and NEVER as a fabricated 0% matched rate or an Invalid Date.
    expect(screen.queryByText('0.0%')).toBeNull();
    expect(screen.queryByText(/Invalid Date/)).toBeNull();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it('renders the real matched rate when it is a measured value', async () => {
    mocks.fetchPaymentRailHealth.mockResolvedValue({
      providers: [
        health({ provider: 'privy', last_event_at: '2026-07-08T14:07:11.000Z', reconciliation_matched_rate: 0.982 }),
      ],
      notConfigured: false,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('98.2%')).toBeInTheDocument());
  });

  it('renders a measured 0% matched rate as "0.0%", distinct from unknown', async () => {
    mocks.fetchPaymentRailHealth.mockResolvedValue({
      providers: [health({ provider: 'privy', reconciliation_matched_rate: 0 })],
      notConfigured: false,
    });
    renderPage();
    await waitFor(() => expect(screen.getByText('0.0%')).toBeInTheDocument());
  });
});

describe('E3 · repair outcome — the error branch (extends existing coverage)', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_PAYMENT_CANONICAL_REPAIR_ENABLED', 'true');
    mocks.fetchPaymentRailHealth.mockResolvedValue({ providers: [health({})], notConfigured: false });
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('surfaces an error-outcome message honestly (not a silent success)', async () => {
    mocks.repairCanonicalBacklog.mockResolvedValue({ status: 'error', message: 'backlog store unavailable' });
    renderPage();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Repair backlog' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Repair backlog' }));
    await waitFor(() => expect(screen.getByText('backlog store unavailable')).toBeInTheDocument());
  });

  it('renders a genuine all-zero repair result as counts of 0 (a fact, not "—")', async () => {
    mocks.repairCanonicalBacklog.mockResolvedValue({
      status: 'repaired',
      result: { scanned: 0, repaired: 0, events_reemitted: 0 },
    });
    renderPage();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Repair backlog' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Repair backlog' }));
    await waitFor(() => expect(screen.getByText('Canonical backlog repair complete')).toBeInTheDocument());
    // Three RepairCount tiles each show "0" — a measured zero, shown honestly.
    expect(screen.getAllByText('0').length).toBeGreaterThanOrEqual(3);
  });
});
