import { Card, CardContent, CardHeader, CardTitle, LoadingState, ErrorState, Badge } from '@aether/ui';
import type { Campaign360OverviewParams } from '../use-campaign-360';
import { useCampaign360Overview } from '../use-campaign-360';

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className="mt-1 text-2xl font-semibold">{value}</div>
      </CardContent>
    </Card>
  );
}

function fmtUSD(n: number) {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtPct(n: number | null) {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

interface Props {
  params: Campaign360OverviewParams;
}

export function Campaign360Overview({ params }: Props) {
  const { data, loading, error } = useCampaign360Overview(params);

  if (loading) return <LoadingState lines={6} className="p-4" />;
  if (error) return <ErrorState title="Overview unavailable" message={error} />;
  if (!data) return null;

  const d = data as Record<string, unknown>;
  const qualityStatus = (d.data_quality as Record<string, unknown>)?.reconciliation_status;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="text-sm text-text-secondary">Attribution model:</span>
        <Badge variant="secondary">{String(d.attribution_model ?? 'last_touch')}</Badge>
        {qualityStatus === 'ok' && <Badge variant="success">Reconciled</Badge>}
        {qualityStatus === 'warn' && <Badge variant="warning">Reconciliation warning</Badge>}
        {qualityStatus === 'error' && <Badge variant="error">Reconciliation error</Badge>}
      </div>

      <div className="grid gap-4 md:grid-cols-3 lg:grid-cols-5">
        <Metric label="Spend" value={fmtUSD(Number(d.spend_usd ?? 0))} />
        <Metric label="Impressions" value={Number(d.impressions ?? 0).toLocaleString()} />
        <Metric label="Clicks" value={Number(d.clicks ?? 0).toLocaleString()} />
        <Metric label="CTR" value={fmtPct(d.ctr as number | null)} />
        <Metric label="CPC" value={d.cpc != null ? fmtUSD(Number(d.cpc)) : '—'} />
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Population funnel</h3>
        <div className="grid gap-4 md:grid-cols-5">
          {[
            { label: 'Observed', value: Number(d.observed_count ?? 0), color: 'bg-blue-500' },
            { label: 'Resolved', value: Number(d.resolved_count ?? 0), color: 'bg-indigo-500' },
            { label: 'Engaged', value: Number(d.engaged_count ?? 0), color: 'bg-violet-500' },
            { label: 'Converted', value: Number(d.converted_count ?? 0), color: 'bg-purple-500' },
            { label: 'Attributed', value: Number(d.attributed_count ?? 0), color: 'bg-pink-500' },
          ].map(({ label, value, color }) => (
            <Card key={label}>
              <CardContent className="pt-4">
                <div className="flex items-center gap-2 mb-1">
                  <div className={`w-2 h-2 rounded-full ${color}`} />
                  <div className="text-xs text-text-muted font-mono">{label}</div>
                </div>
                <div className="text-xl font-semibold">{value.toLocaleString()}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Attribution economics</h3>
        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="Gross attributed revenue" value={fmtUSD(Number(d.gross_attributed_revenue ?? 0))} />
          <Metric label="Net attributed revenue" value={fmtUSD(Number(d.net_attributed_revenue ?? 0))} />
          <Metric label="ROAS" value={d.roas != null ? `${Number(d.roas).toFixed(2)}x` : '—'} />
        </div>
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Identity quality</h3>
        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="Resolution rate" value={fmtPct(d.identity_resolution_rate as number | null)} />
          <Metric label="Touchpoints" value={Number(d.touchpoint_count ?? 0).toLocaleString()} />
          <Metric label="Fractional conversions" value={Number(d.fractional_attributed_conversions ?? 0).toFixed(2)} />
        </div>
      </div>
    </div>
  );
}
