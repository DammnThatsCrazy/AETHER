import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { GraphContext } from '@aether/shared/graph-context-contract';
import {
  GraphContextBar,
  GraphTimeRail,
  GraphWorkspaceFrame,
  NoesisContextStrip,
  allBlueprintLenses,
  resolveLensAvailability,
  useGraphActions,
  useGraphContext,
  useGraphHistory,
} from '@aether/ui/exploration';
import { GraphPage } from '@aether-app/pages/graph/graph-page';
import { deriveGraphMaturity, useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import type { LensResolution } from '@aether/ui/exploration';
import type { GraphNode } from '@aether-app/components/graph/graph-canvas';

function temporalLabel(context: GraphContext): string {
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

function scopeLabels(context: GraphContext): ScopeLabels {
  const scope = context.scope;
  return {
    tenant: scope.tenant_id,
    workspace: scope.workspace_id,
    environment: scope.environment_id,
    ...(scope.account_id ? { account: scope.account_id } : {}),
    ...(scope.organization_id ? { organization: scope.organization_id } : {}),
  };
}

function objectRoute(id: string): string {
  return `/explore?entity=${encodeURIComponent(id)}`;
}

function GraphMaturityPanel() {
  const { data, isLoading, error } = useTenantReadiness();

  let body: ReactNode;
  if (isLoading && !data) {
    body = <p data-testid="graph-maturity-loading">Checking graph foundations…</p>;
  } else if (error) {
    body = <p data-testid="graph-maturity-error">Graph foundation readiness could not be checked.</p>;
  } else if (!data) {
    body = <p data-testid="graph-maturity-unavailable">Graph foundation readiness is unavailable.</p>;
  } else {
    const maturity = deriveGraphMaturity(data);
    if (maturity.state === 'no_data') {
      body = (
        <div data-testid="graph-maturity-no-data">
          <p>The graph needs observed events and links before it can mature.</p>
          <Link className="mt-1 inline-block text-accent underline hover:text-text-primary" to="/activate">
            Connect a source in Activation
          </Link>
        </div>
      );
    } else if (maturity.state === 'building') {
      body = (
        <div data-testid="graph-maturity-building">
          <p>Graph foundations are building — {maturity.blocking.length} check{maturity.blocking.length === 1 ? '' : 's'} still blocking verification.</p>
          <ul className="mt-1 list-inside list-disc" aria-label="Blocking graph foundation checks">
            {maturity.blocking.map((check) => <li key={check}>{check}</li>)}
          </ul>
        </div>
      );
    } else {
      body = <p data-testid="graph-maturity-ready">Graph foundations are verified.</p>;
    }
  }

  return (
    <section data-testid="graph-maturity-panel" className="mb-3 rounded border border-border-subtle p-3 text-xs text-text-secondary">
      <p className="font-medium text-text-primary">Graph maturity</p>
      <div className="mt-1">{body}</div>
    </section>
  );
}

function lensStatusLabel(resolution: LensResolution): string {
  if (resolution.availability === 'available') return 'Available';
  if (resolution.availability === 'not_entitled') return 'Not included';
  if (resolution.availability === 'unauthorized') return 'No access';
  return resolution.entry?.pending ? 'Pending engine binding' : 'Not ready';
}

function LensDock({ objectKind }: {
  readonly objectKind: string;
}) {
  const resolutions = useMemo(() => allBlueprintLenses().map((lens) => resolveLensAvailability(lens.id, {
    objectKind,
    surfaceId: 'graph',
    // Capability and readiness facts are intentionally absent here: the
    // registry resolver must represent those lenses as not-ready, never infer
    // entitlement from the presence of a UI control.
    temporalMode: 'window',
  })), [objectKind]);
  return (
    <div className="p-3 text-xs text-text-secondary">
      <GraphMaturityPanel />
      <div className="flex items-center justify-between gap-2">
        <p className="font-medium text-text-primary">Graph lenses</p>
        <span className="text-[10px] text-text-muted" data-testid="lens-object-kind">{objectKind}</span>
      </div>
      <p className="mt-1">Registered lens availability for this graph context.</p>
      <div className="mt-3 space-y-1" role="list" aria-label="Registered graph lenses">
        {resolutions.map((resolution) => {
          const entry = resolution.entry;
          if (!entry) return null;
          return (
            <div
              key={resolution.lensId}
              role="listitem"
              data-lens-availability={resolution.availability}
              className="flex w-full items-center justify-between rounded border border-border-subtle px-2 py-1.5 text-left"
            >
              <span>{entry.displayName}</span>
              <span className="ml-2 text-[10px] text-text-muted">{lensStatusLabel(resolution)}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-2 text-[10px] text-text-muted">Unavailable lenses stay visible with their registry state.</p>
    </div>
  );
}

/**
 * Graph-first tenant exploration workspace. GraphPage is deliberately
 * composed rather than reimplemented: its existing loading, empty, error,
 * partial/truth, table, path, canvas, and first-click inspector behavior is
 * the graph workspace's source of truth.
 */
export function ExplorePage() {
  const navigate = useNavigate();
  // GraphContextProvider is the host authority for tenant/workspace and
  // environment identity. This route is intentionally not renderable without
  // that provider; no route or deployment label can stand in for its scope.
  const context = useGraphContext();
  const history = useGraphHistory();
  const actions = useGraphActions();
  const [noesisExpanded, setNoesisExpanded] = useState(false);

  const labels = useMemo(() => scopeLabels(context), [context]);
  const currentFocus = context.selection.focused;
  const historyEntries = history.entries;
  const currentTemporalLabel = temporalLabel(context);
  const selectedObjectKind = currentFocus?.kind ?? 'entity';
  const handleObjectSelected = useCallback((node: GraphNode) => {
    const ref = {
      tenant_id: context.scope.tenant_id,
      environment_id: context.scope.environment_id,
      kind: node.kind,
      id: node.id,
    } as const;
    actions.focusObject(ref);
    actions.selectObject(ref);
    navigate(objectRoute(node.id));
  }, [actions, context.scope.environment_id, context.scope.tenant_id, navigate]);

  function moveThroughHistory(direction: 'previous' | 'next') {
    const next = direction === 'previous'
      ? actions.previousFocus(currentFocus)
      : actions.nextFocus(currentFocus);
    if (!next) return;
    actions.focusObject(next);
    navigate(objectRoute(next.id));
  }

  const contextBar = (
    <GraphContextBar
      workspaceLabel={labels.workspace}
      environmentLabel={labels.environment}
      timeLabel={currentTemporalLabel}
    />
  );
  const historyPosition = currentFocus
    ? historyEntries.findIndex((entry) => entry.object.id === currentFocus.id) + 1
    : historyEntries.length;
  const timeRail = (
    <GraphTimeRail
      context={context}
      temporal={context.temporal}
      historyPosition={historyPosition}
      historyCount={historyEntries.length}
      onPrevious={() => moveThroughHistory('previous')}
      onNext={() => moveThroughHistory('next')}
    />
  );
  const noesisStrip = (
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
        <div data-testid="noesis-context-expanded" className="flex flex-wrap items-center gap-2 py-2 text-xs text-text-secondary">
          <span>Noesis opens with this graph context. Query and context handoff remain read-only until an explicit action is chosen.</span>
          <button
            type="button"
            className="text-accent underline hover:text-text-primary"
            onClick={() => navigate('/noesis')}
          >
            Open Noesis
          </button>
        </div>
      )}
    </NoesisContextStrip>
  );

  return (
    <div data-testid="explore-page" className="h-full">
      <GraphWorkspaceFrame
        contextBar={contextBar}
        lensDock={(
          <LensDock objectKind={selectedObjectKind} />
        )}
        canvas={<GraphPage embedded onObjectSelected={handleObjectSelected} />}
        timeRail={timeRail}
        noesisStrip={noesisStrip}
      />
    </div>
  );
}
