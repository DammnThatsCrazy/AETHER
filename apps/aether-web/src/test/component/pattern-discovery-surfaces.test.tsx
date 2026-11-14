import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import {
  ExplorePatternsPanel, PatternLensPanel, PatternSectionPanel, RiskPatternQueueCard,
} from '@aether-app/features/pattern-discovery';
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
  summary: '14 entities share a device and a card.', status: 'surfaced', severity: 'critical', pinned: false,
  surfaced_at: '2026-11-13T09:00:00Z',
  confidence: 0.75, confidence_cap: 0.75, novelty: 1, affected_entity_count: 14,
  risk_categories: ['infrastructure', 'payment'], claim_state: 'inferred',
};

const PROFILE = {
  entity: 'user:u1', surface: 'profile360', withheld: false, advisory: true, claim_state: 'inferred',
  counts: { total: 1, surfaced: 1, reviewed: 0, promoted: 0, watching: 0, hidden: 0 },
  scope: 'entity:user:u1', last_seen_at: null, new_count: 1,
  emerging_patterns: [{ ...ROW, is_new: true }], unresolved_identity_overlaps: [ROW], contradictory_evidence: [],
  baseline_changes: [], behavioral_cohorts: [], similar_profiles: [{ entity: 'user:u2', shared_patterns: 3 }],
};

const reviews: unknown[] = [];
const curations: unknown[] = [];
const seen: unknown[] = [];
const listQueries: string[] = [];

const WHATS_NEW = {
  scope: 'feed', withheld: false, since: '2026-11-10T09:00:00Z', since_source: 'last_seen', last_seen_at: '2026-11-10T09:00:00Z',
  new: [ROW], changed: [], retired: [],
  digest: {
    new: { count: 1, by_kind: { shared_attribute_cluster: 1 }, by_severity: { critical: 1 }, by_segment: {}, risk_categories: {} },
    changed: { count: 0, by_kind: {}, by_severity: {}, by_segment: {}, risk_categories: {} },
    retired: { count: 0, by_kind: {}, by_severity: {}, by_segment: {}, risk_categories: {} },
  },
};

const GRAPH = {
  pattern_id: 't:pat:1', kind: 'shared_attribute_cluster', title: ROW.title, truncated: false, claim_state: 'inferred',
  nodes: [
    { id: 'pattern:t:pat:1', kind: 'pattern', label: 'shared device', role: 'pattern' },
    { id: 'user:u1', kind: 'user', label: 'u1', role: 'member' },
    { id: 'user:u2', kind: 'user', label: 'u2', role: 'member' },
    { id: 'device:d1', kind: 'device', label: 'd1', role: 'attribute' },
  ],
  edges: [
    { source: 'pattern:t:pat:1', target: 'user:u1', type: 'MEMBER_OF_PATTERN' },
    { source: 'pattern:t:pat:1', target: 'user:u2', type: 'MEMBER_OF_PATTERN' },
    { source: 'user:u1', target: 'device:d1', type: 'SHARES' },
  ],
};

const server = setupServer(
  http.get(`${API}/v1/profile/u1/patterns`, () => HttpResponse.json(envelope(PROFILE))),
  http.get(`${API}/v1/profile/u9/patterns`, () => HttpResponse.json(envelope({
    ...PROFILE, entity: 'user:u9', withheld: true, reason_code: 'consent_receipt_missing',
    counts: { total: 0, surfaced: 0, reviewed: 0, promoted: 0, watching: 0, hidden: 0 }, emerging_patterns: [], unresolved_identity_overlaps: [],
    similar_profiles: [],
  }))),
  http.get(`${API}/v1/agent/a1/patterns`, () => HttpResponse.json(envelope({
    entity: 'agent:a1', surface: 'agent360', withheld: false, counts: { total: 1, surfaced: 1, reviewed: 0, promoted: 0, watching: 0, hidden: 0 },
    tool_call_signatures: [{ ...ROW, kind: 'agent_tool_signature', title: 'Shared tool-call signature across 6 principals' }],
    novel_delegation_motifs: [], spawning_anomalies: [], shared_infrastructure: [], cross_principal_behavior: [],
    agent_interactions: [], shared_infrastructure_agents: [], principals: [],
  }))),
  http.get(`${API}/v1/intelligence/patterns`, ({ request }) => {
    listQueries.push(new URL(request.url).search);
    return HttpResponse.json(envelope({ items: [ROW], count: 1, total: 1 }));
  }),
  http.get(`${API}/v1/intelligence/patterns/whats-new`, () => HttpResponse.json(envelope(WHATS_NEW))),
  http.post(`${API}/v1/intelligence/patterns/whats-new/seen`, async ({ request }) => {
    seen.push(await request.json());
    return HttpResponse.json(envelope({ scope: 'feed', last_seen_at: '2026-11-14T12:00:00Z' }));
  }),
  http.get(`${API}/v1/intelligence/patterns/lenses/:lens/:subject`, ({ params }) => HttpResponse.json(envelope({
    lens: params.lens, subject: params.subject, withheld: false, scope: `lens:${String(params.lens)}:${String(params.subject)}`,
    last_seen_at: null, new_count: 1, counts: { total: 1, by_kind: { segment_shift: 1 } },
    groups: [{ kind: 'segment_shift', heading: 'Segment shifts', patterns: [{ ...ROW, kind: 'segment_shift', title: 'Spring promo drives a burst of new wallets', is_new: true }] }],
    patterns: [],
  }))),
  http.post(`${API}/v1/intelligence/patterns/graph-overlay`, () => HttpResponse.json(envelope({
    by_node: { u1: ['t:pat:1'] }, nodes_requested: 2,
    patterns: [{ pattern_id: 't:pat:1', kind: 'shared_attribute_cluster', title: ROW.title, severity: 'critical', status: 'surfaced', members_in_view: ['u1'], affected_entity_count: 14 }],
  }))),
  http.get(`${API}/v1/intelligence/patterns/:id/graph`, () => HttpResponse.json(envelope(GRAPH))),
  http.post(`${API}/v1/intelligence/patterns/:id/curate`, async ({ request }) => {
    const body = await request.json() as Record<string, unknown>;
    curations.push(body);
    return HttpResponse.json(envelope({ ...ROW, pinned: body.action === 'pin' }));
  }),
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
  curations.length = 0;
  seen.length = 0;
  listQueries.length = 0;
});

describe('Pattern discovery surfaces', () => {
  it('renders the Profile 360 section grouped by what the profile asked for', async () => {
    render(<MemoryRouter><PatternSectionPanel surface="profile360" entityId="u1" /></MemoryRouter>);
    expect(await screen.findByText('Emerging patterns · 1')).toBeInTheDocument();
    expect(screen.getByText('Unresolved identity overlaps · 1')).toBeInTheDocument();
    expect(screen.getByText('user:u2 · 3')).toBeInTheDocument();
    expect(screen.getAllByText(ROW.title)[0]?.closest('a')).toHaveAttribute('href', '/patterns?pattern=t%3Apat%3A1');
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

  it('shows the surfaced feed and new count on the Risk overview', async () => {
    render(<MemoryRouter><RiskPatternQueueCard /></MemoryRouter>);
    expect(await screen.findByText('Discovered patterns · 1')).toBeInTheDocument();
    expect(await screen.findByText('1 new since you last looked →')).toHaveAttribute('href', '/patterns?view=new');
    expect(listQueries[0]).toContain('feed=true');
  });

  it('flags new patterns in a 360 section and marks them seen', async () => {
    render(<MemoryRouter><PatternSectionPanel surface="profile360" entityId="u1" /></MemoryRouter>);
    expect(await screen.findByText('1 new since you last looked')).toBeInTheDocument();
    expect(screen.getByText('new')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Mark seen'));
    await waitFor(() => expect(seen).toEqual([{ scope: 'entity:user:u1' }]));
  });

  it('curates a pattern (pin, hide, rename) from the tenant page and shows it on the graph', async () => {
    render(<MemoryRouter initialEntries={['/patterns?pattern=t%3Apat%3A1']}><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Families share devices.')).toBeInTheDocument();
    expect(await screen.findByTestId('pattern-graph-canvas')).toBeInTheDocument();
    expect(screen.getByText('Show on graph →')).toHaveAttribute('href', '/explore?pattern=t%3Apat%3A1');
    fireEvent.click(screen.getByText('Pin'));
    await waitFor(() => expect(curations).toEqual([{ action: 'pin' }]));
    fireEvent.click(screen.getByText('Hide'));
    await waitFor(() => expect(curations).toContainEqual({ action: 'hide' }));
    fireEvent.change(screen.getByLabelText('New title'), { target: { value: 'Card farm on device d1' } });
    fireEvent.click(screen.getByText('Save title'));
    await waitFor(() => expect(curations).toContainEqual({ action: 'rename', title: 'Card farm on device d1' }));
  });

  it('records an optional verdict from the tenant page', async () => {
    render(<MemoryRouter initialEntries={['/patterns?pattern=t%3Apat%3A1']}><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Families share devices.')).toBeInTheDocument();
    fireEvent.change(screen.getByDisplayValue('valid'), { target: { value: 'malicious' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'card farm confirmed by ops' } });
    fireEvent.click(screen.getByText('Record verdict'));
    await waitFor(() => expect(reviews).toEqual([{ verdict: 'malicious', reason: 'card farm confirmed by ops' }]));
  });

  it('shows what is new since the viewer last looked and marks all seen', async () => {
    render(<MemoryRouter initialEntries={['/patterns?view=new']}><PatternsPage /></MemoryRouter>);
    expect(await screen.findByTestId('patterns-whats-new')).toBeInTheDocument();
    expect(await screen.findByText('1 new')).toBeInTheDocument();
    expect(screen.getByText(ROW.title)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Mark all seen'));
    await waitFor(() => expect(seen).toEqual([{ scope: 'feed' }]));
  });

  it('renders a segment lens with new badges', async () => {
    render(<MemoryRouter><PatternLensPanel lens="campaign360" subject="spring" /></MemoryRouter>);
    expect(await screen.findByText('Patterns in this campaign · 1')).toBeInTheDocument();
    expect(screen.getByText('Segment shifts · 1')).toBeInTheDocument();
    expect(screen.getByText('Spring promo drives a burst of new wallets')).toBeInTheDocument();
    expect(screen.getByText('1 new since you last looked')).toBeInTheDocument();
  });

  it('lists patterns touching the objects in an Explore view and opens one on the graph', async () => {
    const onPattern = vi.fn();
    render(<MemoryRouter><ExplorePatternsPanel nodeIds={['u1', 'u7']} patternId={null} onPattern={onPattern} onFocusNode={vi.fn()} /></MemoryRouter>);
    fireEvent.click(screen.getByText('Show patterns touching these 2 objects'));
    fireEvent.click(await screen.findByText(ROW.title));
    expect(onPattern).toHaveBeenCalledWith('t:pat:1');
  });

  it('draws the selected pattern in Explore and reports members in view', async () => {
    render(<MemoryRouter><ExplorePatternsPanel nodeIds={['u1']} patternId="t:pat:1" onPattern={vi.fn()} onFocusNode={vi.fn()} /></MemoryRouter>);
    expect(await screen.findByText(/1 of 2 members are in this graph view/)).toBeInTheDocument();
    expect(screen.getByTestId('pattern-graph-canvas')).toBeInTheDocument();
  });

  it('shows an error state when the feed is unavailable', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => HttpResponse.json({ detail: 'down' }, { status: 503 })));
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Patterns unavailable')).toBeInTheDocument();
  });

  it('shows an empty state when nothing is surfaced', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => HttpResponse.json(envelope({ items: [], count: 0, total: 0 }))));
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByText('Nothing to show')).toBeInTheDocument();
  });

  it('shows loading while the feed is pending, and explains when the feature is off', async () => {
    server.use(http.get(`${API}/v1/intelligence/patterns`, () => new Promise(() => {})));
    const { unmount } = render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(await screen.findByRole('status', { name: 'Loading data' })).toBeInTheDocument();
    unmount();
    state.flags = {};
    render(<MemoryRouter><PatternsPage /></MemoryRouter>);
    expect(screen.getByText('Pattern discovery is not enabled')).toBeInTheDocument();
  });
});
