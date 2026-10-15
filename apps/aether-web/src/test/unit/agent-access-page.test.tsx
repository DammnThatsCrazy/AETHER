/**
 * Agent Access page — honesty coverage.
 *
 * The load-bearing assertions here are the two that protect the product's core
 * guarantee at the last mile:
 *   1. a `null` count renders as "Unknown" WITH its `missing_inputs` reason, and
 *      never as `0`, `—`, `None` or an empty cell;
 *   2. a response the backend flagged as partial (`truncated` / `sampled` /
 *      `counts.scope: "scanned_window_only"`) is labelled as partial next to the
 *      number, not presented as a total.
 *
 * Plus loading / error / genuinely-empty coverage, which must all read
 * distinctly from "unknown".
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { AgentAccessPage } from '@aether-app/pages/agent-access';

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('@aether-app/lib/api/rest/client', () => ({
  restClient: {
    get: mocks.get,
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

beforeAll(() => {
  // The shared queryCache tracks in-flight fetches with `promise.finally(...)`,
  // which leaks an unhandled rejection when a fetcher rejects even though the UI
  // handles the error. Patch it test-locally so the error-state test does not
  // trip vitest's unhandled-error detector.
  const cache = queryCache as unknown as { inFlight: Map<string, Promise<unknown>> };
  queryCache.setInFlight = function <T>(key: string, promise: Promise<T>): void {
    cache.inFlight.set(key, promise as Promise<unknown>);
    void promise.catch(() => undefined).finally(() => cache.inFlight.delete(key));
  };
});

interface ParseableSchema {
  readonly parse: (value: unknown) => unknown;
}

const envelope = (data: unknown) => ({
  data,
  status: 'success',
  timestamp: '2026-07-24T00:00:00Z',
});

/** Route the mocked REST client by path, and run the real zod schema over it. */
function serve(routes: Record<string, unknown>): void {
  mocks.get.mockImplementation(async (path: string, schema: ParseableSchema) => {
    const match = Object.keys(routes).find(prefix => path.startsWith(prefix));
    if (match === undefined) throw new Error(`unrouted path in test: ${path}`);
    return schema.parse(envelope(routes[match]));
  });
}

// ── Fixtures ─────────────────────────────────────────────────────────────────

const KNOWN_SUMMARY = {
  tenant_id: 'tenant-under-test',
  summary_known: true,
  missing_inputs: [],
  basis: 'observed_only',
  complete: true,
  counts: {
    nodes: 9,
    edges: 12,
    agents: 2,
    servers: 3,
    capabilities: 4,
    edges_connects_to: 3,
    edges_exposes: 4,
    edges_authorized_for: 5,
    authorizations_active: 1,
  },
  observed_any: true,
  summary: 'Observed totals, not a proof of total reach.',
};

const UNKNOWN_SUMMARY = {
  tenant_id: 'tenant-under-test',
  summary_known: false,
  missing_inputs: ['capability_installations:scan_truncated', 'capability_catalog:scan_truncated'],
  basis: 'observed_only',
  complete: false,
  counts: {
    nodes: null,
    edges: null,
    agents: null,
    servers: null,
    capabilities: null,
    edges_connects_to: null,
    edges_exposes: null,
    edges_authorized_for: null,
    authorizations_active: null,
  },
  observed_any: true,
  summary: 'Access graph totals for this tenant are UNKNOWN, not zero.',
};

const COMPLETE_FINDINGS = {
  items: [
    {
      code: 'credentials_in_server_url',
      risk_level: 'critical',
      summary: 'Credentials embedded in an observed server URL.',
      evidence: 'server_url=https://redacted@example.invalid',
      capability_id: 'cap_aaa',
      source: 'scan',
    },
  ],
  count: 1,
  limit: 100,
  offset: 0,
  filter: { code: null },
  counts: {
    total: 1,
    scope: 'all_matching_findings',
    by_risk_level: { critical: 1 },
    by_code: { credentials_in_server_url: 1 },
  },
  identity: {
    capabilities_examined: 4,
    declarations_read: 2,
    declarations_truncated: false,
    declaration_read_limit: 1000,
    declared: 2,
    drifted: 0,
    observed_only: 2,
    drift_detection_complete: true,
  },
  coverage: {
    capabilities_examined: 4,
    scan_limit: 1000,
    sampled: false,
    catalog_truncated: false,
    declarations_truncated: false,
    complete: true,
  },
};

const TRUNCATED_FINDINGS = {
  ...COMPLETE_FINDINGS,
  counts: { ...COMPLETE_FINDINGS.counts, total: 137, scope: 'scanned_window_only' },
  identity: { ...COMPLETE_FINDINGS.identity, declarations_truncated: true, drift_detection_complete: false },
  coverage: {
    capabilities_examined: 1000,
    scan_limit: 1000,
    sampled: true,
    catalog_truncated: true,
    declarations_truncated: true,
    complete: false,
  },
};

const PROFILE_INDEX = {
  items: [
    {
      agent_id: 'agent-alpha',
      servers_observed: 2,
      servers: ['mcp.example.invalid', 'tools.example.invalid'],
      providers_observed: ['acme'],
      capabilities_on_installations: 3,
      first_seen_at: '2026-06-01T00:00:00Z',
      last_seen_at: '2026-07-20T00:00:00Z',
      observations_recorded: 41,
    },
  ],
  count: 1,
  limit: 100,
  offset: 0,
  basis: 'observed_only',
  counts: { agents_observed: 1, scope: 'all_observed_agents' },
  scan_limit: 1000,
  truncated: false,
  complete: true,
  note: 'Agents with at least one OBSERVED installation.',
};

const KNOWN_PROFILE = {
  subject: { kind: 'agent', id: 'agent-alpha' },
  profile_known: true,
  missing_inputs: [],
  basis: 'observed_only',
  identity: {
    agent_id: 'agent-alpha',
    providers_observed: ['acme'],
    servers_observed: ['mcp.example.invalid'],
    installation_ids: ['inst_1'],
  },
  observation: {
    first_seen_at: '2026-06-01T00:00:00Z',
    last_seen_at: '2026-07-20T00:00:00Z',
    observations_recorded: 41,
    basis: 'bounded-window observation count',
  },
  counts: {
    servers_observed: 1,
    capabilities_reachable: 2,
    capabilities_invoked: 1,
    capabilities_authorized: 1,
    capabilities_unauthorized: 1,
    authorizations_active: 1,
    observations_recorded: 41,
  },
  reach: {
    servers: ['mcp.example.invalid'],
    capabilities: [
      {
        capability_id: 'cap_aaa',
        server_key: 'mcp.example.invalid',
        provider: 'acme',
        tool_name: 'read_file',
        capability_kind: 'mcp_tool',
        latest_risk_level: 'high',
        basis: 'invoked',
        authorized: true,
      },
      {
        capability_id: 'cap_bbb',
        server_key: 'mcp.example.invalid',
        provider: 'acme',
        tool_name: 'write_file',
        capability_kind: 'mcp_tool',
        latest_risk_level: null,
        basis: 'server_reachable',
        // Tri-state: the authorization read was unavailable for this one.
        authorized: null,
      },
    ],
  },
  authorization: {
    known: true,
    authorizations_active: 1,
    capabilities_authorized: 1,
    capabilities_unauthorized: 1,
    scan_limit: 2000,
  },
  risk: {
    known: true,
    by_latest_risk_level: { high: 1, unknown: 1 },
    note: 'There is deliberately no composite risk or trust score.',
  },
  graph: {
    neighborhood_known: true,
    missing_inputs: [],
    depth: 1,
    limit: 500,
    truncated: false,
    counts: { nodes: 4, edges: 3 },
    node_ids: [],
    node_ids_sampled: false,
  },
  summary: 'Observed reach over the servers this agent was seen connected to.',
};

const UNKNOWN_BLAST_RADIUS = {
  subject: { kind: 'agent', id: 'agent-alpha' },
  exposure_known: false,
  missing_inputs: ['capability_installations:agent_id=agent-alpha'],
  basis: 'observed_only',
  counts: {
    servers_reachable: null,
    capabilities_exposed: null,
    capabilities_invoked: null,
    capabilities_authorized: null,
    capabilities_unauthorized: null,
  },
  servers: [],
  capabilities: [],
  summary: 'Exposure for agent agent-alpha is UNKNOWN, not zero.',
};

const AUTHORIZATIONS = {
  items: [
    {
      authorization_id: 'auth_1',
      agent_id: 'agent-alpha',
      capability_id: 'cap_aaa',
      server_ref: null,
      state: 'active',
      starts_at: '2026-06-01T00:00:00Z',
      ends_at: null,
      revoked_at: null,
      created_at: '2026-06-01T00:00:00Z',
    },
  ],
  count: 1,
};

const CATALOG = {
  items: [
    {
      capability_id: 'cap_aaa',
      capability_kind: 'mcp_tool',
      provider: 'acme',
      server_name: 'mcp.example.invalid',
      server_url: null,
      tool_name: 'read_file',
      latest_risk_level: 'high',
      discovery_state: 'observed',
      first_seen_at: '2026-06-01T00:00:00Z',
      last_seen_at: '2026-07-20T00:00:00Z',
      observation_count: 12,
    },
    {
      capability_id: 'cap_bbb',
      capability_kind: 'mcp_tool',
      provider: 'acme',
      server_name: 'mcp.example.invalid',
      server_url: null,
      tool_name: 'write_file',
      // Never risk-assessed, and never observed a countable number of times.
      latest_risk_level: null,
      discovery_state: 'observed',
      first_seen_at: '2026-06-02T00:00:00Z',
      last_seen_at: '2026-07-19T00:00:00Z',
      observation_count: null,
    },
  ],
  count: 2,
};

const HAPPY_ROUTES: Record<string, unknown> = {
  '/v1/capability-catalog': CATALOG,
  '/v1/capability-graph/summary': KNOWN_SUMMARY,
  '/v1/capability-risk/findings': COMPLETE_FINDINGS,
  '/v1/capability-risk/blast-radius': UNKNOWN_BLAST_RADIUS,
  '/v1/capability-profiles/': KNOWN_PROFILE,
  '/v1/capability-profiles': PROFILE_INDEX,
  '/v1/capability-authorizations': AUTHORIZATIONS,
};

function renderPage() {
  return render(<MemoryRouter><AgentAccessPage /></MemoryRouter>);
}

/** The `<div>` wrapping one labelled count, so assertions are scoped to it. */
function stat(label: string): HTMLElement {
  return screen.getByTestId(`agent-access-stat-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`);
}

beforeEach(() => {
  // Reset BOTH cache maps. The loading-state test parks a promise that never
  // settles, and a leftover in-flight entry would keep the next test's page
  // stuck in loading forever.
  const cache = queryCache as unknown as {
    entries: Map<string, unknown>;
    inFlight: Map<string, unknown>;
  };
  cache.entries.clear();
  cache.inFlight.clear();
  mocks.get.mockReset();
  serve(HAPPY_ROUTES);
});

describe('Agent Access page', () => {
  it('renders the inventory, findings and authorizations for an observed tenant', async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Agent Access' })).toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(within(stat('agents-observed')).getByText('2')).toBeInTheDocument(),
    );
    expect(within(stat('capabilities-observed')).getByText('4')).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByText('Findings, highest risk first')).toBeInTheDocument(),
    );
    expect(screen.getByText('credentials_in_server_url')).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText('Capability authorizations')).toBeInTheDocument(),
    );

    // The catalog list is page-bounded and the API reports no total, so the page
    // says so instead of letting the row count read as an inventory size.
    await waitFor(() =>
      expect(screen.getByText('Observed capabilities')).toBeInTheDocument(),
    );
    expect(screen.getByText(/not the size of your inventory/i)).toBeInTheDocument();
    // A capability with no risk assessment and no observation count reads Unknown,
    // not "low" and not 0.
    const unknownCells = screen
      .getAllByText('Unknown')
      .filter(node => node.closest('[data-unknown="true"]') !== null);
    expect(unknownCells.length).toBeGreaterThanOrEqual(2);
  });

  it('renders a null count as Unknown WITH its reason, and never as 0', async () => {
    serve({ ...HAPPY_ROUTES, '/v1/capability-graph/summary': UNKNOWN_SUMMARY });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Access totals are UNKNOWN, not zero')).toBeInTheDocument(),
    );

    for (const label of [
      'agents-observed',
      'servers-observed',
      'capabilities-observed',
      'agent-to-capability-reach',
      'active-authorizations',
    ]) {
      const cell = stat(label);
      expect(within(cell).getByText('Unknown')).toBeInTheDocument();
      // The three ways a UI silently converts "we do not know" into a claim.
      expect(within(cell).queryByText('0')).toBeNull();
      expect(within(cell).queryByText('—')).toBeNull();
      expect(within(cell).queryByText('None')).toBeNull();
      // The reason must be visible to the user, not just in the payload.
      expect(within(cell).getByText(/Not computed/)).toBeInTheDocument();
    }

    // The specific missing inputs are surfaced verbatim, not paraphrased away.
    expect(
      screen.getAllByText(/capability_installations:scan_truncated/).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/capability_catalog:scan_truncated/).length).toBeGreaterThan(0);
  });

  it('labels a truncated/sampled findings response as partial rather than a total', async () => {
    serve({ ...HAPPY_ROUTES, '/v1/capability-risk/findings': TRUNCATED_FINDINGS });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('This scan did not cover everything')).toBeInTheDocument(),
    );

    // The number is still shown — with its caveat rendered next to it.
    const findingsStat = stat('findings');
    expect(within(findingsStat).getByText('137')).toBeInTheDocument();
    expect(within(findingsStat).getByText(/Partial — scanned window only/)).toBeInTheDocument();

    // Drift detection was incomplete, so the drift count carries its own caveat.
    expect(
      within(stat('drifted-capabilities')).getByText(/Partial — declaration read truncated/),
    ).toBeInTheDocument();

    expect(
      screen.getByText(/capability catalog scan hit its limit/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/declaration read hit its limit/i),
    ).toBeInTheDocument();
  });

  it('renders a genuinely empty tenant as empty, not as unknown', async () => {
    serve({
      ...HAPPY_ROUTES,
      '/v1/capability-graph/summary': {
        ...KNOWN_SUMMARY,
        observed_any: false,
        counts: Object.fromEntries(Object.keys(KNOWN_SUMMARY.counts).map(key => [key, 0])),
        summary: 'No capability observations have been recorded for this tenant.',
      },
    });
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('No capability access observed yet')).toBeInTheDocument(),
    );
    expect(screen.queryByText('Unknown')).toBeNull();
    expect(screen.queryByText(/UNKNOWN, not zero/)).toBeNull();
  });

  it('renders a loading state that is not an unknown state', () => {
    mocks.get.mockImplementation(() => new Promise(() => undefined));
    const { container } = renderPage();

    expect(container.querySelector('.animate-pulse, [class*="skeleton"]')).not.toBeNull();
    expect(screen.queryByText('Unknown')).toBeNull();
    expect(screen.queryByText('No capability access observed yet')).toBeNull();
  });

  it('renders an error state that is not an empty or unknown state', async () => {
    mocks.get.mockImplementation(async () => {
      throw new Error('upstream read failed');
    });
    renderPage();

    await waitFor(() => expect(screen.getByText('upstream read failed')).toBeInTheDocument());
    expect(screen.queryByText('No capability access observed yet')).toBeNull();
    expect(screen.queryByText('Unknown')).toBeNull();
  });

  it('renders tri-state authorization: null is Unknown, never a denial', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText('Observed agents')).toBeInTheDocument());
    await userEvent.selectOptions(
      screen.getByLabelText('Agent to inspect'),
      'agent-alpha',
    );

    await waitFor(() => expect(screen.getByText('Access profile')).toBeInTheDocument());

    // cap_aaa is authorized; cap_bbb's authorization could not be determined.
    const badges = (label: string): HTMLElement[] =>
      screen.queryAllByText(label).filter(node => node.classList.contains('ui-badge'));
    expect(badges('Authorized').length).toBe(1);
    // `authorized: null` must NEVER be styled or labelled as a denial.
    expect(badges('Not authorized')).toHaveLength(0);
    const unknownBadges = screen
      .getAllByText('Unknown')
      .filter(node => node.closest('[data-unknown="true"]') !== null);
    expect(unknownBadges.length).toBeGreaterThan(0);
    // The unknown authorization badge is neutral, not the danger tone used for denial.
    const denialToned = unknownBadges.filter(node => node.className.includes('danger'));
    expect(denialToned).toHaveLength(0);
  });

  it('renders an unknown blast radius as unknown exposure, not zero exposure', async () => {
    renderPage();

    await waitFor(() => expect(screen.getByText('Observed agents')).toBeInTheDocument());
    await userEvent.selectOptions(
      screen.getByLabelText('Agent to inspect'),
      'agent-alpha',
    );

    await waitFor(() =>
      expect(screen.getByText('Exposure is UNKNOWN, not zero')).toBeInTheDocument(),
    );
    for (const label of [
      'blast-servers-reachable',
      'blast-capabilities-exposed',
      'blast-capabilities-authorized',
      'blast-capabilities-unauthorized',
    ]) {
      const cell = stat(label);
      expect(within(cell).getByText('Unknown')).toBeInTheDocument();
      expect(within(cell).queryByText('0')).toBeNull();
    }
    // The reason travels with every unknown count, not only the section notice.
    expect(
      screen.getAllByText(/no observed agent-to-server installation/i).length,
    ).toBeGreaterThan(1);
  });
});
