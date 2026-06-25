import { Card, CardContent, CardHeader, CardTitle, LoadingState, ErrorState, EmptyState, Badge } from '@aether/ui';
import { useCampaign360Overview } from '../use-campaign-360';
import type { Campaign360OverviewParams } from '../use-campaign-360';

interface Props {
  params: Campaign360OverviewParams;
}

export function Campaign360Attribution({ params }: Props) {
  const { data, loading, error } = useCampaign360Overview(params);

  if (loading) return <LoadingState lines={5} />;
  if (error) return <ErrorState title="Attribution unavailable" message={error} />;
  if (!data) return null;

  const d = data as Record<string, unknown>;
  const quality = d.data_quality as Record<string, unknown>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm">Attribution summary</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <div className="text-xs text-text-muted font-mono">Model</div>
              <div className="mt-1 font-medium">{String(d.attribution_model ?? '—')}</div>
            </div>
            <div>
              <div className="text-xs text-text-muted font-mono">Run ID</div>
              <div className="mt-1 font-mono text-xs">{d.attribution_run_id ? String(d.attribution_run_id).slice(0, 16) + '…' : '—'}</div>
            </div>
            <div>
              <div className="text-xs text-text-muted font-mono">Credit weight sum</div>
              <div className="mt-1 font-medium">{Number(d.total_credit_weight ?? 0).toFixed(4)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Data quality</CardTitle></CardHeader>
        <CardContent>
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <div className="text-xs text-text-muted font-mono">Connector freshness</div>
              <div className="mt-1">
                <Badge variant={quality?.connector_freshness === 'fresh' ? 'success' : quality?.connector_freshness === 'stale' ? 'warning' : 'secondary'}>
                  {String(quality?.connector_freshness ?? 'unknown')}
                </Badge>
              </div>
            </div>
            <div>
              <div className="text-xs text-text-muted font-mono">Attribution run</div>
              <div className="mt-1">
                <Badge variant={quality?.attribution_run_freshness === 'fresh' ? 'success' : quality?.attribution_run_freshness === 'stale' ? 'warning' : 'secondary'}>
                  {String(quality?.attribution_run_freshness ?? 'unknown')}
                </Badge>
              </div>
            </div>
            <div>
              <div className="text-xs text-text-muted font-mono">Reconciliation</div>
              <div className="mt-1">
                <Badge variant={quality?.reconciliation_status === 'ok' ? 'success' : quality?.reconciliation_status === 'warn' ? 'warning' : 'error'}>
                  {String(quality?.reconciliation_status ?? 'unknown')}
                </Badge>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
