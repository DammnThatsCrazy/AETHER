import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState } from '@aether/ui';
import { Link } from 'react-router-dom';
import { usePatternDiscoveryEnabled, usePatternList } from './use-patterns';

/** Risk overview: the open discovered-pattern queue, highest priority first. */
export function RiskPatternQueueCard() {
  const enabled = usePatternDiscoveryEnabled();
  const list = usePatternList({ queue: true });
  if (!enabled) return null;
  const items = list.data?.items ?? [];
  return (
    <Card data-testid="risk-pattern-queue">
      <CardHeader><CardTitle>Discovered patterns awaiting review{list.data ? ` · ${list.data.total}` : ''}</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {list.isLoading && !list.data && <LoadingState lines={3} />}
        {list.error && <ErrorState title="Discovered patterns unavailable" message={list.error} onRetry={list.refetch} />}
        {list.data && items.length === 0 && <EmptyState title="Nothing to review" description="No discovered pattern is waiting for review." />}
        {items.slice(0, 5).map(row => (
          <div key={row.pattern_id} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge size="sm">{row.severity ?? 'low'}</Badge>
            <Link className="hover:underline" to={`/patterns?pattern=${encodeURIComponent(row.pattern_id)}`}>{row.title}</Link>
            <span className="text-xs text-text-secondary">{row.affected_entity_count} entities</span>
          </div>
        ))}
        {items.length > 5 && <Link className="text-xs hover:underline" to="/patterns">All {list.data?.total} patterns →</Link>}
      </CardContent>
    </Card>
  );
}
