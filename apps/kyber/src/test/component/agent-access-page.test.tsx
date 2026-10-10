/**
 * Kyber — Agent Access Intelligence operator page.
 *
 * The load-bearing tests here are the honesty ones: a `null` count must render as
 * "Unknown" with the reason it could not be computed and must NEVER render as `0`, and a
 * truncated aggregate must be labelled partial rather than shown as a total. An operator
 * reading "0 unauthorized capabilities" when the truth is "we could not read the
 * authorizations" closes the investigation — so the null cases are asserted both
 * positively (Unknown + reason is on screen) and negatively (no "0" anywhere in the
 * rendered counts).
 *
 * The real feature hooks run; only `restClient` is mocked, so the zod schemas are
 * exercised too — a schema that coerced null to 0 would fail these tests.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { AgentAccessPage } from '@kyber/pages/agent-access';

const restGet = vi.fn();

vi.mock('@kyber/lib/api', () => ({
  restClient: {
    get: (...args: unknown[]) => restGet(...args),
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

const AUTHORITY_COMPLETE = {
  scope: 'cross_tenant',
  totals_known: true,
  missing_inputs: [],
  counts_by_state: { active: 4, pending: 1, expired: 2, revoked: 3 },
  tenants: [
    {
      tenant_id: 'tenant_001',
      known: true,
      missing_inputs: [],
      counts_by_state: { active: 4, pending: 1, expired: 2, revoked: 3 },
      authorizations_scanned: 10,
      scan_limit: 2000,
    },
  ],
  tenant_discovery: { tenants_examined: 1, distinct_tenants_seen: 1, complete: true },
  summary: 'Across 1 tenant(s): 4 active, 1 pending, 2 expired, 3 revoked.',
};

const AUTHORITY_TRUNCATED = {
  scope: 'cross_tenant',
  totals_known: false,
  missing_inputs: ['capability_authorizations:scan_truncated:tenant_id=tenant_002'],
  counts_by_state: { active: null, pending: null, expired: null, revoked: null },
  tenants: [
    {
      tenant_id: 'tenant_001',
      known: true,
      missing_inputs: [],
      counts_by_state: { active: 4, pending: 1, expired: 2, revoked: 3 },
      authorizations_scanned: 10,
      scan_limit: 2000,
    },
    {
      tenant_id: 'tenant_002',
      known: false,
      missing_inputs: ['capability_authorizations:scan_truncated:tenant_id=tenant_002'],
      counts_by_state: { active: null, pending: null, expired: null, revoked: null },
      authorizations_scanned: 2000,
      scan_limit: 2000,
    },
  ],
  tenant_discovery: { tenants_examined: 2, distinct_tenants_seen: 2, complete: true },
  summary:
    'Cross-tenant authorization posture is UNKNOWN, not zero. Required input(s) absent: ' +
    'capability_authorizations:scan_truncated:tenant_id=tenant_002.',
};

const DRIFT_COMPLETE = {
  scope: 'cross_tenant',
  totals_known: true,
  missing_inputs: [],
  counts: { capabilities_examined: 9, declared: 5, drifted: 1, observed_only: 4 },
  findings: [
    {
      tenant_id: 'tenant_001',
      code: 'identity_drift',
      risk_level: 'high',
      summary: 'Declared identity for capability cap_abc no longer matches what was observed.',
      evidence: 'declared_digest=sha256:aaa observed_digest=sha256:bbb',
      capability_id: 'cap_abc',
      source: 'identity',
    },
  ],
  findings_scope: 'all_matching_findings',
  findings_page_limit: 50,
  tenants: [
    {
      tenant_id: 'tenant_001',
      known: true,
      missing_inputs: [],
      counts: { capabilities_examined: 9, declared: 5, drifted: 1, observed_only: 4 },
    },
  ],
  tenant_discovery: { tenants_examined: 1, distinct_tenants_seen: 1, complete: true },
  summary: '1 capability(ies) across 1 tenant(s) no longer match the identity declared.',
};

const DRIFT_TRUNCATED = {
  ...DRIFT_COMPLETE,
  totals_known: false,
  missing_inputs: ['capability_catalog:scan_truncated:tenant_id=tenant_001'],
  counts: {
    capabilities_examined: null,
    declared: null,
    drifted: null,
    observed_only: null,
  },
  findings_scope: 'evidence_only_incomplete_scan',
  tenants: [
    {
      tenant_id: 'tenant_001',
      known: false,
      missing_inputs: ['capability_catalog:scan_truncated:tenant_id=tenant_001'],
      counts: {
        capabilities_examined: null,
        declared: null,
        drifted: null,
        observed_only: null,
      },
    },
  ],
  summary: 'Cross-tenant identity drift is UNKNOWN, not zero.',
};

const BLAST_UNKNOWN = {
  tenant_id: 'tenant_001',
  subject: { kind: 'agent', id: 'ghost-agent' },
  exposure_known: false,
  missing_inputs: ['capability_installations:agent_id=ghost-agent'],
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
  summary:
    'Exposure for agent ghost-agent is UNKNOWN, not zero. Every count is null because it ' +
    'could not be computed — do not read this as no exposure.',
};

const BLAST_TRISTATE = {
  tenant_id: 'tenant_001',
  subject: { kind: 'agent', id: 'agent_001' },
  exposure_known: false,
  missing_inputs: ['capability_authorizations:scan_truncated'],
  basis: 'observed_only',
  counts: {
    servers_reachable: null,
    capabilities_exposed: null,
    capabilities_invoked: null,
    capabilities_authorized: null,
    capabilities_unauthorized: null,
  },
  servers: ['srv_payments'],
  capabilities: [
    {
      capability_id: 'cap_transfer',
      server_key: 'srv_payments',
      provider: 'acme',
      tool_name: 'transfer',
      latest_risk_level: 'high',
      basis: 'invoked',
      authorized: null,
    },
  ],
  summary: 'Exposure for agent agent_001 is UNKNOWN, not zero.',
};

const EMPTY_AUTHORITY = {
  ...AUTHORITY_COMPLETE,
  counts_by_state: {},
  tenants: [],
  tenant_discovery: { tenants_examined: 0, distinct_tenants_seen: 0, complete: true },
};

const EMPTY_DRIFT = {
  ...DRIFT_COMPLETE,
  counts: { capabilities_examined: 0, declared: 0, drifted: 0, observed_only: 0 },
  findings: [],
  tenants: [],
};

// ── Wiring ───────────────────────────────────────────────────────────────────

type Responses = {
  authority?: unknown;
  drift?: unknown;
  blast?: unknown;
  authorityError?: Error;
  driftError?: Error;
};

function mockApi(responses: Responses): void {
  restGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/kyber/capability-ops/authority')) {
      if (responses.authorityError) return Promise.reject(responses.authorityError);
      return Promise.resolve({ data: responses.authority ?? AUTHORITY_COMPLETE });
    }
    if (path.startsWith('/v1/kyber/capability-ops/drift')) {
      if (responses.driftError) return Promise.reject(responses.driftError);
      return Promise.resolve({ data: responses.drift ?? DRIFT_COMPLETE });
    }
    if (path.startsWith('/v1/kyber/capability-ops/blast-radius')) {
      return Promise.resolve({ data: responses.blast ?? BLAST_UNKNOWN });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentAccessPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  // The loading test parks a promise that never settles; leaving it in `inFlight` would
  // make every later test await it forever.
  cache.inFlight.clear();
  restGet.mockReset();
});

// ── Render / loading / error / empty ─────────────────────────────────────────

describe('AgentAccessPage — surface', () => {
  it('renders both cross-tenant aggregates by state and by level', async () => {
    mockApi({});
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Authorization posture (cross-tenant)')).toBeInTheDocument(),
    );
    expect(screen.getByText('Declared-vs-observed drift (cross-tenant)')).toBeInTheDocument();
    expect(screen.getByText('Blast-radius review (one tenant)')).toBeInTheDocument();

    // Counts are rendered per state/level — no invented composite score.
    expect(screen.getByText('Active authorizations')).toBeInTheDocument();
    expect(screen.getByText('Revoked authorizations')).toBeInTheDocument();
    expect(screen.getByText('Drifted')).toBeInTheDocument();
    expect(screen.getByText('Observed, never declared')).toBeInTheDocument();
    expect(screen.queryByText(/risk score/i)).not.toBeInTheDocument();

    // A complete read is labelled as such.
    expect(screen.getAllByText(/Complete read/).length).toBeGreaterThan(0);
    expect(screen.getByText('cap_abc')).toBeInTheDocument();
  });

  it('shows a loading state before the aggregates resolve', () => {
    restGet.mockImplementation(() => new Promise(() => undefined));
    const { container } = renderPage();
    expect(container.querySelectorAll('.animate-pulse, .aether-skeleton').length).toBeGreaterThan(0);
  });

  it('shows the error state when an aggregate fails', async () => {
    mockApi({ authorityError: new Error('operator gate closed') });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load authorization posture')).toBeInTheDocument(),
    );
    expect(screen.getByText('operator gate closed')).toBeInTheDocument();
  });

  it('shows empty states when nothing has been observed', async () => {
    mockApi({ authority: EMPTY_AUTHORITY, drift: EMPTY_DRIFT });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('No capability authorizations observed')).toBeInTheDocument(),
    );
    expect(screen.getByText('No declared capability has drifted')).toBeInTheDocument();
    // Blast radius has no query yet.
    expect(screen.getByText('Name a tenant and an agent to review')).toBeInTheDocument();
  });
});

// ── THE RULE: null is Unknown-with-reason, never 0 ───────────────────────────

describe('AgentAccessPage — null is never rendered as zero', () => {
  it('renders a null authorization count as Unknown with its reason, not 0', async () => {
    mockApi({ authority: AUTHORITY_TRUNCATED, drift: DRIFT_COMPLETE });
    renderPage();

    const activeTile = await waitFor(() => {
      const label = screen.getByText('Active authorizations');
      return label.parentElement as HTMLElement;
    });

    expect(within(activeTile).getByText('Unknown')).toBeInTheDocument();
    expect(within(activeTile).queryByText('0')).not.toBeInTheDocument();
    // The reason travels with the Unknown, so the operator knows what was not read.
    expect(
      within(activeTile).getByText(/capability authorizations/),
    ).toBeInTheDocument();
    expect(within(activeTile).getByText(/scan truncated/)).toBeInTheDocument();
  });

  it('labels a truncated aggregate partial and refuses to call it a total', async () => {
    mockApi({ authority: AUTHORITY_TRUNCATED, drift: DRIFT_COMPLETE });
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByText(/Partial read — authorization totals are Unknown, not zero/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/their sum is not a total/i)).toBeInTheDocument();

    // The readable tenant keeps its numbers, clearly marked Complete; the unreadable one
    // is marked Partial and shows Unknown rather than 0.
    const row = screen.getByText('tenant_002').closest('tr') as HTMLElement;
    expect(within(row).getByText('Partial')).toBeInTheDocument();
    expect(within(row).getAllByText('Unknown').length).toBe(4);
    expect(within(row).queryByText('0')).not.toBeInTheDocument();
  });

  it('renders null drift counts as Unknown and labels the findings as partial evidence', async () => {
    mockApi({ authority: AUTHORITY_COMPLETE, drift: DRIFT_TRUNCATED });
    renderPage();

    const driftedTile = await waitFor(() => {
      const label = screen.getByText('Drifted');
      return label.parentElement as HTMLElement;
    });
    expect(within(driftedTile).getByText('Unknown')).toBeInTheDocument();
    expect(within(driftedTile).queryByText('0')).not.toBeInTheDocument();

    expect(
      screen.getByText(/Partial read — drift totals are Unknown, not zero/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/evidence from an incomplete scan, not every drifted capability/),
    ).toBeInTheDocument();
  });

  it('renders unknown blast-radius exposure as Unknown, never as zero exposure', async () => {
    mockApi({ blast: BLAST_UNKNOWN });
    renderPage();

    await userEvent.type(screen.getByPlaceholderText('tenant_001'), 'tenant_001');
    await userEvent.type(screen.getByPlaceholderText('agent_001'), 'ghost-agent');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() =>
      expect(
        screen.getByText(/Partial read — exposure totals are Unknown, not zero/),
      ).toBeInTheDocument(),
    );

    const exposedTile = screen.getByText('Capabilities exposed').parentElement as HTMLElement;
    expect(within(exposedTile).getByText('Unknown')).toBeInTheDocument();
    expect(within(exposedTile).queryByText('0')).not.toBeInTheDocument();

    const unauthorizedTile = screen.getByText('Capabilities unauthorized')
      .parentElement as HTMLElement;
    expect(within(unauthorizedTile).getByText('Unknown')).toBeInTheDocument();
    expect(within(unauthorizedTile).queryByText('0')).not.toBeInTheDocument();
  });

  it('renders a null `authorized` as Unknown, never as "Not authorized"', async () => {
    mockApi({ blast: BLAST_TRISTATE });
    renderPage();

    await userEvent.type(screen.getByPlaceholderText('tenant_001'), 'tenant_001');
    await userEvent.type(screen.getByPlaceholderText('agent_001'), 'agent_001');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    const row = await waitFor(
      () => screen.getByText('cap_transfer').closest('tr') as HTMLElement,
    );
    expect(within(row).getByText('Unknown')).toBeInTheDocument();
    expect(within(row).queryByText('Not authorized')).not.toBeInTheDocument();
    expect(within(row).queryByText('Authorized')).not.toBeInTheDocument();
  });

  it('sends the tenant_id the operator named on the blast-radius request', async () => {
    mockApi({ blast: BLAST_UNKNOWN });
    renderPage();

    await userEvent.type(screen.getByPlaceholderText('tenant_001'), 'tenant_007');
    await userEvent.type(screen.getByPlaceholderText('agent_001'), 'agent_x');
    await userEvent.click(screen.getByRole('button', { name: 'Review' }));

    await waitFor(() =>
      expect(
        restGet.mock.calls.some(
          ([path]) =>
            typeof path === 'string' &&
            path.startsWith('/v1/kyber/capability-ops/blast-radius') &&
            path.includes('tenant_id=tenant_007') &&
            path.includes('agent_id=agent_x'),
        ),
      ).toBe(true),
    );
  });
});
