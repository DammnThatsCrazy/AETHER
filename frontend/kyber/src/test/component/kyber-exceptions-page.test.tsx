/**
 * Kyber — Exceptions & incidents operator page.
 *
 * The load-bearing tests are the honesty ones, and each is asserted positively AND
 * negatively, because the failure mode is always the same shape: something the operator
 * cannot see reads as something that is not there.
 *
 *   · a ranking can be interrogated — the terms, weights and contributions that produced
 *     the score are on screen, and an exception the backend scored without recording its
 *     inputs says so instead of implying the order is self-evident;
 *   · a suppressed exception shows that it is a SUPPRESSION and shows its reason, and
 *     does not read as resolved;
 *   · a heuristic `correlation_basis` renders visibly differently from a deterministic
 *     one — the deterministic row must not carry the heuristic caveat and vice versa;
 *   · a resume card carries last action, next action, what is blocking and what is
 *     pending verification, and an incident with no next action says so;
 *   · a `null` timeline is Unknown — the heading must not say "(0)" and the page must
 *     not say "No signals attached", because an unread timeline presented as an empty
 *     one closes an investigation that was never actually looked at;
 *   · a term whose contribution the backend did not record is not ranked as a
 *     contribution of zero, and a scale the backend did not record is not invented.
 *
 * Only `restClient` is mocked, so the real feature hooks and the real zod schemas run:
 * a schema that dropped `priority_inputs` or coerced a null count to 0 would fail here.
 */

import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';
import { KyberExceptionsPage } from '@kyber/pages/kyber-exceptions';
import { makePrincipal, renderWithAuth } from '../kyber-auth-doubles';

const restGet = vi.fn();
const restPost = vi.fn();
const restPatch = vi.fn();

vi.mock('@kyber/lib/api', () => ({
  restClient: {
    get: (...args: unknown[]) => restGet(...args),
    post: (...args: unknown[]) => restPost(...args),
    patch: (...args: unknown[]) => restPatch(...args),
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

const OPERATOR_CAPABILITIES = [
  'kyber.incident.read',
  'kyber.incident.manage',
  'kyber.incident.close',
];

// ── Fixtures ─────────────────────────────────────────────────────────────────

const SCORED_EXCEPTION = {
  exception_id: 'kex_leak',
  title: 'Cross-tenant capability leak suspected',
  severity: 'critical',
  bucket: 'critical_now',
  status: 'open',
  confidence: 0.9,
  affected_tenants: ['tenant_001', 'tenant_002'],
  affected_features: [],
  affected_services: ['identity-worker'],
  customer_visible: true,
  security_exposure: true,
  financial_exposure: false,
  data_integrity_exposure: true,
  reversible: false,
  time_to_breach_seconds: 900,
  sla_impact: true,
  priority_score: 87.4211,
  priority_inputs: {
    terms: {
      security_exposure: { value: true, normalized: 1, weight: 3, contribution: 3 },
      tenant_reach: { value: 2, normalized: 0.63, weight: 2, contribution: 1.26 },
      volume: { value: 4, normalized: 0.4, weight: 0.5, contribution: 0.2 },
    },
    weights: { security_exposure: 3, tenant_reach: 2, volume: 0.5 },
    raw_subtotal: 4.46,
    max_raw_score: 12,
    confidence: 0.9,
    confidence_factor: 0.97,
    score: 87.4211,
    dominant_terms: ['security_exposure', 'tenant_reach', 'volume'],
    scale: '0-100',
    scored_at: '2026-07-25T00:00:00Z',
  },
  probable_cause: 'scoped gateway bypass on the identity worker',
  recommended_action: 'pause the identity worker and re-derive authorizations',
  incident_id: 'kin_checkout',
  signal_count: 4,
  first_seen_at: '2026-07-25T00:00:00Z',
  last_seen_at: '2026-07-25T00:05:00Z',
  metadata: {},
};

const UNEXPLAINED_EXCEPTION = {
  ...SCORED_EXCEPTION,
  exception_id: 'kex_unexplained',
  title: 'Connector backlog growing',
  severity: 'medium',
  bucket: 'needs_action',
  security_exposure: false,
  data_integrity_exposure: false,
  reversible: true,
  time_to_breach_seconds: null,
  priority_score: 41.2,
  // The backend scored it but recorded no inputs. The rank cannot be explained, and
  // pretending otherwise is what makes an operator stop questioning the ordering.
  priority_inputs: {},
  probable_cause: null,
  recommended_action: null,
  signal_count: null,
};

/**
 * The backend scored this one and recorded no contribution for `graph_reach`, and no
 * scale at all.
 *
 * Term insertion order matters here and is the whole point: `graph_reach` (unrecorded)
 * is declared BEFORE `volume` (a recorded contribution of exactly zero). Sorting with
 * `(contribution ?? 0)` ties the two and — sort being stable — leaves `graph_reach`
 * above `volume`, ranking an unrecorded value as a measured zero. Ordering unrecorded
 * terms as their own trailing group puts `volume` above `graph_reach` instead.
 */
const PARTLY_RECORDED_EXCEPTION = {
  ...SCORED_EXCEPTION,
  exception_id: 'kex_partial_inputs',
  title: 'Projector lag on the commerce domain',
  severity: 'medium',
  bucket: 'informational',
  security_exposure: false,
  data_integrity_exposure: false,
  reversible: true,
  time_to_breach_seconds: null,
  priority_score: 33.5,
  priority_inputs: {
    terms: {
      tenant_reach: { value: 2, normalized: 0.63, weight: 2, contribution: 1.26 },
      graph_reach: { value: null, normalized: null, weight: 2, contribution: null },
      volume: { value: 0, normalized: 0, weight: 0.5, contribution: 0 },
    },
    weights: { tenant_reach: 2, graph_reach: 2, volume: 0.5 },
    raw_subtotal: 1.26,
    max_raw_score: 12,
    confidence: null,
    confidence_factor: null,
    score: 33.5,
    dominant_terms: ['tenant_reach'],
    scale: null,
    scored_at: '2026-07-25T00:00:00Z',
  },
  metadata: {},
};

const SUPPRESSED_EXCEPTION = {
  ...SCORED_EXCEPTION,
  exception_id: 'kex_suppressed',
  title: 'Vendor webhook retry storm',
  severity: 'low',
  bucket: 'watch',
  status: 'suppressed',
  security_exposure: false,
  data_integrity_exposure: false,
  reversible: true,
  time_to_breach_seconds: null,
  priority_score: 12.5,
  metadata: {
    suppressed_by: 'op_test_001',
    suppressed_at: '2026-07-25T00:10:00Z',
    suppression_reason: 'known noisy vendor; tracked on SUP-4711 until they ship a fix',
  },
};

const QUEUE = {
  order: ['critical_now', 'needs_action', 'watch', 'informational'],
  buckets: {
    critical_now: [SCORED_EXCEPTION],
    needs_action: [UNEXPLAINED_EXCEPTION],
    watch: [SUPPRESSED_EXCEPTION],
    informational: [PARTLY_RECORDED_EXCEPTION],
  },
  items: [
    SCORED_EXCEPTION,
    UNEXPLAINED_EXCEPTION,
    SUPPRESSED_EXCEPTION,
    PARTLY_RECORDED_EXCEPTION,
  ],
  counts: { critical_now: 1, needs_action: 1, watch: 1, informational: 1 },
  total: 4,
  status_filter: 'open',
  generated_at: '2026-07-25T00:15:00Z',
};

const EMPTY_QUEUE = {
  ...QUEUE,
  buckets: { critical_now: [], needs_action: [], watch: [], informational: [] },
  items: [],
  counts: { critical_now: 0, needs_action: 0, watch: 0, informational: 0 },
  total: 0,
};

const INCIDENT = {
  incident_id: 'kin_checkout',
  title: 'checkout-api: 500 spike after rel_88',
  status: 'investigating',
  severity: 'high',
  priority_score: 72.5,
  root_cause: null,
  affected_tenants: ['tenant_001'],
  affected_features: [],
  affected_services: ['checkout-api'],
  release_id: 'rel_88',
  customer_visible: true,
  revenue_exposure: false,
  security_exposure: false,
  data_integrity_exposure: false,
  last_action: 'rolled rel_88 back in staging',
  next_action: 'confirm the error rate stays under 1% for fifteen minutes',
  blocked_by: 'waiting on the payment vendor to answer',
  pending_verification: ['checkout_error_rate', 'mirror_digest_parity'],
  signal_count: 2,
  opened_at: '2026-07-25T00:00:00Z',
  resolved_at: null,
  updated_at: '2026-07-25T00:12:00Z',
  metadata: {},
};

const RESUME_CARD = {
  incident_id: 'kin_checkout',
  title: 'checkout-api: 500 spike after rel_88',
  status: 'investigating',
  severity: 'high',
  priority_score: 72.5,
  last_action: 'rolled rel_88 back in staging',
  next_action: 'confirm the error rate stays under 1% for fifteen minutes',
  blocked_by: 'waiting on the payment vendor to answer',
  pending_verification: ['checkout_error_rate', 'mirror_digest_parity'],
  root_cause: null,
  signal_count: 2,
  affected_services: ['checkout-api'],
  affected_tenants: ['tenant_001'],
  opened_at: '2026-07-25T00:00:00Z',
  updated_at: '2026-07-25T00:12:00Z',
  missing_inputs: [],
};

const UNRESUMABLE_CARD = {
  ...RESUME_CARD,
  incident_id: 'kin_stalled',
  title: 'graph projector lag',
  last_action: null,
  next_action: null,
  blocked_by: null,
  pending_verification: [],
  missing_inputs: ['kyber_graph_store:unavailable'],
};

const DETERMINISTIC_SIGNAL = {
  signal_id: 'kis_release',
  incident_id: 'kin_checkout',
  tenant_id: 'tenant_001',
  source: 'deploy',
  signal_type: 'release_marker',
  error_signature: null,
  service: 'checkout-api',
  feature: null,
  release_id: 'rel_88',
  correlation_basis: 'release_id',
  correlation_confidence: 1,
  observed_at: '2026-07-25T00:01:00Z',
  payload: {},
};

const HEURISTIC_SIGNAL = {
  signal_id: 'kis_coincidence',
  incident_id: 'kin_checkout',
  tenant_id: 'tenant_001',
  source: 'ops_alerts',
  signal_type: 'latency_alert',
  error_signature: 'upstream timeout',
  service: 'search-api',
  feature: null,
  release_id: null,
  correlation_basis: 'time_proximity',
  correlation_confidence: 0.3,
  observed_at: '2026-07-25T00:02:00Z',
  payload: {},
};

const INCIDENT_DETAIL = {
  found: true,
  incident: INCIDENT,
  resume_card: RESUME_CARD,
  timeline: [DETERMINISTIC_SIGNAL, HEURISTIC_SIGNAL],
  correlations: [
    {
      signal_id: 'kis_coincidence',
      basis: 'time_proximity',
      confidence: 0.3,
      attached_at: '2026-07-25T00:02:00Z',
    },
  ],
  weak_links: [
    {
      incident_id: 'kin_other',
      basis: 'time_proximity',
      confidence: 0.3,
      note: 'temporal coincidence only — not merged',
    },
  ],
  commands: [],
  generated_at: '2026-07-25T00:15:00Z',
};

// ── Wiring ───────────────────────────────────────────────────────────────────

interface Responses {
  queue?: unknown;
  queueError?: Error;
  incidents?: unknown;
  incidentDetail?: unknown;
  resumeCards?: unknown;
}

function mockApi(responses: Responses = {}): void {
  restGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/kyber/ops/exceptions')) {
      if (responses.queueError) return Promise.reject(responses.queueError);
      return Promise.resolve({ data: responses.queue ?? QUEUE });
    }
    if (path.startsWith('/v1/kyber/ops/incidents/resume-cards')) {
      return Promise.resolve({
        data: responses.resumeCards ?? {
          cards: [RESUME_CARD, UNRESUMABLE_CARD],
          count: 2,
          generated_at: '2026-07-25T00:15:00Z',
        },
      });
    }
    if (path.startsWith('/v1/kyber/ops/incidents/')) {
      return Promise.resolve({ data: responses.incidentDetail ?? INCIDENT_DETAIL });
    }
    if (path.startsWith('/v1/kyber/ops/incidents')) {
      return Promise.resolve({
        data: responses.incidents ?? {
          incidents: [INCIDENT],
          count: 1,
          status_filter: 'open',
          generated_at: '2026-07-25T00:15:00Z',
        },
      });
    }
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

function renderPage(capabilities: readonly string[] = OPERATOR_CAPABILITIES) {
  return renderWithAuth(<KyberExceptionsPage />, {
    principal: makePrincipal({
      capabilities: [...capabilities],
      max_action_class: 5,
      max_disclosure: 4,
    }),
  });
}

beforeEach(() => {
  queryCache.invalidatePrefix('');
  cache.inFlight.clear();
  restGet.mockReset();
  restPost.mockReset();
  restPatch.mockReset();
});

// ── Surface ──────────────────────────────────────────────────────────────────

describe('KyberExceptionsPage — surface', () => {
  it('renders the queue in bucket order with each bucket count', async () => {
    mockApi();
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Cross-tenant capability leak suspected')).toBeInTheDocument(),
    );
    expect(screen.getByText('Critical now')).toBeInTheDocument();
    expect(screen.getByText('Needs action')).toBeInTheDocument();
    expect(screen.getByText('Watch')).toBeInTheDocument();
    expect(screen.getByText('Informational')).toBeInTheDocument();
    expect(screen.getByText('Connector backlog growing')).toBeInTheDocument();
  });

  it('shows a loading state before the queue resolves', () => {
    restGet.mockImplementation(() => new Promise(() => undefined));
    const { container } = renderPage();
    expect(container.querySelectorAll('.animate-pulse, .aether-skeleton').length).toBeGreaterThan(0);
  });

  it('shows the error state with the backend reason when the queue fails', async () => {
    mockApi({ queueError: new Error('Requested disclosure exceeds the effective ceiling') });
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load the exception queue')).toBeInTheDocument(),
    );
    expect(
      screen.getByText('Requested disclosure exceeds the effective ceiling'),
    ).toBeInTheDocument();
  });

  it('says an empty queue is an answer about the filter, not about the platform', async () => {
    mockApi({ queue: EMPTY_QUEUE });
    renderPage();
    await waitFor(() => expect(screen.getByText('Nothing in this queue')).toBeInTheDocument());
    expect(
      screen.getByText(/an answer about this filter, not about the platform/i),
    ).toBeInTheDocument();
  });
});

// ── A ranking must be interrogable ───────────────────────────────────────────

describe('KyberExceptionsPage — the rank can be interrogated', () => {
  it('shows the terms, weights and contributions that produced the score', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() => screen.getByRole('group', { name: 'Exception kex_leak' }));
    await userEvent.click(within(row).getByRole('button', { name: 'Why this rank' }));

    expect(within(row).getByText('Why this ranks here')).toBeInTheDocument();
    expect(within(row).getByText('Security exposure')).toBeInTheDocument();
    expect(within(row).getByText('Tenant reach')).toBeInTheDocument();
    expect(
      within(row).getByText(/Dominant terms: Security exposure, Tenant reach, Volume/),
    ).toBeInTheDocument();
    // The arithmetic, not just the answer.
    expect(within(row).getByText('4.46')).toBeInTheDocument();
    expect(within(row).getByText('0.97')).toBeInTheDocument();
    // Bucket floors are part of the explanation: a floor can lift a row above the
    // bucket its score alone would have earned.
    expect(
      within(row).getByText(/cross-tenant leak signature, which is always Critical now/),
    ).toBeInTheDocument();
  });

  it('says a rank cannot be explained when the backend recorded no inputs', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_unexplained' }),
    );
    await userEvent.click(within(row).getByRole('button', { name: 'Why this rank' }));

    expect(
      within(row).getByText(/No priority inputs were recorded for this exception/),
    ).toBeInTheDocument();
    expect(within(row).getByText(/unexplained, not as agreed/)).toBeInTheDocument();
    // Negative: no term table is invented to fill the gap.
    expect(within(row).queryByText('Contribution')).not.toBeInTheDocument();
    expect(within(row).queryByText('Security exposure')).not.toBeInTheDocument();
  });

  it('does not rank a term whose contribution was never recorded as a zero one', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_partial_inputs' }),
    );
    await userEvent.click(within(row).getByRole('button', { name: 'Why this rank' }));

    // Positive: the unrecorded contribution is Unknown in its own cell, and the table
    // says why that term sits where it does.
    const rows = within(row).getAllByRole('row');
    const cells = within(rows[rows.length - 1] as HTMLElement).getAllByRole('cell');
    expect(cells[0]?.textContent).toBe('Graph reach');
    expect(cells[cells.length - 1]?.textContent).toBe('Unknown');
    expect(
      within(row).getByText(/The backend recorded no contribution for Graph reach/),
    ).toBeInTheDocument();
    expect(
      within(row).getByText(/not because it was measured as nothing/),
    ).toBeInTheDocument();

    // Negative: the term with a genuinely measured contribution of zero outranks the
    // unrecorded one. `(contribution ?? 0)` ties them and leaves Graph reach above
    // Volume, which is an unrecorded value ordered as if it had been measured.
    const volumeIndex = rows.findIndex(entry =>
      (entry.textContent ?? '').startsWith('Volume'),
    );
    const graphIndex = rows.findIndex(entry =>
      (entry.textContent ?? '').startsWith('Graph reach'),
    );
    expect(volumeIndex).toBeGreaterThan(0);
    expect(graphIndex).toBeGreaterThan(volumeIndex);
  });

  it('does not invent a scale the backend never recorded', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_partial_inputs' }),
    );
    await userEvent.click(within(row).getByRole('button', { name: 'Why this rank' }));

    // Positive: the score is shown with the fact that it has no recorded bound.
    expect(
      within(row).getByText(/on a scale the backend did not record/),
    ).toBeInTheDocument();

    // Negative: no `0-100` anywhere in this row. No backend field supports that bound,
    // and printing it turns an unlabelled number into a percentage in the reader's head.
    expect(row.textContent ?? '').not.toContain('0-100');
  });

  it('renders a null signal count as Unknown rather than zero', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_unexplained' }),
    );
    expect(within(row).getByText('Unknown')).toBeInTheDocument();
    expect(within(row).queryByText('0')).not.toBeInTheDocument();
  });
});

// ── A suppression must announce itself ───────────────────────────────────────

describe('KyberExceptionsPage — suppression states itself and its reason', () => {
  it('shows that the exception was suppressed and why', async () => {
    mockApi();
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_suppressed' }),
    );
    expect(within(row).getByText('Suppressed — silenced, not fixed')).toBeInTheDocument();
    expect(
      within(row).getByText(
        /known noisy vendor; tracked on SUP-4711 until they ship a fix/,
      ),
    ).toBeInTheDocument();
    // Negative: a suppression is not a resolution and must not read as one.
    expect(within(row).queryByText('Resolved')).not.toBeInTheDocument();
  });

  it('flags a suppression that carries no recorded reason', async () => {
    mockApi({
      queue: {
        ...QUEUE,
        buckets: {
          ...QUEUE.buckets,
          watch: [{ ...SUPPRESSED_EXCEPTION, metadata: { suppressed_by: 'op_test_001' } }],
        },
        items: [{ ...SUPPRESSED_EXCEPTION, metadata: { suppressed_by: 'op_test_001' } }],
      },
    });
    renderPage();

    const row = await waitFor(() =>
      screen.getByRole('group', { name: 'Exception kex_suppressed' }),
    );
    expect(
      within(row).getByText(/No suppression reason was recorded/),
    ).toBeInTheDocument();
    expect(
      within(row).getByText(/indistinguishable from an exception that never fired/),
    ).toBeInTheDocument();
  });

  it('requires a reason before it will suppress, and sends the reason it was given', async () => {
    mockApi();
    restPost.mockResolvedValue({
      data: { exception: { ...SCORED_EXCEPTION, status: 'suppressed' } },
    });
    renderPage();

    const row = await waitFor(() => screen.getByRole('group', { name: 'Exception kex_leak' }));
    await userEvent.click(within(row).getByRole('button', { name: 'Suppress' }));

    expect(
      within(row).getByText('Suppressing hides this exception without fixing it'),
    ).toBeInTheDocument();
    const confirm = within(row).getByRole('button', { name: 'Confirm suppression' });
    expect(confirm).toBeDisabled();

    await userEvent.type(
      within(row).getByPlaceholderText('why this is safe to silence'),
      'duplicate of kex_suppressed',
    );
    await userEvent.click(within(row).getByRole('button', { name: 'Confirm suppression' }));

    await waitFor(() =>
      expect(
        restPost.mock.calls.some(
          ([path, , body]) =>
            path === '/v1/kyber/ops/exceptions/kex_leak/suppress' &&
            (body as { reason?: string })?.reason === 'duplicate of kex_suppressed',
        ),
      ).toBe(true),
    );
  });

  it('hides the close controls when the principal does not hold the capability', async () => {
    mockApi();
    renderPage(['kyber.incident.read']);

    await waitFor(() =>
      expect(screen.getByText('Cross-tenant capability leak suspected')).toBeInTheDocument(),
    );
    expect(screen.queryByRole('button', { name: 'Suppress' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resolve' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument();
  });
});

// ── A guess must look like a guess ───────────────────────────────────────────

describe('KyberExceptionsPage — deterministic and heuristic correlations differ', () => {
  it('marks a release-id correlation deterministic and a time-proximity one a guess', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' }));
    await userEvent.click(
      await screen.findByText('checkout-api: 500 spike after rel_88'),
    );

    const deterministic = await waitFor(() =>
      screen.getByRole('group', { name: 'Signal kis_release' }),
    );
    const heuristic = screen.getByRole('group', { name: 'Signal kis_coincidence' });

    // Positive: each row is labelled for what it is.
    const deterministicBadge = within(deterministic).getByText('Deterministic');
    expect(deterministicBadge).toBeInTheDocument();
    expect(
      within(deterministic).getByText(/not on inference/),
    ).toBeInTheDocument();

    const heuristicBadge = within(heuristic).getByText('Heuristic');
    expect(heuristicBadge).toBeInTheDocument();
    expect(
      within(heuristic).getByText(/Inferred\. This attribution is a guess and may be wrong\./),
    ).toBeInTheDocument();

    // Negative: neither row carries the other's label, and the two do not share a
    // treatment — a guess drawn like evidence is the whole failure mode.
    expect(within(deterministic).queryByText('Heuristic')).not.toBeInTheDocument();
    expect(within(heuristic).queryByText('Deterministic')).not.toBeInTheDocument();
    expect(deterministicBadge.className).toContain('text-success');
    expect(deterministicBadge.className).not.toContain('text-warning');
    expect(heuristicBadge.className).toContain('text-warning');
    expect(heuristicBadge.className).not.toContain('text-success');
  });

  it('renders a null timeline as Unknown, never as an incident with no signals', async () => {
    mockApi({ incidentDetail: { ...INCIDENT_DETAIL, timeline: null } });
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' }));
    await userEvent.click(
      await screen.findByText('checkout-api: 500 spike after rel_88'),
    );

    // Positive: the heading counts nothing it did not read, and the reason is on screen.
    const heading = await screen.findByRole('heading', { name: /Attached signals/ });
    expect(heading.textContent).toBe('Attached signals (Unknown)');
    expect(
      screen.getByText(/Timeline Unknown — no signal list came back with this incident/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/That is not\s+the same as none being attached/),
    ).toBeInTheDocument();

    // Negative: neither of the two readings that say "there is nothing here".
    expect(heading.textContent ?? '').not.toContain('(0)');
    expect(
      screen.queryByText('No signals attached to this incident'),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: /^Signal / })).not.toBeInTheDocument();
  });

  it('still says no signals are attached when the timeline was read and was empty', async () => {
    mockApi({ incidentDetail: { ...INCIDENT_DETAIL, timeline: [] } });
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' }));
    await userEvent.click(
      await screen.findByText('checkout-api: 500 spike after rel_88'),
    );

    // A read-and-empty timeline is a measured zero and must keep saying so — the fix
    // above must not turn every empty list into an Unknown.
    const heading = await screen.findByRole('heading', { name: /Attached signals/ });
    expect(heading.textContent).toBe('Attached signals (0)');
    expect(
      screen.getByText('No signals attached to this incident'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Timeline Unknown/)).not.toBeInTheDocument();
  });

  it('shows declined weak links as coincidences that were not merged', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Incidents' }));
    await userEvent.click(
      await screen.findByText('checkout-api: 500 spike after rel_88'),
    );

    expect(
      await screen.findByText('Weak links — declined, not merged'),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Time proximity is not\s+evidence of a shared cause/),
    ).toBeInTheDocument();
  });
});

// ── Resume cards ─────────────────────────────────────────────────────────────

describe('KyberExceptionsPage — resume cards', () => {
  it('carries last action, next action, what blocks and what is pending verification', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Resume cards' }));

    const card = await waitFor(() =>
      screen.getByRole('group', { name: 'Resume card kin_checkout' }),
    );
    expect(
      within(card).getByText(/Last action: rolled rel_88 back in staging/),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(
        /Next action: confirm the error rate stays under 1% for fifteen minutes/,
      ),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(/Blocked by: waiting on the payment vendor to answer/),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(
        /Pending verification: checkout_error_rate, mirror_digest_parity/,
      ),
    ).toBeInTheDocument();
  });

  it('says an incident with no next action cannot be resumed as written', async () => {
    mockApi();
    renderPage();

    await userEvent.click(await screen.findByRole('tab', { name: 'Resume cards' }));

    const card = await waitFor(() =>
      screen.getByRole('group', { name: 'Resume card kin_stalled' }),
    );
    expect(
      within(card).getByText(/none recorded — this incident cannot be resumed as written/),
    ).toBeInTheDocument();
    expect(
      within(card).getByText(/Missing inputs: kyber_graph_store:unavailable/),
    ).toBeInTheDocument();
  });
});
