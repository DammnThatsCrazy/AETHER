import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { KyberTrafficIntelligenceOpsPage } from '@kyber/pages/measurement/kyber-traffic-intelligence-ops-page';

const API = vi.hoisted(() => 'http://localhost:8000');

vi.mock('@kyber/lib/env', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@kyber/lib/env')>();
  return {
    ...actual,
    env: { ...actual.env, VITE_KYBER_ENV: 'local' as const, VITE_API_BASE_URL: API },
    getEnvironment: () => 'local' as const,
    getRuntimeMode: () => 'live' as const,
  };
});

const OPERATIONS_FIXTURE = {
  tenant_id: 'tenant_001',
  window: { start: '2026-06-24', end: '2026-07-24' },
  totals: { touchpoints: 4820, attribution_eligible: 3910, machine_excluded: 412 },
  classification_by_source_class: {
    paid_search: 1200,
    organic_search: 940,
    // Legacy alias must normalize to direct_unknown → "Direct / Unknown".
    direct: 810,
    ai_referral: 120,
  },
  classification_by_proof_level: {
    cryptographic: 640,
    domain_verified: 1500,
    declared: 900,
    none: 300,
  },
  direct_unknown_rate: 0.168,
  evidence_conflict_count: 37,
  invalid_source_link_count: 12,
  source_link_replay_count: 5,
  handoff_correlation: { success: 220, expired: 18, failed: 6 },
  install_referrer_retrieval: { retrieved: 300, timeout: 22, not_available: 40 },
  universal_link_processing_count: 512,
  deferred_attribution: { resolved: 180, unmatched: 40, expired: 20 },
  adattributionkit_ingestion_count: 96,
  sdk_deep_link_parse_failures: 9,
  reclassification_jobs: { running: 1, failed: 0, completed: 14 },
  utm_inconsistency_rate: 0.072,
  classification_drift: { legacy_vs_canonical_divergence_rate: 0.031 },
};

const EMPTY_FIXTURE = {
  tenant_id: 'tenant_empty',
  window: { start: '2026-06-24', end: '2026-07-24' },
  totals: { touchpoints: 0, attribution_eligible: 0, machine_excluded: 0 },
  classification_by_source_class: {},
  classification_by_proof_level: {},
  direct_unknown_rate: 0,
  evidence_conflict_count: 0,
  invalid_source_link_count: 0,
  source_link_replay_count: 0,
  handoff_correlation: { success: 0, expired: 0, failed: 0 },
  install_referrer_retrieval: {},
  universal_link_processing_count: 0,
  deferred_attribution: { resolved: 0, unmatched: 0, expired: 0 },
  adattributionkit_ingestion_count: 0,
  sdk_deep_link_parse_failures: 0,
  reclassification_jobs: { running: 0, failed: 0, completed: 0 },
  utm_inconsistency_rate: 0,
  classification_drift: { legacy_vs_canonical_divergence_rate: 0 },
};

function ok(data: unknown) {
  return HttpResponse.json({ data, status: 'ok', timestamp: new Date().toISOString() });
}

const OPS_PATH = `${API}/v1/kyber/measurement/source-classification/operations`;
const capturedQueries: URLSearchParams[] = [];

const server = setupServer(
  http.get(OPS_PATH, ({ request }) => {
    capturedQueries.push(new URL(request.url).searchParams);
    return ok(OPERATIONS_FIXTURE);
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => { capturedQueries.length = 0; });

function renderPage() {
  return render(<MemoryRouter><KyberTrafficIntelligenceOpsPage /></MemoryRouter>);
}

describe('Kyber Traffic Intelligence Operations page', () => {
  it('renders the operations scorecard from a mocked operations response', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Traffic Intelligence Operations')).toBeInTheDocument());

    // Totals.
    expect(screen.getByText('4,820')).toBeInTheDocument();
    expect(screen.getByText('3,910')).toBeInTheDocument();

    // Rate tiles.
    expect(screen.getByText('16.8%')).toBeInTheDocument(); // direct/unknown
    expect(screen.getByText('3.1%')).toBeInTheDocument();  // classification drift
    expect(screen.getByText('7.2%')).toBeInTheDocument();  // utm inconsistency

    // Integrity counts.
    expect(screen.getByText('Evidence conflicts')).toBeInTheDocument();
    expect(screen.getByText('SDK deep-link parse failures')).toBeInTheDocument();

    // Canonical source-class label — legacy "direct" renders "Direct / Unknown",
    // never "Typed URL", from the shared registry.
    expect(screen.getByText('Direct / Unknown')).toBeInTheDocument();
    expect(screen.getByText('Paid Search')).toBeInTheDocument();
    expect(screen.getByText('Organic Search')).toBeInTheDocument();
    expect(screen.getByText('AI Referral')).toBeInTheDocument();
    expect(screen.queryByText('Typed URL')).toBeNull();

    // Proof-level breakdown (humanized registry values).
    expect(screen.getByText('Cryptographic')).toBeInTheDocument();
    expect(screen.getByText('Domain Verified')).toBeInTheDocument();

    // State breakdowns.
    expect(screen.getByText('Link-use / handoff correlation')).toBeInTheDocument();
    expect(screen.getByText('Deferred attribution')).toBeInTheDocument();
    expect(screen.getByText('Reclassification jobs')).toBeInTheDocument();
    // Deferred resolution rate = 180 / (180+40+20) = 75.0%.
    expect(screen.getByText(/Resolution rate: 75\.0%/)).toBeInTheDocument();
  });

  it('renders zeroed/empty operations without crashing', async () => {
    server.use(http.get(OPS_PATH, () => ok(EMPTY_FIXTURE)));
    renderPage();
    await waitFor(() => expect(screen.getByText('Traffic Intelligence Operations')).toBeInTheDocument());

    // Empty breakdowns fall back to honest copy, not fabricated rows.
    expect(screen.getByText('No classified touchpoints in this window.')).toBeInTheDocument();
    expect(screen.getByText('No proof-level data in this window.')).toBeInTheDocument();
    expect(screen.getByText(/Resolution rate: —/)).toBeInTheDocument();
  });

  it('wires tenant/platform/sdk/time filters to the query params', async () => {
    renderPage();
    await waitFor(() => expect(capturedQueries.length).toBeGreaterThan(0));

    // Default 30-day window is applied on first load.
    const first = capturedQueries[0]!;
    expect(first.get('start')).toBeTruthy();
    expect(first.get('end')).toBeTruthy();

    await userEvent.type(screen.getByLabelText('Tenant'), 'tenant_042');
    await userEvent.selectOptions(screen.getByLabelText('Platform'), 'ios');
    await userEvent.type(screen.getByLabelText('SDK'), 'swift');

    await waitFor(() => {
      const last = capturedQueries[capturedQueries.length - 1]!;
      return expect(last.get('tenant')).toBe('tenant_042')
        && expect(last.get('platform')).toBe('ios')
        && expect(last.get('sdk')).toBe('swift');
    });
  });

  it('shows the error state when operations cannot be loaded', async () => {
    server.use(http.get(OPS_PATH, () => HttpResponse.json({ detail: 'operator permission required' }, { status: 403 })));
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Traffic intelligence operations unavailable')).toBeInTheDocument(),
    );
  });

  it('never renders a hardcoded source-class label for a value absent from the response', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Direct / Unknown')).toBeInTheDocument());
    const sourceCard = screen.getByText('Classification by source class').closest('div');
    expect(sourceCard).not.toBeNull();
    // Only the four classes present in the fixture render — no invented rows.
    expect(within(sourceCard as HTMLElement).queryByText('Affiliate')).toBeNull();
    expect(within(sourceCard as HTMLElement).queryByText('Push')).toBeNull();
  });
});
