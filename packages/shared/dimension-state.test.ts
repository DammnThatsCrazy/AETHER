import { describe, expect, it } from 'vitest';
import {
  dimensionReasonCodes,
  dimensionStatePrecedence,
  dimensionStates,
  worstDimensionState,
} from './dimension-state';

describe('dimension-state', () => {
  it('precedence covers every state exactly once', () => {
    expect([...dimensionStatePrecedence].sort()).toEqual([...dimensionStates].sort());
    expect(dimensionStatePrecedence.length).toBe(dimensionStates.length);
  });

  it('orders precedence best-first and worst-last', () => {
    expect(dimensionStatePrecedence[0]).toBe('ready');
    expect(dimensionStatePrecedence[dimensionStatePrecedence.length - 1]).toBe('error');
  });

  it('worstDimensionState picks the worst state', () => {
    expect(worstDimensionState(['ready', 'empty', 'error'])).toBe('error');
    expect(worstDimensionState(['ready', 'stale'])).toBe('stale');
    expect(worstDimensionState([])).toBe('ready');
    expect(worstDimensionState(['ready', 'ready'])).toBe('ready');
  });

  it('exposes the canonical reason codes', () => {
    expect(dimensionReasonCodes).toContain('past_freshness_sla');
    expect(dimensionReasonCodes).toContain('dependency_failed');
    expect(dimensionReasonCodes).toContain('ok');
  });
});
