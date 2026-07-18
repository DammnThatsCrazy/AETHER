import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState, useTimeContext} from '@aether/ui';
import { useClusterTargetingImpact } from '../use-targeting-intelligence';
import type { ClusterTargetingImpactRecord, JourneyDeltaRecord } from '../api';
import {
  NOT_CONFIGURED_DESCRIPTION,
  NOT_CONFIGURED_TITLE,
  formatCount,
  formatCurrencyAmount,
  formatDateTime,
  formatRate,
  humanize,
} from './targeting-shared';

// ── Funnel ─────────────────────────────────────────────────────────────────────

const FUNNEL_STAGES: ReadonlyArray<{ key: keyof ClusterTargetingImpactRecord; label: string }> = [
  { key: 'memberCount', label: 'Members' },
  { key: 'eligibleCount', label: 'Eligible' },
  { key: 'reachedCount', label: 'Reached' },
  { key: 'engagedCount', label: 'Engaged' },
  { key: 'convertedCount', label: 'Converted' },
  { key: 'attributedCount', label: 'Attributed' },
];

function FunnelSection({ impact }: { readonly impact: ClusterTargetingImpactRecord }) {
  const timeCtx = useTimeContext();
  return (
    <div className="grid grid-cols-2 sm:grid-cols-6 gap-3">
      {FUNNEL_STAGES.map(({ key, label }) => (
        <div key={String(key)} className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
          <p className="text-xs text-text-secondary">{label}</p>
          <p className="text-xl font-semibold text-text-primary mt-0.5">
            {formatCount(impact[key] as number | null | undefined, timeCtx)}
          </p>
        </div>
      ))}
    </div>
  );
}

// ── Economics ──────────────────────────────────────────────────────────────────

function EconomicsSection({ impact }: { readonly impact: ClusterTargetingImpactRecord }) {
  const timeCtx = useTimeContext();
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
        {/* Amounts always carry their currency label; currencies are never merged. */}
        <p className="text-xs text-text-secondary">Spend (USD)</p>
        <p className="text-sm font-semibold text-text-primary mt-0.5">
          {formatCurrencyAmount(impact.spendUsd, 'USD', timeCtx)}
        </p>
      </div>
      <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
        <p className="text-xs text-text-secondary">Revenue (USD)</p>
        <p className="text-sm font-semibold text-text-primary mt-0.5">
          {formatCurrencyAmount(impact.revenueUsd, 'USD', timeCtx)}
        </p>
      </div>
      <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
        <p className="text-xs text-text-secondary">ROAS</p>
        <p className="text-sm font-semibold text-text-primary mt-0.5 font-mono">
          {impact.roas != null ? `${impact.roas.toFixed(2)}x` : '—'}
        </p>
      </div>
      <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
        <p className="text-xs text-text-secondary">LTV delta (USD)</p>
        <p className="text-sm font-semibold text-text-primary mt-0.5">
          {impact.ltvDelta != null ? formatCurrencyAmount(impact.ltvDelta, 'USD', timeCtx) : <span className="font-mono">—</span>}
        </p>
      </div>
    </div>
  );
}

// ── Negative outcomes ──────────────────────────────────────────────────────────

const NEGATIVE_RATES: ReadonlyArray<{ key: keyof ClusterTargetingImpactRecord; label: string }> = [
  { key: 'complaintRate', label: 'Complaint rate' },
  { key: 'unsubscribeRate', label: 'Unsubscribe rate' },
  { key: 'churnSignalRate', label: 'Churn signal rate' },
  { key: 'fraudSignalRate', label: 'Fraud signal rate' },
];

function rateTone(rate: number | null | undefined): string {
  if (rate == null) return 'text-text-muted';
  if (rate >= 0.05) return 'text-danger';
  if (rate > 0.01) return 'text-warning';
  return 'text-text-primary';
}

function NegativeOutcomesSection({ impact }: { readonly impact: ClusterTargetingImpactRecord }) {
  const overexposure = impact.overexposureScore;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {NEGATIVE_RATES.map(({ key, label }) => {
          const rate = impact[key] as number | null | undefined;
          return (
            <div key={String(key)} className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
              <p className="text-xs text-text-secondary">{label}</p>
              <p className={`text-sm font-semibold mt-0.5 font-mono ${rateTone(rate)}`}>{formatRate(rate)}</p>
            </div>
          );
        })}
      </div>
      <div>
        <p className="text-xs text-text-muted mb-1">Overexposure score</p>
        {overexposure == null ? (
          <p className="text-xs text-text-muted font-mono">—</p>
        ) : (
          <div className="flex items-center gap-2">
            <div className="h-1.5 flex-1 bg-surface-overlay rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.max(0, Math.min(1, overexposure)) * 100}%`,
                  backgroundColor: overexposure >= 0.7 ? '#ef4444' : overexposure >= 0.4 ? '#eab308' : '#22c55e',
                }}
              />
            </div>
            <span className="text-xs font-mono text-text-primary">{(overexposure * 100).toFixed(1)}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Journey deltas ─────────────────────────────────────────────────────────────

function JourneyDeltaCard({ delta }: { readonly delta: JourneyDeltaRecord }) {
  const timeCtx = useTimeContext();
  const compared = delta.comparedToClusterIds ?? [];
  const stageDeltas = Object.entries(delta.populationStageDeltas ?? {});
  return (
    <div className="border border-border-default rounded-md px-3 py-2.5 space-y-1.5">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span className="font-mono text-text-primary">{delta.deltaId}</span>
        {compared.length > 0 && (
          <span className="flex items-center gap-1 flex-wrap">
            <span className="text-text-muted">vs</span>
            {compared.map(id => (
              <Badge key={id} variant="info" size="sm" className="font-mono">{id}</Badge>
            ))}
          </span>
        )}
        {(delta.holdoutClusterIds ?? []).length > 0 && (
          <span className="flex items-center gap-1 flex-wrap">
            <span className="text-text-muted">holdouts</span>
            {(delta.holdoutClusterIds ?? []).map(id => (
              <Badge key={id} variant="warning" size="sm" className="font-mono">{id}</Badge>
            ))}
          </span>
        )}
      </div>
      <div className="flex items-center gap-4 flex-wrap text-xs font-mono text-text-muted">
        <span>Reached {formatCount(delta.reachedCount, timeCtx)}</span>
        <span>Engaged {formatCount(delta.engagedCount, timeCtx)}</span>
        <span>Converted {formatCount(delta.convertedCount, timeCtx)}</span>
        <span>Attributed {formatCount(delta.attributedCount, timeCtx)}</span>
        <span>Non-progressed {formatCount(delta.nonProgressedCount, timeCtx)}</span>
      </div>
      {stageDeltas.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {stageDeltas.map(([stage, value]) => (
            <Badge key={stage} variant={value >= 0 ? 'success' : 'danger'} size="sm" className="font-mono">
              {humanize(stage)} {value >= 0 ? '+' : ''}{(value * 100).toFixed(1)}%
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab ────────────────────────────────────────────────────────────────────────

export function ClusterTargetingImpactTab({ clusterId }: { readonly clusterId: string }) {
  const timeCtx = useTimeContext();
  const { response, notConfigured, loading, error, refresh } = useClusterTargetingImpact(clusterId);

  if (loading && !response && !error && !notConfigured) return <LoadingState lines={8} />;
  if (error) return <ErrorState title="Targeting impact unavailable" message={error} onRetry={refresh} />;
  if (notConfigured) return <EmptyState title={NOT_CONFIGURED_TITLE} description={NOT_CONFIGURED_DESCRIPTION} />;

  const impact = response?.impact ?? null;
  const journeyDeltas = response?.journeyDeltas ?? [];

  if (!impact) {
    return (
      <EmptyState
        title="No targeting impact observed"
        description="Targeting impact appears once campaigns observed in your external platforms reach this cluster."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap text-xs text-text-muted">
        {impact.campaignId && impact.campaignId !== 'unknown' && (
          <Badge variant="default" size="sm" className="font-mono">campaign: {impact.campaignId}</Badge>
        )}
        <span>computed {formatDateTime(impact.computedAt, timeCtx)}</span>
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Targeting funnel</h3>
        <FunnelSection impact={impact} />
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Economics</h3>
        <EconomicsSection impact={impact} />
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-2">Negative outcomes</h3>
        <NegativeOutcomesSection impact={impact} />
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Journey deltas vs compared clusters</CardTitle></CardHeader>
        <CardContent>
          {journeyDeltas.length === 0 ? (
            <EmptyState
              title="No journey deltas yet"
              description="Journey deltas appear after this cluster's post-exposure outcomes are compared with reference or holdout clusters."
            />
          ) : (
            <div className="space-y-2">
              {journeyDeltas.map(delta => <JourneyDeltaCard key={delta.deltaId} delta={delta} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
          <p className="text-xs text-text-secondary">Evidence coverage</p>
          <p className="text-sm font-semibold text-text-primary mt-0.5 font-mono">{formatRate(impact.evidenceCoverage)}</p>
        </div>
        <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
          <p className="text-xs text-text-secondary">Identity confidence</p>
          <p className="text-sm font-semibold text-text-primary mt-0.5 font-mono">{formatRate(impact.identityConfidence)}</p>
        </div>
        <div className="bg-surface-raised border border-border-default rounded-md px-4 py-3">
          <p className="text-xs text-text-secondary">Membership confidence</p>
          <p className="text-sm font-semibold text-text-primary mt-0.5 font-mono">{formatRate(impact.clusterMembershipConfidence)}</p>
        </div>
      </div>
    </div>
  );
}
