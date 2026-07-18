import { describe, it, expect } from 'vitest';
import cytoscape from 'cytoscape';
import {
  computeGraphDiff,
  applyGraphDiff,
  isEmptyDiff,
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
