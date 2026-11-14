import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PatternSectionPanel, RiskPatternQueueCard } from '@aether-app/features/pattern-discovery';
import { PatternsPage } from '@aether-app/pages/patterns';
import { queryCache } from '@aether/ui';

const state = vi.hoisted(() => ({ flags: { pattern_discovery_enabled: true } as Record<string, boolean> }));

vi.mock('@aether/ui', async () => {
  const actual = await vi.importActual<typeof import('@aether/ui')>('@aether/ui');
  return {
    ...actual,
    useCapabilities: () => ({
      capabilities: { feature_flags: state.flags }, buildInfo: null, loading: false, error: null, refresh: vi.fn(),
    }),
  };
});

const API = 'http://localhost:8000';

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: '2026-11-14T12:00:00Z' };
}

const ROW = {
  pattern_id: 't:pat:1', kind: 'shared_attribute_cluster', title: '14 entities converge on shared device',
  summary: '14 entities share a device and a card.', status: 'needs_review', severity: 'critical',
  confidence: 0.75, confidence_cap: 0.75, novelty: 1, affected_entity_count: 14,
  risk_categories: ['infrastructure', 'payment'], claim_state: 'inferred',
};

const PROFILE = {
  entity: 'user:u1', surface: 'profile360', withheld: false, advisory: true, claim_state: 'inferred',
  counts: { total: 1, open: 1, reviewed: 0, promoted: 0 },
  emerging_patterns: [ROW], unresolved_identity_overlaps: [ROW], contradictory_evidence: [],
  baseline_changes: [], behavioral_cohorts: [], similar_profiles: [{ entity: 'user:u2', shared_patterns: 3 }],
};

const reviews: unknown[] = [];
const server = setupServer(
  http.get(`${API}/v1/profile/u1/patterns`, () => HttpResponse.json(envelope(PROFILE))),
  http.get(`${API}/v1/profile/u9/patterns`, () => HttpResponse.json(envelope({
    ...PROFILE, entity: 'user:u9', withheld: true, reason_code: 'consent_receipt_missing',
    counts: { total: 0, open: 0, reviewed: 0, promoted: 0 }, emerging_patterns: [], unresolved_identity_overlaps: [],
    similar_profiles: [],
  }))),
  http.get(`${API}/v1/agent/a1/patterns`, () => HttpResponse.json(envelope({
    entity: 'agent:a1', surface: 'agent360', withheld: false, counts: { total: 1, open: 1, reviewed: 0, promoted: 0 },
    tool_call_signatures: [{ ...ROW, kind: 'agent_tool_signature', title: 'Shared tool-call signature across 6 principals' }],
    novel_delegation_motifs: [], spawning_anomalies: [], shared_infrastructure: [], cross_principal_behavior: [],
    agent_interactions: [], shared_infrastructure_agents: [], principals: [],
  }))),
  http.get(`${API}/v1/intelligence/patterns`, () => HttpResponse.json(envelope({ items: [ROW], count: 1, total: 1 }))),
  http.get(`${API}/v1/intelligence/patterns/:id`, () => HttpResponse.json(envelope({
    ...ROW, evidence: [{ type: 'shared_attribute_values', basis: 'observed', strength: 0.2 }],
    competing_explanations: [{ id: 'shared_household_device', note: 'Families share devices.' }], review_history: [],
  }))),
  http.post(`${API}/v1/intelligence/patterns/:id/review`, async ({ request }) => {
    reviews.push(await request.json());
    return HttpResponse.json(envelope({ ...ROW, status: 'confirmed_malicious' }));
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
beforeEach(() => {
  queryCache.clear();
  state.flags = { pattern_discovery_enabled: true };
  reviews.length = 0;
});

describe('Pattern discovery surfaces', () => {
  it('renders the Profile 360 section grouped by what the profile asked for', async () => {
    render(<MemoryRouter><PatternSectionPanel surface="profile360" entityId="u1" /></MemoryRouter>);
    expect(await screen.findByText('Emerging patterns · 1')).toBeInTheDocument();
    expect(screen.getByText('Unresolved identity overlaps · 1')).toBeInTheDocument();
    expect(screen.getByText('user:u2 · 3')).toBeInTheDocument();
    expect(screen.getAllByText(ROW.title)[0].closest('a')).toHaveAttribute('href', '/patterns?pattern=t%3Apat%3A1');
  });

  it('says when consent withholds the section', async () => {
    render(<MemoryRouter><PatternSectionPanel surface="profile360" entityId="u9" /></MemoryRouter>);
    expect(await screen.findByText('Withheld')).toBeInTheDocument();
  });

  it('renders the Agent 360 section', async () => {
    render(<MemoryRouter><PatternSectionPanel surface="agent360" entityId="a1" /></MemoryRouter>);
    expect(await screen.findByText('Tool-call signatures · 1')).toBeInTheDocument();
  });

  it('renders nothing when the capability is off', () => {
    state.flags = {};
    const { container } = render(<MemoryRouter><PatternSectionPanel surface="profile360" entityId="u1" /><RiskPatternQueueCard /></MemoryRouter>);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the open queue on the Risk overview', async () => {
    render(<MemoryRouter><RiskPatternQueueCard /></MemoryRouter>);
    expect(await screen.findByText('Discovered patterns awaiting review · 1')).toBeInTheDocument();
  });

  it('reviews a pattern from the tenant page', async () => {
    render(<MemoryRouter initialEntries={['/patterns?pattern=t%3Apat%3A1']}><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Families share devices.')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('valid'), { target: { value: 'malicious' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'card farm confirmed by ops' } });
    fireEvent.click(screen.getByText('Record verdict'));
    await waitFor(() => expect(reviews).toEqual([{ verdict: 'malicious', reason: 'card farm confirmed by ops' }]));
  });

  it('shows an error state when the queue is unavailable', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => HttpResponse.json({ detail: 'down' }, { status: 503 })));
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Patterns unavailable')).toBeInTheDocument();
  });

  it('shows an empty state when nothing needs review', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => HttpResponse.json(envelope({ items: [], count: 0, total: 0 }))));
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument();
  });

  it('shows loading while the queue is pending, and explains when the feature is off', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => new Promise(() => {})));
    const { unmount } = render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByRole('status', { name: 'Loading data' })).toBeInTheDocument();
    unmount();
    state.flags = {};
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(screen.getByText('Pattern discovery is not enabled')).toBeInTheDocument();
  });
});
