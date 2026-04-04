import { describe, it, expect } from 'vitest';
import type { ActionClass } from '@shiki/types';

describe('ActionClass', () => {
  it('represents 6 levels from 0 to 5', () => {
    const classes: ActionClass[] = [0, 1, 2, 3, 4, 5];
    expect(classes.length).toBe(6);
    expect(classes[0]).toBe(0);
    expect(classes[5]).toBe(5);
  });

  const classDescriptions: Record<ActionClass, string> = {
    0: 'read-only',
    1: 'safe additive automation',
    2: 'moderate enrichment',
    3: 'operational interventions',
    4: 'graph-sensitive changes',
    5: 'destructive / compliance / legal',
  };

  it('has descriptions for all classes', () => {
    expect(Object.keys(classDescriptions)).toHaveLength(6);
  });
});
