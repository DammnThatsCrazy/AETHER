import { describe, expect, it } from 'vitest';
import {
  buildNetwork,
  directConnections,
  edgeAmount,
  findReadPath,
  formatAmount,
  initials,
  linkKind,
  linkLabel,
  nodeCategory,
  scopeSnapshot,
} from '@aether-app/pages/explore/explore-network';
import { placeArcs, placeLabels } from '@aether-app/pages/explore/explore-visuals';

const node = (id: string, kind: string, metadata: Record<string, unknown> = {}) => ({ id, kind, label: id, metadata });
const edge = (id: string, source: string, target: string, relationType: string, metadata: Record<string, unknown> = {}) => ({
  id, source, target, relationType, interactionClass: 'H2A' as const, weight: 1, metadata,
});

const NONE = new Set<never>();

describe('Graph network model', () => {
  it('sorts kinds into the toolbar categories', () => {
    expect(nodeCategory('User')).toBe('people');
    expect(nodeCategory('entity')).toBe('people');
    expect(nodeCategory('Merchant')).toBe('organizations');
    expect(nodeCategory('Agent')).toBe('agents');
    expect(nodeCategory('Wallet')).toBe('wallets');
    expect(nodeCategory('Source')).toBe('applications');
    expect(nodeCategory('cluster')).toBe('syndicates');
    expect(nodeCategory('device')).toBe('devices');
    expect(nodeCategory('mystery')).toBe('other');
  });

  it('labels a link with money only when the edge carries an amount', () => {
    expect(edgeAmount(edge('e', 'a', 'b', 'SENT'))).toBeNull();
    expect(linkLabel(edge('e', 'a', 'b', 'SENT'))).toBe('sent');
    expect(linkLabel(edge('e', 'a', 'b', 'DELEGATES', { volume_usd: 1842 }))).toBe('$1.8K');
    expect(linkLabel(edge('e', 'a', 'b', 'PAID', { amount: 500, currency: 'sol' }))).toBe('500 SOL');
    expect(linkLabel(edge('e', 'a', 'b', 'PURCHASED', { value: 418 }))).toBe('418');
    expect(formatAmount({ amount: 12_000, currency: 'USD' })).toBe('$12K');
    expect(linkKind(edge('e', 'a', 'b', 'PURCHASED', { value: 1 }))).toBe('buys');
    expect(linkKind(edge('e', 'a', 'b', 'FLAGGED_BY'))).toBe('risk');
    expect(linkKind(edge('e', 'a', 'b', 'ATTRIBUTED_TO'))).toBe('campaign');
    expect(linkKind(edge('e', 'a', 'b', 'TRANSFER'))).toBe('money');
    expect(linkKind(edge('e', 'a', 'b', 'HOUSEHOLD'))).toBe('relationship');
  });

  it('builds principal cards, rows and hop-limited counts from the read', () => {
    const snapshot = {
      nodes: [node('p1', 'User'), node('p2', 'User'), node('p3', 'User'), node('a1', 'Agent'), node('w1', 'Wallet'), node('a2', 'Agent')],
      edges: [edge('1', 'p1', 'a1', 'DELEGATES'), edge('2', 'p1', 'w1', 'OWNS'), edge('3', 'p1', 'p2', 'SENT', { amount_usd: 5 }), edge('4', 'p2', 'p3', 'KNOWS'), edge('5', 'a2', 'a1', 'LAUNCHED_BY')],
    };
    const all = buildNetwork(snapshot, { scopeId: null, hops: 1, perspective: 'all', hiddenCategories: NONE, search: '' });
    // Hops are ignored without a scope; a2 is not owned by a person, so it gets a card.
    expect(all.cards.map(c => c.node.id).sort()).toEqual(['a2', 'p1', 'p2', 'p3']);
    expect(all.cards.find(c => c.node.id === 'p1')!.rows.map(r => r.node.id)).toEqual(['a1', 'w1']);
    expect(all.links.find(l => l.id === 'p1|p2')).toMatchObject({ label: '$5', kind: 'money' });

    const scoped = buildNetwork(snapshot, { scopeId: 'p1', hops: 1, perspective: 'all', hiddenCategories: NONE, search: '' });
    expect(scoped.scope?.id).toBe('p1');
    expect(scoped.cards[0]!.node.id).toBe('p1');
    expect(scoped.cards.map(c => c.node.id)).not.toContain('p3');
    expect(scoped.counts.get('people')).toBe(2);

    const agents = buildNetwork(snapshot, { scopeId: null, hops: null, perspective: 'agent', hiddenCategories: NONE, search: '' });
    expect(agents.cards.map(c => c.node.id).sort()).toEqual(['a1', 'a2']);

    const noWallets = buildNetwork(snapshot, { scopeId: null, hops: null, perspective: 'all', hiddenCategories: new Set(['wallets']), search: '' });
    expect(noWallets.cards.find(c => c.node.id === 'p1')!.rows.map(r => r.node.id)).toEqual(['a1']);

    const searched = buildNetwork(snapshot, { scopeId: null, hops: null, perspective: 'all', hiddenCategories: NONE, search: 'w1' });
    expect(searched.cards.map(c => c.node.id)).toEqual(['p1']);
  });

  it('places linked principals next to each other', () => {
    const snapshot = {
      nodes: [node('a', 'User'), node('b', 'User'), node('c', 'User'), node('d', 'User')],
      edges: [edge('1', 'a', 'c', 'KNOWS'), edge('2', 'c', 'd', 'KNOWS'), edge('3', 'a', 'd', 'KNOWS')],
    };
    const net = buildNetwork(snapshot, { scopeId: 'a', hops: null, perspective: 'all', hiddenCategories: NONE, search: '' });
    expect(net.cards.map(c => c.node.id)).toEqual(['a', 'c', 'd']);
  });

  it('lists direct connections and finds the shortest path through the read', () => {
    const snapshot = {
      nodes: [node('a', 'User'), node('b', 'Agent'), node('c', 'User')],
      edges: [
        edge('1', 'a', 'b', 'DELEGATES', { valid_from: '2026-08-11T00:00:00Z', confidence: 0.95 }),
        edge('2', 'b', 'c', 'ACTS_FOR', { valid_from: '2026-09-29T00:00:00Z', confidence: 0.91 }),
      ],
    };
    expect(directConnections('b', snapshot).map(c => `${c.node.id}:${c.label}`)).toEqual(['a:delegates', 'c:acts for']);
    const path = findReadPath('a', 'c', snapshot)!;
    expect(path.steps.map(s => s.node.id)).toEqual(['a', 'b', 'c']);
    expect(path.steps.map(s => s.relation)).toEqual(['delegates', 'acts for', null]);
    expect(path.hops).toBe(2);
    expect(path.firstObserved).toBe(Date.parse('2026-08-11T00:00:00Z'));
    expect(path.confidence).toBe(0.91);
    expect(findReadPath('a', 'missing', snapshot)).toBeNull();
    expect(findReadPath('a', 'c', { nodes: snapshot.nodes, edges: [] })).toBeNull();
  });

  it('scopes a trace to the neighbourhood of an object', () => {
    const snapshot = {
      status: 'ready' as const,
      clusters: [],
      nodes: [node('a', 'User'), node('b', 'User'), node('c', 'User'), node('d', 'User')],
      edges: [edge('1', 'a', 'b', 'K'), edge('2', 'b', 'c', 'K'), edge('3', 'c', 'd', 'K')],
    };
    expect(scopeSnapshot(snapshot, 'a', 2).nodes.map(n => n.id)).toEqual(['a', 'b', 'c']);
    expect(scopeSnapshot(snapshot, 'a', 2).edges.map(e => e.id)).toEqual(['1', '2']);
    expect(scopeSnapshot(snapshot, 'missing', 2)).toBe(snapshot);
    expect(scopeSnapshot(snapshot, null, 2)).toBe(snapshot);
  });

  it('makes initials for card avatars', () => {
    expect(initials('Jordan Smith')).toBe('JS');
    expect(initials('@trailandsummit')).toBe('TR');
    expect(initials('')).toBe('?');
  });
});

describe('Graph globe helpers', () => {
  const place = (key: string, lat: number, lng: number, nodeIds: string[]) => ({ key, label: key, lat, lng, nodeIds });

  it('merges links between two located places into one arc', () => {
    const atl = place('Atlanta, US', 33.7, -84.4, ['p1', 'p2']);
    const man = place('Manchester, UK', 53.5, -2.2, ['o1']);
    const arcs = placeArcs([atl, man], [
      edge('1', 'p1', 'o1', 'PURCHASED', { value: 418, valid_from: '2026-09-29T00:00:00Z' }),
      edge('2', 'o1', 'p2', 'SHIPS_TO'),
      edge('3', 'p1', 'p2', 'KNOWS'),
      edge('4', 'p1', 'nowhere', 'KNOWS'),
    ]);
    expect(arcs).toHaveLength(1);
    expect(arcs[0]).toMatchObject({ count: 2, value: 418, firstObserved: Date.parse('2026-09-29T00:00:00Z') });
  });

  it('never overlaps two globe labels and always labels the selected place', () => {
    const markers = [
      { place: place('Atlanta, US', 0, 0, ['a', 'b']), p: { x: 30, y: 50 }, size: 3 },
      { place: place('Boston, US', 0, 0, ['c']), p: { x: 31, y: 50.5 }, size: 2 },
      { place: place('New York, US', 0, 0, ['d']), p: { x: 30.5, y: 49.5 }, size: 2 },
      { place: place('Atlanta East, US', 0, 0, ['e']), p: { x: 30.2, y: 50.2 }, size: 2 },
      { place: place('Atlanta West, US', 0, 0, ['f']), p: { x: 30.1, y: 50.1 }, size: 2 },
    ];
    const labels = placeLabels(markers, 'Atlanta West, US');
    expect(labels.has('Atlanta West, US')).toBe(true);
    const boxes = [...labels.values()].map(l => {
      const w = l.text.length * 1.3;
      const x0 = l.anchor === 'start' ? l.x : l.anchor === 'end' ? l.x - w : l.x - w / 2;
      return { x0, x1: x0 + w, y0: l.y - 2.2, y1: l.y + 0.6 };
    });
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i]!;
        const b = boxes[j]!;
        expect(a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0).toBe(false);
      }
    }
    expect(labels.size).toBeLessThan(markers.length + 1);
  });
});
