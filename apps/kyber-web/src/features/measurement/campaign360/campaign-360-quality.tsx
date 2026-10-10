import { Card, CardContent, CardHeader, CardTitle, LoadingState, ErrorState, Badge, formatCount, useTimeContext } from '@aether/ui';
import { useCampaign360Overview } from '../use-campaign-360';
import type { Campaign360OverviewParams } from '../use-campaign-360';

interface Props {
  params: Campaign360OverviewParams;
}

function QualityRow({ label, value, status }: { label: string; value: string; status?: 'ok' | 'warn' | 'error' | 'unknown' }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border last:border-0">
      <span className="text-sm text-text-secondary">{label}</span>
      <div className="flex items-center gap-2">
        {status && (
          <Badge variant={status === 'ok' ? 'success' : status === 'warn' ? 'warning' : status === 'error' ? 'danger' : 'default'}>
            {status}
          </Badge>
        )}
        <span className="text-sm font-mono">{value}</span>
      </div>
    </div>
  );
}

export function Campaign360Quality({ params }: Props) {
  const { data, loading, error } = useCampaign360Overview(params);
  const timeCtx = useTimeContext();

  if (loading) return <LoadingState lines={5} />;
  if (error) return <ErrorState title="Quality data unavailable" message={error} />;
  if (!data) return null;

  const d = data as Record<string, unknown>;
  const q = d.data_quality as Record<string, unknown>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-sm">Operator diagnostics</CardTitle></CardHeader>
        <CardContent>
          <QualityRow
            label="Connector freshness"
            value={String(q?.connector_freshness ?? 'unknown')}
            status={q?.connector_freshness as 'ok' | 'warn' | 'error' | 'unknown' ?? 'unknown'}
          />
          <QualityRow
            label="Attribution run freshness"
            value={String(q?.attribution_run_freshness ?? 'unknown')}
            status={q?.attribution_run_freshness === 'fresh' ? 'ok' : q?.attribution_run_freshness === 'stale' ? 'warn' : 'error'}
          />
          <QualityRow
            label="Projection lag"
            value={q?.projection_lag_hours != null ? `${q.projection_lag_hours}h` : '—'}
          />
          <QualityRow
            label="Reconciliation"
            value={String(q?.reconciliation_status ?? 'unknown')}
            status={q?.reconciliation_status as 'ok' | 'warn' | 'error' | 'unknown' ?? 'unknown'}
          />
          <QualityRow
            label="Completeness"
            value={q?.completeness_pct != null ? `${q.completeness_pct}%` : '—'}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-sm">Attribution run</CardTitle></CardHeader>
        <CardContent>
          <QualityRow label="Run ID" value={d.attribution_run_id ? String(d.attribution_run_id) : 'none'} />
          <QualityRow label="Model" value={String(d.attribution_model ?? '—')} />
          <QualityRow label="Total credit weight" value={Number(d.total_credit_weight ?? 0).toFixed(6)} />
          <QualityRow label="Touchpoints" value={formatCount(Number(d.touchpoint_count ?? 0), timeCtx)} />
        </CardContent>
      </Card>
    </div>
  );
}
