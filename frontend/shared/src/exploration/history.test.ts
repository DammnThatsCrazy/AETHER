import { describe, expect, it } from 'vitest';
import { appendTrail, clearHistory, createExplorationHistory, nextFocus, previousFocus } from './history';
import type { ExplorationTrailEntry } from '@aether/shared/graph-context-contract';

const scope = { tenant_id: 't1', environment_id: 'staging' } as const;
const entry = (id: string, occurred_at = `2026-01-0${id}T00:00:00Z`): ExplorationTrailEntry => ({ object: { ...scope, kind: 'entity', id }, action: 'open', occurred_at });

describe('exploration history', () => {
  it('dedupes by object, keeps newest occurrence, and caps oldest entries', () => {
    let history = createExplorationHistory(scope);
    history = appendTrail(history, entry('1'), 2); history = appendTrail(history, entry('2'), 2); history = appendTrail(history, entry('1', 'later'), 2);
    expect(history.entries.map((item) => item.object.id)).toEqual(['2', '1']);
    expect(history.entries[1]?.occurred_at).toBe('later');
  });
  it('offers previous and next focus helpers without mutation', () => {
    const entries = [entry('1'), entry('2'), entry('3')];
    expect(previousFocus(entries, entries[1]!.object)?.id).toBe('1');
    expect(nextFocus(entries, entries[1]!.object)?.id).toBe('3');
    expect(entries).toHaveLength(3);
  });
  it('clears trail on scope change', () => {
    const history = appendTrail(appendTrail(createExplorationHistory(scope), entry('1')), { ...entry('2'), object: { ...entry('2').object, tenant_id: 't2' } });
    expect(history.entries.map((item) => item.object.id)).toEqual(['2']);
    expect(clearHistory({ tenant_id: 't2', environment_id: 'prod' }).entries).toEqual([]);
  });
});
