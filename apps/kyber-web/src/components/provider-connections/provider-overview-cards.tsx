import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
} from '@aether/ui';
import type { ProviderConnectionsOverview } from '@kyber/features/provider-connections';

interface Props {
  readonly data: ProviderConnectionsOverview;
}

/**
 * Aggregate connection counts by lifecycle state. Deliberately tenant-anonymous:
 * an operator sees how many connections exist per provider per state, never which
 * tenant owns them — the tenant drill-down is its own surface.
 *
 * ``providers`` is ``identity -> state -> count``. A provider with no row in any
 * state is simply absent here; nothing is coerced to a confident zero.
 */
export function ProviderOverviewCards({ data }: Props) {
  const states: Record<string, number> = {};
  for (const byState of Object.values(data.providers)) {
    for (const [state, count] of Object.entries(byState)) {
      states[state] = (states[state] ?? 0) + count;
    }
  }
  const stateEntries = Object.entries(states);

  return (
    <div className="grid gap-3 md:grid-cols-4">
      <Card>
        <CardContent>
          <div className="text-xs text-text-muted font-mono">Total connections</div>
          <div className="mt-1 text-2xl font-semibold text-text-primary">{data.total}</div>
          {data.truncated === true ? (
            <div className="text-[10px] text-text-muted font-mono">
              truncated at cap {data.cap ?? 'unknown'}
            </div>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <div className="text-xs text-text-muted font-mono">Providers with connections</div>
          <div className="mt-1 text-2xl font-semibold text-text-primary">
            {Object.keys(data.providers).length}
          </div>
        </CardContent>
      </Card>
      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle>Connections by lifecycle state</CardTitle>
        </CardHeader>
        <CardContent>
          {stateEntries.length === 0 ? (
            <EmptyState title="No connections" description="No provider connections have been created across tenants." />
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {stateEntries.map(([state, count]) => (
                <Badge key={state} variant="default">
                  <span className="font-mono">{state}</span>
                  <span className="ml-1.5 font-semibold">{count}</span>
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
