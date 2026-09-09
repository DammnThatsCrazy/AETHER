import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { GraphContext } from '@aether/shared/graph-context-contract';
import {
  GraphContextBar,
  GraphTimeRail,
  GraphWorkspaceFrame,
  NoesisContextStrip,
  useGraphActions,
  useGraphContext,
  useGraphHistory,
} from '@aether/ui/exploration';
import { GraphPage } from '@aether-app/pages/graph/graph-page';

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
          <div className="p-3 text-xs text-text-secondary">
            <p className="font-medium text-text-primary">Graph lenses</p>
            <p className="mt-1">Layer and overlay controls remain attached to the graph canvas.</p>
          </div>
        )}
        canvas={<GraphPage embedded />}
        timeRail={timeRail}
        noesisStrip={noesisStrip}
      />
    </div>
  );
}
