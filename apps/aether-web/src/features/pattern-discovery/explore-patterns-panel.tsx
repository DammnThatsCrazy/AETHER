import { useMemo, useState, type ReactNode } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { PatternGraphCanvas } from './pattern-graph-canvas';
import { usePatternDiscoveryEnabled, usePatternGraph, usePatternOverlay } from './use-patterns';

/** Graph node ids for a pattern's member keys (`user:abc` matches node `abc` or `user:abc`). */
function memberNodeIds(memberKeys: readonly string[], nodeIds: readonly string[]): Set<string> {
  const present = new Set(nodeIds);
  const out = new Set<string>();
  for (const key of memberKeys) {
    if (present.has(key)) out.add(key);
    const bare = key.includes(':') ? key.slice(key.indexOf(':') + 1) : key;
    if (present.has(bare)) out.add(bare);
  }
  return out;
}

/** Computes the node ids to highlight for the pattern shown on the graph (``?pattern=``). */
export function PatternHighlightBridge({ patternId, nodeIds, children }: {
  readonly patternId: string | null;
  readonly nodeIds: readonly string[];
  readonly children: (ids: ReadonlySet<string> | undefined) => ReactNode;
}) {
  const graph = usePatternGraph(patternId);
  const ids = useMemo(() => {
    if (!patternId || !graph.data) return undefined;
    return memberNodeIds(graph.data.nodes.filter(n => n.role === 'member').map(n => n.id), nodeIds);
  }, [patternId, graph.data, nodeIds]);
  return <>{children(ids)}</>;
}

/** Explore: the pattern being shown on the graph, or the patterns touching what is in view. */
export function ExplorePatternsPanel({ nodeIds, patternId, onPattern, onFocusNode }: {
  readonly nodeIds: readonly string[];
  readonly patternId: string | null;
  readonly onPattern: (id: string | null) => void;
  readonly onFocusNode: (id: string) => void;
}) {
  const enabled = usePatternDiscoveryEnabled();
  const [open, setOpen] = useState(false);
  const graph = usePatternGraph(patternId);
  const overlay = usePatternOverlay(open && !patternId ? nodeIds : []);
  if (!enabled) return null;

  if (patternId) {
    const inView = graph.data ? memberNodeIds(graph.data.nodes.filter(n => n.role === 'member').map(n => n.id), nodeIds) : new Set<string>();
    return (
      <Card data-testid="explore-pattern-panel">
        <CardHeader><CardTitle>Pattern on the graph</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {graph.isLoading && !graph.data && <LoadingState lines={3} />}
          {graph.error && <ErrorState title="Pattern graph unavailable" message={graph.error} onRetry={graph.refetch} />}
          {graph.data && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{graph.data.title}</span>
                <Button size="sm" variant="ghost" onClick={() => onPattern(null)}>Clear pattern</Button>
              </div>
              <p className="text-xs" style={{ color: 'var(--ae-mute)' }}>
                {inView.size} of {graph.data.nodes.filter(n => n.role === 'member').length} members are in this graph view and are outlined in amber. Click a member to focus it.
              </p>
              <PatternGraphCanvas graph={graph.data} onNodeClick={(id) => {
                const bare = id.includes(':') ? id.slice(id.indexOf(':') + 1) : id;
                onFocusNode(nodeIds.includes(id) ? id : bare);
              }} />
            </>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="explore-patterns-in-view">
      <CardHeader><CardTitle>Patterns in this view</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {!open ? (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)} disabled={nodeIds.length === 0}>
            Show patterns touching these {nodeIds.length} objects
          </Button>
        ) : (
          <>
            {overlay.isLoading && !overlay.data && <LoadingState lines={2} />}
            {overlay.error && <ErrorState title="Patterns unavailable" message={overlay.error} onRetry={overlay.refetch} />}
            {overlay.data && overlay.data.patterns.length === 0 && (
              <EmptyState title="No surfaced patterns here" description="None of the objects in view belong to a surfaced pattern." />
            )}
            {overlay.data?.patterns.slice(0, 8).map(p => (
              <div key={p.pattern_id} className="flex flex-wrap items-center gap-2 text-sm">
                <Badge size="sm">{p.severity ?? 'low'}</Badge>
                <button type="button" className="text-left hover:underline" onClick={() => onPattern(p.pattern_id)}>{p.title}</button>
                <span className="text-xs" style={{ color: 'var(--ae-mute)' }}>{p.members_in_view.length} in view</span>
              </div>
            ))}
          </>
        )}
      </CardContent>
    </Card>
  );
}
