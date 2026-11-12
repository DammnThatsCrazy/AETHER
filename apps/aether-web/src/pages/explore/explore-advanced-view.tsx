import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { GraphContext, GraphObjectRef } from '@aether/shared/graph-context-contract';
import {
  GraphTimeRail,
  NoesisContextStrip,
  allBlueprintLenses,
  FilterBar,
  FilterBuilder,
  resolveLensAvailability,
  useExplorationFilters,
  useGraph,
  useGraphActions,
  useGraphContext,
  useGraphHistory,
} from '@aether/ui/exploration';
import type { LensResolution } from '@aether/ui/exploration';
import { GraphPage } from '@aether-app/pages/graph/graph-page';
import { deriveGraphMaturity, useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import type { GraphEdge, GraphNode } from '@aether-app/components/graph/graph-canvas';
import type { GraphCluster } from '@aether-app/features/graph/use-graph-data';
import { ExploreSnapshotControls } from '@aether-app/features/graph/explore-snapshot-controls';
import { Eyebrow, Panel, TonePill, type Tone } from '@aether-app/components/ae-ui';

export function temporalLabel(context: GraphContext): string {
  const temporal = context.temporal;
  if (temporal.mode === 'as_of') return temporal.as_of ? `As of ${temporal.as_of}` : 'Point-in-time graph';
  if (temporal.mode === 'compare') return temporal.compare_to ? `Compared with ${temporal.compare_to}` : 'Comparison graph';
  if (temporal.mode === 'relative') return `Relative ${temporal.field}`;
  return `Window · ${temporal.field}`;
}

interface ScopeLabels {
  readonly tenant: string;
  readonly workspace: string;
  readonly environment: string;
  readonly account?: string;
  readonly organization?: string;
}

export function scopeLabels(context: GraphContext): ScopeLabels {
  const scope = context.scope;
  return {
    tenant: scope.tenant_id,
    workspace: scope.workspace_id,
    environment: scope.environment_id,
    ...(scope.account_id ? { account: scope.account_id } : {}),
    ...(scope.organization_id ? { organization: scope.organization_id } : {}),
  };
}

const mute = { color: 'var(--ae-mute)' } as const;

export function ContextPill({ name, value }: { readonly name: string; readonly value: string }) {
  const available = value.trim().length > 0;
  return (
    <span
      className="ae-card inline-flex min-w-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-[12px]"
      data-context-key={name.toLowerCase()}
      data-availability={available ? 'available' : 'unavailable'}
      aria-label={`${name}: ${available ? value : 'Unavailable'}`}
    >
      <span style={mute}>{name}</span>
      <span className="truncate">{available ? value : 'Unavailable'}</span>
    </span>
  );
}

// ── Graph maturity (tenant readiness) ───────────────────────────────────────

export function GraphMaturityPanel() {
  const { data, isLoading, error } = useTenantReadiness();

  let tone: Tone = 'mute';
  let label = 'Checking';
  let body: ReactNode;
  if (isLoading && !data) {
    body = <p data-testid="graph-maturity-loading">Checking graph foundations…</p>;
  } else if (error) {
    tone = 'amber';
    label = 'Unavailable';
    body = <p data-testid="graph-maturity-error">Graph foundation readiness could not be checked.</p>;
  } else if (!data) {
    tone = 'amber';
    label = 'Unavailable';
    body = <p data-testid="graph-maturity-unavailable">Graph foundation readiness is unavailable.</p>;
  } else {
    const maturity = deriveGraphMaturity(data);
    if (maturity.state === 'no_data') {
      tone = 'blue';
      label = 'No data yet';
      body = (
        <div data-testid="graph-maturity-no-data" className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p>The graph needs observed events and links before it can mature.</p>
          <Link className="ae-focus hover:underline" style={{ color: 'var(--ae-blue-ink)' }} to="/activate">
            Connect a source in Activation
          </Link>
        </div>
      );
    } else if (maturity.state === 'building') {
      tone = 'amber';
      label = 'Building';
      body = (
        <div data-testid="graph-maturity-building">
          <p>Graph foundations are building — {maturity.blocking.length} check{maturity.blocking.length === 1 ? '' : 's'} still blocking verification.</p>
          <ul className="mt-1 flex flex-wrap gap-1.5" aria-label="Blocking graph foundation checks">
            {maturity.blocking.map((check) => (
              <li key={check} className="ae-mono rounded-full px-2 py-px text-[11px]" style={{ background: 'var(--ae-amber-tint)', color: 'var(--ae-amber)' }}>{check}</li>
            ))}
          </ul>
        </div>
      );
    } else {
      tone = 'sage';
      label = 'Verified';
      body = <p data-testid="graph-maturity-ready">Graph foundations are verified.</p>;
    }
  }

  return (
    <section data-testid="graph-maturity-panel" className="ae-card flex flex-wrap items-start gap-x-3 gap-y-1 rounded-2xl px-4 py-3 text-[13px]">
      <span className="flex items-center gap-2">
        <Eyebrow>Graph maturity</Eyebrow>
        <TonePill tone={tone}>{label}</TonePill>
      </span>
      <div className="min-w-0 flex-1" style={mute}>{body}</div>
    </section>
  );
}

// ── Registered lens registry + query builder ───────────────────────────────

function lensStatusLabel(resolution: LensResolution): string {
  if (resolution.availability === 'available') return 'Available';
  if (resolution.availability === 'not_entitled') return 'Not included';
  if (resolution.availability === 'unauthorized') return 'No access';
  return resolution.entry?.pending ? 'Pending engine binding' : 'Not ready';
}

function lensStatusTone(resolution: LensResolution): Tone {
  if (resolution.availability === 'available') return 'sage';
  if (resolution.availability === 'not_entitled' || resolution.availability === 'unauthorized') return 'mute';
  return 'amber';
}

function RegistryPanel({ objectKind }: { readonly objectKind: string }) {
  const { population, addFilter, removeFilterAt, setPopulation } = useExplorationFilters();
  const resolutions = useMemo(() => allBlueprintLenses().map((lens) => resolveLensAvailability(lens.id, {
    objectKind,
    surfaceId: 'graph',
    // Capability and readiness facts are intentionally absent here: the
    // registry resolver must represent those lenses as not-ready, never infer
    // entitlement from the presence of a UI control.
    temporalMode: 'window',
  })), [objectKind]);
  return (
    <Panel className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex flex-col gap-0.5">
          <Eyebrow>Registered lenses</Eyebrow>
          <span className="text-[12px]" style={mute}>Registry availability for this graph context. Unavailable lenses stay visible with their state.</span>
        </span>
        <span className="ae-mono text-[11px]" style={mute} data-testid="lens-object-kind">{objectKind}</span>
      </div>
      <div className="flex flex-col" role="list" aria-label="Registered graph lenses">
        {resolutions.map((resolution) => {
          const entry = resolution.entry;
          if (!entry) return null;
          return (
            <div
              key={resolution.lensId}
              role="listitem"
              data-lens-availability={resolution.availability}
              className="flex items-center justify-between gap-2 border-t py-2 text-[13px]"
              style={{ borderColor: 'var(--ae-edge-soft)' }}
            >
              <span className="truncate">{entry.displayName}</span>
              <TonePill tone={lensStatusTone(resolution)}>{lensStatusLabel(resolution)}</TonePill>
            </div>
          );
        })}
      </div>
      <details className="rounded-xl border" style={{ borderColor: 'var(--ae-edge)' }} data-testid="graph-query-controls">
        <summary className="ae-focus cursor-pointer px-3 py-2 text-[13px] font-medium">Query builder</summary>
        <div className="flex flex-col gap-2 border-t p-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
          <FilterBar
            population={population}
            onRemove={removeFilterAt}
            onClear={() => setPopulation(null)}
          />
          <FilterBuilder surface="graph" onAdd={addFilter} />
        </div>
      </details>
    </Panel>
  );
}

// ── Advanced explorer (`/explore?view=advanced`) ────────────────────────────

/**
 * The full Entity Graph explorer, registered-lens list, query builder and
 * snapshot controls, kept behind `?view=advanced` so the Graph page itself can
 * follow the design (cards, inspector, path strip). GraphPage is composed, not
 * reimplemented: its loading, empty, error, truth, table, path finder, canvas
 * and inspector behaviour stays the source of truth here.
 */
export function ExploreAdvancedView({ onBack }: { readonly onBack: () => void }) {
  const navigate = useNavigate();
  const context = useGraphContext();
  const graph = useGraph();
  const history = useGraphHistory();
  const actions = useGraphActions();
  const [noesisExpanded, setNoesisExpanded] = useState(false);

  const labels = useMemo(() => scopeLabels(context), [context]);
  const currentFocus = context.selection.focused;
  const historyEntries = history.entries;
  const currentTemporalLabel = temporalLabel(context);
  const selectedObjectKind = currentFocus?.kind ?? 'entity';
  // Context navigation keeps the advanced view: the graph query owns every
  // other parameter, and dropping `view` would bounce the analyst back out.
  const navigateWithContext = useCallback(() => {
    const query = graph.toQuery();
    navigate(query ? `/explore?${query}&view=advanced` : '/explore?view=advanced');
  }, [graph, navigate]);
  const selectGraphObject = useCallback((object: Pick<GraphObjectRef, 'id' | 'kind'>) => {
    const ref = {
      tenant_id: context.scope.tenant_id,
      environment_id: context.scope.environment_id,
      kind: object.kind,
      id: object.id,
    } satisfies GraphObjectRef;
    actions.selectObject(ref);
    actions.focusObject(ref);
    actions.appendHistory({
      object: ref,
      action: 'select',
      occurred_at: new Date().toISOString(),
    });
    navigateWithContext();
  }, [actions, context.scope.environment_id, context.scope.tenant_id, navigateWithContext]);
  const handleObjectSelected = useCallback((node: GraphNode) => selectGraphObject(node), [selectGraphObject]);
  const handleClusterSelected = useCallback((cluster: GraphCluster) => {
    selectGraphObject({ id: cluster.id, kind: 'cluster' });
  }, [selectGraphObject]);
  const handleEdgeSelected = useCallback((edge: GraphEdge) => {
    selectGraphObject({ id: edge.id, kind: 'edge' });
  }, [selectGraphObject]);

  function moveThroughHistory(direction: 'previous' | 'next') {
    const next = direction === 'previous'
      ? actions.previousFocus(currentFocus)
      : actions.nextFocus(currentFocus);
    if (!next) return;
    actions.focusObject(next);
    navigateWithContext();
  }

  const historyPosition = currentFocus
    ? historyEntries.findIndex((entry) => entry.object.id === currentFocus.id) + 1
    : historyEntries.length;

  return (
    <div data-testid="explore-advanced" className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <button type="button" onClick={onBack} className="ae-focus self-start text-[12px] hover:underline" style={mute}>← Graph</button>
          <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">Advanced explorer</h1>
          <span className="text-[14px]" style={mute}>Canvas, table, path finder, registered lenses, query builder and snapshots.</span>
        </div>
        <div className="flex min-w-0 flex-wrap items-center gap-2" data-testid="graph-context-bar" role="list" aria-label="Graph context">
          <ContextPill name="Workspace" value={labels.workspace} />
          <ContextPill name="Environment" value={labels.environment} />
          <ContextPill name="Time" value={currentTemporalLabel} />
        </div>
      </div>

      <GraphMaturityPanel />

      <section data-testid="graph-workspace-frame" aria-label="Graph workspace" className="ae-glass-card flex min-w-0 flex-col overflow-hidden rounded-[22px]">
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
          <span className="flex flex-col gap-0.5">
            <Eyebrow>Explorer</Eyebrow>
            <span className="text-[12px]" style={mute}>Every object and relationship in this read: canvas, table, path finder and inspector.</span>
          </span>
        </div>
        <div className="min-w-0">
          <GraphPage
            embedded
            onObjectSelected={handleObjectSelected}
            onClusterSelected={handleClusterSelected}
            onEdgeSelected={handleEdgeSelected}
          />
        </div>
        <GraphTimeRail
          context={context}
          temporal={context.temporal}
          historyPosition={historyPosition}
          historyCount={historyEntries.length}
          onPrevious={() => moveThroughHistory('previous')}
          onNext={() => moveThroughHistory('next')}
        />
        <NoesisContextStrip
          contextChips={[
            labels.workspace,
            labels.environment,
            currentTemporalLabel,
            ...(currentFocus ? [`Focus · ${currentFocus.kind}:${currentFocus.id}`] : []),
          ]}
          expanded={noesisExpanded}
          onToggle={() => setNoesisExpanded((expanded) => !expanded)}
        >
          {noesisExpanded && (
            <div data-testid="noesis-context-expanded" className="flex flex-wrap items-center gap-2 py-2 text-[12px]" style={mute}>
              <span>Noesis opens with this graph context. Query and context handoff remain read-only until an explicit action is chosen.</span>
              <button
                type="button"
                className="ae-focus hover:underline"
                style={{ color: 'var(--ae-blue-ink)' }}
                onClick={() => {
                  const query = graph.toQuery();
                  navigate(query ? `/noesis?${query}` : '/noesis');
                }}
              >
                Open Noesis
              </button>
            </div>
          )}
        </NoesisContextStrip>
      </section>

      <RegistryPanel objectKind={selectedObjectKind} />

      <ExploreSnapshotControls />
    </div>
  );
}

