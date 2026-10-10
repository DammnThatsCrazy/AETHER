import type { ExplorationTrailEntry, GraphObjectRef } from '@aether/shared/graph-context-contract';
import type { SelectionScope } from './selection-model';

export const DEFAULT_EXPLORATION_TRAIL_MAX = 50;
export const MAX_EXPLORATION_TRAIL_ENTRIES = DEFAULT_EXPLORATION_TRAIL_MAX;
export interface ExplorationHistory {
  readonly scope: SelectionScope;
  readonly entries: readonly ExplorationTrailEntry[];
}
const sameScope = (a: SelectionScope, b: SelectionScope): boolean => a.tenant_id === b.tenant_id
  && a.workspace_id === b.workspace_id && a.environment_id === b.environment_id;
const sameRef = (a: GraphObjectRef, b: GraphObjectRef): boolean => a.tenant_id === b.tenant_id && a.environment_id === b.environment_id && a.kind === b.kind && a.id === b.id;
const validMax = (max: number): number => Number.isInteger(max) && max > 0 ? max : DEFAULT_EXPLORATION_TRAIL_MAX;

function assertScope(scope: SelectionScope): void {
  for (const key of ['tenant_id', 'workspace_id', 'environment_id'] as const) {
    if (typeof scope[key] !== 'string' || scope[key].length === 0) throw new Error(`active scope ${key} is required`);
  }
}

function entryInScope(entry: ExplorationTrailEntry, scope: SelectionScope): boolean {
  const object = entry?.object;
  return Boolean(object && object.tenant_id && object.environment_id && object.kind && object.id
    && object.tenant_id === scope.tenant_id && object.environment_id === scope.environment_id);
}

function validateHistory(history: ExplorationHistory): void {
  assertScope(history.scope);
  if (history.entries.some((entry) => !entryInScope(entry, history.scope))) {
    throw new Error('Exploration trail entry is outside the active scope');
  }
}

export function createExplorationHistory(scope: SelectionScope, entries: readonly ExplorationTrailEntry[] = []): ExplorationHistory {
  assertScope(scope);
  if (entries.some((entry) => !entryInScope(entry, scope))) {
    throw new Error('Exploration trail entry is outside the active scope');
  }
  return { scope: { ...scope }, entries: entries.slice(-DEFAULT_EXPLORATION_TRAIL_MAX) };
}
export function appendTrail(
  history: ExplorationHistory,
  entry: ExplorationTrailEntry,
  activeScope: SelectionScope,
  max = DEFAULT_EXPLORATION_TRAIL_MAX,
): ExplorationHistory {
  validateHistory(history);
  assertScope(activeScope);
  if (!entryInScope(entry, activeScope)) {
    throw new Error('Exploration trail entry is outside the active scope');
  }
  if (!sameScope(history.scope, activeScope)) {
    return { scope: { ...activeScope }, entries: [entry].slice(-validMax(max)) };
  }
  const deduped = history.entries.filter((item) => !sameRef(item.object, entry.object));
  return { scope: { ...history.scope }, entries: [...deduped, entry].slice(-validMax(max)) };
}
export function clearHistory(scope: SelectionScope): ExplorationHistory {
  assertScope(scope);
  return { scope: { ...scope }, entries: [] };
}

export function previousFocus(entries: readonly ExplorationTrailEntry[], current: GraphObjectRef | null = null): GraphObjectRef | null {
  const end = current ? entries.findIndex((entry) => sameRef(entry.object, current)) : entries.length;
  for (let i = (end < 0 ? entries.length : end) - 1; i >= 0; i -= 1) if (!current || !sameRef(entries[i]!.object, current)) return entries[i]!.object;
  return null;
}
export function nextFocus(entries: readonly ExplorationTrailEntry[], current: GraphObjectRef | null = null): GraphObjectRef | null {
  const start = current ? entries.findIndex((entry) => sameRef(entry.object, current)) : -1;
  for (let i = start + 1; i < entries.length; i += 1) if (!current || !sameRef(entries[i]!.object, current)) return entries[i]!.object;
  return null;
}
