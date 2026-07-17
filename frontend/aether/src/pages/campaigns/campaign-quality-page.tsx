import {
  Card, CardContent, CardHeader,
  ErrorState, LoadingState,
  formatCount, useTimeContext,
} from '@aether/ui';
import { useCampaignQuality } from '@aether-app/features/campaigns/use-campaign-quality';

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

type QualityMetric = { label: string; value: string; description: string; variant: 'good' | 'warn' | 'bad' | 'neutral' };

function Gauge({ value, label }: { value: number | null; label: string }) {
  const pct = value !== null ? Math.min(100, Math.max(0, value * 100)) : 0;
  const color = pct >= 90 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-danger';
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-text-secondary">{label}</span>
        <span className={`font-semibold ${pct >= 90 ? 'text-success' : pct >= 70 ? 'text-warning' : 'text-danger'}`}>
          {value !== null ? `${pct.toFixed(1)}%` : '—'}
        </span>
      </div>
      <div className="h-2 bg-surface-overlay rounded-full">
        <div className={`h-2 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function MetricCard({ label, value, description, variant }: QualityMetric) {
  const textColor = variant === 'good' ? 'text-success' : variant === 'warn' ? 'text-warning' : variant === 'bad' ? 'text-danger' : 'text-text-primary';
  return (
    <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3 space-y-1">
      <p className="text-xs text-text-secondary">{label}</p>
      <p className={`text-xl font-semibold ${textColor}`}>{value}</p>
      <p className="text-xs text-text-muted">{description}</p>
    </div>
  );
}

export function CampaignQualityPage() {
  const timeCtx = useTimeContext();
  const { data, isLoading, error } = useCampaignQuality();

  const q = (data ?? {}) as Record<string, unknown>;

  const spendRate = q.spend_mapping_rate as number | null ?? null;
  const touchpointRate = q.touchpoint_mapping_rate as number | null ?? null;
  const openReviews = q.open_reviews as number | undefined;
  const totalCampaigns = q.total_campaigns as number | undefined;
  const externalCampaigns = q.external_campaigns as number | undefined;
  const resolvedSpend = q.resolved_spend_records as number | undefined;
  const totalSpend = q.total_spend_records as number | undefined;

  const metrics: QualityMetric[] = [
    {
      label: 'Open mapping reviews',
      value: openReviews !== undefined ? formatCount(openReviews, timeCtx) : '—',
      description: 'Evidence items awaiting manual campaign assignment',
      variant: openReviews === undefined ? 'neutral' : openReviews === 0 ? 'good' : openReviews < 50 ? 'warn' : 'bad',
    },
    {
      label: 'Total campaigns',
      value: totalCampaigns !== undefined ? formatCount(totalCampaigns, timeCtx) : '—',
      description: 'Canonical campaigns in registry (all origins)',
      variant: 'neutral',
    },
    {
      label: 'External campaigns',
      value: externalCampaigns !== undefined ? formatCount(externalCampaigns, timeCtx) : '—',
      description: 'Campaigns imported from connected ad platforms',
      variant: 'neutral',
    },
    {
      label: 'Resolved spend records',
      value: resolvedSpend !== undefined && totalSpend !== undefined
        ? `${formatCount(resolvedSpend, timeCtx)} / ${formatCount(totalSpend, timeCtx)}`
        : '—',
      description: 'Spend records with canonical campaign UUID',
      variant: resolvedSpend === undefined ? 'neutral' : (resolvedSpend / (totalSpend ?? 1)) >= 0.95 ? 'good' : 'warn',
    },
  ];

  if (error) return (
    <div className="p-8">
      <ErrorState title="Failed to load quality metrics" message={String(error)} />
    </div>
  );

  if (isLoading) return (
    <div className="p-8">
      <LoadingState lines={6} />
    </div>
  );

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Measurement Quality</h1>
        <p className="text-sm text-text-secondary mt-0.5">
          Campaign resolution health — what fraction of spend and touchpoints map to canonical Aether UUIDs.
        </p>
      </div>

      {/* Resolution rate gauges */}
      <Card>
        <CardHeader>
          <span className="text-sm font-medium text-text-primary">Resolution rates</span>
        </CardHeader>
        <CardContent className="space-y-4">
          <Gauge value={spendRate} label="Spend record mapping rate" />
          <Gauge value={touchpointRate} label="Touchpoint mapping rate" />
        </CardContent>
      </Card>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {metrics.map(m => (
          <MetricCard key={m.label} {...m} />
        ))}
      </div>

      {/* Guidance when quality is low */}
      {(spendRate !== null && spendRate < 0.9) || (openReviews !== undefined && openReviews > 50) ? (
        <div className="border border-warning/40 bg-warning/10 rounded-md px-4 py-3 space-y-1">
          <p className="text-sm font-medium text-warning">Mapping quality below target</p>
          <ul className="text-xs text-text-secondary space-y-0.5 list-disc pl-4">
            {spendRate !== null && spendRate < 0.9 && (
              <li>Spend mapping rate is below 90%. Run the backfill script or resolve open reviews.</li>
            )}
            {openReviews !== undefined && openReviews > 50 && (
              <li>
                {openReviews} open mapping reviews. <a href="/campaign-intelligence/mapping-review" className="text-accent hover:underline">Review queue →</a>
              </li>
            )}
          </ul>
        </div>
      ) : null}

      {/* Raw data for debugging */}
      {Object.keys(q).length > 0 && (
        <details className="text-xs text-text-muted">
          <summary className="cursor-pointer hover:text-text-secondary">Raw quality data</summary>
          <pre className="mt-2 bg-surface-raised border border-border-default rounded p-3 overflow-x-auto">
            {JSON.stringify(q, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
