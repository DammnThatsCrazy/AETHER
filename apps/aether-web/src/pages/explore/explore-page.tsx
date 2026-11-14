import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import type { GraphObjectRef } from '@aether/shared/graph-context-contract';
import { useGraphActions, useGraphContext } from '@aether/ui/exploration';
import type { GraphNode } from '@aether-app/components/graph/graph-canvas';
import { ExploreAdvancedView } from './explore-advanced-view';
import { ExploreNetworkView } from './explore-network-view';
import { useExploreGraphRead } from './explore-read';
import { ExploreTraceView, type TraceVisual } from './explore-trace-view';

/**
 * Graph (`/explore`; Claude Design handoff: Aether Explore → Graph, Aether
 * Graph Trace). One route, three views chosen by `?view=`:
 *
 * - default: the network view — toolbar, principal cards, inspector, path strip;
 * - `view=trace`: the flow, globe, lenses and replay, scoped to `entity` when
 *   present (`tv=globe|flow|both` picks the visual);
 * - `view=advanced`: the Entity Graph explorer, registered lenses, query
 *   builder and snapshots (GraphPage composed as before).
 *
 * Existing deep links keep working: `entity` / `selected_entity` scope the
 * network view (and still deep-select inside the advanced explorer), `cluster`
 * and every graph-context parameter are left in place for GraphPage and the
 * graph provider.
 */
export function ExplorePage() {
  const [params, setParams] = useSearchParams();
  const context = useGraphContext();
  const actions = useGraphActions();
  const view = params.get('view');
  const scopeId = params.get('entity') ?? params.get('selected_entity');

  const update = useCallback((mutate: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(params);
    mutate(next);
    setParams(next);
  }, [params, setParams]);

  const setView = useCallback((value: string | null, extra?: (next: URLSearchParams) => void) => update(next => {
    if (value) next.set('view', value);
    else next.delete('view');
    if (value !== 'trace') next.delete('tv');
    extra?.(next);
  }), [update]);

  const setScope = useCallback((id: string | null) => update(next => {
    next.delete('selected_entity');
    if (id) next.set('entity', id);
    else next.delete('entity');
  }), [update]);

  const selectObject = useCallback((node: Pick<GraphNode, 'id' | 'kind'>) => {
    const ref = {
      tenant_id: context.scope.tenant_id,
      environment_id: context.scope.environment_id,
      kind: node.kind,
      id: node.id,
    } satisfies GraphObjectRef;
    actions.selectObject(ref);
    actions.focusObject(ref);
  }, [actions, context.scope.environment_id, context.scope.tenant_id]);

  if (view === 'advanced') {
    return <ExploreAdvancedView onBack={() => setView(null)} />;
  }
  return <ExploreReadViews view={view} scopeId={scopeId} params={params} setView={setView} setScope={setScope} selectObject={selectObject} />;
}

/** Views drawn from the page's one graph read (kept apart so the advanced explorer does not double-read). */
function ExploreReadViews({ view, scopeId, params, setView, setScope, selectObject }: {
  readonly view: string | null;
  readonly scopeId: string | null;
  readonly params: URLSearchParams;
  readonly setView: (value: string | null, extra?: (next: URLSearchParams) => void) => void;
  readonly setScope: (id: string | null) => void;
  readonly selectObject: (node: Pick<GraphNode, 'id' | 'kind'>) => void;
}) {
  const snapshot = useExploreGraphRead();
  const openTrace = (id: string | null, visual: TraceVisual) => setView('trace', next => {
    next.set('tv', visual);
    next.delete('selected_entity');
    if (id) next.set('entity', id);
  });

  if (view === 'trace') {
    const tv = params.get('tv');
    const visual: TraceVisual = tv === 'flow' || tv === 'both' ? tv : 'globe';
    return (
      <ExploreTraceView
        snapshot={snapshot}
        scopeId={scopeId}
        visual={visual}
        onVisual={(v) => openTrace(scopeId, v)}
        onBack={() => setView(null)}
        onShowInGraph={(node) => {
          selectObject(node);
          setView(null, next => { next.delete('selected_entity'); next.set('entity', node.id); });
        }}
      />
    );
  }

  return (
    <ExploreNetworkView
      snapshot={snapshot}
      scopeId={scopeId}
      onScope={setScope}
      onSelectObject={selectObject}
      onOpenTrace={openTrace}
      onOpenAdvanced={() => setView('advanced')}
    />
  );
}
