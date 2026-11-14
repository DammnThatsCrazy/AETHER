import { describe, expect, it } from 'vitest';
import {
  buildFlow,
  buildPlaces,
  defaultLens,
  flowColumn,
  indexGraph,
  lensRows,
  objectLinks,
} from '@aether-app/pages/explore/explore-model';

const node = (id: string, kind: string, metadata: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({ id, kind, label: id, metadata, ...extra });
const edge = (id: string, source: string, target: string, relationType: string, metadata: Record<string, unknown> = {}) => ({
  id, source, target, relationType, interactionClass: 'H2A', weight: 1, metadata,
});

describe('Graph explore model', () => {
  it('places kinds in the left-to-right lanes', () => {
    expect(flowColumn('entity')).toBe('people');
    expect(flowColumn('Device')).toBe('people');
    expect(flowColumn('Agent')).toBe('agents');
    expect(flowColumn('Wallet')).toBe('agents');
    expect(flowColumn('Organization')).toBe('destinations');
    expect(flowColumn('Session')).toBe('sources');
  });

  it('only enables lenses whose inputs are present in the read', () => {
    const bare = indexGraph({ nodes: [node('a', 'entity')], edges: [] });
    expect(Object.values(bare.lenses).every(l => !l.available)).toBe(true);
    expect(defaultLens(bare)).toBe('activity');

    const rich = indexGraph({
      nodes: [node('p', 'entity', { value: 120 }, { riskScore: 0.2 }), node('a', 'Agent')],
      edges: [edge('e', 'p', 'a', 'DELEGATES', { valid_from: '2026-09-01T00:00:00Z' })],
    });
    expect(rich.lenses.value.available).toBe(true);
    expect(rich.lenses.activity.available).toBe(true);
    expect(rich.lenses.authority.available).toBe(true);
    expect(rich.lenses.risk.available).toBe(true);
    expect(rich.lenses.time.available).toBe(true);
    expect(rich.timeRange).toEqual([Date.parse('2026-09-01T00:00:00Z'), Date.parse('2026-09-01T00:00:00Z')]);
  });

  it('caps each lane, reports what it left out and fades links after the replay cutoff', () => {
    const people = Array.from({ length: 9 }, (_, i) => node(`p${i}`, 'entity'));
    const snapshot = {
      nodes: [...people, node('a', 'Agent')],
      edges: [
        edge('e1', 'p0', 'a', 'DELEGATES', { valid_from: '2026-09-01T00:00:00Z' }),
        edge('e2', 'p1', 'a', 'DELEGATES', { valid_from: '2026-09-10T00:00:00Z' }),
      ],
    };
    const index = indexGraph(snapshot);
    const flow = buildFlow(snapshot, index, 'activity', { perColumn: 7, cutoff: Date.parse('2026-09-05T00:00:00Z') });
    const lane = flow.columns.find(c => c.id === 'people')!;
    expect(lane.total).toBe(9);
    expect(lane.hidden).toBe(2);
    expect(flow.links).toHaveLength(2);
    expect(flow.links.find(l => l.source === 'p1')?.pending).toBe(true);
    expect(flow.links.find(l => l.source === 'p0')?.pending).toBe(false);
  });

  it('groups places and counts objects with no location as unknown', () => {
    const summary = buildPlaces([
      node('a', 'entity', { city: 'Atlanta', country: 'US', latitude: 33.7, longitude: -84.4 }),
      node('b', 'entity', { city: 'Atlanta', country: 'US' }),
      node('c', 'entity'),
    ]);
    expect(summary.places).toHaveLength(1);
    expect(summary.places[0]).toMatchObject({ label: 'Atlanta, US', lat: 33.7, nodeIds: ['a', 'b'] });
    expect(summary.unknown).toBe(1);
  });

  it('ranks lens rows from real measures only', () => {
    const snapshot = { nodes: [node('x', 'entity', {}, { riskScore: 0.9 }), node('y', 'entity', {}, { riskScore: 0.3 }), node('z', 'entity')], edges: [] };
    const rows = lensRows(snapshot, indexGraph(snapshot), 'risk');
    expect(rows.map(r => r.id)).toEqual(['x', 'y']);
  });

  it('links objects only to routes that exist', () => {
    expect(objectLinks(node('e1', 'entity'), []).map(l => l.to)).toEqual(['/users/e1']);
    expect(objectLinks(node('ag', 'Agent'), []).map(l => l.to)).toEqual(['/agents/ag']);
    expect(objectLinks(node('w', 'Wallet'), [])).toEqual([]);
  });
});
