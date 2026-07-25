import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { SemanticReviewQueuePage } from '@kyber/pages/semantic';

// Pin the runtime to the explicit live local environment so requests hit the
// absolute base URL that the MSW server intercepts. (vi.hoisted: the vi.mock factories below are
// hoisted above ordinary top-level consts.)
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

// Backend-shaped principal: capabilities and ceilings come from the server,
// never from a decoded token.
const authState = vi.hoisted(() => ({
  capabilities: [
    'kyber.approvals.decide',
    'kyber.controller.intervene',
    'kyber.command.dispatch',
    'kyber.diagnostics.run',
    'kyber.diagnostics.read',
    'kyber.action.revert',
    'kyber.notes.write',
    'kyber.export.create',
  ] as string[],
}));

vi.mock('@kyber/features/auth', () => ({
  useAuth: () => ({
    status: 'authenticated' as const,
    isAuthenticated: true,
    isLoading: false,
    error: null,
    session: null,
    lastSyncedAt: Date.now(),
    principal: {
      operator_id: 'op_001',
      email: 'operator@aether.dev',
      display_name: 'Operator',
      employment_status: 'active',
      environment: 'local',
      session_id: 'sess_001',
      session_status: 'active',
      authentication_strength: 'device_bound',
      device_id: 'dev_001',
      device_approval_state: 'approved',
      role_template_ids: ['kyber.role.engineering'],
      capabilities: authState.capabilities,
      max_disclosure: 5,
      max_action_class: 5,
      presence_expires_at: null,
      authority_expires_at: null,
      idle_expires_at: null,
      step_up_expires_at: null,
      active_scope: null,
      may_approve_devices: true,
    },
    login: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const FLEET_HEALTH_FIXTURE = {
  enabled_tenants: 4,
  classified_observations: 1287,
  sentiment_observations: 356,
  abstention_rate: 0.125,
  quarantined_observations: 9,
  consent_restricted_observations: 3,
  model_versions: [
    'deterministic-semantic-classifier@1.0.0',
    'deterministic-sentiment-classifier@1.0.0',
  ],
  status_breakdown: { classified: 1121, abstained: 154, quarantined: 9, consent_restricted: 3 },
  // Hardcoded backend placeholders (semantic routes overwrite these with 0/0/false).
  queue_lag_seconds: 0,
  graph_promotion_rate: 0,
  cross_tenant_contamination: false,
};

const REVIEW_ITEMS = [
  {
    id: 'srq_ambiguous_001',
    tenant_id: 'tenant_001',
    queue_type: 'ambiguous_subject',
    subject_ref: 'subject_abc',
    source_event_id: 'evt_001',
    status: 'open',
    payload: {},
    created_at: '2026-07-22T10:00:00.000Z',
  },
  {
    id: 'srq_campaign_002',
    tenant_id: 'tenant_002',
    queue_type: 'campaign_mapping',
    subject_ref: null,
    source_event_id: 'evt_002',
    status: 'open',
    payload: {},
    created_at: '2026-07-21T08:00:00.000Z',
  },
];

const QUEUE_TAXONOMY = ['ambiguous_subject', 'campaign_mapping', 'graph_promotion_candidate'];

function ok(data: unknown) {
  return HttpResponse.json({ data, status: 'ok', timestamp: new Date().toISOString() });
}

const requestLog = { fleetHealth: 0, reviewQueue: 0 };

const server = setupServer(
  http.get(`${API}/v1/kyber/semantic/fleet-health`, () => {
    requestLog.fleetHealth += 1;
    return ok(FLEET_HEALTH_FIXTURE);
  }),
  http.get(`${API}/v1/kyber/semantic/review-queue`, ({ request }) => {
    requestLog.reviewQueue += 1;
    const queueType = new URL(request.url).searchParams.get('queue_type');
    const items = queueType ? REVIEW_ITEMS.filter(i => i.queue_type === queueType) : REVIEW_ITEMS;
    return ok({
      items,
      count: items.length,
      counts_by_queue: { ambiguous_subject: 1, campaign_mapping: 1 },
      queues: QUEUE_TAXONOMY,
    });
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  authState.capabilities = [
    'kyber.approvals.decide',
    'kyber.controller.intervene',
    'kyber.command.dispatch',
    'kyber.diagnostics.run',
    'kyber.diagnostics.read',
    'kyber.action.revert',
    'kyber.notes.write',
    'kyber.export.create',
  ];
  requestLog.fleetHealth = 0;
  requestLog.reviewQueue = 0;
});

function renderPage() {
  return render(<MemoryRouter><SemanticReviewQueuePage /></MemoryRouter>);
}

describe('Kyber Semantic Operations page', () => {
  it('renders the fleet-health scorecard from the real computed fields', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Semantic Operations')).toBeInTheDocument());

    // Real (computed) metrics.
    await waitFor(() => expect(screen.getByText('Enabled tenants')).toBeInTheDocument());
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Classified observations')).toBeInTheDocument();
    expect(screen.getByText('1287')).toBeInTheDocument();
    expect(screen.getByText('Abstention rate')).toBeInTheDocument();
    expect(screen.getByText('12.5%')).toBeInTheDocument();
    expect(screen.getByText('Quarantined observations')).toBeInTheDocument();
    expect(screen.getByText('Consent-restricted observations')).toBeInTheDocument();
    expect(screen.getByText('Sentiment observations')).toBeInTheDocument();

    // Status breakdown and model versions.
    expect(screen.getByText('Status breakdown')).toBeInTheDocument();
    expect(screen.getByText('abstained')).toBeInTheDocument();
    expect(screen.getByText('1121')).toBeInTheDocument();
    expect(screen.getByText('Model versions')).toBeInTheDocument();
    expect(screen.getByText('deterministic-semantic-classifier@1.0.0')).toBeInTheDocument();
  });

  it('labels the hardcoded backend placeholders as not yet instrumented instead of live metrics', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Not yet instrumented')).toBeInTheDocument());

    // The three placeholder fields appear once each, as instrumentation labels
    // (badges inside the "Not yet instrumented" card) — never as metric tiles.
    for (const label of ['Queue lag', 'Graph promotion rate', 'Cross-tenant contamination']) {
      const nodes = screen.getAllByText(label);
      expect(nodes).toHaveLength(1);
      expect(nodes[0]!.classList.contains('ui-badge')).toBe(true);
    }
    expect(screen.getByText(/hardcoded placeholder values/)).toBeInTheDocument();

    // No metric tile (the 2xl value styling) renders the placeholder values.
    const metricValues = Array.from(document.querySelectorAll('.text-2xl')).map(el => el.textContent);
    expect(metricValues).not.toContain('0');
    expect(metricValues).not.toContain('false');
  });

  it('renders the review queue and filters by queue type', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('srq_ambiguous_001')).toBeInTheDocument());
    expect(screen.getByText('srq_campaign_002')).toBeInTheDocument();
    expect(screen.getByText('subject_abc')).toBeInTheDocument();

    // Tabs come from the response taxonomy with counts.
    expect(screen.getByRole('tab', { name: 'All' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'graph promotion candidate (0)' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: 'campaign mapping (1)' }));
    await waitFor(() => expect(screen.queryByText('srq_ambiguous_001')).toBeNull());
    expect(screen.getByText('srq_campaign_002')).toBeInTheDocument();
  });

  it('renders an honest empty state when the review queue has no items', async () => {
    server.use(
      http.get(`${API}/v1/kyber/semantic/review-queue`, () =>
        ok({ items: [], count: 0, counts_by_queue: {}, queues: QUEUE_TAXONOMY }),
      ),
    );
    renderPage();
    await waitFor(() => expect(screen.getByText('Review queue is empty')).toBeInTheDocument());
    expect(screen.getByText(/appear here when semantic workers enqueue them/)).toBeInTheDocument();
  });

  it('shows the error state when fleet health cannot be loaded', async () => {
    server.use(
      http.get(`${API}/v1/kyber/semantic/fleet-health`, () =>
        HttpResponse.json({ detail: 'operator permission required' }, { status: 403 }),
      ),
    );
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Unable to load semantic fleet health')).toBeInTheDocument(),
    );
  });

  it('gates the page behind operator approval permissions and never fetches when denied', async () => {
    authState.capabilities = [];
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Operator approval permissions required')).toBeInTheDocument(),
    );
    expect(screen.queryByText('Enabled tenants')).toBeNull();
    expect(screen.queryByRole('tab', { name: 'All' })).toBeNull();
    expect(requestLog.fleetHealth).toBe(0);
    expect(requestLog.reviewQueue).toBe(0);
  });
});
