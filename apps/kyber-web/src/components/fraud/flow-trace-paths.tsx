import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, LoadingState, formatCount, useTimeContext } from '@aether/ui';
import { useFlowTracePaths } from '@kyber/features/fraud/use-fraud';

interface FlowTracePathsProps {
  readonly traceId: string;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function riskVariant(score: unknown): 'default' | 'warning' | 'danger' {
  const n = Number(score ?? 0);
  if (n >= 75) return 'danger';
  if (n >= 45) return 'warning';
  return 'default';
}

function patternVariant(tag: string): 'default' | 'warning' | 'danger' {
  if (['circular', 'cycle_member', 'passes_through_mule'].includes(tag)) return 'danger';
  if (['split', 'merge', 'fan_out', 'fan_in', 'aggregation_point'].includes(tag)) return 'warning';
  return 'default';
}

type PathRow = Record<string, unknown>;

export function FlowTracePaths({ traceId }: FlowTracePathsProps) {
  const timeCtx = useTimeContext();
  const { data, isLoading } = useFlowTracePaths(traceId);

  const raw = asRec(data as unknown);
  const paths: PathRow[] = Array.isArray(raw.paths) ? raw.paths as PathRow[] : [];

  if (isLoading) return <LoadingState lines={3} />;
  if (paths.length === 0) {
    return <EmptyState title="No paths" description="No paths found for this trace." />;
  }

  return (
    <div className="flex flex-col gap-2">
      {paths.map((path, i) => {
        const nodes = Array.isArray(path.nodes) ? path.nodes as Record<string, unknown>[] : [];
        const patterns = Array.isArray(path.pattern_tags) ? path.pattern_tags as string[] : [];
        const riskScore = path.risk_score;
        const hopCount = nodes.length;
        const totalAmount = path.total_amount_usd;

        return (
          <Card key={fmt(path.id) || i}>
            <CardHeader className="py-2 px-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-text-primary">
                    Path {i + 1} — {hopCount} hop{hopCount !== 1 ? 's' : ''}
                  </span>
                  {patterns.map(tag => (
                    <Badge key={tag} variant={patternVariant(tag)}>{tag}</Badge>
                  ))}
                </div>
                <div className="flex items-center gap-2">
                  {totalAmount !== undefined && (
                    <span className="text-xs text-text-muted">
                      ${formatCount(Number(totalAmount), timeCtx)}
                    </span>
                  )}
                  <Badge variant={riskVariant(riskScore)}>
                    {riskScore !== undefined ? Number(riskScore).toFixed(1) : '—'}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0 pb-2 px-4">
              <div className="flex items-center gap-1 flex-wrap text-[10px] font-mono text-text-secondary">
                {nodes.map((node, j) => (
                  <span key={j} className="flex items-center gap-1">
                    <span className="bg-surface-sunken px-1.5 py-0.5 rounded">
                      {fmt(node.entity_id ?? node.id)}
                    </span>
                    {j < nodes.length - 1 && <span className="text-text-muted">→</span>}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
