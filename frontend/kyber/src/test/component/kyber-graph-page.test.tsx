/**
 * Kyber — Kyber Graph operator console.
 *
 * The load-bearing tests here are the honesty ones, and each is asserted both
 * positively and negatively because the failure mode is always the same shape:
 * an absence of knowledge rendered as good news.
 *
 *   · `totals_known: false` ⇒ the partial banner is on screen AND no numeric
 *     total is rendered in the totals region (not even a 0);
 *   · a stale projection row is marked stale, and its state badge is re-labelled
 *     so a stale row can never read as a current healthy one;
 *   · a suppressed cohort shows its suppression reason instead of an empty table;
 *   · `exposure_known: false` ⇒ Unknown plus reasons, never a reach count;
 *   · `truncated: true` ⇒ the bounded-traversal notice, with the lowered confidence;
 *   · a 403 on the D3 tenant read renders "requires an active tenant scope" with
 *     the backend's own reason — not a generic failure.
 *
 * Only `restClient` is mocked, so the real feature hooks and the real zod schemas
 * run: a schema that coerced a null count to 0, or dropped `stale`, would fail here.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { KyberGraphPage } from '@kyber/pages/kyber-graph';

const restGet = vi.fn();
const restPost = vi.fn();

vi.mock('@kyber/lib/api', () => ({
  restClient: {
    get: (...args: unknown[]) => restGet(...args),
    post: (...args: unknown[]) => restPost(...args),
  },
}));

const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`, which
  // leaks an unhandled rejection when a fetcher rejects even though the UI renders an
  // ErrorState. Patch it test-locally (same fix as imports-ops-page.test.tsx).
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────────────

const PLATFORM_COMPLETE = {
  available: true,
  environment: null,
  nodes: {
    Service: [
      {
        node_key: 'service:identity-worker',
        node_type: 'Service',
        display_name: 'identity-worker',
        environment: 'production',
        health: 'healthy',
      },
      {
        node_key: 'service:ledger',
        node_type: 'Service',
        display_name: 'ledger',
        environment: 'production',
        health: 'degraded',
      },
    ],
    Release: [
      {
        node_key: 'release:2026.07.1',
        node_type: 'Release',
        display_name: '2026.07.1',
        environment: 'production',
        health: 'unknown',
      },
      {
        node_key: 'release:2026.07.2',
        node_type: 'Release',
        display_name: '2026.07.2',
        environment: 'production',
        health: 'no_data',
      },
    ],
  },
  counts: { Service: 2, Release: 2 },
  node_count: 4,
  by_health: { healthy: 1, degraded: 1, unknown: 1, no_data: 1 },
  state: 'degraded',
  truncated: false,
  totals_known: true,
  missing_inputs: [],
  queries_issued: 9,
  computed_at: '2026-07-25T12:00:00+00:00',
};

const PLATFORM_PARTIAL = {
  ...PLATFORM_COMPLETE,
  state: 'unknown',
  truncated: true,
  totals_known: false,
  missing_inputs: ['kyber_graph_nodes:Service:scan_truncated'],
};

const FLEET_COMPLETE = {
  environment: null,
  projections: {
    graph_health: {
      row_count: 12,
      tenant_count: 12,
      by_state: { healthy: 11, degraded: 1 },
      by_region: { 'eu-west': 12 },
      by_dimension: { '-': 12 },
      score: { count: 12, min: 0.4, mean: 0.8, max: 1 },
      state: 'degraded',
      stale: false,
      oldest_computed_at: '2026-07-25T11:58:00+00:00',
      oldest_row_age_seconds: 120,
      max_age_seconds: 900,
      totals_known: true,
      missing_inputs: [],
      truncated: false,
      computed_at: '2026-07-25T12:00:00+00:00',
    },
  },
  projection_count: 1,
  tenant_count: 12,
  state: 'degraded',
  by_state: { healthy: 11, degraded: 1 },
  stale: false,
  oldest_computed_at: '2026-07-25T11:58:00+00:00',
  oldest_row_age_seconds: 120,
  max_age_seconds: 900,
  totals_known: true,
  missing_inputs: [],
  truncated: false,
  queries_issued: 1,
  scan_limit: 2000,
  computed_at: '2026-07-25T12:00:00+00:00',
};

/**
 * A partial fleet read that STILL carries integers. This is the shape the page
 * has to refuse to call a total: the backend keeps `tenant_count: 7` even with
 * `totals_known: false`, and 7 is a count of what was read, not the fleet.
 */
const FLEET_PARTIAL = {
  ...FLEET_COMPLETE,
  projections: {
    graph_health: {
      ...FLEET_COMPLETE.projections.graph_health,
      row_count: 7,
      tenant_count: 7,
      state: 'unknown',
      totals_known: false,
      truncated: true,
      missing_inputs: ['kyber_fleet_projections:scan_truncated'],
    },
  },
  tenant_count: 7,
  state: 'unknown',
  totals_known: false,
  truncated: true,
  missing_inputs: ['kyber_fleet_projections:scan_truncated'],
};

/** A stale row whose own state still reads `healthy` — the trap this page must not fall into. */
const FLEET_STALE = {
  ...FLEET_COMPLETE,
  projections: {
    ingestion_lag: {
      ...FLEET_COMPLETE.projections.graph_health,
      state: 'healthy',
      stale: true,
      oldest_computed_at: '2026-07-25T09:00:00+00:00',
      oldest_row_age_seconds: 10800,
      totals_known: false,
      missing_inputs: ['fleet_projection_stale:max_age_seconds=900'],
    },
  },
  stale: true,
  state: 'unknown',
  oldest_computed_at: '2026-07-25T09:00:00+00:00',
  oldest_row_age_seconds: 10800,
  totals_known: false,
  missing_inputs: ['fleet_projection_stale:max_age_seconds=900'],
};

const COHORT_DEFINED = {
  cohort: {
    cohort_id: 'kco_0001',
    name: 'degraded-eu-west',
    filters: { projection: 'graph_health' },
    minimum_size: 3,
    created_by: 'operator_001',
    created_at: '2026-07-25T12:00:00+00:00',
  },
  normalised: false,
};

const COHORT_SUPPRESSED = {
  cohort_id: 'kco_0001',
  name: 'degraded-eu-west',
  filters: { projection: 'graph_health' },
  environment: null,
  minimum_size: 3,
  queries_issued: 1,
  computed_at: '2026-07-25T12:00:00+00:00',
  suppressed: true,
  reason: 'below_minimum_cohort_size',
  member_count: null,
  members: null,
  state: 'unknown',
  stale: true,
  totals_known: false,
  missing_inputs: ['cohort_below_minimum:below_minimum_cohort_size'],
  truncated: false,
};

const COHORT_RESOLVED = {
  ...COHORT_SUPPRESSED,
  suppressed: false,
  reason: null,
  member_count: 5,
  members: ['tenant_001', 'tenant_002', 'tenant_003', 'tenant_004', 'tenant_005'],
  members_disclosure_gated: false,
  row_count: 5,
  by_state: { healthy: 4, degraded: 1 },
  by_region: { 'eu-west': 5 },
  by_dimension: { '-': 5 },
  score: { count: 5, min: 0.5, mean: 0.7, max: 0.9 },
  state: 'degraded',
  stale: false,
  totals_known: true,
  missing_inputs: [],
  oldest_computed_at: '2026-07-25T11:58:00+00:00',
  oldest_row_age_seconds: 120,
  max_age_seconds: 900,
};

const BLAST_COMPLETE = {
  subject_type: 'Service',
  subject_id: 'identity-worker',
  environment: 'production',
  exposure_known: true,
  missing_inputs: [],
  affected_services: ['service:ledger'],
  affected_features: ['feature:checkout'],
  affected_tenants: [],
  affected_graph_domains: [],
  customer_visible: true,
  traversal_depth: 3,
  truncated: false,
  confidence: 0.9,
  evidence_references: [],
  computed_at: '2026-07-25T12:00:00+00:00',
};

const BLAST_UNKNOWN = {
  ...BLAST_COMPLETE,
  subject_id: 'ghost-service',
  exposure_known: false,
  missing_inputs: ['kyber_graph_node:node_key=service:ghost-service'],
  affected_services: [],
  affected_features: [],
  customer_visible: false,
  traversal_depth: 0,
  confidence: 0,
};

const BLAST_TRUNCATED = {
  ...BLAST_COMPLETE,
  exposure_known: false,
  truncated: true,
  confidence: 0.45,
  missing_inputs: ['kyber_graph_edges:fanout_truncated:service:identity-worker'],
};

const TENANT_GRANTED = {
  tenantVisible: {
    tenant_id: 'tenant_001',
    vertex_type: null,
    vertices: [{ vertex_id: 'v_1', vertex_type: 'Profile', properties: {} }],
    vertex_count: 1,
    truncated: false,
  },
  operatorDiagnostics: {
    surface: 'query',
    capability: 'kyber.graph.tenant.read',
    granted_disclosure: 'D3_TENANT_VISIBLE',
    identifiers_masked: false,
    scope_id: 'scope_001',
    purpose: 'incident_investigation',
    requested_limit: 500,
    budget: 500,
    result_count: 1,
    truncated: false,
    evidence_disclosure_gated: true,
    evidence_reference_count: 0,
    evidence_references: [],
    missing_inputs: [],
    exposure_known: true,
    computed_at: '2026-07-25T12:00:00+00:00',
  },
};

/** What the ordered gate raises when no active scope names the tenant. */
function forbidden(detail: string, denialReason: string): Error {
  const error = new Error(detail) as Error & {
    status: number;
    code: string;
    problem: Record<string, unknown>;
  };
  error.name = 'RestClientError';
  error.status = 403;
  error.code = 'FORBIDDEN';
  error.problem = {
    type: 'about:blank',
    title: 'Forbidden',
    status: 403,
    code: 'FORBIDDEN',
    detail,
    details: { denial_reason: denialReason },
  };
  return error;
}

// ── Wiring ───────────────────────────────────────────────────────────────────

interface Responses {
  readonly platform?: unknown;
  readonly fleet?: unknown;
  readonly cohort?: unknown;
  readonly cohortDefine?: unknown;
  readonly blast?: unknown;
  readonly tenant?: unknown;
  readonly platformError?: Error;
  readonly tenantError?: Error;
}

function mockApi(responses: Responses): void {
  restGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/kyber/graph/platform')) {
      if (responses.platformError) return Promise.reject(responses.platformError);
      return Promise.resolve({ data: responses.platform ?? PLATFORM_COMPLETE });
    }
    if (path.startsWith('/v1/kyber/graph/fleet')) {
      return Promise.resolve({ data: responses.fleet ?? FLEET_COMPLETE });
    }
    if (path.startsWith('/v1/kyber/graph/cohorts/')) {
      return Promise.resolve({ data: responses.cohort ?? COHORT_SUPPRESSED });
    }
    if (path.startsWith('/v1/kyber/graph/tenants/')) {
      if (responses.tenantError) return Promise.reject(responses.tenantError);
      return Promise.resolve({ data: responses.tenant ?? TENANT_GRANTED });
    }
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });

  restPost.mockImplementation((path: string) => {
    if (path.startsWith('/v1/kyber/graph/blast-radius')) {
      return Promise.resolve({ data: responses.blast ?? BLAST_COMPLETE });
    }
    if (path.startsWith('/v1/kyber/graph/cohorts')) {
      return Promise.resolve({ data: responses.cohortDefine ?? COHORT_DEFINED });
    }
    return Promise.reject(new Error(`unexpected POST ${path}`));
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <KyberGraphPage />
    </MemoryRouter>,
  );
}

async function openTab(name: string): Promise<void> {
  await userEvent.click(screen.getByRole('tab', { name }));
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  // The loading test parks a promise that never settles; leaving it in `inFlight` would
  // make every later test await it forever.
  cache.inFlight.clear();
  restGet.mockReset();
  restPost.mockReset();
});

// ── Surface ──────────────────────────────────────────────────────────────────

describe('KyberGraphPage — surface', () => {
  it('renders every graph surface as its own tab, lowest disclosure first', async () => {
    mockApi({});
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Platform topology (D0)')).toBeInTheDocument(),
    );
    for (const tab of ['Platform', 'Fleet', 'Cohorts', 'Blast radius', 'Tenant scope']) {
      expect(screen.getByRole('tab', { name: tab })).toBeInTheDocument();
    }
  });

  it('shows a loading state before the topology resolves', () => {
    restGet.mockImplementation(() => new Promise(() => undefined));
    restPost.mockImplementation(() => new Promise(() => undefined));
    const { container } = renderPage();
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0);
  });

  it('shows the error state when a surface fails for a non-authorization reason', async () => {
    mockApi({ platformError: new Error('graph store unreachable') });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load platform topology')).toBeInTheDocument(),
    );
    expect(screen.getByText('graph store unreachable')).toBeInTheDocument();
  });
});

// ── 1. Platform topology ─────────────────────────────────────────────────────

describe('KyberGraphPage — platform topology', () => {
  it('renders unknown and no_data distinctly from healthy', async () => {
    mockApi({});
    renderPage();

    await waitFor(() => expect(screen.getByText('identity-worker')).toBeInTheDocument());

    const healthyRow = screen.getByText('identity-worker').closest('tr') as HTMLElement;
    expect(within(healthyRow).getByText('healthy')).toBeInTheDocument();

    const unknownRow = screen.getByText('2026.07.1').closest('tr') as HTMLElement;
    expect(within(unknownRow).getByText('unknown')).toBeInTheDocument();
    expect(within(unknownRow).queryByText('healthy')).not.toBeInTheDocument();

    const noDataRow = screen.getByText('2026.07.2').closest('tr') as HTMLElement;
    expect(within(noDataRow).getByText('no data')).toBeInTheDocument();
    expect(within(noDataRow).queryByText('healthy')).not.toBeInTheDocument();
    expect(within(noDataRow).queryByText('unknown')).not.toBeInTheDocument();
  });

  it('renders the node total only when the topology read was complete', async () => {
    mockApi({});
    renderPage();

    const tile = await waitFor(
      () => screen.getByText('Platform nodes').parentElement as HTMLElement,
    );
    expect(within(tile).getByText('4')).toBeInTheDocument();
    expect(screen.getByText(/Complete read/)).toBeInTheDocument();
  });

  it('refuses to show a platform total when totals_known is false', async () => {
    mockApi({ platform: PLATFORM_PARTIAL });
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText(/Partial read — platform topology totals are Unknown, not zero/),
      ).toBeInTheDocument(),
    );

    const totals = screen.getByTestId('platform-totals');
    expect(within(totals).getAllByText('Unknown').length).toBe(2);
    expect(within(totals).queryByText('0')).not.toBeInTheDocument();
    expect(within(totals).queryByText('4')).not.toBeInTheDocument();
  });
});

// ── 2. Fleet ─────────────────────────────────────────────────────────────────

describe('KyberGraphPage — fleet', () => {
  it('shows the fleet total when the read was complete', async () => {
    mockApi({});
    renderPage();
    await openTab('Fleet');

    await waitFor(() => expect(screen.getByText('graph_health')).toBeInTheDocument());
    const totals = screen.getByTestId('fleet-totals');
    expect(within(totals).getByText('12')).toBeInTheDocument();
    expect(within(totals).queryByText('Unknown')).not.toBeInTheDocument();
  });

  it('shows the partial banner and NO numeric total when totals_known is false', async () => {
    mockApi({ fleet: FLEET_PARTIAL });
    renderPage();
    await openTab('Fleet');

    await waitFor(() =>
      expect(
        screen.getByText(/Partial read — fleet totals are Unknown, not zero/),
      ).toBeInTheDocument(),
    );
    // The reason travels with the Unknown.
    expect(screen.getAllByText(/scan truncated/).length).toBeGreaterThan(0);
    expect(screen.getByText(/their sum is not a total/i)).toBeInTheDocument();

    // Positively Unknown, and negatively: no total at all — not the 7 the backend
    // still returned, and not a 0 either.
    const totals = screen.getByTestId('fleet-totals');
    expect(within(totals).getAllByText('Unknown').length).toBe(2);
    expect(within(totals).queryByText('0')).not.toBeInTheDocument();
    expect(within(totals).queryByText('7')).not.toBeInTheDocument();
    expect(within(totals).queryByText('1')).not.toBeInTheDocument();
  });

  it('marks a stale projection row stale and never lets it read as current health', async () => {
    mockApi({ fleet: FLEET_STALE });
    renderPage();
    await openTab('Fleet');

    const row = await waitFor(() => screen.getByTestId('fleet-row-ingestion_lag'));

    // The row says stale, in its own cell...
    expect(within(row).getByText('Stale — not current')).toBeInTheDocument();
    expect(within(row).queryByText('Current')).not.toBeInTheDocument();
    // ...and the state badge is re-labelled, so a stale `healthy` cannot read as healthy.
    expect(within(row).getByText('healthy · stale')).toBeInTheDocument();
    expect(within(row).queryByText('healthy')).not.toBeInTheDocument();

    // The section-level notice spells out why that matters.
    expect(screen.getByText('Stale — this is not a current answer')).toBeInTheDocument();
    expect(screen.getByText(/converts .we do not know. into .it is fine./)).toBeInTheDocument();
  });
});

// ── 3. Cohorts ───────────────────────────────────────────────────────────────

describe('KyberGraphPage — cohorts', () => {
  it('shows the suppression reason instead of an empty table', async () => {
    mockApi({ cohort: COHORT_SUPPRESSED });
    renderPage();
    await openTab('Cohorts');

    await userEvent.type(screen.getByPlaceholderText('kco_0001'), 'kco_0001');
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }));

    await waitFor(() =>
      expect(
        screen.getByText('Cohort suppressed — this is not an empty cohort'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText('below_minimum_cohort_size')).toBeInTheDocument();
    expect(screen.getByText(/never as .no tenant matched./)).toBeInTheDocument();

    // A suppressed cohort has no member count, and none is invented.
    expect(screen.queryByText('Members')).not.toBeInTheDocument();
    expect(screen.queryByTestId('cohort-totals')).not.toBeInTheDocument();
  });

  it('renders a resolved cohort with its members and totals', async () => {
    mockApi({ cohort: COHORT_RESOLVED });
    renderPage();
    await openTab('Cohorts');

    await userEvent.type(screen.getByPlaceholderText('kco_0001'), 'kco_0001');
    await userEvent.click(screen.getByRole('button', { name: 'Evaluate' }));

    await waitFor(() => expect(screen.getByTestId('cohort-totals')).toBeInTheDocument());
    const totals = screen.getByTestId('cohort-totals');
    expect(within(totals).getAllByText('5').length).toBe(2);
    expect(screen.getByText('tenant_003')).toBeInTheDocument();
    expect(
      screen.queryByText('Cohort suppressed — this is not an empty cohort'),
    ).not.toBeInTheDocument();
  });

  it('defines a cohort with the minimum size the operator asked for', async () => {
    mockApi({});
    renderPage();
    await openTab('Cohorts');

    await userEvent.type(screen.getByPlaceholderText('degraded-eu-west'), 'eu-degraded');
    await userEvent.type(screen.getByPlaceholderText('graph_health'), 'graph_health');
    await userEvent.click(screen.getByRole('button', { name: 'Define cohort' }));

    await waitFor(() =>
      expect(
        restPost.mock.calls.some(
          ([path, , body]) =>
            path === '/v1/kyber/graph/cohorts' &&
            (body as { name?: string; minimum_size?: number }).name === 'eu-degraded' &&
            (body as { minimum_size?: number }).minimum_size === 3,
        ),
      ).toBe(true),
    );
  });
});

// ── 4. Blast radius ──────────────────────────────────────────────────────────

describe('KyberGraphPage — blast radius', () => {
  it('renders unknown exposure as Unknown with reasons, never as a reach count', async () => {
    mockApi({ blast: BLAST_UNKNOWN });
    renderPage();
    await openTab('Blast radius');

    await userEvent.type(screen.getByPlaceholderText('identity-worker'), 'ghost-service');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() =>
      expect(
        screen.getByText(/Partial read — exposure totals are Unknown, not zero/),
      ).toBeInTheDocument(),
    );

    const totals = screen.getByTestId('blast-totals');
    expect(within(totals).getAllByText('Unknown').length).toBe(4);
    // The empty affected_* lists must NOT become "0 services reached".
    expect(within(totals).queryByText('0')).not.toBeInTheDocument();
    expect(within(totals).getAllByText(/kyber graph node/).length).toBeGreaterThan(0);

    expect(
      screen.getByText(/this is not evidence of a safe change/),
    ).toBeInTheDocument();
  });

  it('says the traversal was bounded and shows the reduced confidence', async () => {
    mockApi({ blast: BLAST_TRUNCATED });
    renderPage();
    await openTab('Blast radius');

    await userEvent.type(screen.getByPlaceholderText('identity-worker'), 'identity-worker');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() =>
      expect(
        screen.getByText(
          'Traversal was bounded — this reach is a lower bound, not the reach',
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/lowered its confidence to 0\.45/)).toBeInTheDocument();
    expect(
      screen.getByText(/a lower bound on the reach, never all of it/),
    ).toBeInTheDocument();
    // A bounded walk is never presented as complete.
    expect(screen.queryByText(/Complete read/)).not.toBeInTheDocument();
  });

  it('reports a complete review as complete, with its counts', async () => {
    mockApi({ blast: BLAST_COMPLETE });
    renderPage();
    await openTab('Blast radius');

    await userEvent.type(screen.getByPlaceholderText('identity-worker'), 'identity-worker');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() => expect(screen.getByText(/Complete read/)).toBeInTheDocument());
    const totals = screen.getByTestId('blast-totals');
    expect(within(totals).getAllByText('1').length).toBe(2);
    expect(within(totals).getAllByText('0').length).toBe(2);
    expect(
      screen.queryByText(
        'Traversal was bounded — this reach is a lower bound, not the reach',
      ),
    ).not.toBeInTheDocument();
  });
});

// ── 5. One scoped tenant (D3) ────────────────────────────────────────────────

describe('KyberGraphPage — scoped tenant read', () => {
  it('renders a 403 as "requires an active tenant scope", not a generic failure', async () => {
    mockApi({
      tenantError: forbidden(
        'No active tenant access scope for this session',
        'scope_missing',
      ),
    });
    renderPage();
    await openTab('Tenant scope');

    await userEvent.type(screen.getByPlaceholderText('tenant_001'), 'tenant_001');
    await userEvent.click(screen.getByRole('button', { name: 'Read scoped graph' }));

    await waitFor(() =>
      expect(screen.getByText('Requires an active tenant scope')).toBeInTheDocument(),
    );
    // The backend's own reason, and the gate step that refused.
    expect(
      screen.getByText(/No active tenant access scope for this session/),
    ).toBeInTheDocument();
    expect(screen.getByText(/denial_reason: scope_missing/)).toBeInTheDocument();
    expect(screen.getByText(/request a scope, then retry/)).toBeInTheDocument();

    // Not a generic error, and not an empty tenant.
    expect(
      screen.queryByText('Unable to read the scoped tenant graph'),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('No vertices on this page')).not.toBeInTheDocument();
  });

  it('renders the scoped page when the scope is live', async () => {
    mockApi({});
    renderPage();
    await openTab('Tenant scope');

    await userEvent.type(screen.getByPlaceholderText('tenant_001'), 'tenant_001');
    await userEvent.click(screen.getByRole('button', { name: 'Read scoped graph' }));

    await waitFor(() => expect(screen.getByText('v_1')).toBeInTheDocument());
    expect(screen.getByText('D3_TENANT_VISIBLE')).toBeInTheDocument();
    expect(screen.queryByText('Requires an active tenant scope')).not.toBeInTheDocument();
  });
});
