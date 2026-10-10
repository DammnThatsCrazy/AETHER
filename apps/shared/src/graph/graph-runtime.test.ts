import { describe, it, expect } from 'vitest';
import cytoscape from 'cytoscape';
import {
  computeGraphDiff,
  applyGraphDiff,
  isEmptyDiff,
  placeIncrementalNodes,
  zoomLevelFor,
  type RuntimeElement,
} from './graph-runtime';

function node(id: string, extra: Record<string, unknown> = {}, classes?: string): RuntimeElement {
  return { group: 'nodes', data: { id, ...extra }, ...(classes ? { classes } : {}) };
}
function edge(id: string, source: string, target: string): RuntimeElement {
  return { group: 'edges', data: { id, source, target } };
}

describe('computeGraphDiff', () => {
  it('detects adds, removes, and updates by id', () => {
    const prev = [node('a', { label: 'A' }), node('b'), edge('e1', 'a', 'b')];
    const next = [node('a', { label: 'A2' }), node('c'), edge('e1', 'a', 'b')];
    const diff = computeGraphDiff(prev, next);
    expect(diff.added.map((e) => e.data.id)).toEqual(['c']);
    expect(diff.removedIds).toEqual(['b']);
    expect(diff.updated.map((e) => e.data.id)).toEqual(['a']);
    expect(diff.structuralChange).toBe(2);
  });

  it('is empty for identical element sets (no churn)', () => {
    const els = [node('a'), edge('e1', 'a', 'a')];
    expect(isEmptyDiff(computeGraphDiff(els, els))).toBe(true);
  });
});

describe('applyGraphDiff on a persistent instance', () => {
  it('applies adds/removes/updates while keeping the same instance', () => {
    const cy = cytoscape({ headless: true });
    const sameInstance = cy;

    applyGraphDiff(
      cy,
      computeGraphDiff([], [node('a', { label: 'A' }), node('b'), edge('e1', 'a', 'b')]),
    );
    expect(cy.nodes().map((n) => n.id()).sort()).toEqual(['a', 'b']);
    expect(cy.edges().length).toBe(1);

    applyGraphDiff(
      cy,
      computeGraphDiff(
        [node('a', { label: 'A' }), node('b'), edge('e1', 'a', 'b')],
        [node('a', { label: 'A2' }), node('c')],
      ),
    );

    // Instance identity is stable across updates — never destroyed/recreated.
    expect(cy).toBe(sameInstance);
    expect(cy.nodes().map((n) => n.id()).sort()).toEqual(['a', 'c']);
    expect(cy.getElementById('a').data('label')).toBe('A2');
    expect(cy.edges().length).toBe(0); // e1 dropped with its endpoint b
  });

  it('replaces node data wholesale so removed fields disappear (no stale merge)', () => {
    const cy = cytoscape({ headless: true });
    applyGraphDiff(cy, computeGraphDiff([], [node('a', { label: 'A', score: 0.9 })]));
    expect(cy.getElementById('a').data('score')).toBe(0.9);

    // The score field is gone in the next snapshot — it must not linger and keep
    // coloring risk/trust overlays from stale data.
    applyGraphDiff(
      cy,
      computeGraphDiff([node('a', { label: 'A', score: 0.9 })], [node('a', { label: 'A' })]),
    );
    expect(cy.getElementById('a').data('score')).toBeUndefined();
    expect(cy.getElementById('a').data('label')).toBe('A');
    expect(cy.getElementById('a').data('id')).toBe('a'); // id preserved
  });

  it('recreates an edge whose endpoints changed (in-place data() cannot move it)', () => {
    const cy = cytoscape({ headless: true });
    const before = [node('a'), node('b'), node('c'), edge('e1', 'a', 'b')];
    applyGraphDiff(cy, computeGraphDiff([], before));
    expect(cy.getElementById('e1').source().id()).toBe('a');
    expect(cy.getElementById('e1').target().id()).toBe('b');

    // e1 keeps its id but reassigns target b -> c.
    applyGraphDiff(cy, computeGraphDiff(before, [node('a'), node('b'), node('c'), edge('e1', 'a', 'c')]));
    const e = cy.getElementById('e1');
    expect(e.length).toBe(1);
    expect(e.data('source')).toBe('a');
    expect(e.data('target')).toBe('c');
    expect(e.source().id()).toBe('a'); // rendered endpoint actually moved
    expect(e.target().id()).toBe('c');
  });

  it('recreates an endpoint-changed edge onto a node added in the same diff', () => {
    const cy = cytoscape({ headless: true });
    const before = [node('a'), node('b'), edge('e1', 'a', 'b')];
    applyGraphDiff(cy, computeGraphDiff([], before));

    // e1 now points a -> d, where d is a brand-new node in the same diff. The
    // recreated edge must be added AFTER the new node exists, or cytoscape throws.
    applyGraphDiff(cy, computeGraphDiff(before, [node('a'), node('b'), node('d'), edge('e1', 'a', 'd')]));
    const e = cy.getElementById('e1');
    expect(e.length).toBe(1);
    expect(e.target().id()).toBe('d');
  });
});

describe('placeIncrementalNodes', () => {
  function positionedGraph() {
    const cy = cytoscape({ headless: true });
    cy.add([
      { group: 'nodes', data: { id: 'a' }, position: { x: 100, y: 100 } },
      { group: 'nodes', data: { id: 'b' }, position: { x: 300, y: 100 } },
      { group: 'edges', data: { id: 'ab', source: 'a', target: 'b' } },
    ]);
    return cy;
  }

  it('places a new node next to an already-positioned neighbour, not at the origin', () => {
    const cy = positionedGraph();
    cy.add([
      { group: 'nodes', data: { id: 'c' } }, // cytoscape drops it at (0,0)
      { group: 'edges', data: { id: 'ac', source: 'a', target: 'c' } },
    ]);
    placeIncrementalNodes(cy, ['c']);

    const p = cy.getElementById('c').position();
    expect(p.x === 0 && p.y === 0).toBe(false);
    const a = cy.getElementById('a').position();
    const dist = Math.hypot(p.x - a.x, p.y - a.y);
    expect(dist).toBeLessThanOrEqual(60); // anchored on neighbour a
  });

  it('falls back to the centre of the existing graph when a node has no neighbour', () => {
    const cy = positionedGraph();
    cy.add({ group: 'nodes', data: { id: 'x' } }); // isolated
    placeIncrementalNodes(cy, ['x']);

    const p = cy.getElementById('x').position();
    expect(p.x === 0 && p.y === 0).toBe(false);
    // Existing nodes centre on (200, 100); the placement anchors there, not (0,0).
    expect(Math.hypot(p.x - 200, p.y - 100)).toBeLessThanOrEqual(60);
  });

  it('is a no-op with no added ids', () => {
    const cy = positionedGraph();
    expect(() => placeIncrementalNodes(cy, [])).not.toThrow();
    expect(cy.getElementById('a').position()).toEqual({ x: 100, y: 100 });
  });
});

describe('zoomLevelFor (semantic zoom)', () => {
  it('maps viewport zoom to a semantic detail level', () => {
    expect(zoomLevelFor(0.3)).toBe('macro');
    expect(zoomLevelFor(0.8)).toBe('meso');
    expect(zoomLevelFor(1.5)).toBe('detail');
  });

  it('honours custom thresholds', () => {
    expect(zoomLevelFor(2, { meso: 1, detail: 3 })).toBe('meso');
    expect(zoomLevelFor(0.5, { meso: 1, detail: 3 })).toBe('macro');
  });
});
