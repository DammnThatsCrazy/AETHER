import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { ThemeProvider, queryCache } from '@aether/ui';
import { RelationshipsPage } from '@aether-app/pages/relationships';

const s = vi.hoisted(() => ({
  traverse: (() => Promise.resolve({ nodes: [], edges: [] })) as (body: unknown) => Promise<unknown>,
  path: (() => Promise.resolve({ nodes: [], edges: [] })) as (body: unknown) => Promise<unknown>,
  users: (() => Promise.resolve({ entities: [], total: 0 })) as () => Promise<unknown>,
  traverseCalls: [] as unknown[],
}));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    me: { profile: () => Promise.resolve({ tenant_id: 't1' }) },
    entities: {
      list: () => s.users(),
      search: () => s.users().then(r => ({ results: (r as { entities: unknown[] }).entities, total: 0 })),
    },
    graphIntelligence: {
      traverse: (body: unknown) => { s.traverseCalls.push(body); return s.traverse(body); },
      path: (body: unknown) => s.path(body),
    },
  },
}));

const NETWORK = {
  nodes: [
    { id: 'u1', kind: 'user', label: 'Ada Obi', properties: {} },
    { id: 'a1', kind: 'agent', label: 'Shopping agent', properties: {} },
    { id: 'u2', kind: 'user', label: 'Kemi Obi', properties: {} },
    { id: 'o1', kind: 'organization', label: 'Northpeak', properties: {} },
  ],
  edges: [
    {
      id: 'u1:DELEGATES:a1', type: 'DELEGATES', from: 'u1', to: 'a1', directed: true, validFrom: '2026-03-18T00:00:00Z',
      properties: { relationship_score: 0.8, confidence: 0.95, evidence_refs: ['Delegation grant recorded'], source: 'delegations', scope: 'purchase' },
    },
    { id: 'u1:SIMILAR_TO:u2', type: 'SIMILAR_TO', from: 'u1', to: 'u2', directed: true, validFrom: '2025-01-10T00:00:00Z', properties: { relationship_score: 0.6 } },
    { id: 'u1:MEMBER_OF:o1', type: 'MEMBER_OF', from: 'u1', to: 'o1', directed: true, properties: {} },
  ],
  explainability: { summary: 'Traversal complete: 4 nodes, 3 edges' },
};

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname}{l.search}</div>;
}

function renderAt(path: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/relationships" element={<RelationshipsPage />} />
          <Route path="/relationships/:entityId" element={<RelationshipsPage />} />
          <Route path="*" element={<div>elsewhere</div>} />
        </Routes>
        <Where />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Relationships', () => {
  beforeEach(() => {
    queryCache.invalidatePrefix('relationships:');
    queryCache.invalidate('me-profile');
    s.traverse = () => Promise.resolve(NETWORK);
    s.path = () => Promise.resolve({ nodes: [], edges: [] });
    s.users = () => Promise.resolve({ entities: [], total: 0 });
    s.traverseCalls = [];
  });

  it('asks who to centre on and links real profiles', async () => {
    s.users = () => Promise.resolve({ entities: [{ id: 'u1', display_name: 'Ada Obi', email: 'ada@example.com' }], total: 1 });
    renderAt('/relationships');
    const option = await screen.findByTestId('anchor-option');
    expect(option).toHaveTextContent('Ada Obi');
    expect(option).toHaveAttribute('href', '/relationships/u1?kind=user');

    fireEvent.change(screen.getByLabelText('Entity id'), { target: { value: 'agent-42' } });
    fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/relationships/agent-42');
  });

  it('shows a loading state while the graph is read', () => {
    s.traverse = () => new Promise(() => {});
    renderAt('/relationships/u1');
    expect(screen.getByText('Reading the graph…')).toBeInTheDocument();
  });

  it('says nothing is recorded rather than inventing links', async () => {
    s.traverse = () => Promise.resolve({ nodes: [{ id: 'u1', kind: 'user', label: 'Ada Obi' }], edges: [] });
    renderAt('/relationships/u1');
    expect(await screen.findByTestId('relationships-empty')).toHaveTextContent('No relationships are recorded for Ada Obi within 1 hop.');
  });

  it('marks an unavailable read as unavailable, never as empty', async () => {
    s.traverse = () => Promise.reject(new Error('graph offline'));
    renderAt('/relationships/u1');
    expect(await screen.findByText('Relationships for this entity are unavailable right now.')).toBeInTheDocument();
    expect(screen.queryByTestId('relationships-empty')).not.toBeInTheDocument();
  });

  it('draws the ego network, filters by type and opens a relationship with its evidence', async () => {
    renderAt('/relationships/u1?kind=user');
    const network = await screen.findByTestId('ego-network');
    expect(within(network).getAllByTestId('network-node')).toHaveLength(4);
    expect(within(network).getAllByTestId('network-edge')).toHaveLength(3);
    expect(s.traverseCalls[0]).toMatchObject({ tenantId: 't1', start: { kind: 'user', id: 'u1' }, depth: 1 });

    fireEvent.click(screen.getByRole('tab', { name: /Human ↔ Agent · 1/ }));
    expect(within(screen.getByTestId('ego-network')).getAllByTestId('network-edge')).toHaveLength(1);
    fireEvent.click(screen.getByRole('tab', { name: /All · 3/ }));

    fireEvent.click(screen.getByRole('tab', { name: 'Relationships' }));
    const rows = screen.getAllByTestId('relationship-row');
    expect(rows[0]).toHaveTextContent('Ada Obi ── delegates ── Shopping agent');
    expect(rows[0]).toHaveTextContent('80');
    fireEvent.click(rows[0]!);
    expect(screen.getByTestId('selected-panel')).toHaveTextContent('Shopping agent');
    fireEvent.click(screen.getByTestId('open-relationship'));

    const detail = await screen.findByTestId('relationship-detail');
    expect(within(detail).getByTestId('evidence-ladder')).toHaveTextContent('Delegation grant recorded');
    expect(within(detail).getByTestId('evidence-ladder')).toHaveTextContent('Reported by delegations');
    expect(within(detail).getByTestId('recorded-facts')).toHaveTextContent('purchase');
    expect(within(detail).getByRole('link', { name: 'Open Shopping agent →' })).toHaveAttribute('href', '/agents/a1');
    expect(within(detail).getByRole('link', { name: 'Open Ada Obi →' })).toHaveAttribute('href', '/users/u1');
    expect(within(detail).getByRole('link', { name: 'Centre on Shopping agent →' })).toHaveAttribute('href', '/relationships/a1?kind=agent');
    expect(screen.getByTestId('where')).toHaveTextContent('rel=u1%3ADELEGATES%3Aa1');

    fireEvent.click(within(detail).getByRole('button', { name: /← Relationships/ }));
    expect(await screen.findByTestId('relationship-list')).toBeInTheDocument();
  });

  it('requests more hops and shows the arc diagram and formation history', async () => {
    renderAt('/relationships/u1');
    await screen.findByTestId('ego-network');
    fireEvent.click(screen.getByRole('button', { name: '2 hops' }));
    expect(screen.getByTestId('where')).toHaveTextContent('hops=2');
    await screen.findByTestId('ego-network');
    expect(s.traverseCalls.at(-1)).toMatchObject({ depth: 2 });

    fireEvent.click(screen.getByRole('tab', { name: 'By type' }));
    expect(screen.getAllByTestId('arc')).toHaveLength(3);

    fireEvent.click(screen.getByRole('tab', { name: 'History' }));
    const history = screen.getByTestId('relationship-history-list');
    expect(history).toHaveTextContent('Ada Obi delegates Shopping agent');
    expect(history).toHaveTextContent('1 link carry no date.');
  });

  it('traces a path to another entity through the graph path read', async () => {
    s.path = () => Promise.resolve({
      nodes: [
        { id: 'u1', kind: 'user', label: 'Ada Obi' },
        { id: 'a1', kind: 'agent', label: 'Shopping agent' },
        { id: 'w1', kind: 'wallet', label: 'Wallet 0x1a' },
      ],
      edges: [
        { id: 'e1', type: 'DELEGATES', from: 'u1', to: 'a1', directed: true },
        { id: 'e2', type: 'CONTROLS', from: 'a1', to: 'w1', directed: true },
      ],
    });
    renderAt('/relationships/u1?view=paths');
    const explorer = await screen.findByTestId('path-explorer');
    fireEvent.change(within(explorer).getByLabelText('Target entity id'), { target: { value: 'w1' } });
    fireEvent.click(within(explorer).getByRole('button', { name: 'Trace' }));
    const steps = await screen.findByTestId('path-steps');
    expect(steps).toHaveTextContent('Ada Obi');
    expect(steps).toHaveTextContent('delegates');
    expect(steps).toHaveTextContent('Wallet 0x1a');
    expect(within(steps).getByRole('link', { name: /Shopping agent/ })).toHaveAttribute('href', '/agents/a1');
  });

  it('says when no path exists within the hop limit', async () => {
    renderAt('/relationships/u1?view=paths&to=zz&depth=3');
    expect(await screen.findByTestId('path-none')).toHaveTextContent('No path within 3 hops.');
  });
});
